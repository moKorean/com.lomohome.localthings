"""Startup self-check for the Homey Python runtime.

The transport layer this app depends on needs three things from the runtime
that a normal Homey app never exercises: the bundled native extensions must
load, pyOpenSSL must expose the DTLS API, and the app must be allowed to open
a UDP socket from a background thread. None of that can be verified off-device,
so it is checked once at startup and logged.

Every probe is read-only and failure is reported rather than raised — a failing
probe should show up in the log, not stop the app from starting.
"""

import platform
import socket
import sys
import threading


def _probe(name, fn):
    try:
        return f"{name}: {fn()}"
    except Exception as exc:
        return f"{name}: FAILED ({type(exc).__name__}: {exc})"


def _interpreter():
    return f"{platform.python_version()} on {platform.machine()} ({sys.platform})"


def _smartthings_local():
    import smartthings_local

    return getattr(smartthings_local, "__version__", "version unknown")


def _cbor2():
    import cbor2

    # The C extension and the pure-Python fallback share an API; which one
    # loaded tells us whether the native wheel actually made it onto the device.
    impl = "native" if getattr(cbor2, "_cbor2", None) else "pure-python"
    return f"{impl}, roundtrip={cbor2.loads(cbor2.dumps({'a': 1})) == {'a': 1}}"


def _pyopenssl_dtls():
    from OpenSSL import SSL

    ctx = SSL.Context(SSL.DTLS_METHOD)
    ctx.set_cipher_list(b"ECDHE-ECDSA-AES128-GCM-SHA256:@SECLEVEL=0")
    has_mtu = hasattr(SSL.Connection, "set_ciphertext_mtu")
    return f"DTLS_METHOD ok, cipher list accepted, set_ciphertext_mtu={has_mtu}"


def _udp_from_thread():
    """Bind the real source port the transport will use (see PORTING.md).

    DTLS_LOCAL_PORT_BASE is 49700; binding one port in that range from a
    background thread is exactly what DtlsCoapSession does, so this is the
    probe most likely to reveal a sandbox restriction.
    """
    result = {}

    def run():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.bind(("0.0.0.0", 49700))
                result["ok"] = f"bound {sock.getsockname()}"
        except Exception as exc:
            result["ok"] = f"FAILED ({type(exc).__name__}: {exc})"

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=5)
    if t.is_alive():
        return "FAILED (thread did not finish in 5s)"
    return result.get("ok", "FAILED (no result)")


def _local_addresses():
    """The LAN address the appliance would see. A 172.17.x.x/bridge-looking
    address here means the app cannot reach LAN appliances over UDP."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # No packet is sent; connect() on UDP just picks the outbound route.
        sock.connect(("8.8.8.8", 53))
        return sock.getsockname()[0]


PROBES = (
    ("interpreter", _interpreter),
    ("smartthings-local", _smartthings_local),
    ("cbor2", _cbor2),
    ("pyopenssl-dtls", _pyopenssl_dtls),
    ("udp-bind-from-thread", _udp_from_thread),
    ("outbound-address", _local_addresses),
)


def run(log) -> None:
    """Run every probe, passing each result line to `log`."""
    log("--- runtime self-check ---")
    for name, fn in PROBES:
        log(_probe(name, fn))
    log("--- end self-check ---")
