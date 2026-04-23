"""URL parsing, normalization, and scheme dispatch."""

from enum import Enum, auto
from urllib.parse import urlparse, urlunparse, uses_netloc, uses_relative

# Register non-standard schemes so urljoin() resolves relative URLs correctly.
for _scheme in ("gemini", "gopher", "spartan", "titan"):
    if _scheme not in uses_netloc:
        uses_netloc.append(_scheme)
    if _scheme not in uses_relative:
        uses_relative.append(_scheme)


class Scheme(Enum):
    HTTP = auto()
    HTTPS = auto()
    GEMINI = auto()
    GOPHER = auto()
    SPARTAN = auto()
    TITAN = auto()
    UNKNOWN = auto()


def normalize_url(raw: str) -> str:
    """
    Turn a bare hostname or partial URL into a full URL string.
    - 'example.org'        -> 'https://example.org'
    - 'gemini://...'       -> unchanged
    - 'http://...'         -> unchanged
    """
    raw = raw.strip()
    if not raw:
        return ""

    parsed = urlparse(raw)

    # If no scheme, infer from the shape of the input
    if not parsed.scheme:
        if raw.startswith("/"):
            raw = "file://" + raw
        else:
            raw = "https://" + raw
        parsed = urlparse(raw)

    return urlunparse(parsed)


def detect_scheme(url: str) -> Scheme:
    scheme = urlparse(url).scheme.lower()
    return {
        "http":    Scheme.HTTP,
        "https":   Scheme.HTTPS,
        "gemini":  Scheme.GEMINI,
        "gopher":  Scheme.GOPHER,
        "spartan": Scheme.SPARTAN,
        "titan":   Scheme.TITAN,
    }.get(scheme, Scheme.UNKNOWN)
