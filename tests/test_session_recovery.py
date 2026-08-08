"""Reads recovered from a dead session and writes did not.

Samsung's firmware closes a session between polls — `_get` has reconnected around
that since early on, which is why polling looks reliable. `write` did not, so a
command issued into a session that had just been closed was lost, and the only
sign was an error on a tile the user had just touched. The asymmetry was the bug:
the same appliance, the same socket, two code paths that disagreed about whether a
dropped session is recoverable.

The second test is the boundary that keeps the fix from becoming its own bug. A
reply carrying a non-success code is the appliance *answering* — the induction
cooktop returns 4.05 to every write it will never accept — so re-sending asks a
second time for something already refused, on a session that was never dead.
"""

import asyncio

import pytest

from lib.session import Session

CHANGED = 0x44  # 2.04
METHOD_NOT_ALLOWED = 0x85  # 4.05


class FakeCoapSession:
    """Stands in for DtlsCoapSession. Records posts and can fail the first one."""

    def __init__(self, fail_first=False, code=CHANGED):
        self.fail_first = fail_first
        self.code = code
        self.posts = []
        self.closed = False

    def post(self, path_segs, payload, timeout=None):
        self.posts.append(list(path_segs))
        if self.fail_first and len(self.posts) == 1:
            raise ConnectionError("send failed: session is gone")
        return self.code, b""

    def close(self):
        self.closed = True


def build_session(monkeypatch, sessions):
    """A Session whose connect hands out `sessions` in order."""
    made = iter(sessions)
    session = Session("10.0.0.1", 5683, "cert", "key", log=lambda *_: None)

    async def fake_connect():
        if session._session is None:
            session._session = next(made)

    monkeypatch.setattr(session, "_connect_unlocked", fake_connect)
    return session


def test_a_write_into_a_dead_session_reconnects_and_retries(monkeypatch):
    dead = FakeCoapSession(fail_first=True)
    fresh = FakeCoapSession()
    session = build_session(monkeypatch, [dead, fresh])

    asyncio.run(session.write(["mode", "vs", "0"], {"x": 1}))

    # The dead one was closed rather than left holding the source port, and the
    # command actually reached the appliance on the session that replaced it.
    assert dead.closed
    assert fresh.posts == [["mode", "vs", "0"]]


def test_a_refusal_is_not_retried(monkeypatch):
    """4.05 is an answer, not a dropped session. Sending it twice helps nobody and
    doubles what the appliance is asked to refuse."""
    refusing = FakeCoapSession(code=METHOD_NOT_ALLOWED)
    session = build_session(monkeypatch, [refusing])

    with pytest.raises(ConnectionError):
        asyncio.run(session.write(["cooktop", "status", "vs", "0"], {"power": "Off"}))

    assert len(refusing.posts) == 1
    assert not refusing.closed


def test_a_write_that_fails_twice_still_raises(monkeypatch):
    """One retry, not a loop. The caller has to hear about a write that never
    landed — a silently swallowed failure is what made this class of bug invisible
    upstream."""

    class AlwaysFails(FakeCoapSession):
        def post(self, path_segs, payload, timeout=None):
            self.posts.append(list(path_segs))
            raise ConnectionError("still gone")

    first, second = AlwaysFails(), AlwaysFails()
    session = build_session(monkeypatch, [first, second])

    with pytest.raises(ConnectionError):
        asyncio.run(session.write(["mode", "vs", "0"], {"x": 1}))

    assert len(first.posts) == 1
    assert len(second.posts) == 1
