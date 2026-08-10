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

### Reach Homey over the local API, not `homey api raw`

**Do not call `homey api raw` bare.** The CLI's default mode authenticates against
Athom's cloud on *every* invocation, and each call is a fresh process so nothing
caches — which is what trips the rate limit described below. The neighbouring
`../com.lomohome.homeyscript` repo already solves address resolution (mDNS →
`homeylocal.com` HTTPS) and auth, and its helper works against this app's endpoints
unchanged. Reuse it; the cloud-call count is zero.

```sh
cd ../com.lomohome.homeyscript && node -e '
const { api, connectionInfo } = await import("./tools/lib.mjs");
console.log(await connectionInfo());
console.log(JSON.stringify(await api("GET", "/api/app/com.lomohome.localthings/resources")));
'
```

Confirmed against this app 2026-08-08: `diagnostics` and `resources` both answer,
`접속: https://192-168-1-133.homey.homeylocal.com (mDNS 192.168.1.133)`. `api(method,
path, body)` parses the JSON and returns it, so the 64 KB pipe truncation below
cannot happen either — the response never crosses a process boundary. It needs a
local API key at `~/.homey_api_key/key`; that repo's `README.md` has the setup and
a `--token`/`curl` form for shell one-liners.

The endpoints, whichever transport reaches them:

| | |
|---|---|
| `GET /api/app/com.lomohome.localthings/diagnostics` | every device in one call |
| `GET …/resources` | this app's cache; `raw=1` for un-redacted |
| `POST …/read-resource` `{"path":"/oic/d"}` | live, all appliances |
| `POST …/write-resource` `{"host":"…","path":"…","body":{…}}` | writes, then reads back |

`homey app install`, `homey app publish` and `homey app validate` still go through
the CLI and still need cloud auth — the local API replaces investigation calls, not
releases. There is no `homey app log`. `homey app run` **replaces** the installed app
and removes it when the run ends — use `homey app install`.

If you do fall back to `homey api raw`, two things bite. **Redirect to a file before
reading a long response: piping truncates it at ~64 KB**, mid-object, with no error.
This produced two wrong conclusions in one day — the device list looked as though it
contained no appliances of ours, and the insights list looked as though the
capabilities we had just flagged were absent, which was written up as "the flag does
not apply to existing devices" and was simply the cut. The same call redirected to a
file returned 276 KB and every series was there.

```sh
homey api raw --path /api/manager/insights/log > /tmp/ins.json   # then read the file
```

An absence in a truncated response is not evidence of absence. If a query returns
nothing you expected, check the size of what you actually received first. (`--json`
is a boolean output flag; request bodies go in `--body`.)

And the cloud rate limit: it bites hard after a burst, and polling to see whether it
has cleared keeps it tripped. Back off in single long waits — and mean it: checking
counts as a request, so three "has it cleared yet?" probes are three more strikes.

It is Athom's **cloud** API that limits, not the Homey on the LAN, so once tripped
**`homey app install` fails too** — with `Too many requests` from
`getAuthenticatedUser`, several stack frames deep and easy to misread as a build or
login problem. Every bare `homey api raw` spends from that budget regardless of what
it asks for, which is the reason for the local-API rule above. Appliance-side cost is
a separate matter: `read-resource` and `write-resource` make the appliances do real
DTLS work, so prefer one `diagnostics` call that returns every device over one call
per device even when the transport is free.

`homey app publish` needs the same cloud auth, so a tripped limit blocks a release
too — and it gets as far as `✓ Validating app...` and `✓ Pre-processed app` first,
which makes the failure look like the upload's fault rather than the limit's.

How long it lasts, measured 2026-08-05 (the only timing recorded so far):

| | |
|---|---|
| Burst that tripped it | one `/device/0` read across all nine appliances — nine appliance reads in one call — plus two `diagnostics` and an `app install` inside ~15 min |
| Last call to succeed | 23:37 (`app install`) |
| Failures | 23:39, 23:44, 23:58 |
| Cleared by | ~00:25, on the first attempt after 23:58 |

So the window outlasted 19 minutes and three attempts, and was gone inside 50. An
11-minute back-off was not enough; a 60-minute one was longer than it needed to be.

**This reading cannot tell whether probing extends the window.** If each attempt
reset a ~20-minute timer, recovery after the 23:58 failure lands at ~00:18; if the
window is a fixed ~45 minutes from the burst, it lands at ~00:25. The successful
attempt fits both, so the paragraph above keeps its advice — back off in one long
wait — on the grounds that it costs nothing if probing is harmless and saves the
release if it is not.

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

**Speed is refused while the unit is powered off**, and the refusal is not in
`ac_mode_matrix` because it is not about the operating mode. Measured 2026-08-09 on
the 손님방 air conditioner: `/mode/convenient/vs/0` advertises the full
`supportedModes` (`Off Nano LongWind Speed Sleep NanoSleep`) whether the unit is on or
off, live and in cache, and stays full right through a power-on transition — yet
writing `Speed` to a switched-off unit answers `controlResponse result False`. So the
supported list says nothing about power state, and a caller that powers a unit on must
let the power-on land before setting Speed. Whether the other comfort modes behave the
same way was not tested.

### A list of features is not a write contract

The induction cooktop's `/cooktop/spec/vs/0` advertises
`supportedFeatureList: [kitchenService, remoteChildLock, remotePowerOff]`, which lines
up neatly with three owner-reported behaviours: off works, on does not, burners do not.
1.0.3 shipped a power-off toggle on that reasoning, and it failed on the owner's first
attempt.

The appliance answers **4.05 Method Not Allowed** to a POST on `/cooktop/status/vs/0`
for `power` and `childLock` alike, hob off and hob running, with `smartControlState` on
and GET working throughout. So the second half of the reasoning was wrong too: the
child-lock write, described in a code comment as "verified on the unit here" and used
as proof that the list could be trusted, does not work either. Whatever those entries
mean — most plausibly that the feature exists over Samsung's cloud — they say nothing
about this resource taking a POST.

What to take from it:

- **A capability list tells you what to try, never what will work.** The only evidence
  that a write works is a write that worked, on that appliance, read back.
- **Check the control before believing a claim.** One POST to the hood in the same
  minute was accepted, which is what turned "our transport is broken" into "this
  appliance refuses writes" in a single step. Without it the conclusion would have been
  a guess.
- **A comment saying "verified" is not verification.** That one was load-bearing for a
  feature built two days later and nobody re-ran it. If a write matters, pin it with a
  test that talks to something, or write down when and how it was confirmed.

The whole apparatus built for the toggle — `Spec.refusal`, `make_flow_cards.OFF_ONLY`,
a dedicated error message — was removed with it rather than left as an abstraction with
no user. `tests/test_induction_cooktop.py` holds the reopening condition: an appliance
of that family answering something other than 4.05.

### Check what a counter counts before tuning it

`_notified` counts initial notifications *and* the state changes that follow, because
it is only cleared at re-subscribe. Two devices' counts therefore mean the same thing
only at the same offset from their last re-subscribe. Ignoring that produced a full
day of wrong conclusions in both directions on 2026-08-03 — first "the registration
burst loses the initial notifications", then an over-correction to "the appliances
send none at all", which two switched-off units reading 27/27 promptly refuted.

Three habits, in order of how much they would have saved:

- **Instrument the identity, not just the count.** "6 of 9" cannot distinguish a
  resource that never reports from a lossy channel; naming the six can.
  `observe_silent_hrefs` in `api.py` exists for this.
- **Perturb and watch.** Switching one unit on took the counter 0 → 7 in 70s with the
  retry window untouched, settling in one step what hours of reading had not. The
  standing permission to operate the appliances makes this cheap — use it.
- **Do not write a conclusion from one reading.** Both of the day's wrong answers were
  single-timepoint readings stated as settled. Take the second reading first — here
  four rounds showed one switched-off unit delivering 27/27, 27/27, 27/27 and 8/27 at
  the same offset, so any one of them would have "proved" something.

Repeat a round cheaply with `POST /api/manager/apps/app/<id>/restart` over the local
API. There is no way to disable an app from the CLI, and uninstalling would unpair
the user's devices.

`docs/BACKLOG.md` has the full record, including the loss mode that is still open.

### A mapping that reads nothing looks exactly like one that works

None means "leave the capability alone", so a wrong path or field name never raises:
the device pairs, the capability appears, the tile stays blank forever, and the suite
passes. Six appliance types shipped that way and were only found on 2026-08-04, by
checking reads against the reference's committed dumps — the clean station read
nothing at all, the water purifier's locks pointed at two resources that do not exist,
the oven family had four fields that are not fields of `/oven/vs/0`, and
`remainingTime` was parsed as a digit string when every dump uses `HH:MM:SS`.

`tests/test_no_dead_mappings.py` holds the two invariants that catch it, both measured
against those dumps — the closest thing to hardware for the fourteen types nobody here
owns. **No path is bound that nothing reports**, and **no spec is blank on every dump
of its type**. Blank on some dumps is ordinary: that board does not report that field.
Blank on all of them means the mapping is wrong or unconfirmable, so it goes in the
allow-list with a reason or it gets fixed. When adding or editing a type, run those
dumps through it before believing the mapping.

## The appliance checks the identifier, not the signature

Measured 2026-08-03, and it is why `lib/cert.py::mint_self_signed` exists: a certificate
carrying the right `uuid:` token and the extension profile of a working certificate was
accepted by an air conditioner and a refrigerator while signed by a CA generated on the
spot. Live reads through the app, not merely a completed DTLS handshake — the handshake
completes for a certificate the appliance then refuses to answer, so it is not the
discriminator. SHA-256 works as well as the SHA-1 the real chain uses, which is what
keeps this pure `cryptography` (49 refuses to sign SHA-1; pyOpenSSL would be needed).

This reversed the file's earlier premise, which said the appliance accepts a certificate
"signed by the AC14K_M intermediate CA". Consequences worth knowing before changing any
of it:

- `inspect_leaf` verifies **no** signature, issuer or chain link. It checks that two PEM
  blocks parse, that the key matches the certificate, and that a `uuid:` token exists.
  Do not treat "inspect_leaf accepted it" as evidence a certificate works — a
  self-signed fake passes.
- A pasted certificate always wins and is never re-issued over. `SETTING_CERT_SOURCE`
  is what makes that decidable; a certificate with no flag is treated as pasted, because
  every certificate predating the flag was.
- The minimum the appliance actually requires was never isolated, so the profile is
  reproduced field for field. Trimming it would be a guess.

## Verified hardware

Four air conditioners (`TP1X_DA-AC-CAC-01001`), one induction cooktop, one range
hood (`AHD-WW-TP1-22`), three refrigerators (`TP2X_REF_21K`). Only these four types
are claimed in the app description; the other fourteen are routed and mapped from
the reference but unverified, and that distinction is deliberate — see the support
table in `README.md`.

There is no hardware here for any of the other fourteen, so anything about them
arrives as a report. One has: a user reports a **Blue Sky 5500 air purifier**
working (2026-08-05). That went into the support table as a report, not as
verification, and the air purifier stays out of the four — a report says the unit
paired and showed something, which cannot distinguish a correct reading from a
plausible wrong one. "블루스카이 5500" is a marketing series spanning several model
numbers and at least two board generations, and the board token was not reported,
so which of `AIR`/`TVTL`/`VTWW`/`AVT` carried it is unknown. `docs/BACKLOG.md` has
what would settle it.

The three refrigerators are **two different variants**, and which is which matters
because they behave differently and half the fridge bugs have come from testing one
and assuming the other:

| Paired as | Variant | Notes |
|---|---|---|
| 냉장고 | Fridge-only | One compartment. No convertible mode. Its door lives in the `/doors/vs/0` aggregate; `/door/onedoorfreezer/vs/0` exists but never moves |
| 냉동고, 음료장 | Convertible, same model | Fridge / freezer / **kimchi**. Currently freezer and cooler respectively. Their door lives in `/door/onedoorfreezer/vs/0`; the aggregate sits at Close |

Kimchi is a third convertible position the owner confirms exists on both. Nothing in
the app reads or writes it yet — `docs/BACKLOG.md`.

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
developer dashboard, so a version is not live just because publish succeeded — and
**check which version is actually live before writing the changelog**, because that
is what decides its contents.

**A version number is spent the moment it is published, promoted or not.** A second
`publish` under the same number is refused outright:

    ✖ com.lomohome.localthings@1.0.6 has already been published or is currently in
      review. Increase the version of your app.

So work that lands after a build is uploaded cannot join that build — it needs the
next number, even when the uploaded one never reached the store. Found on 2026-08-10
by trying to fold a day's work into an already-uploaded 1.0.6; the result was 1.0.6
sitting unpromoted with three builds and everything moving to 1.0.7. Bump *before*
publishing anything you may still add to, and expect an abandoned version to become
an `UNPROMOTED` entry rather than something to reuse.

**The entry covers everything since the last live version, not since the last
version.** The two differ whenever a build was never promoted, and then its news has
to travel forward or nobody ever reads it: 1.0.5 sat unpromoted while 1.0.4 was
live, so 1.0.6's entry carries 1.0.5's paragraph as well as its own. Getting this
backwards loses a release's worth of notes silently.

The opposite failure is what happened from 1.0.3 to 1.0.6, where each entry
prepended its news to the whole of the last one regardless: 1.0.6 reached ten
paragraphs of which two were about 1.0.6, so a user opening the store read the app's
entire history under the heading of the version they were installing.
`tests/test_changelog.py` holds both ends — a paragraph may repeat only from a
version listed in its `UNPROMOTED` set, with the reason. **Take a version out of
that set once it is promoted**, or the exception quietly becomes the accumulation
again.
