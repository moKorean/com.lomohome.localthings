"""Client certificate handling.

Samsung appliances grant full local access (`perm=31` on `href=*`) to the UUID
published in Samsung's own cloud-gateway TLS certificate subject. A certificate
carrying that UUID and signed by the AC14K_M intermediate CA is what the
appliance accepts.

The app takes that finished certificate, not the CA that signed it. The user
mints it once with the upstream `setup_cert.py` and pastes the result — so the
AC14K_M private key never reaches Homey and is never stored here. Because the
UUID comes from Samsung's gateway rather than from the appliance, one certificate
works for every appliance on the network; it is per-installation, not per-device.
See docs/CA-SETUP.md.

Everything here is pure `cryptography`: the app container has no openssl CLI, so
the subprocess approach upstream's script uses is unavailable.
"""

import datetime
import re
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from .const import SAMSUNG_CLOUD_HOST, SAMSUNG_CLOUD_PORT

_CERT_BLOCK_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)
_UUID_RE = re.compile(r"uuid:([0-9a-f-]{36})", re.IGNORECASE)


class InvalidCredentials(Exception):
    """The pasted certificate or key is unusable. Message is shown to the user."""


def _uuid_from_subject(cert: x509.Certificate) -> str | None:
    """The appliance locates the peer UUID by scanning the subject for 'uuid:',
    so it can sit in any RDN. Check OU first, then the whole subject."""
    for attr in cert.subject:
        if attr.oid == NameOID.ORGANIZATIONAL_UNIT_NAME:
            match = _UUID_RE.search(str(attr.value))
            if match:
                return match.group(1).lower()
    match = _UUID_RE.search(cert.subject.rfc4514_string())
    return match.group(1).lower() if match else None


def inspect_leaf(cert_pem: str, key_pem: str) -> dict:
    """Validate a pasted leaf certificate and describe it for the settings page.

    Checked here, at paste time, so a truncated copy or a mismatched pair is
    reported as such instead of surfacing later as an opaque DTLS handshake
    failure during pairing.

    Returns {uuid, expires, expired, chain_length}. Raises InvalidCredentials.
    """
    blocks = _CERT_BLOCK_RE.findall(cert_pem or "")
    if not blocks:
        raise InvalidCredentials(
            "No certificate found. Paste the full contents of "
            "client_fullchain.pem, including the BEGIN/END lines."
        )
    try:
        leaf = x509.load_pem_x509_certificate(blocks[0].encode())
    except Exception as exc:
        raise InvalidCredentials(f"Could not read the certificate: {exc}") from exc

    try:
        key = serialization.load_pem_private_key((key_pem or "").encode(), password=None)
    except Exception as exc:
        raise InvalidCredentials(
            f"Could not read the private key: {exc}. "
            "Paste the full contents of client.key. An encrypted key is not supported."
        ) from exc

    if leaf.public_key().public_numbers() != key.public_key().public_numbers():
        raise InvalidCredentials(
            "The certificate and private key do not belong together. "
            "Make sure both came from the same setup_cert.py run."
        )

    uuid = _uuid_from_subject(leaf)
    if not uuid:
        raise InvalidCredentials(
            "This certificate carries no uuid: token in its subject, so an "
            "appliance will reject it. It does not look like a setup_cert.py "
            "output."
        )

    expires = leaf.not_valid_after_utc
    if len(blocks) == 1:
        raise InvalidCredentials(
            "Only one certificate found. Paste client_fullchain.pem (the leaf "
            "plus the CA chain), not client.pem — the appliance needs the chain "
            "to verify the leaf."
        )

    return {
        "uuid": uuid,
        "expires": expires.date().isoformat(),
        "expired": expires <= datetime.datetime.now(datetime.UTC),
        "chain_length": len(blocks),
    }


def fetch_samsung_uuid(timeout: float = 15.0) -> str:
    """Read the current peer UUID from Samsung's cloud gateway certificate.

    Used only to tell the user whether their stored certificate still matches the
    UUID appliances currently expect — the app never needs this to connect, since
    the UUID is baked into the certificate they pasted.

    Verification is disabled deliberately: the chain contains a self-signed cert
    and only the subject is read, never trusted.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(
        (SAMSUNG_CLOUD_HOST, SAMSUNG_CLOUD_PORT), timeout=timeout
    ) as raw, ctx.wrap_socket(raw, server_hostname=SAMSUNG_CLOUD_HOST) as tls:
        der = tls.getpeercert(binary_form=True)
    uuid = _uuid_from_subject(x509.load_der_x509_certificate(der))
    if not uuid:
        raise RuntimeError(
            f"No uuid: token in the {SAMSUNG_CLOUD_HOST} certificate subject"
        )
    return uuid
