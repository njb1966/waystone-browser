"""Async Spartan protocol client (spartan://, port 300, plain TCP)."""

import asyncio
import socket
from urllib.parse import urlparse

DEFAULT_PORT = 300


class SpartanError(Exception):
    pass


async def fetch(
    url: str,
    body: bytes = b"",
    timeout: float = 15.0,
) -> tuple[int, str, bytes]:
    """
    Fetch a Spartan URL.  Returns (status_code, meta, response_body).
    Pass a non-empty *body* for data-submission requests (= links).
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or DEFAULT_PORT
    path = parsed.path or "/"

    loop = asyncio.get_event_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise SpartanError(f"DNS lookup for {host} timed out")
    except OSError as e:
        raise SpartanError(f"Could not resolve {host}: {e}")

    if not infos:
        raise SpartanError(f"No addresses found for {host}")

    # Prefer IPv4 to avoid broken IPv6 stacks.
    infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)

    last_err: Exception = SpartanError(f"Could not connect to {host}:{port}")
    reader = writer = None
    for _af, _socktype, _proto, _cname, sockaddr in infos:
        ip = sockaddr[0]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout,
            )
            break
        except (asyncio.TimeoutError, OSError) as e:
            last_err = e
            continue

    if writer is None:
        if isinstance(last_err, asyncio.TimeoutError):
            raise SpartanError(f"Connection to {host}:{port} timed out")
        raise SpartanError(f"Could not connect to {host}:{port}: {last_err}")

    try:
        request_line = f"{host} {path} {len(body)}\r\n"
        writer.write(request_line.encode("utf-8"))
        if body:
            writer.write(body)
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        raw_line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        response_line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")

        if not response_line:
            raise SpartanError("Empty response from server")

        space_idx = response_line.find(" ")
        if space_idx < 1:
            raise SpartanError(f"Malformed response line: {response_line!r}")

        try:
            status = int(response_line[:space_idx])
        except ValueError:
            raise SpartanError(f"Invalid status code: {response_line[:space_idx]!r}")

        meta = response_line[space_idx + 1:].strip()

        if status == 2:
            resp_body = await asyncio.wait_for(reader.read(), timeout=60.0)
            return status, meta, resp_body
        return status, meta, b""

    except asyncio.TimeoutError:
        raise SpartanError(f"Timed out communicating with {host}:{port}")
    except OSError as e:
        raise SpartanError(f"I/O error: {e}")
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except Exception:
            pass
