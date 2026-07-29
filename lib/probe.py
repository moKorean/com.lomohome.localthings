"""UDP liveness sweep and the /device/0 probe used during pairing."""

import contextlib
import ipaddress
import socket
import zlib

import cbor2
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from .const import (
    DTLS_LOCAL_PORT_BASES,
    LIVENESS_PROBE_TIMEOUT_S,
    PREFERRED_PROBE_PORTS,
    PROBE_GET_TIMEOUT_S,
    PROBE_PORT_RANGE,
)
from .resources import parse_device0, read_serial

# Fatal alerts the appliance sends when it is reading our plaintext handshake
# against an association it still believes is live — the aftermath of a previous
# run that died without close_notify. The handshake never completes, and it never
# will on that 5-tuple, so these are the signal to move to another source port
# rather than to keep retrying or to give up. Matched on the message text because
# pyOpenSSL surfaces the alert only as the third element of an SSL.Error tuple.
_STALE_PEER_ALERTS = (
    "decode error",        # alert 50 — could not parse the record it received
    "unexpected message",  # alert 10 — right record, wrong epoch to expect it in
    "bad record mac",      # alert 20 — decrypted our plaintext against old keys
    "illegal parameter",   # alert 47
    "handshake failure",   # alert 40
)


def peer_holds_stale_session(exc: BaseException) -> bool:
    """Whether `exc` is the appliance rejecting a handshake it has stale state for."""
    text = str(exc).lower()
    return any(alert in text for alert in _STALE_PEER_ALERTS)


def local_source_port(host: str, attempt: int = 0) -> int:
    """Deterministic UDP source port for this device's DTLS socket.

    Must be stable across restarts and unique per device on this Homey: the
    library's socket is unconnected (recvfrom), so two devices sharing a source
    port would mis-demux each other's datagrams. For the usual dotted-IPv4 host
    the last octet is the offset (unique on a /24); anything else folds a stable
    CRC32 into the same 256-wide window.

    `attempt` selects which base that offset is added to. Attempt 0 is the
    stable choice and the only one used in normal operation; later attempts
    exist so a peer holding a stale association on the first port can be reached
    from a 5-tuple it has no state for. See DTLS_LOCAL_PORT_BASES.
    """
    try:
        offset = int(ipaddress.IPv4Address(host)) & 0xFF
    except (ipaddress.AddressValueError, ValueError):
        offset = zlib.crc32(host.encode()) & 0xFF
    base = DTLS_LOCAL_PORT_BASES[attempt % len(DTLS_LOCAL_PORT_BASES)]
    return base + offset


def find_live_ports(
    host: str, ports=None, timeout: float = LIVENESS_PROBE_TIMEOUT_S
) -> list[int]:
    """Narrow the port range before paying for a DTLS handshake.

    UDP is connectionless, but a *connected* UDP socket surfaces the ICMP
    port-unreachable a closed port returns as ECONNREFUSED. So send one probe
    datagram per port and watch for that error:

      ECONNREFUSED       -> closed (device actively rejected it)
      silence / any data -> may be live (open|filtered); a candidate

    The in-process equivalent of `nmap -sU`, minus the root requirement.
    """
    candidates = []
    for port in ports or PROBE_PORT_RANGE:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            # Contents are irrelevant; a real ClientHello is unnecessary just to
            # test for life.
            sock.send(b"\x00")
            try:
                sock.recv(4096)
                candidates.append(port)
            except TimeoutError:
                candidates.append(port)
            except ConnectionRefusedError:
                pass
        except ConnectionRefusedError:
            pass
        except OSError:
            pass
        finally:
            sock.close()
    return order_candidates(candidates)


def order_candidates(ports: list[int]) -> list[int]:
    """Try the historically known DTLS ports first."""
    preferred = [p for p in PREFERRED_PROBE_PORTS if p in ports]
    rest = sorted(p for p in ports if p not in PREFERRED_PROBE_PORTS)
    return preferred + rest


def probe(host: str, leaf_cert_pem: str, leaf_key_pem: str) -> dict:
    """Find the live port and read /device/0. Blocking; run in an executor.

    Returns {port, serial, resources}. Raises ConnectionError when no port in
    the range answers.
    """
    candidates = find_live_ports(host)
    if not candidates:
        raise ConnectionError(
            f"No live DTLS port on {host} in "
            f"{PROBE_PORT_RANGE[0]}-{PROBE_PORT_RANGE[-1]}. "
            "This may not be a supported appliance."
        )

    def attempt_once(port: int, source_attempt: int) -> dict:
        session = None
        try:
            session = DtlsCoapSession(
                host,
                port,
                cert_pem=leaf_cert_pem,
                key_pem=leaf_key_pem,
                local_port=local_source_port(host, source_attempt),
            )
            session.connect()
            session.start_reader()
            code, payload = session.get(["device", "0"], timeout=PROBE_GET_TIMEOUT_S)
            if code != 0x45 or not payload:
                raise ConnectionError(
                    f"port {port}: GET /device/0 returned {code >> 5}.{code & 0x1F:02d}"
                )
            resources = parse_device0(cbor2.loads(payload))
            return {
                "port": port,
                "serial": read_serial(resources, host, port),
                "resources": resources,
            }
        finally:
            if session is not None:
                with contextlib.suppress(Exception):
                    session.close()

    last_error = None
    for port in candidates:
        # Source-port escalation is nested inside the destination loop rather than
        # wrapped around it: an appliance holding a stale association rejects every
        # destination port identically, so retrying all of them on the same source
        # port would report "no port answered" for a device that is simply waiting
        # to be approached from a 5-tuple it has no state for.
        for source_attempt in range(len(DTLS_LOCAL_PORT_BASES)):
            try:
                return attempt_once(port, source_attempt)
            except Exception as exc:
                last_error = exc
                if not peer_holds_stale_session(exc):
                    break
    raise ConnectionError(f"No port on {host} completed a session: {last_error}")
