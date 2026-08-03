# Working in this repository

A Homey app that controls Samsung appliances over local DTLS/CoAP, ported from the
[LocalThings](https://github.com/mbillow/localthings) Home Assistant integration.
`README.md` describes what it does. This file is about how to change it.

## Before you push

CI runs three steps. Run all three, not just the tests — two pushes have gone red
because only the tests were run and `ruff` catches things a passing suite says
nothing about.

```sh
uv run ruff check . --exclude python_packages     # --fix handles most of it
uv run pytest tests/ -q
uv run python scripts/check_reference_coverage.py
homey app validate --level publish
```

`uv run` re-syncs the venv from `pyproject.toml` and will drop `ruff`/`pytest` if
they were installed by hand. Restore them the way CI does:
`uv pip install 'smartthings-local>=0.1.2' pytest ruff`.

## The rule that matters most: measure, don't infer

Field names and value domains come from the appliance, never from what a name
suggests. The range hood shipped once with **every** field guessed wrong — it
paired and then sat there reading nothing, while the unit tests passed, because a
consistently wrong mapping satisfies a structural check.

The method that replaced guessing:

1. Read the appliance directly. `read-resource` goes to the device; `resources`
   returns this app's cache, and **the two are not the same** — a conclusion drawn
   from the cache alone has been wrong here at least twice.
2. Commit the dump as an obfuscated fixture and assert against it.
3. Where one dump is ambiguous, find a natural experiment — two convertible
   fridges in opposite modes settled what a single unit could not.

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
homey api raw --path /api/app/com.lomohome.localthings/resources        # cache; raw=1 for un-redacted
homey api raw -X POST --path /api/app/com.lomohome.localthings/read-resource \
  --body '{"path":"/oic/d"}'                                            # live, all appliances
homey api raw -X POST --path /api/app/com.lomohome.localthings/write-resource \
  --body '{"host":"…","path":"…","body":{…}}'                           # writes, then reads back
```

`--json` is a boolean output flag; request bodies go in `--body`. There is no
`homey app log`. `homey app run` **replaces** the installed app and removes it when
the run ends — use `homey app install`.

The Homey API rate-limits hard after a burst, and polling to see whether the limit
has cleared keeps it tripped. Back off in single long waits.

### An acknowledgement is not evidence

These appliances accept writes for things they will not honour and answer without a
rejection flag. Three separate bugs have come from trusting that reply:

- A mode set seconds after power-on is accepted, then overwritten by the mode the
  appliance restores as it starts.
- Setting a comfort mode takes a unit out of AI Comfort, and vice versa. Which
  settings each operating mode honours is in `lib/registry/ac_mode_matrix.py` —
  reported by the owner, checked against the appliance's own interface.
- A write payload for a list-shaped resource carries only the entry id and the
  changed field. Folding it into the cache with `dict.update` replaced the whole
  list; see `_fold_write_into`.

Confirm by reading back, and re-send when the appliance takes it back.

## Verified hardware

Four air conditioners (`TP1X_DA-AC-CAC-01001`), one induction cooktop, one range
hood (`AHD-WW-TP1-22`), three refrigerators (`TP2X_REF_21K`). Only these four types
are claimed in the app description; the other fourteen are routed and mapped from
the reference but unverified, and that distinction is deliberate — see the support
table in `README.md`.

Writing to these appliances changes the user's home. Record the state first,
restore afterwards, and say so.

## Layout

| Path | |
|---|---|
| `lib/registry/` | Type routing (`/oic/d`, then board tokens) and per-appliance capability maps |
| `lib/appliance/device.py` | Session, poll loop, writes, capability reconciliation |
| `lib/appliance/driver.py` | Pairing, repair, Flow card listeners |
| `lib/probe.py` | Port sweep, DTLS liveness gate, pairing probe |
| `scripts/make_flow_cards.py` | Generates the Flow cards; `--check` runs in the suite |
| `docs/BACKLOG.md` | Unmapped resources and recorded decisions, each with the experiment that would settle it |
| `docs/PORTING.md` | Design notes from the port. Historical — `README.md` is the current-state document |

Flow cards and their listeners are both generated from the capability manifest.
Adding a capability without regenerating fails the suite. Homey fires triggers for
custom capabilities itself (`<capability>_true` / `_changed`); only sub-capabilities
need dispatching, and firing plain ones too would run every Flow twice.

## Staying in step with the reference

Two checkouts sit beside this one: `../localthings-reference` and
`../smartthings-local-reference`. `check_reference_coverage.py` and
`tests/test_all_types.py` compare our routing tables against the reference's.

Both read those tables with `ast`, deliberately. They used regexes, the reference
adopted `ruff`, its literals went from `'REF'` to `"REF"`, and both silently parsed
**nothing** — the parity test iterated an empty dict and passed. Both now refuse an
empty parse. A check that cannot fail is worse than no check, because it reads as
evidence.

Where this app diverges from the reference on purpose, the code says so and why.
Do not "fix" those back without new measurements.

## Contributing upstream

Commits must be authored by the user alone — **no `Co-Authored-By` or agent
trailers**, in this repo or in PRs. The upstream maintainer asked for it directly.

Run the reference's own suite before opening a PR
(`uv venv --python 3.13`, `requirements-dev.txt`; 3.14 breaks `mashumaro`). Watch
the diff size: `cs.json` is CRLF there, and a JSON round-trip rewrites the file.

## Releasing

"배포해" means the whole sequence: bump `.homeycompose/app.json`, write the
changelog entry in both `en` and `ko`, update both READMEs, commit and push, then
`homey app publish`. `HOMEY_HEADLESS=1` runs it non-interactively with the right
answers (no version bump — step one already did that; changelog must pre-exist).

Publishing uploads a build. Promoting it to the store is a separate step on the
developer dashboard, so a version is not live just because publish succeeded.
