"""URL parsing, normalization, and scheme dispatch."""

from enum import Enum, auto
from urllib.parse import urlparse, urlunparse, uses_netloc, uses_relative

# Register non-standard schemes so urljoin() resolves relative URLs correctly.
for _scheme in ("gemini", "gopher"):
    if _scheme not in uses_netloc:
        uses_netloc.append(_scheme)
    if _scheme not in uses_relative:
        uses_relative.append(_scheme)


class Scheme(Enum):
    HTTP = auto()
    HTTPS = auto()
    GEMINI = auto()
    GOPHER = auto()
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

    # If no scheme, assume https
    if not parsed.scheme:
        raw = "https://" + raw
        parsed = urlparse(raw)

    return urlunparse(parsed)


def detect_scheme(url: str) -> Scheme:
    scheme = urlparse(url).scheme.lower()
    return {
        "http": Scheme.HTTP,
        "https": Scheme.HTTPS,
        "gemini": Scheme.GEMINI,
        "gopher": Scheme.GOPHER,
    }.get(scheme, Scheme.UNKNOWN)
