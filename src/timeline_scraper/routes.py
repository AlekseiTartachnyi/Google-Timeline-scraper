"""Routed distance between a trip's endpoints, from the Google Routes API.

Timeline reports the length of the *recorded GPS track*: where the signal is
poor it wanders, and a 1.5 mi downtown drive comes back as 4.0 mi. The road
network says something different, and the difference is worth seeing — so both
numbers are kept side by side and neither is corrected into the other (spec
§9.5). A detour is legitimate: a track longer than the route is a row to look
at, never an error to fix automatically.

Two routes are asked for per trip, because the road a toll buys is a different
road: the default one, which uses tolls where they are quicker, and the one
that avoids them. The miles differ, which is the point of having both columns.

What this needs to run:

  * a Google Maps Platform API key with the Routes API enabled, in the
    environment variable GOOGLE_MAPS_API_KEY;
  * an address on both ends of the trip. A trip whose endpoint the scrape could
    not fill is left alone — nothing here guesses at a location.

Every answer is cached on disk by (origin, destination, tolls), so a home-to-
office pair that repeats forty times in a month is paid for once, and a re-run
of `flatten` over the same export costs nothing at all.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from .model import Trip

logger = logging.getLogger(__name__)

ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
KEY_ENV = "GOOGLE_MAPS_API_KEY"

# Only the distance is asked for. The field mask is not optional on this API,
# and a narrow one is also what keeps the call in the cheapest billing tier.
FIELD_MASK = "routes.distanceMeters"
# TRAFFIC_UNAWARE for the same reason: traffic-aware routing is billed higher,
# and the length of a road does not depend on what time it is driven.
ROUTING_PREFERENCE = "TRAFFIC_UNAWARE"

METERS_PER_MILE = 1609.344
TIMEOUT_S = 20
# Consecutive failures after which the run stops asking. A bad key or a Routes
# API that was never enabled fails identically on every row; without this, one
# wrong character in the key means several hundred pointless calls.
GIVE_UP_AFTER = 3

CACHE_NAME = "route-cache.json"
CACHE_VERSION = 1


def api_key() -> str | None:
    """Return the API key from the environment, or None if it is not set."""
    key = os.environ.get(KEY_ENV, "").strip()
    return key or None


def endpoint_query(address: str | None, missing: bool) -> str | None:
    """Return what to ask the API for one end of a trip, or None if nothing can be.

    The address alone, never the place name: "Home" and "Office" are labels this
    phone made up and they route to whatever Google thinks those words mean
    somewhere else in the world. A `Missing visit` is Google saying it recorded
    a stop it could not name — there is nothing to route to.
    """
    if missing or not address:
        return None
    return address.strip() or None


def _cache_key(origin: str, destination: str, avoid_tolls: bool) -> str:
    return "\n".join((origin, destination, "avoid-tolls" if avoid_tolls else "any-road"))


class RouteLookup:
    """Routed miles for a trip, asked once and remembered.

    Kept as an object rather than a function because a run has state worth
    keeping: the cache, the counts that go in the summary, and whether the API
    has failed often enough that asking again is a waste.
    """

    def __init__(self, key: str, cache_path: Path | None = None) -> None:
        self.key = key
        self.cache_path = cache_path
        self.cache: dict[str, float | None] = {}
        self.cache_dirty = False
        # For the line the command prints when it finishes.
        self.asked = 0
        self.cached = 0
        self.skipped = 0
        self.failed = 0
        self.no_route = 0
        self._consecutive_failures = 0
        self.gave_up = False
        self._load_cache()

    # -- cache ---------------------------------------------------------------

    def _load_cache(self) -> None:
        """Read the cache written by an earlier run, if there is a usable one."""
        if self.cache_path is None or not self.cache_path.exists():
            return
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("Ignoring unreadable route cache %s: %s", self.cache_path, exc)
            return
        if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
            logger.warning("Route cache %s is a different version; starting fresh",
                           self.cache_path)
            return
        entries = payload.get("entries")
        if isinstance(entries, dict):
            self.cache = entries
            logger.info("Route cache: %d answer(s) already on disk", len(entries))

    def save_cache(self) -> None:
        """Write the cache back if anything new was learned."""
        if self.cache_path is None or not self.cache_dirty:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {"version": CACHE_VERSION, "entries": self.cache},
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        self.cache_dirty = False

    # -- lookups -------------------------------------------------------------

    def for_trip(self, trip: Trip) -> tuple[float | None, float | None]:
        """Return (miles allowing tolls, miles avoiding tolls) for one trip.

        Either or both are None when the answer is not known — no address on an
        end of the trip, no road between the two, or the API refused. The cell
        is then left empty rather than filled with a number nobody checked.
        """
        origin = endpoint_query(trip.from_address, trip.from_missing)
        destination = endpoint_query(trip.to_address, trip.to_missing)
        if origin is None or destination is None:
            self.skipped += 1
            return None, None
        return (
            self.miles(origin, destination, avoid_tolls=False),
            self.miles(origin, destination, avoid_tolls=True),
        )

    def miles(self, origin: str, destination: str, avoid_tolls: bool) -> float | None:
        """Return the routed miles between two addresses, from cache or the API."""
        key = _cache_key(origin, destination, avoid_tolls)
        if key in self.cache:
            self.cached += 1
            return self.cache[key]
        if self.gave_up:
            return None

        miles, answered = self._request(origin, destination, avoid_tolls)
        if not answered:
            self.failed += 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= GIVE_UP_AFTER:
                self.gave_up = True
                logger.error(
                    "The Routes API failed %d times in a row; no more lookups this "
                    "run. The rows already answered are kept, and the cache means a "
                    "re-run only asks for what is still missing.",
                    self._consecutive_failures,
                )
            return None

        self._consecutive_failures = 0
        self.asked += 1
        if miles is None:
            self.no_route += 1
        self.cache[key] = miles
        self.cache_dirty = True
        # Written as each answer arrives, not once at the end: these answers cost
        # money, and a run stopped with Ctrl-C halfway through a month must not
        # have to buy them again.
        self.save_cache()
        return miles

    def _request(
        self, origin: str, destination: str, avoid_tolls: bool
    ) -> tuple[float | None, bool]:
        """Ask the API once. Returns (miles, whether the API answered at all).

        The two are separate on purpose: "there is no road between these two
        places" is an answer worth caching, and "the network was down" is not.
        """
        body: dict[str, object] = {
            "origin": {"address": origin},
            "destination": {"address": destination},
            "travelMode": "DRIVE",
            "routingPreference": ROUTING_PREFERENCE,
            "units": "IMPERIAL",
        }
        if avoid_tolls:
            body["routeModifiers"] = {"avoidTolls": True}

        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            logger.error("Routes API returned %s for %r -> %r: %s",
                         exc.code, origin, destination, detail)
            return None, False
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.error("Routes API unreachable for %r -> %r: %s",
                         origin, destination, exc)
            return None, False

        routes = payload.get("routes") or []
        if not routes:
            logger.warning("No driving route between %r and %r", origin, destination)
            return None, True
        meters = routes[0].get("distanceMeters")
        if not isinstance(meters, (int, float)):
            logger.warning("Routes API answered without a distance for %r -> %r",
                           origin, destination)
            return None, True
        return round(meters / METERS_PER_MILE, 1), True

    # -- summary -------------------------------------------------------------

    def summary(self) -> str:
        """Return the one line the command logs when the sheet is written."""
        return (
            f"{self.asked} lookup(s) charged, {self.cached} answered from cache, "
            f"{self.skipped} trip(s) skipped for want of an address, "
            f"{self.no_route} with no road between the ends, {self.failed} failed"
        )


def open_lookup(cache_path: Path | None) -> RouteLookup | None:
    """Return a lookup ready to use, or None with the reason already logged."""
    key = api_key()
    if key is None:
        logger.error(
            "--routes needs a Google Maps Platform API key with the Routes API "
            "enabled, in the environment variable %s. Set it in the same terminal "
            "and run the command again.",
            KEY_ENV,
        )
        return None
    return RouteLookup(key, cache_path)
