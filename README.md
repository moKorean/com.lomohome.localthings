# SmartThings Local

**English** · **[한국어 README](README.ko.md)**

A Homey app that controls newer Samsung appliances directly on your own network, with
no SmartThings cloud in between.

It is a port of the Home Assistant integration
[mbillow/localthings](https://github.com/mbillow/localthings) to Homey. The app opens a
DTLS-over-CoAP session straight to the appliance to read state and send commands, so
there is no cloud round-trip.

> **Status: in the [Homey App Store](https://homey.app/a/com.lomohome.localthings/)**
> — follow that link for the version actually live, since a submitted release sits
> in certification for a while before it is served. Four air conditioners, an
> induction cooktop, a range hood and three refrigerators are discovered, paired
> and controlled on real hardware, with state arriving by CoAP OBSERVE (polling
> continues as a five-minute safety sweep). All 77 custom capabilities are usable
> in Flows. The remaining fourteen appliance types are routed and mapped but not
> verified against hardware. Design notes
> and measurements are in [`docs/PORTING.md`](docs/PORTING.md); unmapped resources and
> recorded decisions are in [`docs/BACKLOG.md`](docs/BACKLOG.md).

## How it works

| Layer | Detail |
|---|---|
| Transport | DTLS 1.2 on one of UDP `49152-49160`, authenticated with a client certificate |
| Cipher | `ECDHE-ECDSA-AES128-GCM-SHA256` (requires `@SECLEVEL=0`), ciphertext MTU pinned to 1200 |
| Authentication | A client certificate carrying the identifier published by Samsung's cloud gateway. The appliance checks that identifier, not the signature — so the app issues its own |
| Protocol | CoAP, with token-stable Block2 transfers and OBSERVE subscriptions |
| Payload | OCF resource representations encoded as CBOR |
| Modelling | The `/device/0` batch response is parsed into per-href resources, and a per-appliance-type registry maps hrefs onto Homey capabilities |
| Identification | `/oic/d`, where the appliance declares its own OCF device type, then the board token in its model strings. Two independent routes to the same answer |

## Which appliances

Samsung appliances running Tizen RT 3.x / DAWIT 3.0+ firmware — roughly 2022 and later.

**The app claims support for air conditioners, induction cooktops, range hoods and
refrigerators** — the four types verified on real hardware. The code routes all eighteen
types the reference covers (see [Support status](#support-status)), but the other
fourteen are deliberately left out of the app description and tags because they could not be
tested. They may well work; please try one and report what you find.

If you add an unsupported appliance by IP, the app builds a **support report** from that
appliance's own `/device/0` dump. Per-unit identifiers — serial number, MAC addresses,
your Wi-Fi network name — are redacted; the resource paths and field names needed to map
the type are kept.

Older firmware that only exposes `8888/tcp` (roughly 2018–2022, token-based HTTPS) is
out of scope.

To check an appliance:

```sh
nmap -Pn -sU -p 49152-49160 "$APPLIANCE_IP"
```

The app's **Add device → Search** does the same thing across your whole network, and
identifies what answers, so you do not need to know any addresses.

> The store descriptions live in [`README.txt`](README.txt) (English) and
> [`README.ko.txt`](README.ko.txt) (Korean). Those two files are the app description at
> review time.

## Installing

Install the app and add your appliances. The app issues its own client certificate on
first run, so there is no separate certificate step and nothing to do on a computer.

### 1 — Install the app

**➡️ [Install from the Homey App Store](https://homey.app/a/com.lomohome.localthings/)**

That is all most people need. To run it from source instead — to develop, or to try a
change that has not been released — you need the
[Homey CLI](https://apps.developer.homey.app/the-basics/getting-started) and Docker.

```sh
npm install -g homey
homey login

git clone https://github.com/moKorean/com.lomohome.localthings.git
cd com.lomohome.localthings
homey app install
```

The first run takes a few minutes while `homey app install` resolves `pythonPackages`
into per-architecture virtualenvs.

> `homey app run` (development mode) **replaces** a permanent installation and
> **removes the app when the run ends**. Unless you are developing, use
> `homey app install`.

### 2 — Nothing. The app issues its own certificate

On first run the app reads the identifier appliances expect from Samsung's gateway,
generates a key, and issues itself a client certificate. **Settings → Apps →
SmartThings Local** shows the identifier, the expiry date, and that the app issued it;
there is also a button to issue a fresh one, for after replacing a Homey or if the
identifier ever changes.

**One certificate covers every Samsung appliance in the house.** The identifier comes
from Samsung's gateway rather than from any appliance, so it is one per installation,
not one per device.

What makes this possible is that **the appliance checks the identifier in the
certificate, not who signed it** — measured against an air conditioner and a
refrigerator, both of which accepted a certificate signed by a key generated on the
spot. So no CA private key is fetched, bundled, pasted or stored, and the app needs
nothing from any other machine. (This also means anything on your LAN could do the
same; the identifier is public, and the `AC14K_M` CA key has been public for years.
Issuing locally does not widen that.)

If Homey has no internet route when the app starts, no certificate is issued then —
open the app settings and use the button once it does.

#### Supplying your own certificate instead (optional)

You can still paste a certificate signed by Samsung's `AC14K_M` CA, and it takes
precedence: the app never replaces a certificate you supplied. Use this if you would
rather hold one signed by Samsung, or if an appliance update ever stops accepting the
app's own.

> **➡️ The walkthrough is in [`docs/CA-SETUP.en.md`](docs/CA-SETUP.en.md).**

```sh
git clone https://github.com/QuiteYellow/SmartThings-Local.git
cd SmartThings-Local
python3 -m venv .venv && .venv/bin/pip install pyOpenSSL
OUT_DIR=./certs TARGET_IP=192.168.1.90 .venv/bin/python setup_cert.py --test
```

Paste `client_fullchain.pem` into **Certificate chain** and `client.key` into **Private
key**. `client.pem` will not work — it is the leaf alone. The app **never receives a CA
private key** either way.

### 3 — Add appliances

**Devices → Add device → SmartThings Local → Search**

The app sweeps your local network, finds appliances that answer and identifies each
one. It takes a minute or two, and results appear as they are found. If you know an
address you can type it instead — the field prefills your subnet, so only the last
number needs typing.

### If something goes wrong

A device's **⋯ menu → Maintenance → Repair** checks the connection, finds an appliance
that changed address by serial number, or lets you set an address by hand.

You can inspect an installed app without development mode:

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

## Flow automation

Homey creates Flow cards for **its own built-in capabilities only**. The 77 this app
defines had none, so you could not switch a hood's light from a Flow or raise a
notification from filter wear.

There are now **131 cards** — 29 actions, 78 conditions, 24 triggers.

| Kind | Scope |
|---|---|
| Action | **Every** setable capability. This was the gap that actually blocked automation |
| Condition | **Every** capability. Being able to read a value in a Flow is what makes a sensor worth having |
| Trigger | **Only what is an event** — residual heat, safety shutoff, probe connected, progress. "Child lock changed" is not something a Flow waits for |

That total never lands on one user at once. Every card's device argument carries a
`capabilities=` filter, so **a card is only offered for appliances that have that
capability** — a hood owner sees 21.

### One card for a whole air-conditioner scene

Chaining the single-setting cards makes each one decide what to send from this
app's cache of `/device/0`, which polling refreshes — up to five minutes apart once
the device is on push. A card that runs straight after another can therefore act on
state from before it.

Worse, an acknowledgement is not evidence. Measured on real hardware: switch a
unit on and set its mode about three seconds later, and the write is accepted and
then **overwritten by the mode the appliance restores as it starts**. That is the
setting the reported Flow lost — the one that runs first after "turn on".

**Apply air conditioner settings** takes power, mode, temperature, air purify and
comfort mode in one card. It re-reads the appliance after every step, confirms the
value actually stayed, and re-sends it if the appliance took it back — verified on
hardware to recover exactly the case above. Leave any field on "leave unchanged"
(or temperature at 0) to skip it.

**The operating mode takes priority**, because each mode honours only some of the
other settings — and the ones it does not are still accepted on the wire and
answered without a rejection flag. That is what the original report turned out to
be: the comfort-mode card at the end of the Flow was undoing the mode set earlier,
so the setting that ran first looked like the one that failed.

| Mode | Target temp | Fan speed | Direction | Air purify | Wind-Free | Long wind | Speed |
|---|---|---|---|---|---|---|---|
| AI Comfort | ✓ | | ✓ | ✓ | | | |
| Auto | ✓ | | ✓ | ✓ | | | |
| Cool | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Dry | ✓ | | ✓ | ✓ | ✓ | ✓ | |
| Fan | | ✓ | ✓ | ✓ | ✓ | ✓ | |

Checked mode by mode against the appliance's own interface. The card leaves
anything the chosen mode will not take alone rather than writing it and having it
ignored. `Heat` and `Wind` are absent because these units are cooling-only, and an
unknown mode constrains nothing — the rule is to block only what is confirmed
impossible. The table lives in
[`lib/registry/ac_mode_matrix.py`](lib/registry/ac_mode_matrix.py).

### Homey fires the triggers itself

Homey has a convention for custom capabilities: when `set_capability_value` changes one,
Homey runs a Flow trigger card named `<capability>_true` / `<capability>_false` for a
boolean, or `<capability>_changed` for anything else. The cards use those ids, so the
app has almost no firing code.

It does not fire on every poll because
[`Device._apply`](lib/appliance/device.py) only calls the setter **when the value
actually differs.** Whether or not Homey gates on change internally, the result is the
same.

**Sub-capabilities are the exception.** Homey would look for a card called
`localthings_alarm_hot_surface.2_true`, which cannot exist, so a cooktop's per-burner
residual-heat alarm and a purifier's per-filter alarms would never trigger anything.
**Only those** are dispatched by the app, against the base capability's card — firing
plain capabilities too would trigger every Flow twice.

### Generated and checked

The cards are generated from the capability definitions by
[`scripts/make_flow_cards.py`](scripts/make_flow_cards.py), and a test runs its
`--check` mode: add a capability without its cards and the test fails. **The condition
and action listeners are generated from the same manifest** — writing one per card would
be a hundred near-identical functions, and the first to drift from its card would fail
only for whoever owned that appliance.

Action cards go through `trigger_capability_listener`, not `set_capability_value`. The
latter moves Homey's copy without touching the appliance and does not raise when the
appliance refuses — which would have a Flow report a success it never got.

## What lands in the timeline

Homey writes a timeline line by itself when a **boolean** capability carrying insight
titles changes — which is why power and the absence sensor were already there and
nothing else was. Auto dry and the self check now carry those titles too, so a cycle
starting and finishing shows up as an event, and the absence sensor says which way it
went rather than just that it moved.

Two things cannot go that way, which is why they were missing: a **number** with
insights becomes a chart and produces no line, and a **string** cannot be logged at
all — not one capability of type `string` in Homey's own library sets `insights`. So
mode and target-temperature changes are written explicitly, with the mode in the words
you picked it by. Off by default, per appliance, under **Settings → Timeline**: a house
of nine appliances writing every setpoint change buries the timeline, and one nobody
wants is worse than none.

## It survives an IP change

Identity is the **serial number** (the device's data id), not the address. When an
address changes:

- After three consecutive failed polls the app sweeps the subnet, finds the appliance
  **whose serial matches** and updates itself. No re-pairing.
- The serial is checked on every poll, so **two identical units that swap addresses
  cannot end up driving each other** — the app fails rather than binding to the wrong
  appliance.
- The IP, port and connection status in the device's advanced settings always reflect
  reality.

Relocation takes a minute or two, during which the device is unavailable. Reserving a
**static lease** on your router avoids the path entirely.

## Requirements

- **Homey Pro on firmware v13.0.0 or newer.** The app runs on Homey's Python runtime
  (`"runtime": "python"`, Python 3.14), so it will not install below v13.
- `local` platform only, because it needs LAN UDP. It cannot work on Homey Cloud.
- **A client certificate** — the app issues its own on first run; nothing to prepare.
  You may instead supply one signed by
  `AC14K_M` on your computer, once, and paste it into **Settings → Apps → SmartThings
  Local**. Because the UUID comes from Samsung's gateway rather than from any appliance,
  **one certificate covers every Samsung appliance in the house**, and adding an
  appliance afterwards needs only its IP address. See
  [`docs/CA-SETUP.en.md`](docs/CA-SETUP.en.md).

  The app **never receives a CA private key** — it stores only an already-issued
  certificate.

## Layout

```
app.py                        Entry point (subclasses homey.app.App, exported as homey_export)
api.py                        Settings-page API (validate, store and describe the certificate)
settings/index.html           App settings — certificate entry and issuing instructions (en/ko)
lib/
  const.py                    Measured protocol constants (port ranges, timeouts, source-port bases)
  cert.py                     Certificate validation and description, gateway UUID check (pure cryptography)
  probe.py                    Port sweep, DTLS liveness gate, and the pairing probe
  discovery.py                Subnet sweep, response-based, no false positives
  compat.py                   SDK contract adapters (settings and i18n, sync and async)
  session.py                  asyncio wrapper around DtlsCoapSession
  resources.py                /device/0 batch parsing, serial handling
  registry/                   Type routing (/oic/d, then board tokens) and per-appliance capability maps
    ac_mode_matrix.py         Which settings each air-conditioner mode actually honours
  support.py                  Unsupported-appliance report, with per-unit identifiers redacted
  selfcheck.py                Runtime self-check, once at startup
  appliance/                  Driver and device implementation, separated so a per-type driver could subclass it
    driver.py                 Discovery, pairing, Flow card listeners
    device.py                 Session upkeep, poll loop, writes, capability reconciliation
drivers/appliance/
  driver.py                   15-line shim subclassing lib/appliance/driver.py
  device.py                   15-line shim subclassing lib/appliance/device.py
  pair/configure.html         Pairing view (en/ko). Manual IP entry prefills the subnet
  repair/reconnect.html       Repair view — check the connection, find by serial, set an address
locales/{en,ko}.json          App i18n (without it, i18n.get_language falls back to en)
scripts/
  make_flow_cards.py          Generates Flow cards from the capability definitions (--check verifies)
  make_store_images.py        Store images; make_driver_images.py does the driver images
  check_reference_coverage.py Reports what the reference routes and this app does not
tests/
  fixtures/                   Real /device/0 dumps, with identifiers obfuscated
  test_registry.py            Registry regression tests
  test_range_hood.py          Pins the hood mapping against a real dump
  test_refrigerator.py        Three refrigerators compared (convertible cooling/freezing, fridge-only)
  test_flow_cards.py          Checks the generated cards against the capability definitions
  test_support_report.py      Checks the redaction in the unsupported-appliance report
python_packages/              Per-architecture venvs built by the Homey CLI (not committed)
```

The transport layer is not reimplemented here; it is delegated to
[`smartthings-local`](https://pypi.org/project/smartthings-local/), declared in
`app.json`'s `pythonPackages` and installed by the Homey CLI into per-architecture
virtualenvs with `uv` at build time.

**There is one driver, not one per appliance type.** The type is determined at runtime
from the resource surface, so at pairing time there is nothing to base a driver choice
on. Instead each device is created with only the capabilities `Registry.capabilities()`
computed for it, so a unit gets exactly what it reported.

### Support status

All **eighteen** types the reference supports are routed, but they are verified to
different degrees. An unverified entry was ported from the reference's field definitions
and never seen on the appliance itself — and as the range hood demonstrated,
**guessing field names is usually wrong**: it pairs, shows capabilities, and reads
nothing.

| Appliance | Status |
|---|---|
| **Air conditioner** (`RAC/PRAC/KRAC/CAC/WAC/FAC/CAWW/ARA`) | **Verified on hardware.** Power, target and current temperature, mode, fan, comfort modes, airflow, air purify, auto clean, panel and edge lighting, UV, absence power saving, humidity, power, dust, filter, sound, Smart Cool Clean state and progress (38) |
| **Induction cooktop** (`COOKTOP`) | **Verified on hardware.** Per-burner level, state and residual heat, child lock (writable), smart control, safety shutoff, power, Bluetooth probe (19) |
| **Range hood** (`AHD`) | **Verified on hardware** (AHD-WW-TP1-22). Power, 5-step fan (writable), light on/off and 2-step brightness (writable), auto-ventilation state, filter usage and replacement alarm, air quality and PM10/2.5/1.0, cumulative energy (14) |
| **Refrigerator** (`REF`) | **Verified on hardware** (three TP2X_REF_21K Kitchen Fit units — convertible cooling, convertible freezing, fridge-only). Per-compartment current and target temperature (writable), convertible-compartment mode (read-only — the appliance refuses the change remotely, including from Samsung's own app), rapid cool (writable), door, two cumulative energy counters, instantaneous power, self check, firmware (9) |
| Washer (`WW/WD/WF/WV/WA*`) | Unverified. Machine state, progress, remaining time, wash temperature, spin, rinse, cumulative water |
| Dryer (`DV*`) | Unverified. Machine state, progress, remaining time, dry level, wrinkle prevention |
| Dishwasher (`ADW`, `DW*`) | Unverified. Machine state, progress, sanitize, heated dry, cumulative water, sound |
| Air purifier (`AIR/TVTL/VTWW/AVT`) | Unverified. Fan, panel light, pet filter, HEPA filter, air quality, PM10/2.5/1.0 |
| Dehumidifier (`DHM`) | Unverified. Humidity, target humidity (writable), filter |
| Oven, range, microwave (`OVEN/RANGE/MICROWAVE`) | Unverified. Operation state, mode, cavity and target temperature, door — **no heat control** |
| Gas cooktop (`CT`) | Unverified. Power state, whether a burner is in use — **read-only** |
| Water purifier (`WATERPURIFIER`) | Unverified. Operation state, child lock, water filter, cumulative water |
| Clean station (`VSKR`, `VSWW`) | Unverified. Operation state, dust bag usage and warning |
| AirDresser (`DF`) | Unverified. Operation state, progress, sanitize |
| Air monitor (`ASM`) | Unverified. Air quality, PM10/2.5/1.0, CO2, humidity, battery — sensors only, the board has no power resource |
| Heat pump (`EHS`) | Unverified. Power, leaving-water temperature and setpoint. Zone mode, the hot-water loop and away mode need capabilities of their own — see BACKLOG |

**What "unverified" means**: the field names, resource paths and writability were taken
from the reference's definitions, and routing and manifest consistency are covered by
tests — but **the type has never been seen on the actual appliance.** Where the
reference's comments left a shape ambiguous, a value may read wrongly. The shared core
(power, child lock, alarms, energy, operation state) is the same code already working on
the verified types.

**No appliance type exposes heat control.** The reference states the principle for
cooktops — an automation must never start heating remotely — and this port applies it to
ovens, ranges, microwaves and cooktops alike, enforced by a test.

`CAC` (Korean ceiling/commercial units) was missing from the reference's routing table
and added here.

### Staying in sync with the reference

A script checks whether the reference has gained appliance support. It compares the
**routing tables directly** rather than release notes, so a token added quietly is still
caught.

```sh
cd ../localthings-reference && git pull && cd -
python3 scripts/check_reference_coverage.py
```

It reports types not yet ported, board tokens the reference routes and this app does
not, tokens the two route differently, and **tokens only this app has**, which are
candidates to contribute upstream.

## Reference projects

Three projects are cloned alongside this one and used as continuous references. None of
them is vendored into this repository.

### 1. `../localthings-reference/` — [mbillow/localthings](https://github.com/mbillow/localthings)

**The port's origin.** A Home Assistant custom integration for local control of newer
Samsung appliances (MIT). Appliance-type detection, the href → entity registry, state
polling and OBSERVE management, the certificate-issuing flow — **the whole
device-modelling layer** is here. This is the part being ported.

It does not implement the low-level transport itself either; it delegates to the
[`smartthings-local`](https://pypi.org/project/smartthings-local/) library from
[QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local) — pure
Python, with only `cbor2` and `pyopenssl` as dependencies. DTLS goes through pyOpenSSL's
`SSL.DTLS_METHOD`.

Files worth reading:

| File | Contents |
|---|---|
| `config_flow.py` | Adding a device: UUID lookup → certificate issue → port sweep → `/device/0` check |
| `coordinator.py` | DTLS session lifecycle, polling, the write path, per-device fixed source port |
| `observe.py` | OBSERVE subscriptions, demotion to polling on failure, retry |
| `registry/` | href → capability → entity mapping (most of the code) |

```sh
cd ../localthings-reference && git pull   # refresh the reference
```

### 2. `../smartthings-local-reference/` — [QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local)

**Source of the transport layer.** The upstream repository for the
[`smartthings-local`](https://pypi.org/project/smartthings-local/) package installed via
`app.json`'s `pythonPackages`. The package alone is enough to run, but the source is
needed when debugging the protocol.

- `smartthings_local/protocol/dtls_session.py` — DTLS handshake and CoAP session. The
  comments here are the evidence for the non-negotiable wire constants
- `smartthings_local/protocol/coap.py` — CoAP encoding and decoding, Block2, OBSERVE
- **`setup_cert.py`** — the certificate-issuing script users run once; see
  [`docs/CA-SETUP.en.md`](docs/CA-SETUP.en.md)
- `mqtt_demo/` — an example bridge built on the library, useful for session lifecycle

### 3. `../homey-pythonscript-reference/` — [jaccoh/homey-pythonscript](https://github.com/jaccoh/homey-pythonscript)

**Proof that Python works on Homey.** A Homey app that runs Python from Advanced Flow.
What it establishes:

- Homey Apps SDK v3 **supports a native Python runtime.** Declare `"runtime": "python"`,
  `"pythonVersion": "3.14"` and `"pythonPackages": [...]` in `app.json`, and export a
  subclass of `homey.app.App` from `app.py` (needs `compatibility: ">=13.0.0"`).
- `pythonPackages` is resolved by the Homey CLI at build time with `uv` into
  **per-architecture virtualenvs** (`python_packages/{amd64,arm64}/.venv/`) shipped with
  the app — so native wheels are fetched for the target architecture, which is
  linux-aarch64 on Homey Pro.
- A venv can even be created and populated at runtime under `/userdata/venvs/`
  (`pythonscript/venv_manager.py`).

**Why that matters here:** Node.js has no DTLS, so the alternative was reimplementing a
DTLS and CoAP stack in pure JavaScript. With the Python runtime, declaring
`smartthings-local` in `pythonPackages` is the entire transport layer, and the reference
integration's Python can be carried across nearly as-is. The full comparison is in
[`docs/PORTING.md`](docs/PORTING.md), section 2.

Files worth reading: `app.json` (how the runtime is declared), `app.py` (entry point and
Flow card registration), `pythonscript/venv_manager.py` (runtime venv management),
`api.py` (the settings-page API).

## Development

```sh
homey app build                    # resolve pythonPackages into per-arch venvs (needs Docker)
homey app validate --level publish
homey app install                  # permanent install
```

> `homey app run` (dev mode) replaces a permanent installation and **removes the app
> when the run ends.** Run `homey app install` again afterwards.

An installed app can be inspected without dev mode:

```sh
homey api raw --path /api/app/com.lomohome.localthings/diagnostics
```

It returns the resolved language, locales, credential sizes, and per-device push state
(subscription count, notifications seen, whether it is observing).

Two more endpoints exist because mapping an appliance correctly means reading what it
actually reports rather than guessing, which is how the range hood shipped with every
field name wrong:

```sh
# every resource each appliance reports (per-unit identifiers redacted; raw=1 opts out)
homey api raw --path /api/app/com.lomohome.localthings/resources

# one path, on every appliance at once — for paths /device/0 does not carry
homey api raw -X POST --path /api/app/com.lomohome.localthings/read-resource \
  --body '{"path":"/oic/d"}'

# write one path and read it straight back, so "accepted but not committed" shows up
homey api raw -X POST --path /api/app/com.lomohome.localthings/write-resource \
  --body '{"host":"192.168.1.203","path":"/temperature/desired/cooler/0",
           "body":{"temperature":4}}'
```

`/oic/d` is the case `read-resource` was added for: it is absent from every `/device/0`
batch response, so whether real hardware populates it could not be answered without a
direct GET. All nine appliances here do.

`homey app build` pulls the official builder images
(`ghcr.io/athombv/python-homey-app-builder-{arm64,amd64}`) and produces
`python_packages/{amd64,arm64}/.venv/`. Those are not committed — about 36 MB of
binaries, reproducible from `app.json`. After a fresh clone, run `homey app build` once.

For local tests and linting:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check .
```

## Languages

Korean and English are supported, and **any language not declared falls back to
English** — app name, description, 77 capabilities, 131 Flow cards, settings labels,
three webviews and device names alike. `tests/test_i18n.py` enforces it, because adding
a Korean string and forgetting the English one is invisible to whoever wrote it.

Error messages raised from Python are translated too. Homey's server-side i18n resolves
the *app's* language rather than the user's, so the app stores the UI language a webview
reported and uses that — see [`docs/PORTING.md`](docs/PORTING.md), section 11.

## Licence

GPL-3.0-or-later.

The protocol analysis and device registry design build on
[mbillow/localthings](https://github.com/mbillow/localthings) (MIT, © Marc Billow) and
[QuiteYellow/SmartThings-Local](https://github.com/QuiteYellow/SmartThings-Local), and
the DTLS-CoAP transport is `smartthings-local` (MIT, © Jack Nagy) used unmodified. MIT
permits reuse but requires the copyright and permission notices to travel with the code,
so both licences are reproduced in full in [`NOTICE`](NOTICE), which also records which
part of this app derives from which project. The same credit is in the app manifest's
`copyright` and `contributors` (App Store guideline 2.1).

`assets/capabilities/mdi-*.svg` are taken unmodified from
[Material Design Icons](https://pictogrammers.com/library/mdi/) (Pictogrammers Free
License / Apache-2.0). New capability icons come from the same set:

```sh
curl -O https://raw.githubusercontent.com/Templarian/MaterialDesign/master/svg/<name>.svg
```
