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

from lib import cert  # noqa: E402
from lib.const import SETTING_LEAF_CERT, SETTING_LEAF_KEY  # noqa: E402


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


def _stored(homey) -> tuple[str, str]:
    return (
        homey.settings.get(SETTING_LEAF_CERT) or "",
        homey.settings.get(SETTING_LEAF_KEY) or "",
    )


async def get_status(homey, **kwargs):
    """What the settings page shows on load.

    Never returns the stored PEMs — the page only needs to know whether they are
    present and healthy, and echoing key material into a webview serves no
    purpose.
    """
    cert_pem, key_pem = _stored(homey)
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
    cert_pem, key_pem = _stored(homey)
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

    homey.settings.set(SETTING_LEAF_CERT, cert_pem + "\n")
    homey.settings.set(SETTING_LEAF_KEY, key_pem + "\n")
    _log(homey, f"Client certificate stored (uuid:{info['uuid']}, expires {info['expires']})")
    return {"ok": True, **info}


async def clear_credentials(homey, **kwargs):
    for key in (SETTING_LEAF_CERT, SETTING_LEAF_KEY):
        try:
            homey.settings.unset(key)
        except Exception:
            # Not every build exposes unset(); an empty value reads the same to
            # every consumer here.
            homey.settings.set(key, "")
    _log(homey, "Client certificate cleared")
    return {"ok": True}
