"""OCF /device/0 batch parsing and identity extraction.

Ported from the reference integration's registry/batch.py and identity.py.
"""

INFORMATION_HREF = "/information/vs/0"


def is_stub_rep(rep) -> bool:
    """True for the device's "resource exists, no data fetched yet" marker — an
    echoed {"href": ...} with no other fields.

    Distinct from a genuinely empty {}, which is the device's confirmed (if
    empty) answer for a resource this model will never populate. Conflating the
    two makes every field-gated value on a permanently-empty resource look like
    a not-yet-fetched stub forever.
    """
    return isinstance(rep, dict) and set(rep.keys()) == {"href"}


def parse_device0(device0) -> dict[str, dict]:
    """Extract {href: rep} from a /device/0 CBOR list response.

    Entry [0] is the device-level rep and is skipped. Stub reps pass through
    unchanged so callers can tell them apart from confirmed-empty ones.
    """
    if not isinstance(device0, list):
        return {}
    out = {}
    for entry in device0[1:]:
        if not isinstance(entry, dict):
            continue
        href = entry.get("href")
        rep = entry.get("rep")
        if href and isinstance(rep, dict):
            out[href] = rep
    return out


def is_placeholder_serial(serial: str) -> bool:
    """True for a non-empty serialNum that isn't actually a real identity.

    The ARTIK051_DONGLE_REF firmware family reports the literal 'Nothing(SVC)'
    for every unit — non-empty, so a plain falsy check misses it. The serial
    feeds the Homey device id, so two such units would silently collide.
    """
    return (serial or "").strip().lower().startswith("nothing")


def read_serial(resources: dict, host: str, port: int) -> str:
    """Stable unique id for the appliance, falling back to host:port."""
    serial = (
        resources.get(INFORMATION_HREF, {}).get("x.com.samsung.da.serialNum") or ""
    )
    if not serial or is_placeholder_serial(serial):
        return f"{host}:{port}"
    return str(serial)


def read_identity(resources: dict) -> dict:
    """Model strings used for device typing and display."""
    info = resources.get(INFORMATION_HREF, {})
    return {
        "manufacturer": info.get("x.com.samsung.da.manufacturer") or "Samsung",
        "model": info.get("x.com.samsung.da.modelNum") or "",
        "description": info.get("x.com.samsung.da.description") or "",
    }
