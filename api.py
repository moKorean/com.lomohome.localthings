"""Settings-page API.

Backs the app settings view where the user supplies the client certificate. The
certificate is app-scoped rather than per-device: its UUID comes from Samsung's
cloud gateway, not from any appliance, so one certificate authenticates to all of
them and rotating it fixes every device at once.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lib import cert, compat  # noqa: E402
from lib.const import (  # noqa: E402
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SETTING_PAIR_ENV,
)


async def _run(fn, *args):
    return await asyncio.get_running_loop().run_in_executor(None, fn, *args)


def _body(kwargs: dict) -> dict:
    """Request body, however this Homey build delivers it.

    Some versions pass it as `body`, others flatten the fields into kwargs. The
    reference Python app reads both, so do the same rather than betting on one.
    """
    body = kwargs.get("body")
    return body if isinstance(body, dict) else kwargs


def _log(homey, message: str) -> None:
    """Log if this build exposes a logger here; never fail a request over it."""
    for target in (getattr(homey, "app", None), homey):
        log = getattr(target, "log", None)
        if callable(log):
            try:
                log(message)
                return
            except Exception:
                pass


async def _stored(homey) -> tuple[str, str]:
    return (
        await compat.setting_get(homey, SETTING_LEAF_CERT),
        await compat.setting_get(homey, SETTING_LEAF_KEY),
    )


async def get_status(homey, **kwargs):
    """What the settings page shows on load.

    Never returns the stored PEMs — the page only needs to know whether they are
    present and healthy, and echoing key material into a webview serves no
    purpose.
    """
    cert_pem, key_pem = await _stored(homey)
    # Logged so the settings page reaching the backend can be told apart from it
    # failing before the request — the two look identical in the UI.
    _log(homey, f"settings GET /status (configured={bool(cert_pem and key_pem)})")
    if not cert_pem or not key_pem:
        return {"configured": False}

    try:
        info = await _run(cert.inspect_leaf, cert_pem, key_pem)
    except cert.InvalidCredentials as exc:
        return {"configured": True, "valid": False, "error": str(exc)}

    return {"configured": True, "valid": True, **info}


async def check_uuid(homey, **kwargs):
    """Compare the stored certificate's identity with the one appliances
    currently expect. A mismatch means the certificate needs re-minting; it is
    the one failure mode that looks like a broken network but isn't."""
    cert_pem, key_pem = await _stored(homey)
    if not cert_pem:
        return {"configured": False}
    try:
        stored = await _run(cert.inspect_leaf, cert_pem, key_pem)
    except cert.InvalidCredentials as exc:
        return {"ok": False, "error": str(exc)}
    try:
        live = await _run(cert.fetch_samsung_uuid)
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach Samsung's gateway: {exc}"}
    return {"ok": stored["uuid"] == live, "stored": stored["uuid"], "live": live}


async def save_credentials(homey, **kwargs):
    """Validate then store. Validation failure leaves the previous value intact."""
    body = _body(kwargs)
    cert_pem = str(body.get("cert_pem") or "").strip()
    key_pem = str(body.get("key_pem") or "").strip()
    if not cert_pem or not key_pem:
        raise ValueError("Both the certificate and the private key are required.")

    info = await _run(cert.inspect_leaf, cert_pem, key_pem)

    await compat.setting_set(homey, SETTING_LEAF_CERT, cert_pem + "\n")
    await compat.setting_set(homey, SETTING_LEAF_KEY, key_pem + "\n")

    # Read back before reporting success. A write that silently stored nothing
    # would otherwise surface much later as "set up required" during pairing,
    # with no clue that saving was what failed.
    stored_cert, stored_key = await _stored(homey)
    if not stored_cert or not stored_key:
        _log(homey, "settings POST /credentials: write did not persist")
        raise RuntimeError(
            "Homey did not persist the certificate. Please try again, or "
            "restart the app if it keeps happening."
        )
    _log(homey, f"Client certificate stored (uuid:{info['uuid']}, expires {info['expires']}, "
                f"cert={len(stored_cert)}B key={len(stored_key)}B)")
    return {"ok": True, **info}


async def clear_credentials(homey, **kwargs):
    for key in (SETTING_LEAF_CERT, SETTING_LEAF_KEY):
        await compat.setting_unset(homey, key)
    _log(homey, "Client certificate cleared")
    return {"ok": True}


async def diagnostics(homey, **kwargs):
    """What the app resolves at runtime, readable without a dev session.

    `homey app run` replaces the installed app and removes it when the run ends,
    so debugging through it costs the user their paired devices. This endpoint is
    reachable from an installed app via
    `homey api raw --path /api/app/com.lomohome.localthings/diagnostics`.
    """
    report = {}

    def record(label, get):
        try:
            value = get()
        except Exception as exc:
            report[label] = f"raised {type(exc).__name__}: {exc}"
            return
        report[label] = value if isinstance(value, (str, int, float, bool, type(None))) else repr(value)[:200]

    record("i18n.get_language", lambda: homey.i18n.get_language())
    record("i18n.get_strings.keys", lambda: sorted((homey.i18n.get_strings() or {}).keys()))
    record("manifest.name", lambda: (homey.manifest or {}).get("name"))
    report["compat.language"] = await compat.language(homey)

    cert_pem, key_pem = await _stored(homey)
    report["credentials"] = {"cert_bytes": len(cert_pem), "key_bytes": len(key_pem)}
    report["pair_env"] = await compat.setting_get(homey, SETTING_PAIR_ENV) or "(not reported yet)"
    return report
