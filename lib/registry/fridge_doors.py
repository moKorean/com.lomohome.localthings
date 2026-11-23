"""Measured TP1X_REF_21K two-door encoding; not a Samsung-wide convention.

Both individual resources push; /doors/vs/0 only answered GET and registration
in the recorded tests. The raw cooler state feeds the fridge contact. The raw
freezer state is only used for the combined alarm: it cannot identify which
door is open in all positions. See docs/COMBI-DOORS.md.
"""

COOLER = "/door/cooler/0"
FREEZER = "/door/freezer/0"
AGGREGATE = "/doors/vs/0"
SOURCES = frozenset((COOLER, FREEZER))
COOLER_CAP = "localthings_cooler_door_open"
CAPABILITIES = frozenset(("alarm_contact", COOLER_CAP))
DEBOUNCE_S = 3.0


def _aggregate_items(rep: dict) -> dict:
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list) or len(items) != 2:
        return {}
    by_id = {str(item.get("x.com.samsung.da.id")): item
             for item in items if isinstance(item, dict)}
    return by_id if by_id.keys() == {"0", "1"} else {}


def matches(resources: dict) -> bool:
    info = resources.get("/information/vs/0") or {}
    if not isinstance(info, dict):
        return False
    model = str(info.get("x.com.samsung.da.modelNum") or "").split("|")[0]
    aggregate = resources.get(AGGREGATE)
    if model != "TP1X_REF_21K" or not isinstance(aggregate, dict):
        return False

    # The US TP1X_REF_21K fixture has a third door (/door/cvroom/0).
    # Its push behavior and encoding have not been tested; keep it on the
    # existing path. Reject a third door even if only one source advertises it.
    door_hrefs = {href for href in resources if href.startswith(("/door/", "/kimchidoors/"))}
    return (
        door_hrefs == SOURCES
        and all(isinstance(resources[path], dict) for path in SOURCES)
        and bool(_aggregate_items(aggregate))
    )


def open_state(rep: dict) -> bool | None:
    raw = rep.get("openState", rep.get("x.com.samsung.da.openState"))
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in ("open", "opened", "true"):
            return True
        if value in ("close", "closed", "false"):
            return False
    return None


def aggregate_states(rep: dict) -> dict[str, bool] | None:
    """Use only a fresh GET of the aggregate, never its non-updating push cache."""
    items = _aggregate_items(rep)
    if not items:
        return None
    # The control run matched item 0 to raw freezer and item 1 to raw cooler.
    freezer, cooler = open_state(items["0"]), open_state(items["1"])
    if freezer is None or cooler is None:
        return None
    return {FREEZER: freezer, COOLER: cooler}


def values(resources: dict) -> dict:
    """Return the fridge contact and combined alarm for the reported states.

    Ignore the aggregate here: it does not push, and a cached Open in that copy
    must not hold the combined alarm on after both live sources have closed.
    An unknown input cannot clear the combined alarm.
    """
    cooler = open_state(resources.get(COOLER) or {})
    freezer = open_state(resources.get(FREEZER) or {})
    combined = None
    if cooler is True or freezer is True:
        combined = True
    elif cooler is False and freezer is False:
        combined = False
    return {COOLER_CAP: cooler, "alarm_contact": combined}


def read_cooler(_rep, resources):
    return values(resources)[COOLER_CAP]
