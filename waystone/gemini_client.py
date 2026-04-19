"""Async Gemini protocol client."""

import asyncio
import hashlib
import os
import ssl
import tempfile
from dataclasses import dataclass
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

@dataclass
class GeminiHeader:
    """Response header — available immediately after connection, before body."""
    status: int
    meta: str
    fingerprint: str   # SHA-256 hex of DER-encoded server cert


@dataclass
class GeminiResponse:
    """Complete response (header + buffered body).  Used by fetch()."""
    status: int
    meta: str
    body: bytes
    fingerprint: str


class GeminiError(Exception):
    pass


# ---------------------------------------------------------------------------
# SSL context management
#
# Re-using the same SSLContext object across requests lets OpenSSL cache TLS
# sessions.  On a resumed session the handshake takes one fewer round-trip,
# which matters most when a relay adds a second TLS hop between us and the
# origin capsule.
# ---------------------------------------------------------------------------

_ANON_CTX: Optional[ssl.SSLContext] = None


def _get_anon_ctx() -> ssl.SSLContext:
    """Return (or lazily create) the shared anonymous SSL context."""
    global _ANON_CTX
    if _ANON_CTX is None:
        _ANON_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        _ANON_CTX.check_hostname = False
        _ANON_CTX.verify_mode = ssl.CERT_NONE
    return _ANON_CTX


def _make_cert_ctx(cert_pem: bytes, key_pem: bytes) -> ssl.SSLContext:
    """Create a fresh SSL context with the given client certificate loaded."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # ssl module requires file paths; write to temp files and delete immediately
    # after load_cert_chain — OpenSSL copies the data into memory.
    cf = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    cf.write(cert_pem)
    cf.close()
    kf = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    kf.write(key_pem)
    kf.close()
    try:
        ctx.load_cert_chain(certfile=cf.name, keyfile=kf.name)
    except ssl.SSLError as e:
        raise GeminiError(f"Invalid client certificate: {e}") from e
    finally:
        os.unlink(cf.name)
        os.unlink(kf.name)
    return ctx


# ---------------------------------------------------------------------------
# Streaming connection
# ---------------------------------------------------------------------------

class GeminiStream:
    """
    An open Gemini connection.

    The response header is available immediately via ``.header``.
    The body can be consumed either incrementally via ``chunks()`` or all
    at once via ``read_all()``.  Always close the stream when done — use
    ``async with`` or call ``aclose()`` explicitly.
    """

    def __init__(
        self,
        header: GeminiHeader,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.header = header
        self._reader = reader
        self._writer = writer
        self._closed = False

    async def chunks(
        self, size: int = 65536, timeout: float = 30.0
    ) -> AsyncGenerator[bytes, None]:
        """
        Async generator yielding raw body bytes chunks as they arrive.
        Raises GeminiError on timeout or I/O failure.
        Does NOT close the stream — the caller (or ``async with``) does that.
        """
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._reader.read(size), timeout=timeout
                )
            except asyncio.TimeoutError:
                raise GeminiError("Timed out waiting for body data")
            except OSError as e:
                raise GeminiError(f"Read error: {e}")
            if not chunk:
                break
            yield chunk

    async def read_all(self, timeout: float = 60.0) -> bytes:
        """Read the entire body into memory (for binary downloads)."""
        try:
            return await asyncio.wait_for(self._reader.read(), timeout=timeout)
        except asyncio.TimeoutError:
            raise GeminiError("Timed out reading response body")
        except OSError as e:
            raise GeminiError(f"Read error: {e}")
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception:
                pass

    async def __aenter__(self) -> "GeminiStream":
        return self

    async def __aexit__(self, *_) -> None:
        await self.aclose()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def open_request(
    url: str,
    timeout: float = 15.0,
    cert_pem: Optional[bytes] = None,
    key_pem: Optional[bytes] = None,
) -> GeminiStream:
    """
    Open a Gemini request and return a GeminiStream with the response header
    already parsed.  The caller must read the body and close the stream.

    Raises GeminiError on connection or protocol failure.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 1965

    ctx = _make_cert_ctx(cert_pem, key_pem) if (cert_pem and key_pem) else _get_anon_ctx()

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise GeminiError(f"Connection to {host}:{port} timed out")
    except OSError as e:
        raise GeminiError(f"Could not connect to {host}:{port}: {e}")

    ssl_obj = writer.get_extra_info("ssl_object")
    der = ssl_obj.getpeercert(binary_form=True)
    if not der:
        writer.close()
        raise GeminiError(f"Server at {host}:{port} presented no certificate")
    fingerprint = hashlib.sha256(der).hexdigest()

    try:
        writer.write(f"{url}\r\n".encode("utf-8"))
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


async def fetch(
    url: str,
    timeout: float = 15.0,
    cert_pem: Optional[bytes] = None,
    key_pem: Optional[bytes] = None,
) -> GeminiResponse:
    """
    Convenience wrapper: open a request, buffer the entire body, return a
    GeminiResponse.  Use open_request() directly when streaming is needed.
    """
    stream = await open_request(url, timeout=timeout, cert_pem=cert_pem, key_pem=key_pem)
    body = b""
    if stream.header.status // 10 == 2:
        body = await stream.read_all()   # closes stream when done
    else:
        await stream.aclose()
    return GeminiResponse(
        status=stream.header.status,
        meta=stream.header.meta,
        body=body,
        fingerprint=stream.header.fingerprint,
    )
