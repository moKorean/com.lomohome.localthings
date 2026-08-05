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

    Every entry is examined, including [0]. Most firmware opens the batch with a
    device-level collection representation, but not all of it does, and skipping
    [0] unconditionally silently dropped the first resource on the firmware that
    does not — a wrong path never raises here, so the loss is invisible.

    Measured 2026-08-05 by reading raw `/device/0` off all nine appliances in one
    call. Eight open with a collection rep carrying no `href` — the refrigerators
    and the hood send a bare `{}`, the air conditioners `{"rt": …, "if": …}` — so
    the `href` check below discards them whether or not [0] is examined. The
    induction cooktop opens directly with `/connectionconfig/vs/0`, a real
    resource with a rep, and that one was being thrown away: the appliance
    returns 13 entries and our committed dump of it had 12. The reference reached
    the same fix from an NV9000D dump of the same board family (its fixture's own
    note: "This firmware starts directly with /connectionconfig/vs/0").

    Stub reps pass through unchanged so callers can tell them apart from
    confirmed-empty ones.
    """
    if not isinstance(device0, list):
        return {}
    out = {}
    for entry in device0:
        if not isinstance(entry, dict):
            continue
        href = entry.get("href")
        rep = entry.get("rep")
        if href and isinstance(rep, dict):
            out[href] = rep
    return out


def is_placeholder_serial(serial: str) -> bool:
    """True for a non-empty serialNum that isn't actually a real identity.

    Two firmware families do this, and both are non-empty, so a plain falsy
    check misses them:

    - ARTIK051_DONGLE_REF reports the literal 'Nothing(SVC)' on every unit.
    - The DA_WM_A51_20_COMMON laundry boards report a flash-unset sentinel —
      every character the same repeated hex digit. Reference #189 had a washer
      and a dryer, two different physical units, both reporting
      'FFFFFFFFFFFFFFF'.

    The serial is this app's identity for an appliance: it seeds the device id,
    and every poll re-checks it so two units that swap addresses cannot drive
    each other. A placeholder shared across units would defeat both, so these
    fall back to host:port instead.

    The repeated-digit rule is deliberately narrow — at least 8 characters, all
    identical, and a hex digit. A real serial is not going to be 'AAAAAAAA',
    while a short or non-hex run ('---', '0000') could plausibly be part of one.
    """
    text = (serial or "").strip()
    if text.lower().startswith("nothing"):
        return True
    upper = text.upper()
    return len(upper) >= 8 and len(set(upper)) == 1 and upper[0] in "0123456789ABCDEF"


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
