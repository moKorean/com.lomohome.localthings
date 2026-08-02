"""The Repair flow.

Repair exists so that the three things that break a working appliance — an expired
certificate, an address change automatic relocation could not follow, and a unit
that was simply unreachable — do not cost the user their device, its Flows and its
history. That makes a repair which *reports* success without delivering it the
worst outcome available: the user believes the problem is fixed and stops looking.
"""

import ast
import asyncio
import sys
import types
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parent.parent
DRIVER = APP_ROOT / "lib/appliance/driver.py"
DEVICE = APP_ROOT / "lib/appliance/device.py"


@pytest.fixture
def driver_instance():
    """The real driver class with the runtime-provided `homey` module stubbed."""
    stub = types.ModuleType("homey")
    driver_module = types.ModuleType("homey.driver")

    class Driver:
        def log(self, *args):
            pass

    driver_module.Driver = Driver
    stub.driver = driver_module
    saved = {name: sys.modules.get(name) for name in ("homey", "homey.driver")}
    sys.modules["homey"], sys.modules["homey.driver"] = stub, driver_module
    try:
        from lib.appliance.driver import ApplianceDriver
        instance = object.__new__(ApplianceDriver)
        instance.log = lambda *args: None
        yield instance
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _FakeDevice:
    def __init__(self, name="unit"):
        self.name = name
        self.moved_to = None
        self.store = {"host": "192.168.1.9", "port": 49154, "serial": "SER123"}

    def get_name(self):
        return self.name

    def get_store(self):
        return dict(self.store)

    async def move_to(self, host, port):
        self.moved_to = (host, port)


class _FakeSession:
    def __init__(self):
        self.handlers = {}

    def set_handler(self, name, handler):
        self.handlers[name] = handler


# --- the address has to reach the running device ---------------------------


def test_repair_moves_the_device_rather_than_only_its_stored_address(driver_instance):
    """Writing the store alone looks equivalent and is not.

    Nothing re-reads it: the SDK has no store-change hook and Device.on_init reads
    it once, so a repair that only persisted the address left the running device
    polling the old one, showing the old one in its settings, and reporting success.
    It took effect on the next app restart.
    """
    device = _FakeDevice()
    asyncio.run(driver_instance._repoint(device, "192.168.1.44", 49153))
    assert device.moved_to == ("192.168.1.44", 49153)


def test_the_device_move_carries_the_session_with_it():
    """move_to has to do more than store the address: close the old session, rebuild
    it at the new one, and drop the observe state that belonged to the closed
    session. Read from the source because no fixture can stand in for a DTLS
    session."""
    source = DEVICE.read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "move_to"
    )
    body = ast.unparse(function)
    assert "_session.close" in body, "the old session is left open"
    assert "Session(" in body, "no new session is built at the new address"
    assert "_remember_location" in body, "the address is not persisted"
    assert "_observing = False" in body, "observe state outlives the session"
    assert "_sync_settings" in body, "the settings keep showing the old address"


def test_automatic_relocation_and_repair_share_one_path():
    """They diverged once, which is how repair ended up doing less. A second
    implementation is what let one of them be right and the other wrong."""
    source = DEVICE.read_text()
    relocate = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_relocate"
    )
    body = ast.unparse(relocate)
    assert "self.move_to" in body, "relocation no longer goes through move_to"
    assert "Session(" not in body, "relocation builds its own session again"


def test_repoint_does_not_swallow_a_failed_move(driver_instance):
    """A repair that could not move the device must not report that it did."""
    class Failing(_FakeDevice):
        async def move_to(self, host, port):
            raise RuntimeError("no credentials")

    with pytest.raises(RuntimeError):
        asyncio.run(driver_instance._repoint(Failing(), "192.168.1.44", 49153))


# --- one repair session must not move another session's device -------------


def test_each_repair_session_keeps_its_own_device(driver_instance):
    """The device used to be parked on the driver, so two repair views open at once
    shared it: the second to open won, and the first view's 'set the address by
    hand' would then move the second appliance."""
    first, second = _FakeDevice("first"), _FakeDevice("second")
    session_a, session_b = _FakeSession(), _FakeSession()
    asyncio.run(driver_instance.on_repair(session_a, first))
    asyncio.run(driver_instance.on_repair(session_b, second))

    resolved = []
    driver_instance._on_repair_state = lambda device, data=None: _record(resolved, device)
    # Re-bind through the same wrapper the session uses.
    handler = driver_instance._for_session(driver_instance._on_repair_state, first)
    asyncio.run(handler({}))
    assert resolved == [first], "the later session's device leaked into the earlier one"


async def _record(sink, device):
    sink.append(device)


def test_the_driver_no_longer_parks_the_device_on_itself():
    """Code only. The comment above on_repair names the old attribute to explain why
    it went, and a plain substring check reads that as still using it — the same
    trap two earlier tests in this suite fell into."""
    code = "\n".join(
        line.split("#", 1)[0] for line in DRIVER.read_text().splitlines()
    )
    assert "self._repair_device" not in code, (
        "driver-level repair state is what let two sessions cross"
    )


# --- identity is still checked before moving anything ----------------------


def test_both_move_paths_refuse_a_different_appliance():
    """Pointing a device at another appliance would make it silently control the
    wrong thing — worse than staying broken."""
    source = DRIVER.read_text()
    tree = ast.parse(source)
    for name in ("_on_repair_host", "_on_repair_find"):
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name
        )
        body = ast.unparse(function)
        assert "serial" in body, f"{name} does not consult the serial"
        assert "_repoint" in body, f"{name} does not go through _repoint"


def test_the_serial_check_is_skipped_only_for_a_host_port_placeholder():
    """A unit with no usable serial stores 'host:port' instead. That cannot identify
    anything, so the check is skipped — but only for that shape."""
    source = DRIVER.read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_repair_host"
    )
    body = ast.unparse(function)
    assert '":" not in expected' in body or "':' not in expected" in body


# --- testing the connection must not break it ------------------------------


def test_the_connection_test_uses_the_devices_own_session():
    """A second session to the address the device already holds evicts the live one.

    This app pins one UDP source port per appliance so a reconnect reuses the same
    5-tuple and the appliance discards any orphaned association — the library's own
    comment says so, and that is the point of the fixed port. Aimed at a *live*
    session it destroys the subscriptions instead, and nothing tells the device:
    `_observing` stays True, so it does not resubscribe for OBSERVE_REFRESH_S and
    silently drops to the summary sweep meanwhile.
    """
    source = DRIVER.read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_on_repair_test"
    )
    body = "\n".join(
        line.split("#", 1)[0] for line in ast.unparse(function).splitlines()
    )
    assert "check_now" in body, "the test opens its own session again"
    assert "probe.probe" not in body, (
        "probing the stored address competes with the live session for its source port"
    )


def test_check_now_reads_through_the_live_session():
    source = DEVICE.read_text()
    function = next(
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "check_now"
    )
    body = ast.unparse(function)
    assert "_session.read_device0" in body
    assert "read_serial" in body, "the reply is not checked against the stored serial"


def test_the_paths_that_do_probe_rebuild_the_session_afterwards():
    """_on_repair_find and _on_repair_host legitimately probe, and may land on the
    address the device is already using. That is safe only because both end in
    _repoint, which closes and rebuilds the session."""
    tree = ast.parse(DRIVER.read_text())
    for name in ("_on_repair_find", "_on_repair_host"):
        function = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name
        )
        body = ast.unparse(function)
        assert "probe.probe" in body and "_repoint" in body, (
            f"{name} probes without rebuilding the session"
        )
