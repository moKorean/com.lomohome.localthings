"""Leaf certificate minting.

Samsung appliances grant full local access (`perm=31` on `href=*`) to the UUID
published in Samsung's own cloud-gateway TLS certificate subject. A cert
carrying that UUID and signed by the AC14K_M intermediate CA is what the
appliance accepts, so the app mints one per device from the CA the user supplied
once. See docs/CA-SETUP.md.

Everything here is pure `cryptography` — deliberately no `openssl` subprocess,
unlike the upstream `setup_cert.py`, because the Homey app container has no
openssl CLI. This mirrors the reference integration's config_flow, which does
the same for the same reason.
"""

import datetime
import re
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .const import SAMSUNG_CLOUD_HOST, SAMSUNG_CLOUD_PORT

_CERT_BLOCK_RE = re.compile(
    r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)", re.DOTALL
)
_UUID_RE = re.compile(r"uuid:([0-9a-f-]+)", re.IGNORECASE)


class InvalidCA(Exception):
    """The supplied CA cert/key could not be loaded or don't pair."""


def fetch_samsung_uuid(timeout: float = 15.0) -> str:
    """Read the peer UUID from Samsung's cloud gateway TLS certificate.

    Verification is disabled on purpose: the chain contains a self-signed cert,
    and we only read the subject rather than trusting it. Nothing is sent — this
    is a handshake and a certificate read.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with socket.create_connection(
        (SAMSUNG_CLOUD_HOST, SAMSUNG_CLOUD_PORT), timeout=timeout
    ) as raw:
        with ctx.wrap_socket(raw, server_hostname=SAMSUNG_CLOUD_HOST) as tls:
            der = tls.getpeercert(binary_form=True)

    cert = x509.load_der_x509_certificate(der)
    for attr in cert.subject:
        if attr.oid == NameOID.ORGANIZATIONAL_UNIT_NAME:
            match = _UUID_RE.search(str(attr.value))
            if match:
                return match.group(1).lower()
    raise RuntimeError(
        f"No uuid: token in {SAMSUNG_CLOUD_HOST} certificate subject"
    )


def validate_ca(ca_cert_pem: str, ca_key_pem: str) -> None:
    """Raise InvalidCA unless the PEMs load and the key matches the cert.

    Checked at the point the user pastes them, so a typo surfaces there instead
    of as an opaque handshake failure during pairing.
    """
    ca_cert, ca_key = _load_ca(ca_cert_pem, ca_key_pem)
    if ca_cert.public_key().public_numbers() != ca_key.public_key().public_numbers():
        raise InvalidCA("CA certificate and private key do not pair")


def _load_ca(ca_cert_pem: str, ca_key_pem: str):
    match = _CERT_BLOCK_RE.search(ca_cert_pem or "")
    if not match:
        raise InvalidCA("No certificate block found in the CA certificate PEM")
    try:
        ca_cert = x509.load_pem_x509_certificate(match.group(1).encode())
    except Exception as exc:
        raise InvalidCA(f"Could not load CA certificate: {exc}") from exc
    try:
        ca_key = serialization.load_pem_private_key(
            (ca_key_pem or "").encode(), password=None
        )
    except Exception as exc:
        raise InvalidCA(f"Could not load CA private key: {exc}") from exc
    return ca_cert, ca_key


def mint_leaf(ca_cert_pem: str, ca_key_pem: str, uuid: str) -> tuple[str, str]:
    """Mint a fresh RSA-2048 leaf signed by the CA.

    Returns (fullchain_pem, leaf_key_pem). fullchain_pem is the leaf followed by
    the CA PEM as given, which is the order use_certificate_chain_file wants.

    Signed with SHA-256, following the reference integration. Upstream's
    standalone setup_cert.py uses SHA-1 instead; both are accepted by the
    devices tested, and SHA-256 is the maintained path.
    """
    ca_cert, ca_key = _load_ca(ca_cert_pem, ca_key_pem)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    now = datetime.datetime.now(datetime.timezone.utc)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([
                x509.NameAttribute(NameOID.COUNTRY_NAME, "KR"),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"uuid:{uuid}"),
                x509.NameAttribute(NameOID.COMMON_NAME, f"urn:uuid:{uuid}"),
            ])
        )
        .issuer_name(ca_cert.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=10 * 365))
        .sign(ca_key, hashes.SHA256())
    )

    leaf_cert_pem = leaf.public_bytes(serialization.Encoding.PEM).decode()
    leaf_key_pem = leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()

    # Guarantee a newline between the blocks whether or not the pasted CA PEM
    # ended with one.
    fullchain = leaf_cert_pem.rstrip("\n") + "\n" + (ca_cert_pem or "")
    if not fullchain.endswith("\n"):
        fullchain += "\n"
    return fullchain, leaf_key_pem
