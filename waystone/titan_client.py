"""Async Titan protocol client (upload to Gemini capsules via TLS)."""

import asyncio
import hashlib
import socket
from urllib.parse import urlparse

from .gemini_client import _get_anon_ctx, GeminiStream, GeminiHeader, GeminiError

DEFAULT_PORT = 1965


async def upload(
    url: str,
    body: bytes,
    token: str = "",
    mime: str = "text/plain",
    timeout: float = 15.0,
) -> GeminiStream:
    """
    Upload *body* to a titan:// URL.
    Returns a GeminiStream whose header carries the server's Gemini-style response.
    The caller must read and close the stream.
    """
    # Strip any params that may already be on the URL before we append ours.
    base_url = url.split(";")[0]
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    port = parsed.port or DEFAULT_PORT

    params = [f"size={len(body)}", f"mime={mime}"]
    if token:
        params.append(f"token={token}")
    request_url = base_url + ";" + ";".join(params)

    ctx = _get_anon_ctx()

    loop = asyncio.get_event_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise GeminiError(f"DNS lookup for {host} timed out")
    except OSError as e:
        raise GeminiError(f"Could not resolve {host}: {e}")

    if not infos:
        raise GeminiError(f"No addresses found for {host}")

    infos.sort(key=lambda i: 0 if i[0] == socket.AF_INET else 1)

    last_err: Exception = GeminiError(f"Could not connect to {host}:{port}")
    reader = writer = None
    for _af, _socktype, _proto, _cname, sockaddr in infos:
        ip = sockaddr[0]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=ctx, server_hostname=host),
                timeout=timeout,
            )
            break
        except (asyncio.TimeoutError, OSError) as e:
            last_err = e
            continue

    if writer is None:
        if isinstance(last_err, asyncio.TimeoutError):
            raise GeminiError(f"Connection to {host}:{port} timed out")
        raise GeminiError(f"Could not connect to {host}:{port}: {last_err}")

    ssl_obj = writer.get_extra_info("ssl_object")
    der = ssl_obj.getpeercert(binary_form=True)
    if not der:
        writer.close()
        raise GeminiError(f"Server at {host}:{port} presented no certificate")
    fingerprint = hashlib.sha256(der).hexdigest()

    try:
        writer.write(f"{request_url}\r\n".encode("utf-8"))
        writer.write(body)
        await asyncio.wait_for(writer.drain(), timeout=timeout)

        raw_header = await asyncio.wait_for(reader.readline(), timeout=timeout)
        header_str = raw_header.decode("utf-8", errors="replace").rstrip("\r\n")

        if len(header_str) < 2:
            writer.close()
            raise GeminiError("Invalid or empty response header")

        try:
            status = int(header_str[:2])
        except ValueError:
            writer.close()
            raise GeminiError(f"Non-numeric status code: {header_str[:2]!r}")

        meta = header_str[3:].strip() if len(header_str) > 3 else ""

    except asyncio.TimeoutError:
        writer.close()
        raise GeminiError("Timed out waiting for server response")
    except OSError as e:
        writer.close()
        raise GeminiError(f"Read error: {e}")

    return GeminiStream(GeminiHeader(status, meta, fingerprint), reader, writer)
