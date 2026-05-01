from __future__ import annotations

import re

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_strip(text: str | None) -> str:
    """Strip HTML tags and collapse whitespace. Used before sponsorship scan."""
    if not text:
        return ""
    cleaned = _HTML_TAG.sub(" ", text)
    return _WS.sub(" ", cleaned).strip()


# US state codes + names (lowercase). Includes DC.
US_STATES: frozenset[str] = frozenset({
    "al", "alabama", "ak", "alaska", "az", "arizona", "ar", "arkansas",
    "ca", "california", "co", "colorado", "ct", "connecticut",
    "de", "delaware", "fl", "florida", "ga", "georgia", "hi", "hawaii",
    "id", "idaho", "il", "illinois", "in", "indiana", "ia", "iowa",
    "ks", "kansas", "ky", "kentucky", "la", "louisiana",
    "me", "maine", "md", "maryland", "ma", "massachusetts",
    "mi", "michigan", "mn", "minnesota", "ms", "mississippi", "mo", "missouri",
    "mt", "montana", "ne", "nebraska", "nv", "nevada",
    "nh", "new hampshire", "nj", "new jersey", "nm", "new mexico",
    "ny", "new york", "nc", "north carolina", "nd", "north dakota",
    "oh", "ohio", "ok", "oklahoma", "or", "oregon",
    "pa", "pennsylvania", "ri", "rhode island",
    "sc", "south carolina", "sd", "south dakota",
    "tn", "tennessee", "tx", "texas", "ut", "utah",
    "vt", "vermont", "va", "virginia", "wa", "washington",
    "wv", "west virginia", "wi", "wisconsin", "wy", "wyoming",
    "dc", "district of columbia", "washington dc", "washington d.c.",
})


US_CITIES: frozenset[str] = frozenset({
    "san francisco", "sf", "new york", "nyc", "new york city",
    "seattle", "boston", "los angeles", "la", "austin", "denver",
    "chicago", "atlanta", "san jose", "palo alto", "mountain view",
    "redwood city", "menlo park", "cambridge", "brooklyn",
    "bay area", "silicon valley", "san diego", "portland",
    "miami", "dallas", "houston", "philadelphia", "phoenix",
    "minneapolis", "pittsburgh", "raleigh", "durham", "charlotte",
    "nashville", "salt lake city", "st. louis", "kansas city",
})


US_GENERIC: frozenset[str] = frozenset({
    "united states", "usa", "u.s.", "u.s.a.", "us only",
    "remote - us", "remote (us)", "remote, us", "remote us",
    "us remote", "remote united states", "remote, united states",
    "anywhere in the us", "us-remote", "north america",
})


NON_US_BLOCKERS: frozenset[str] = frozenset({
    # cities
    "london", "berlin", "paris", "munich", "amsterdam", "dublin",
    "tel aviv", "tokyo", "singapore", "bangalore", "bengaluru",
    "hyderabad", "mumbai", "delhi", "pune", "shanghai", "beijing",
    "hong kong", "sydney", "melbourne", "toronto", "vancouver",
    "montreal", "ottawa", "calgary", "mexico city", "são paulo",
    "sao paulo", "buenos aires", "santiago", "bogotá", "bogota",
    "lima", "quito", "caracas", "barcelona", "madrid", "milan",
    "rome", "stockholm", "copenhagen", "oslo", "helsinki", "warsaw",
    "prague", "budapest", "vienna", "zurich", "geneva",
    # regions
    "europe", "emea", "apac", "latam", "asia", "south america",
    "central america", "middle east",
    # countries / codes
    "uk", "united kingdom", "germany", "france", "india", "china",
    "japan", "canada", "can", "australia", "ireland", "netherlands",
    "spain", "italy", "switzerland", "sweden", "poland", "brazil",
    "mexico", "argentina", "uruguay", "chile", "colombia", "peru",
    "venezuela", "ecuador", "bolivia", "paraguay", "costa rica",
    "panama", "hungary", "romania", "portugal", "greece", "turkey",
    "israel", "south korea", "korea", "thailand", "vietnam",
    "indonesia", "philippines", "malaysia", "south africa", "nigeria",
    "kenya", "egypt", "uae", "saudi arabia",
})
