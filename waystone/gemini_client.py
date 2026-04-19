"""Async Gemini protocol client."""

import asyncio
import hashlib
import os
import ssl
import tempfile
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass
class GeminiResponse:
    status: int
    meta: str
    body: bytes
    fingerprint: str   # SHA-256 hex of DER-encoded leaf cert


class GeminiError(Exception):
    pass


async def fetch(
    url: str,
    timeout: float = 15.0,
    cert_pem: Optional[bytes] = None,
    key_pem: Optional[bytes] = None,
) -> GeminiResponse:
    """
    Perform a single Gemini request and return the response.
    Does NOT follow redirects — caller handles that.
    Pass cert_pem + key_pem (PEM bytes) to send a client certificate.
    Raises GeminiError on connection/protocol failure.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 1965

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    if cert_pem and key_pem:
        # ssl module requires file paths; write temp files and delete immediately
        # after load_cert_chain (certs are copied into memory by OpenSSL).
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

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise GeminiError(f"Connection to {host}:{port} timed out")
    except OSError as e:
        raise GeminiError(f"Could not connect to {host}:{port}: {e}")

    # Capture cert fingerprint before sending anything
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
        header = raw_header.decode("utf-8", errors="replace").rstrip("\r\n")

        if len(header) < 2:
            raise GeminiError("Invalid or empty response header")

        try:
            status = int(header[:2])
        except ValueError:
            raise GeminiError(f"Non-numeric status code: {header[:2]!r}")

        meta = header[3:].strip() if len(header) > 3 else ""

        body = b""
        if status // 10 == 2:
            body = await asyncio.wait_for(reader.read(), timeout=60.0)

    except asyncio.TimeoutError:
        raise GeminiError("Timed out waiting for server response")
    except OSError as e:
        raise GeminiError(f"Read error: {e}")
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=2.0)
        except Exception:
            pass

    return GeminiResponse(status=status, meta=meta, body=body, fingerprint=fingerprint)
