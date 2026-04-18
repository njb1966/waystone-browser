"""Async Gopher protocol client (RFC 1436)."""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

# Item types that should be downloaded rather than rendered
BINARY_TYPES: frozenset[str] = frozenset("5 6 9 g I s".split())


@dataclass
class GopherItem:
    type: str       # single character from RFC 1436
    display: str    # human-readable label
    selector: str   # path sent to server
    host: str
    port: int


@dataclass
class GopherResponse:
    item_type: str   # parsed from URL
    body: bytes


class GopherError(Exception):
    pass


def parse_url(url: str) -> tuple[str, int, str, str]:
    """
    Decompose a gopher:// URL into (host, port, item_type, selector).

    gopher://host/1/pub/games  →  host, 70, '1', '/pub/games'
    gopher://host/             →  host, 70, '1', ''
    gopher://host:7070/0/file  →  host, 7070, '0', '/file'
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 70
    path = parsed.path or "/"

    if len(path) > 1:
        item_type = path[1]
        selector = path[2:]
    else:
        item_type = "1"
        selector = ""

    return host, port, item_type, selector


def item_url(item: GopherItem) -> str:
    """Build a gopher:// URL for a menu item, or the bare URL for h-type items."""
    if not item.host:
        return ""
    if item.type == "h" and item.selector.startswith("URL:"):
        return item.selector[4:]
    port_part = f":{item.port}" if item.port != 70 else ""
    return f"gopher://{item.host}{port_part}/{item.type}{item.selector}"


async def fetch(url: str, timeout: float = 15.0, query: str = "") -> GopherResponse:
    """
    Open a plain TCP connection, send the selector (+ optional search query for
    type-7 items), and read until EOF.
    Raises GopherError on connection or protocol failure.
    """
    host, port, item_type, selector = parse_url(url)

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise GopherError(f"Connection to {host}:{port} timed out")
    except OSError as e:
        raise GopherError(f"Could not connect to {host}:{port}: {e}")

    try:
        line = f"{selector}\t{query}\r\n" if query else f"{selector}\r\n"
        writer.write(line.encode("utf-8"))
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        body = await asyncio.wait_for(reader.read(), timeout=60.0)
    except asyncio.TimeoutError:
        raise GopherError("Timed out reading response")
    except OSError as e:
        raise GopherError(f"Read error: {e}")
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except Exception:
            pass

    return GopherResponse(item_type=item_type, body=body)


def parse_menu(body: bytes) -> list[GopherItem]:
    """
    Parse a Gopher directory (type 1) response into a list of GopherItems.
    Each line: type + display\\tselector\\thost\\tport
    A bare '.' line marks the end of the menu.
    """
    items: list[GopherItem] = []
    text = body.decode("utf-8", errors="replace")

    for line in text.splitlines():
        line = line.rstrip("\r")
        if line == ".":
            break

        if not line:
            items.append(GopherItem(type="i", display="", selector="", host="", port=0))
            continue

        item_type = line[0]
        parts = line[1:].split("\t")
        display  = parts[0] if len(parts) > 0 else ""
        selector = parts[1] if len(parts) > 1 else ""
        host     = parts[2] if len(parts) > 2 else ""
        try:
            port = int(parts[3].strip()) if len(parts) > 3 else 70
        except ValueError:
            port = 70

        items.append(GopherItem(
            type=item_type,
            display=display,
            selector=selector,
            host=host,
            port=port,
        ))

    return items
