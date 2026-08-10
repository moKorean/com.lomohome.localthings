"""Which air-conditioner settings each operating mode will actually accept.

Reported by the owner of the four units this app is developed against, checked
against the appliance's own interface mode by mode. It is not derived from the
protocol: the appliance accepts writes for settings the mode does not honour and
answers without a rejection flag, which is exactly why a Flow could ask for
something and be told it succeeded.

    mode        target temp   fan speed   direction   air purify   Wind-Free   Long wind   Speed
    AI Comfort      yes           no         yes          yes         no          no        no
    Auto            yes           no         yes          yes         no          no        no
    Cool            yes           yes        yes          yes         yes         yes       yes
    Dry             yes           no         yes          yes         yes         yes       no
    Fan             no            yes        yes          yes         yes         yes       no

**Power state is a second axis and is not in this table.** A switched-off unit
refuses `Speed` outright — measured 2026-08-09 on the 손님방 unit, `controlResponse
result False` — and `/mode/convenient/vs/0` advertises all six comfort modes
whether it is on or off, right through the power-on transition, so nothing here or
on the wire predicts it. It is not encoded because it is not a property of the
operating mode, and because the answer is timing rather than refusal: the same
write succeeds 6-8 seconds after the power write lands. `driver._apply_step`
handles it by retrying, which is the only thing that can work when the constraint
is invisible until the write is attempted.

Two things are deliberately *not* encoded:

- Modes absent from the table (`Heat`, `Wind`). These units are cooling-only —
  their `supportedModes` is AIComfort/Auto/Cool/Dry/Fan — so nothing is known
  about them, and an unknown mode allows everything rather than guessing.
- Comfort modes absent from a row's list (`Sleep`, `NanoSleep`). Only the three
  that were checked are named, so the others pass through.

The bias is uniform: block only what has been confirmed impossible. A wrong
"blocked" silently drops a setting the user asked for, which is the failure this
table exists to prevent; a wrong "allowed" leaves the previous behaviour, which
is at worst no better than before.
"""

TARGET_TEMPERATURE = "temperature"
FAN_SPEED = "fan"
WIND_DIRECTION = "direction"
AIR_PURIFY = "air_purify"
COMFORT = "convenient"

# mode -> the settings that mode refuses. Comfort modes are listed by their own
# value, because the restriction is per comfort mode rather than per setting: Dry
# takes Wind-Free and Long wind but not Speed.
_BLOCKED: dict[str, frozenset] = {
    # Air purify is *not* blocked here. It was, on a first reading of the table,
    # and the owner corrected it: it does work under AI Comfort. That matches what
    # was measured during a Flow run — /option/airpurify/vs/0 read On with the mode
    # AIComfort and stayed On across samples.
    "AIComfort": frozenset({FAN_SPEED, "Nano", "LongWind", "Speed"}),
    "Auto": frozenset({FAN_SPEED, "Nano", "LongWind", "Speed"}),
    "Cool": frozenset(),
    "Dry": frozenset({FAN_SPEED, "Speed"}),
    "Fan": frozenset({TARGET_TEMPERATURE, "Speed"}),
}

# Comfort modes are values of one setting, so a blocked one means "leave the
# comfort mode alone", not "this setting does not exist".
COMFORT_OFF = "Off"


def accepts(mode, setting: str, value=None) -> bool:
    """Whether `mode` will honour `setting`.

    `value` matters only for the comfort mode, where the restriction is per
    value. Turning the comfort mode off is never blocked — that is the appliance's
    own resting state, not a contradiction.
    """
    blocked = _BLOCKED.get(str(mode) if mode is not None else "")
    if blocked is None:
        # An unrecognised or unknown mode constrains nothing.
        return True
    if setting == COMFORT:
        if value in (None, COMFORT_OFF):
            return True
        return value not in blocked
    return setting not in blocked


def known_modes() -> frozenset:
    return frozenset(_BLOCKED)
