"""The DTLS source-port strategy and the recovery it exists for.

Binding one stable source port per device is what makes an appliance evict the
association a previous run left behind (RFC 6347 4.2.8). Some firmware does not
do that eviction: it reads our plaintext ClientHello as a record inside the epoch
it still thinks is live, cannot parse it, and answers

    DTLS handshake error (SSL routines, tlsv1 alert decode error)

which no amount of retrying on that same port will clear. These tests pin the two
halves of the escape hatch — recognising that alert, and having somewhere else to
go — because both are silent when broken: the symptom is one device that never
reconnects while every other device is fine.
"""

import ipaddress

import pytest

from lib.const import DTLS_LOCAL_PORT_BASES
from lib.probe import local_source_port, peer_holds_stale_session

# The alert as pyOpenSSL surfaces it, and the message the user actually saw.
OBSERVED_FAILURE = (
    "DTLS handshake error ([('SSL routines', '', 'tlsv1 alert decode error')])"
)


def test_the_observed_failure_is_recognised():
    assert peer_holds_stale_session(OBSERVED_FAILURE)


@pytest.mark.parametrize(
    "message",
    [
        "[('SSL routines', '', 'tlsv1 alert decode error')]",
        "[('SSL routines', '', 'unexpected message')]",
        "[('SSL routines', '', 'decryption failed or bad record mac')]",
        "[('SSL routines', '', 'tlsv1 alert illegal parameter')]",
        "[('SSL routines', '', 'sslv3 alert handshake failure')]",
    ],
)
def test_peer_side_alerts_are_recognised(message):
    assert peer_holds_stale_session(Exception(message))


@pytest.mark.parametrize(
    "message",
    [
        # A real certificate problem: escalating the source port would turn one
        # clear error into three slow ones and hide the actual cause.
        "[('SSL routines', '', 'certificate verify failed')]",
        "[('SSL routines', '', 'tlsv1 alert unknown ca')]",
        "[Errno 65] No route to host",
        "GET /device/0 -> 4.04",
        "timed out",
    ],
)
def test_other_failures_are_not_treated_as_stale_sessions(message):
    assert not peer_holds_stale_session(Exception(message))


def test_first_attempt_is_the_stable_port():
    """Attempt 0 must stay the deterministic choice, or the eviction that makes
    the whole scheme work stops happening on the common path."""
    assert local_source_port("192.168.1.90") == DTLS_LOCAL_PORT_BASES[0] + 90
    assert local_source_port("192.168.1.90", 0) == local_source_port("192.168.1.90")


def test_each_attempt_moves_to_a_different_port():
    ports = [
        local_source_port("192.168.1.90", n) for n in range(len(DTLS_LOCAL_PORT_BASES))
    ]
    assert len(set(ports)) == len(ports), ports


def test_retry_ports_cannot_collide_with_another_devices_first_choice():
    """A retry port landing on some other device's attempt-0 port would make two
    devices share a source port, and the library's socket is unconnected — they
    would mis-demux each other's datagrams. So the windows must not overlap."""
    windows = [range(base, base + 256) for base in DTLS_LOCAL_PORT_BASES]
    for i, first in enumerate(windows):
        for second in windows[i + 1 :]:
            assert not set(first) & set(second), (first, second)


def test_every_address_on_a_24_gets_its_own_port_in_every_window():
    for attempt in range(len(DTLS_LOCAL_PORT_BASES)):
        ports = {
            local_source_port(str(ipaddress.IPv4Address(f"192.168.1.{n}")), attempt)
            for n in range(256)
        }
        assert len(ports) == 256, f"attempt {attempt} collided"


def test_attempt_wraps_rather_than_raising():
    """Callers loop over range(len(BASES)); an off-by-one must not crash a
    reconnect path that is already handling an error."""
    beyond = len(DTLS_LOCAL_PORT_BASES)
    assert local_source_port("192.168.1.90", beyond) == local_source_port(
        "192.168.1.90", 0
    )
