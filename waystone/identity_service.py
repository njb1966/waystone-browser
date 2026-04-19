"""Client certificate identity management for Gemini capsules."""

import datetime
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from .db import Database


# ---------------------------------------------------------------------------
# Standalone crypto helpers (no DB dependency)
# ---------------------------------------------------------------------------

def generate_cert(common_name: str) -> tuple[bytes, bytes]:
    """Generate a self-signed RSA-2048 certificate. Returns (cert_pem, key_pem)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def export_p12(name: str, cert_pem: bytes, key_pem: bytes,
               password: Optional[bytes] = None) -> bytes:
    """Serialize an identity to PKCS#12 bytes suitable for export."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    enc = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    return pkcs12.serialize_key_and_certificates(
        name=name.encode(),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=enc,
    )


def import_p12(data: bytes, password: Optional[bytes] = None) -> tuple[str, bytes, bytes]:
    """
    Parse a PKCS#12 blob and return (common_name, cert_pem, key_pem).
    Raises ValueError if parsing fails.
    """
    try:
        key, cert, _ = pkcs12.load_key_and_certificates(data, password)
    except Exception as exc:
        raise ValueError(f"Could not parse .p12 file: {exc}") from exc

    if cert is None or key is None:
        raise ValueError("The .p12 file does not contain a certificate and key.")

    name = "Imported"
    try:
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if attrs:
            name = attrs[0].value
    except Exception:
        pass

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return name, cert_pem, key_pem


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class IdentityService:
    """Async service for managing Gemini client certificate identities."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Identity CRUD
    # ------------------------------------------------------------------

    async def create(self, name: str) -> int:
        """Generate and store a new identity. Returns the new row id."""
        cert_pem, key_pem = generate_cert(name)
        async with self._db.conn.execute(
            "INSERT INTO identities (name, cert_pem, key_pem) VALUES (?, ?, ?)",
            (name, cert_pem.decode(), key_pem.decode()),
        ) as cur:
            identity_id = cur.lastrowid
        await self._db.conn.commit()
        return identity_id

    async def store(self, name: str, cert_pem: bytes, key_pem: bytes) -> int:
        """Store an externally-provided cert+key. Returns the new row id."""
        async with self._db.conn.execute(
            "INSERT INTO identities (name, cert_pem, key_pem) VALUES (?, ?, ?)",
            (name, cert_pem.decode(), key_pem.decode()),
        ) as cur:
            identity_id = cur.lastrowid
        await self._db.conn.commit()
        return identity_id

    async def list_all(self) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT id, name, created_at FROM identities ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def get(self, identity_id: int) -> Optional[dict]:
        """Return full identity record including cert/key PEM, or None."""
        async with self._db.conn.execute(
            "SELECT id, name, cert_pem, key_pem FROM identities WHERE id = ?",
            (identity_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def delete(self, identity_id: int) -> None:
        await self._db.conn.execute(
            "DELETE FROM identities WHERE id = ?", (identity_id,)
        )
        await self._db.conn.commit()

    async def rename(self, identity_id: int, name: str) -> None:
        await self._db.conn.execute(
            "UPDATE identities SET name = ? WHERE id = ?", (name, identity_id)
        )
        await self._db.conn.commit()

    # ------------------------------------------------------------------
    # Host → identity mapping
    # ------------------------------------------------------------------

    async def get_for_host(self, host: str, port: int = 1965) -> Optional[dict]:
        """Return the identity (with cert/key) mapped to this host, or None."""
        async with self._db.conn.execute(
            """SELECT i.id, i.name, i.cert_pem, i.key_pem
               FROM identities i
               JOIN identity_hosts ih ON ih.identity_id = i.id
               WHERE ih.host = ? AND ih.port = ?""",
            (host, port),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def assign_host(self, host: str, port: int, identity_id: int) -> None:
        await self._db.conn.execute(
            """INSERT INTO identity_hosts (host, port, identity_id) VALUES (?, ?, ?)
               ON CONFLICT(host, port) DO UPDATE SET identity_id = excluded.identity_id""",
            (host, port, identity_id),
        )
        await self._db.conn.commit()

    async def unassign_host(self, host: str, port: int) -> None:
        await self._db.conn.execute(
            "DELETE FROM identity_hosts WHERE host = ? AND port = ?", (host, port)
        )
        await self._db.conn.commit()

    async def list_hosts_for_identity(self, identity_id: int) -> list[dict]:
        async with self._db.conn.execute(
            "SELECT host, port FROM identity_hosts WHERE identity_id = ? ORDER BY host",
            (identity_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def export_p12(self, identity_id: int,
                         password: Optional[bytes] = None) -> bytes:
        identity = await self.get(identity_id)
        if not identity:
            raise ValueError(f"No identity with id={identity_id}")
        return export_p12(
            identity["name"],
            identity["cert_pem"].encode(),
            identity["key_pem"].encode(),
            password,
        )
