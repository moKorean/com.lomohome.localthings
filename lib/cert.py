"""Client certificate handling.

Samsung appliances grant full local access (`perm=31` on `href=*`) to the UUID
published in Samsung's own cloud-gateway TLS certificate subject. **What the
appliance checks is that UUID, not who signed the certificate** — measured
2026-08-03, and it is why this app can issue its own.

The measurement: a certificate carrying the right UUID and the extension profile
below, signed by a CA generated on the spot, was accepted by an air conditioner
and a refrigerator — live reads through the app, not merely a completed
handshake. SHA-256 worked as well as the SHA-1 the real chain uses. So the
AC14K_M intermediate CA, whose private key upstream's `setup_cert.py` downloads
in order to sign, is not needed at all: no CA key is fetched, bundled, pasted or
stored, and `mint_self_signed` needs nothing but the UUID.

That reverses this file's earlier premise, which said the appliance accepts a
certificate "signed by the AC14K_M intermediate CA". It does accept those — the
user can still paste one, and that takes precedence — but the signature is not
what it verifies. Note what this implies about the appliances: anything on the
LAN can mint an equivalent certificate, since the UUID is public. That was
already true (AC14K_M's key has been public for years); issuing locally does not
widen it.

Because the UUID comes from Samsung's gateway rather than from the appliance, one
certificate works for every appliance on the network; it is per-installation, not
per-device. See docs/CA-SETUP.md.

Everything here is pure `cryptography`: the app container has no openssl CLI, so
the subprocess approach upstream's script uses is unavailable. Signing is SHA-256
deliberately — `cryptography` 49 refuses to sign with SHA-1 at all, and since the
appliance does not verify the signature there is nothing to gain from the
pyOpenSSL detour that would be needed to produce one.
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


# The profile below is copied field-for-field from a working appliance
# certificate, because the minimum the appliance actually requires has not been
# isolated — only that this whole shape works. Reproducing it exactly is the
# conservative choice; trimming it would be a guess.
_ISSUER = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "KR"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
    x509.NameAttribute(NameOID.COMMON_NAME, "AC14K_M"),
    x509.NameAttribute(NameOID.EMAIL_ADDRESS, "AC14K_M@samsung.com"),
])
# Samsung's own OCF extensions. 1.3.6.1.4.1.51414.0.1.2 sits alongside the
# standard client/server auth OIDs in the real certificate's EKU;
# 1.3.6.1.4.1.51414.1.3 carries the UTF8String "samsung.role.hub".
_OCF_EKU_OID = x509.ObjectIdentifier("1.3.6.1.4.1.51414.0.1.2")
_OCF_ROLE_OID = x509.ObjectIdentifier("1.3.6.1.4.1.51414.1.3")
_OCF_ROLE_DER = b"\x0c\x10samsung.role.hub"
_KEY_SIZE = 2048
_VALID_YEARS = 10
# Backdated an hour so a Homey whose clock is slightly behind the appliance's does
# not reject its own freshly issued certificate as not-yet-valid.
_BACKDATE = datetime.timedelta(hours=1)


def _subject_for(uuid: str) -> x509.Name:
    """Subject RDNs in the order the real certificate uses.

    The appliance scans the subject for a `uuid:` token (see `_uuid_from_subject`),
    so OU is what matters; CN, O and C are reproduced for fidelity.
    """
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, f"uuid:{uuid}"),
        x509.NameAttribute(NameOID.COMMON_NAME, f"urn:uuid:{uuid}"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Samsung Electronics"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "KR"),
    ])


def mint_self_signed(uuid: str) -> tuple[str, str]:
    """Issue a client certificate for `uuid`, needing nothing else.

    Returns (fullchain_pem, key_pem) ready for `inspect_leaf` and storage: a leaf
    plus the CA generated here to sign it. Two blocks rather than one because the
    appliance is given a chain and `inspect_leaf` requires one — that CA is
    otherwise inert, and its key is discarded when this returns.

    Raises InvalidCredentials if `uuid` is not a UUID, so a bad value from the
    gateway cannot produce a certificate that would fail later at pairing.
    """
    if not _UUID_RE.fullmatch(f"uuid:{(uuid or '').strip()}"):
        raise InvalidCredentials(
            f"{uuid!r} is not a UUID, so no certificate can be issued for it."
        )
    uuid = uuid.strip().lower()

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    not_before = datetime.datetime.now(datetime.UTC) - _BACKDATE
    not_after = not_before + datetime.timedelta(days=365 * _VALID_YEARS)

    ca = (
        x509.CertificateBuilder()
        .subject_name(_ISSUER).issuer_name(_ISSUER)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before).not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    leaf = (
        x509.CertificateBuilder()
        .subject_name(_subject_for(uuid)).issuer_name(_ISSUER)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before).not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_encipherment=True,
                content_commitment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False, crl_sign=False,
                encipher_only=False, decipher_only=False,
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([
                x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                _OCF_EKU_OID,
            ]),
            critical=False,
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.UniformResourceIdentifier(f"urn:uuid:{uuid}"),
                x509.UniformResourceIdentifier(f"uri:uuid:{uuid}"),
                x509.UniformResourceIdentifier(f"uuid:{uuid}"),
                x509.DNSName(uuid),
            ]),
            critical=False,
        )
        .add_extension(
            x509.UnrecognizedExtension(_OCF_ROLE_OID, _OCF_ROLE_DER),
            critical=False,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    pem = serialization.Encoding.PEM
    fullchain = (
        leaf.public_bytes(pem).decode() + ca.public_bytes(pem).decode()
    )
    key_pem = leaf_key.private_bytes(
        pem,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return fullchain, key_pem


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
