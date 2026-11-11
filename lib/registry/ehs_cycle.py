"""Readings decoded from `/ehscycle/vs/0`, the EHS heat pump's cycle log.

`indoor` and `outdoor` each hold a few `{"datetime", "cycledata"}` samples,
oldest first, and `cycledata` is a hex-encoded fixed-width record. The byte map
comes from https://www.dwellsee.com/decoding-guide/ by way of the reference's
issue #678 (0-indexed; temperatures are `byte - 55` in °C):

    indoor, 31 bytes (TP1X, MIM-H04EN) or 36 bytes (S905D3)
      2     return water temperature
      3     flow water temperature
      6-7   flow rate, uint16 big-endian / 10 L/min
      8     circulation pump speed, %
    outdoor, 28 bytes
      0-1   compressor frequency, int16 big-endian, Hz
      8     outdoor temperature

**A guide is not a measurement**, so only the offsets with an independent check
are bound. Each of these is cross-read against a resource of the same dump:
outdoor byte 8 decodes to 8 °C on the MIM-H04EN while its
`/temperatures/outside/vs/0` reports 7.9, and the S905D3 sample in the
reference's #697 matches its `/overview/vs/0` flow, return and flow rate. The
guide's remaining offsets — discharge, evaporator saturation and suction
temperature, and the compressor's target frequency — have no second source in
any dump, and the reference itself ships them hidden by default. Homey has no
hidden-by-default tile, so publishing them would put four permanently visible
readings on the device on the strength of a web page alone. They stay out;
docs/BACKLOG.md carries them.

Any other record length reads as unknown rather than being decoded at an offset
that may mean something else.

**The log stops advancing while the unit is off**, so an old sample would read
as live. Anything older than 30 minutes is withheld — samples arrive every 30 s
on the S905D3 and every 5 minutes on the TP1X, and the boards' clocks report
UTC. This is why the reference's own dumps decode to nothing when the suite runs
them: their samples are weeks old, which is the rule working rather than a dead
mapping. `tests/test_ehs_cycle.py` decodes the same dumps against a clock set to
the sample's own time and asserts the values.
"""

from datetime import UTC, datetime, timedelta

HREF = "/ehscycle/vs/0"

INDOOR_LENGTHS = (31, 36)
OUTDOOR_LENGTHS = (28,)

# Above this the value is not a flow rate. Some boards report it scaled up by
# further powers of ten — the MIM-H04EN dump reads 0x6D60, which is 2800 L/min —
# so a reading past this is unknown rather than published.
MAX_FLOW_LPM = 100.0

STALE_AFTER = timedelta(minutes=30)


def _now() -> datetime:
    """Indirected so a test can decode a committed dump at its own timestamp."""
    return datetime.now(UTC)


def _parse_datetime(value):
    """The boards write `2026-10-27T20:54:01`, with no offset, in UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _fresh_bytes(rep, which: str, lengths: tuple[int, ...]) -> bytes | None:
    samples = rep.get(which) if isinstance(rep, dict) else None
    if not isinstance(samples, list) or not samples:
        return None
    sample = samples[-1]
    if not isinstance(sample, dict):
        return None
    taken = _parse_datetime(sample.get("datetime"))
    if taken is None or _now() - taken > STALE_AFTER:
        return None
    try:
        raw = bytes.fromhex(sample.get("cycledata") or "")
    except (TypeError, ValueError):
        return None
    return raw if len(raw) in lengths else None


def _reader(which: str, lengths: tuple[int, ...], decode):
    def read(rep, _resources):
        raw = _fresh_bytes(rep, which, lengths)
        return None if raw is None else decode(raw)

    return read


def _indoor(decode):
    return _reader("indoor", INDOOR_LENGTHS, decode)


def _outdoor(decode):
    return _reader("outdoor", OUTDOOR_LENGTHS, decode)


def _temperature(offset: int):
    return lambda raw: float(raw[offset] - 55)


def _flow_rate(raw: bytes):
    """uint16 big-endian over bytes 6-7, tenths of a litre per minute.

    Byte 6 is the high byte and not a flag — a flow above 25.5 L/min sets it, so
    reading byte 7 alone wraps.
    """
    lpm = int.from_bytes(raw[6:8], "big") / 10
    return lpm if lpm <= MAX_FLOW_LPM else None


read_flow_temperature = _indoor(_temperature(3))
read_return_temperature = _indoor(_temperature(2))
read_flow_rate = _indoor(_flow_rate)
read_pump_speed = _indoor(lambda raw: float(raw[8]))
read_compressor_hz = _outdoor(
    lambda raw: float(int.from_bytes(raw[0:2], "big", signed=True))
)
read_outdoor_temperature = _outdoor(_temperature(8))


def outdoor_temperature_unmeasured(_rep, resources) -> bool:
    """`/temperatures/outside/vs/0` reads the same sensor to 0.1 °C, so the
    log's whole-degree copy is only bound where that resource is absent."""
    return "/temperatures/outside/vs/0" not in (resources or {})
