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

from lib import cert, compat, i18n, support
from lib.const import (
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SETTING_PAIR_ENV,
    SETTING_UI_LANGUAGE,
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


def _params(kwargs: dict) -> dict:
    """Request parameters, wherever this Homey build puts them.

    `_body` covers a POST. A GET's query string arrives under `query` on the builds
    checked, which is why an earlier `?host=` filter was silently ignored and dumped
    every appliance instead of one. Both are merged rather than chosen between.
    """
    merged = {}
    for source in (kwargs.get("query"), kwargs.get("params"), _body(kwargs)):
        if isinstance(source, dict):
            merged.update(source)
    return merged


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
        raise ValueError(i18n.translate(
            "error.credentials_required", await compat.ui_language(homey)))

    info = await _run(cert.inspect_leaf, cert_pem, key_pem)

    await compat.setting_set(homey, SETTING_LEAF_CERT, cert_pem + "\n")
    await compat.setting_set(homey, SETTING_LEAF_KEY, key_pem + "\n")

    # Read back before reporting success. A write that silently stored nothing
    # would otherwise surface much later as "set up required" during pairing,
    # with no clue that saving was what failed.
    stored_cert, stored_key = await _stored(homey)
    if not stored_cert or not stored_key:
        _log(homey, "settings POST /credentials: write did not persist")
        raise RuntimeError(i18n.translate(
            "error.credentials_not_persisted", await compat.ui_language(homey)))
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
        scalar = isinstance(value, (str, int, float, bool, type(None)))
        report[label] = value if scalar else repr(value)[:200]

    record("i18n.get_language", lambda: homey.i18n.get_language())
    record("i18n.get_strings.keys", lambda: sorted((homey.i18n.get_strings() or {}).keys()))
    record("manifest.name", lambda: (homey.manifest or {}).get("name"))
    report["compat.language"] = await compat.language(homey)

    cert_pem, key_pem = await _stored(homey)
    report["credentials"] = {"cert_bytes": len(cert_pem), "key_bytes": len(key_pem)}
    report["ui_language"] = (
        await compat.setting_get(homey, SETTING_UI_LANGUAGE) or "(not reported yet)"
    )
    report["pair_env"] = (
        await compat.setting_get(homey, SETTING_PAIR_ENV) or "(not reported yet)"
    )
    report["devices"] = _device_report(homey)
    return report


async def resources(homey, **kwargs):
    """Every resource a paired appliance reports, verbatim.

    Mapping an appliance type correctly needs the actual field names and the
    actual supported-value lists, and guessing them produces capabilities that
    read null and writes the appliance refuses — which is indistinguishable, from
    the outside, from the appliance not supporting the feature at all.

    A device already holds this from its last poll, so nothing extra is asked of
    the appliance. Reachable from an installed app via
    `homey api raw --path /api/app/com.lomohome.localthings/resources`.

    Per-unit identifiers are redacted by default, because the most likely thing to
    happen to this output is being pasted somewhere public. Pass `raw=1` to see them,
    which is only ever needed when debugging identity matching itself.

    Optional `host` narrows the dump to one appliance, since a whole house of them
    is a lot of output.
    """
    params = _params(kwargs)
    wanted = str(params.get("host") or "").strip()
    raw = str(params.get("raw") or "").strip().lower() in ("1", "true", "yes")
    try:
        devices = homey.drivers.get_driver("appliance").get_devices()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}

    out = {}
    for device in devices:
        try:
            host = (device.get_store() or {}).get("host")
            if wanted and str(host) != wanted:
                continue
            resource_map = getattr(device, "_resources", {}) or {}
            registry_name = getattr(device, "_registry", None)
            out[str(device.get_name())] = {
                "host": host,
                "registry": registry_name and registry_name.name,
                # Not sorted: the order a device holds these in is the order Homey
                # renders them, so sorting here hid a real ordering problem.
                "bound_capabilities": list(device.get_capabilities() or ()),
                "resources": (
                    resource_map if raw else support.redact(resource_map)
                ),
            }
        except Exception as exc:
            out[f"error-{len(out)}"] = f"{type(exc).__name__}: {exc}"
    return out or {"error": "no matching device"}


async def write_resource(homey, **kwargs):
    """Write one resource on one appliance and read it straight back.

    A diagnostic, for the question "does this appliance accept a write on this path at
    all". Guessing the answer is how the refrigerator setpoint was implemented twice
    without working either time; this makes it a measurement. The write goes through
    the device's own session, so it is the same transport a capability write uses.

        homey api raw --method POST \
          --path /api/app/com.lomohome.localthings/write-resource \
          --json '{"host":"192.168.1.203","path":"/temperature/desired/cooler/0",
                   "body":{"temperature":4}}'

    Returns the appliance's own response plus the resource re-read after the write, so
    "accepted but not committed" is distinguishable from "committed".
    """
    params = _params(kwargs)
    host = str(params.get("host") or "").strip()
    path = str(params.get("path") or "").strip()
    body = params.get("body")
    if isinstance(body, str):
        import json as _json
        try:
            body = _json.loads(body)
        except ValueError:
            return {"error": "body is not valid JSON"}
    if not host or not path or not isinstance(body, dict):
        return {"error": "host, path and a JSON object body are all required"}

    try:
        devices = homey.drivers.get_driver("appliance").get_devices()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    device = next(
        (d for d in devices if str((d.get_store() or {}).get("host")) == host), None
    )
    if device is None:
        return {"error": f"no paired appliance at {host}"}

    segments = [s for s in path.strip("/").split("/") if s]
    session = getattr(device, "_session", None)
    if session is None:
        return {"error": "device has no session"}

    result = {"host": host, "path": "/" + "/".join(segments), "sent": body}
    try:
        response = await session.write(segments, body)
        result["response"] = response
        result["accepted"] = session.write_accepted(response)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    # The point of the endpoint: what the appliance holds *after* the write.
    try:
        snapshot = await session.read_device0()
        result["after"] = snapshot.get(result["path"])
    except Exception as exc:
        result["after_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _device_report(homey) -> list:
    """Per-device push/poll state.

    The mode decision is only logged otherwise, and reading app logs means running
    a dev session — which replaces the installed app and removes it when it ends.
    """
    try:
        driver = homey.drivers.get_driver("appliance")
        devices = driver.get_devices()
    except Exception as exc:
        return [f"unavailable: {type(exc).__name__}: {exc}"]

    report = []
    for device in devices:
        entry = {}
        for label, get in (
            ("name", lambda d=device: d.get_name()),
            ("available", lambda d=device: d.get_available()),
            ("host", lambda d=device: (d.get_store() or {}).get("host")),
            ("registry", lambda d=device: getattr(d, "_registry", None)
             and d._registry.name),
            ("observing", lambda d=device: getattr(d, "_observing", None)),
            ("subscriptions", lambda d=device: getattr(
                getattr(d, "_session", None), "subscription_count", None)),
            ("notified_hrefs", lambda d=device: len(getattr(d, "_notified", ()) or ())),
            ("capabilities", lambda d=device: len(d.get_capabilities() or ())),
            # The values, not just the count. "the capability is bound" and "the
            # capability holds the value the appliance reports" are different
            # claims, and only the second one is what the user sees on the tile.
            ("values", lambda d=device: {
                c: d.get_capability_value(c) for c in sorted(d.get_capabilities() or ())
            }),
        ):
            try:
                entry[label] = get()
            except Exception as exc:
                entry[label] = f"raised {type(exc).__name__}: {exc}"
        report.append(entry)
    return report


async def set_language(homey, **kwargs):
    """Record the UI language the settings page resolved.

    The page asks its own Homey object, which knows the user's language; the app's
    Python i18n does not. Stored so messages raised from Python can use it.
    """
    body = _body(kwargs)
    await compat.remember_ui_language(homey, body.get("language"))
    return {"ok": True, "language": await compat.ui_language(homey)}
