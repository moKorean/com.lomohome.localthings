"""Asyncio wrapper around DtlsCoapSession.

The library is thread-based: a reader thread owns the UDP socket and callers
block on a per-token Event. Homey's app runtime is asyncio, so every blocking
call goes through a worker thread, and one lock per session serialises access
because the library's rate limiter and pending-token table assume a single
logical caller.
"""

import asyncio

import cbor2
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from .const import DTLS_LOCAL_PORT_BASES, PROBE_GET_TIMEOUT_S
from .probe import local_source_port, peer_holds_stale_session
from .resources import parse_device0


class Session:
    """One sustained DTLS-CoAP session to one appliance."""

    def __init__(self, host: str, port: int, cert_pem: str, key_pem: str, log=print,
                 on_notification=None):
        self._host = host
        self._port = port
        self._cert_pem = cert_pem
        self._key_pem = key_pem
        self._log = log
        self._session = None
        self._lock = asyncio.Lock()
        # on_notification(href, rep) is invoked on the event loop, never on the
        # library's reader thread.
        self._on_notification = on_notification
        self._loop = None
        self._subscribed: set = set()

    @property
    def connected(self) -> bool:
        return self._session is not None

    async def _run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    async def connect(self) -> None:
        async with self._lock:
            await self._connect_unlocked()

    def _dispatch(self, href: str, payload: bytes) -> None:
        """OBSERVE callback. Runs on the library's reader thread, so the decoded
        update is handed to the event loop rather than acted on here."""
        loop, callback = self._loop, self._on_notification
        if loop is None or callback is None:
            return
        try:
            rep = cbor2.loads(payload) if payload else None
        except Exception:
            return
        if isinstance(rep, dict):
            loop.call_soon_threadsafe(callback, href, rep)

    async def _connect_unlocked(self) -> None:
        if self._session is not None:
            return

        self._loop = asyncio.get_running_loop()

        def build(local_port: int):
            session = DtlsCoapSession(
                self._host,
                self._port,
                cert_pem=self._cert_pem,
                key_pem=self._key_pem,
                local_port=local_port,
                on_notification=self._dispatch,
            )
            session.connect()
            session.start_reader()
            return session

        # Attempt 0 is the stable source port. A peer that rejects the handshake
        # because it is still holding the previous association gets one more try
        # per remaining port window; every other failure propagates immediately,
        # because retrying a bad certificate or an unreachable host on a new port
        # only turns one clear error into three slow ones.
        last_attempt = len(DTLS_LOCAL_PORT_BASES) - 1
        for attempt in range(len(DTLS_LOCAL_PORT_BASES)):
            local_port = local_source_port(self._host, attempt)
            try:
                self._session = await self._run(build, local_port)
                break
            except Exception as exc:
                if attempt == last_attempt or not peer_holds_stale_session(exc):
                    raise
                self._log(
                    f"handshake rejected from :{local_port} ({exc}); the appliance "
                    f"is still holding the previous session — retrying from a new "
                    f"source port"
                )

        self._log(f"DTLS session established to {self._host}:{self._port}")

        # A fresh session carries no observations, so anything previously
        # subscribed must be re-registered or it goes silently stale.
        if self._subscribed:
            paths = sorted(self._subscribed)
            self._subscribed.clear()
            for path in paths:
                try:
                    await self._subscribe_unlocked(list(path))
                except Exception as exc:
                    self._log(f"re-subscribe /{'/'.join(path)} failed: {exc}")

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        session, self._session = self._session, None
        if session is None:
            return
        # close_notify matters: without it the appliance keeps an orphaned
        # association for 5-15 minutes and the next session's reads hang.
        try:
            await self._run(session.close)
        except Exception as exc:
            self._log(f"session close failed: {exc}")

    async def subscribe(self, path_segs: list[str]) -> None:
        """Register an OBSERVE. The initial notification and every later change
        arrive through the on_notification callback."""
        async with self._lock:
            await self._connect_unlocked()
            await self._subscribe_unlocked(path_segs)

    async def _subscribe_unlocked(self, path_segs: list[str]) -> None:
        session = self._session
        await self._run(lambda: session.subscribe(list(path_segs)))
        self._subscribed.add(tuple(path_segs))

    @property
    def subscription_count(self) -> int:
        return len(self._subscribed)

    async def read_device0(self) -> dict:
        """Full {href: rep} snapshot. Reconnects once on a dropped session."""
        payload = await self._get(["device", "0"])
        return parse_device0(cbor2.loads(payload))

    async def _get(self, path_segs: list[str]) -> bytes:
        async with self._lock:
            await self._connect_unlocked()
            try:
                return await self._get_unlocked(path_segs)
            except (ConnectionError, TimeoutError) as exc:
                self._log(f"GET /{'/'.join(path_segs)} failed ({exc}); reconnecting")
                await self._close_unlocked()
                await self._connect_unlocked()
                return await self._get_unlocked(path_segs)

    async def _get_unlocked(self, path_segs: list[str]) -> bytes:
        session = self._session

        def do_get():
            return session.get(path_segs, timeout=PROBE_GET_TIMEOUT_S)

        code, payload = await self._run(do_get)
        if code != 0x45 or not payload:
            raise ConnectionError(
                f"GET /{'/'.join(path_segs)} -> {code >> 5}.{code & 0x1F:02d}"
            )
        return payload

    async def write(self, path_segs: list[str], body: dict) -> dict:
        """POST a resource update and return the device's parsed response.

        The device echoes the new value plus a `controlResponse.result` flag; a
        2.04 code alone is not proof the write was accepted, so callers should
        check the flag.
        """
        async with self._lock:
            await self._connect_unlocked()
            session = self._session
            encoded = cbor2.dumps(body)

            def do_post():
                return session.post(path_segs, encoded, timeout=PROBE_GET_TIMEOUT_S)

            code, payload = await self._run(do_post)

        if code not in (0x44, 0x45):  # 2.04 Changed / 2.05 Content
            raise ConnectionError(
                f"POST /{'/'.join(path_segs)} -> {code >> 5}.{code & 0x1F:02d}"
            )
        if not payload:
            return {}
        try:
            return cbor2.loads(payload)
        except Exception:
            return {}

    @staticmethod
    def write_accepted(response: dict) -> bool:
        """Whether the device's own ack says the write took.

        Absent flag counts as accepted — not every resource returns one, and the
        CoAP code already succeeded by this point.
        """
        control = (response or {}).get("controlResponse")
        if not isinstance(control, dict) or "result" not in control:
            return True
        return bool(control["result"])
