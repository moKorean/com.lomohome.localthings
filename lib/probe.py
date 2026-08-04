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


class ProbeFailure(ConnectionError):
    """A pairing failure that knows which of them it is.

    Every way pairing could fail used to raise one of three English sentences
    assembled here, with the underlying exception appended — so an IP with nothing
    on it, an appliance on cloud-only firmware, one still holding the last session,
    and one that will not accept our certificate all read alike, and none of them
    were translated. The reference hit the same wall and split it into a taxonomy
    (mbillow/localthings, "Replace the blanket cannot connect with a real failure
    taxonomy"); this is the same idea over our own failure modes.

    `error_key` is an i18n key the caller translates — probe() is blocking and
    language-free by design, so it names the message rather than rendering it. The
    detail stays in the exception text for the log.
    """

    def __init__(self, error_key: str, detail: str = "", **params):
        self.error_key = error_key
        self.params = params
        super().__init__(detail or error_key)


# Which bucket a failed attempt lands in depends on *when* it failed, not on the
# exception type: the appliance rejects a certificate by completing the handshake
# and then never answering (docs — the handshake is not the discriminator, measured
# while establishing that it checks the identifier and not the signature). So a
# failure before the session is up is a handshake problem, and one after it is up is
# the certificate. This is where we diverge from the reference, which reads
# certificate rejection off a handshake alert; on this hardware that alert does not
# come.
_ERR_NO_RESPONSE = "error.probe_no_response"
_ERR_NO_DTLS = "error.probe_no_dtls_server"
_ERR_HANDSHAKE = "error.probe_handshake_refused"
_ERR_CERTIFICATE = "error.probe_certificate_refused"


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
    """Every port worth a handshake, nominations and rescues together."""
    nominated, rescued = sweep_ports(host, ports, timeout)
    return nominated + rescued


def sweep_ports(
    host: str, ports=None, timeout: float = LIVENESS_PROBE_TIMEOUT_S
) -> tuple[list[int], list[int]]:
    """Narrow the port range before paying for a DTLS handshake.

    UDP is connectionless, but a *connected* UDP socket surfaces the ICMP
    port-unreachable a closed port returns as ECONNREFUSED. So send one probe
    datagram per port and watch for that error:

      ECONNREFUSED       -> closed (device actively rejected it)
      silence / any data -> may be live (open|filtered); a candidate

    The in-process equivalent of `nmap -sU`, minus the root requirement.

    Returns the sweep's own nominations and the rescued preferred ports
    separately, because only the first kind may be second-guessed — see the
    comment on `rescued` below and `speaks_dtls`.
    """
    wanted = list(ports or PROBE_PORT_RANGE)
    candidates = []
    for port in wanted:
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

    # The ICMP verdict above is not trustworthy on every network path. The
    # reference integration's issue #192 captured a device on a segregated VLAN
    # where this sweep called three closed ports live while never reporting the
    # one port a concurrent nmap found genuinely open|filtered — and that port was
    # 49154, one of the two we already have strong prior evidence for.
    #
    # So a "not live" verdict does not get to overrule that prior: the
    # historically confirmed ports always get a real handshake attempt.
    #
    # They are appended last, where the reference promotes them to the front.
    # That divergence is deliberate — the reference probes one host the user
    # typed in, while this app sweeps a whole subnet, and most of what answers is
    # not a Samsung appliance. Promoting would spend two guaranteed extra
    # handshakes on every non-appliance host that responds. Appending reaches the
    # same appliance in the #192 case, where the sweep's own candidates all fail
    # first anyway, without making a subnet scan slower for everyone else.
    rescued = [
        port for port in PREFERRED_PROBE_PORTS
        if port in wanted and port not in candidates
    ]
    return order_candidates(candidates), rescued


def order_candidates(ports: list[int]) -> list[int]:
    """Try the historically known DTLS ports first."""
    preferred = [p for p in PREFERRED_PROBE_PORTS if p in ports]
    rest = sorted(p for p in ports if p not in PREFERRED_PROBE_PORTS)
    return preferred + rest


def speaks_dtls(host: str, port: int, timeout: float = 1.0) -> bool | None:
    """Whether a real DTLS server answers on this port, or None if unknowable.

    The UDP sweep above cannot tell a silent port from a DTLS server: anything
    that does not answer with ICMP-unreachable looks live. Measured against the
    air conditioner at 192.168.1.90 it called three ports live where one was, and
    against a host that is not an appliance at all it called three live where none
    were — each of those costs a full handshake to disprove.

    A real DTLS server answers a ClientHello with a HelloVerifyRequest in about
    one round trip, before any certificate work (RFC 6347 §4.2.1), so one exchange
    settles it. The probe is stateless: the server replies without allocating an
    association, so this leaves nothing behind for the real handshake to trip over
    — which matters here, because this app pins a source port per device and an
    orphaned association would be evicted rather than ignored.

    Returns None when the question cannot be answered — the library is older than
    0.1.2 and has no probe, or the host is unreachable in a way that raises rather
    than times out. A None is treated as "try anyway" by the caller, so a failure
    to probe never removes a port the previous behaviour would have attempted.
    """
    try:
        # Imported by path, not `from ... import dtls_probe`: the submodule is not
        # re-exported from the package's __init__, so the `from` form raises
        # ImportError even where the module is present.
        import smartthings_local.protocol.dtls_probe as dtls_probe
    except Exception:
        # Not just ImportError: this is an optional accelerator, and no way for it
        # to fail loading may take pairing down with it.
        return None
    try:
        result = dtls_probe.probe(host, port, stateless=True, retries=1,
                                  timeout=timeout)
    except Exception:
        # `Host is down` and friends arrive as OSError rather than a DEAD result.
        return None
    return "LIVE" in str(getattr(result, "outcome", result)).upper()


def _read_device_types(session) -> tuple:
    """`/oic/d`'s `rt` on an open session, or `()` if the appliance will not say.

    Deliberately cannot fail the probe. `/device/0` has already succeeded by this
    point, so the appliance is reachable and pairable; a board that answers 4.04 on
    `/oic/d` must still pair on its board token, exactly as it did before this read
    existed. Turning a supplementary signal into a pairing failure would be worst on
    the unfamiliar hardware it is meant to help.
    """
    try:
        code, payload = session.get(["oic", "d"], timeout=PROBE_GET_TIMEOUT_S)
        if code != 0x45 or not payload:
            return ()
        decoded = cbor2.loads(payload)
        types = decoded.get("rt") if isinstance(decoded, dict) else None
    except Exception:
        return ()
    if isinstance(types, str):
        types = [types]
    if not isinstance(types, (list, tuple)):
        return ()
    return tuple(str(t) for t in types if str(t) != "oic.wk.d")


def probe(host: str, leaf_cert_pem: str, leaf_key_pem: str) -> dict:
    """Find the live port and read /device/0. Blocking; run in an executor.

    Returns {port, serial, resources, device_types}. Raises ConnectionError when no
    port in the range answers.
    """
    nominated, rescued = sweep_ports(host)
    candidates = nominated + rescued
    if not candidates:
        raise ProbeFailure(
            _ERR_NO_RESPONSE, host=host,
            detail=f"No live DTLS port on {host} in "
                   f"{PROBE_PORT_RANGE[0]}-{PROBE_PORT_RANGE[-1]}",
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
            # Past this line the handshake completed, so a failure from here on is
            # the certificate rather than the connection — see the note above.
            answered.add(port)
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
                "device_types": _read_device_types(session),
            }
        finally:
            if session is not None:
                with contextlib.suppress(Exception):
                    session.close()

    last_error = None
    unreachable = 0
    answered: set[int] = set()
    for port in candidates:
        # Confirm the port before paying for a handshake, and only when it is
        # about to be tried — probing them all up front would charge the common
        # case, where the first candidate is the historically correct port and
        # answers immediately.
        #
        # Only the sweep's own nominations are second-guessed. The rescued
        # preferred ports exist precisely because a liveness verdict was wrong
        # once (reference #192, a segregated VLAN), and replacing one such verdict
        # with another would put that case back.
        if port not in rescued and speaks_dtls(host, port) is False:
            unreachable += 1
            continue
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
    if last_error is None and unreachable:
        raise ProbeFailure(
            _ERR_NO_DTLS, host=host,
            detail=f"No DTLS server on {host} in "
                   f"{PROBE_PORT_RANGE[0]}-{PROBE_PORT_RANGE[-1]}",
        )
    # `answered` is what separates the two: a handshake that completed on some port
    # and then produced nothing usable points at the certificate, and that is worth
    # saying because the fix is a button in the app settings. Anything else is a
    # connection that never got up, which usually clears by itself.
    key = _ERR_CERTIFICATE if answered else _ERR_HANDSHAKE
    raise ProbeFailure(
        key, host=host,
        detail=f"No port on {host} completed a session "
               f"(handshake completed on {sorted(answered)}): {last_error}",
    )
