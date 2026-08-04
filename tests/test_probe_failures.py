"""Which failure pairing reports, and why the certificate case is separable.

Adding a device by address used to answer nearly every failure with one English
sentence: nothing at that address, an appliance on cloud-only firmware, one still
holding the previous session, and one that will not accept our certificate all read
alike. Only one of those is fixed by checking the address, and the certificate one is
now fixable with a button in the app settings — so telling them apart is worth more
than it was.

The split rests on a measurement rather than on an alert code: this hardware rejects
a certificate by *completing* the handshake and then answering nothing (see
lib/cert.py, where that is what made the identifier-not-signature finding testable).
So the discriminator is whether a session ever came up, which is what these pin.
"""

import pytest

from lib import probe


class _FakeSession:
    """Stands in for DtlsCoapSession. `fail_at` decides how far it gets."""

    def __init__(self, fail_at, exception):
        self.fail_at = fail_at
        self.exception = exception
        self.closed = False

    def connect(self):
        if self.fail_at == "connect":
            raise self.exception

    def start_reader(self):
        pass

    def get(self, _path, timeout=None):
        if self.fail_at == "get":
            raise self.exception
        return 0x45, b""

    def close(self):
        self.closed = True


def _install(monkeypatch, *, nominated=(49153,), rescued=(), live=True,
             fail_at="get", exception=None):
    exception = exception or TimeoutError("timed out")
    sessions = []

    def session_factory(*_args, **_kwargs):
        session = _FakeSession(fail_at, exception)
        sessions.append(session)
        return session

    monkeypatch.setattr(probe, "sweep_ports",
                        lambda host: (list(nominated), list(rescued)))
    monkeypatch.setattr(probe, "speaks_dtls", lambda host, port: live)
    monkeypatch.setattr(probe, "DtlsCoapSession", session_factory)
    return sessions


def _failure(monkeypatch, **kwargs):
    _install(monkeypatch, **kwargs)
    with pytest.raises(probe.ProbeFailure) as caught:
        probe.probe("192.0.2.10", "cert", "key")
    return caught.value


def test_nothing_answering_the_sweep_is_reported_as_no_response(monkeypatch):
    failure = _failure(monkeypatch, nominated=(), rescued=())
    assert failure.error_key == "error.probe_no_response"
    assert failure.params == {"host": "192.0.2.10"}


def test_ports_that_answer_but_speak_no_dtls_are_reported_separately(monkeypatch):
    """The cloud-only-firmware case. Telling the user to check the address here
    sends them after the wrong thing."""
    failure = _failure(monkeypatch, live=False)
    assert failure.error_key == "error.probe_no_dtls_server"


def test_a_handshake_that_never_completes_is_not_blamed_on_the_certificate(
        monkeypatch):
    failure = _failure(
        monkeypatch, fail_at="connect",
        exception=Exception("[('SSL routines', '', 'tlsv1 alert decode error')]"))
    assert failure.error_key == "error.probe_handshake_refused"


def test_a_session_that_comes_up_and_answers_nothing_points_at_the_certificate(
        monkeypatch):
    failure = _failure(monkeypatch, fail_at="get")
    assert failure.error_key == "error.probe_certificate_refused"


def test_the_certificate_verdict_needs_a_completed_handshake_not_just_a_live_port(
        monkeypatch):
    """A live port with a refused handshake must not read as a certificate problem:
    that would send the user to re-issue a certificate that was never the issue."""
    handshake = _failure(monkeypatch, fail_at="connect",
                         exception=Exception("[Errno 65] No route to host"))
    assert handshake.error_key == "error.probe_handshake_refused"


def test_a_rescued_port_still_reaches_the_certificate_verdict(monkeypatch):
    """Rescued ports skip the liveness check, so they take a different path into the
    handshake and must land in the same bucket."""
    failure = _failure(monkeypatch, nominated=(), rescued=(49153,), live=False)
    assert failure.error_key == "error.probe_certificate_refused"


def test_every_session_is_closed_even_when_the_attempt_fails(monkeypatch):
    sessions = _install(monkeypatch)
    with pytest.raises(probe.ProbeFailure):
        probe.probe("192.0.2.10", "cert", "key")
    assert sessions and all(s.closed for s in sessions)


def test_the_failure_keeps_the_detail_for_the_log(monkeypatch):
    """The user gets the translated sentence; whoever reads the log needs the port
    and the underlying error."""
    failure = _failure(monkeypatch)
    assert "192.0.2.10" in str(failure)
    assert "timed out" in str(failure)


def test_a_successful_probe_still_returns_the_device(monkeypatch):
    """The classification must not have turned the working path into a failure."""
    monkeypatch.setattr(probe, "sweep_ports", lambda host: ([49153], []))
    monkeypatch.setattr(probe, "speaks_dtls", lambda host, port: True)
    monkeypatch.setattr(probe, "parse_device0", lambda _payload: {"/oic/d": {}})
    monkeypatch.setattr(probe, "read_serial", lambda *a, **k: "SERIAL")
    monkeypatch.setattr(probe, "cbor2", type("C", (), {"loads": staticmethod(
        lambda _b: {})})())
    monkeypatch.setattr(probe, "_read_device_types", lambda _session: ())

    class _Working(_FakeSession):
        def get(self, _path, timeout=None):
            return 0x45, b"\xa0"

    monkeypatch.setattr(probe, "DtlsCoapSession",
                        lambda *a, **k: _Working(None, None))
    result = probe.probe("192.0.2.10", "cert", "key")
    assert result["port"] == 49153
    assert result["serial"] == "SERIAL"
