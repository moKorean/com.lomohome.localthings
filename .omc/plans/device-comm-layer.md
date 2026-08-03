# Device communication layer — work plan

**Status: pending approval.** Revised after Architect and Critic review (verdict:
ITERATE). Four items cut, one added at the front; the amendments are folded in, not
re-argued.

Mode: **DELIBERATE**. Nine appliances in a lived-in home sit behind this code; the
transport is the one layer where a wrong change is invisible in tests and visible in
the house.

---

## Corrections to the briefing, before anything else

### The fact that reorganises everything below

`DtlsCoapSession.subscribe()`'s docstring (smartthings-local 0.1.2,
`protocol/dtls_session.py:633-639`): *"The initial 2.05 notification and all
subsequent state-change notifications will fire on_notification"*. The initial 2.05
fires **on registration**, not on appliance activity, so a healthy channel produces one
notification per registration whatever the appliance is doing.

The measured 3/27 therefore means **24 registrations produced nothing**. Idleness does
not explain it. Every reading below that treated a low count as "the appliance was
quiet" is void — including the one 0.6.4 was built on.

### C1. The subscribe burst does not block anything. It floods.

`subscribe()` is fire-and-forget: it mints a 1-byte observe token, registers it in
`_observe_tokens`, calls `_send_dgram` once, and returns. It never calls `pace()` and
never waits for the 2.05. `_send_dgram` (`:338`) sets `_last_send_ts` but does not pace
either. `pace()` is called from one place: `get()`, for block index > 0.

- 27 subscribes take **microseconds**, not 5 s, and `Session.subscribe` takes and
  releases `self._lock` once per href — so polls and writes were never queued behind a
  5-second hold. That premise is void.
- What happens instead is 27 CON registrations at line rate. **Corrected framing:** the
  `5 req/s` figure is not a documented appliance limit. `dtls_session.py:58-63` records
  measured ceilings of *dryer ~14 req/s, oven ~8 req/s, dishwasher unknown*, and says
  5 req/s "is conservative enough for all tested devices; tune per device once the
  ceiling is measured empirically". **No AC ceiling has ever been measured.** The honest
  statement: 27 sends with no inter-send delay into an appliance whose input ceiling is
  unknown, while the library's own bulk path (`refresh_observes`, `:604`) sleeps 0.1 s
  after the deregisters and 0.05 s between subscribes. "100x over the documented limit"
  was arithmetic on a default, and is withdrawn.

One live hypothesis for the 24 missing notifications, now one of three — the cheapest to
test, and one line.

### C2. Deregistration is not missing. It is missing *on the two paths that matter*.

`session.close()` (`:277`) deregisters every live token before shutting DTLS down, so
`on_uninit` and `move_to` do clean up — when they run. What never deregisters:

- **Demotion.** `_evaluate_observe` sets `_observing = False` and returns.
- **Re-subscription.** `_try_observe` calls `Session.subscribe` again for hrefs already
  in `Session._subscribed`. Each call mints a new 1-byte token (`_next_observe_tok`,
  `:325`), seeded in `0x40..0xff` and wrapped with `& 0xFF` — a small space against 27
  hrefs a round. After enough rounds a registration **collides with a token the
  appliance still holds**, which the library's comment says silently no-ops.
  `refresh_observes()` exists to prevent exactly this, and is unused.

`Session._subscribed` is a `set`, so re-subscribing does not move `subscription_count`.
The one diagnostics field that would show the leak cannot — and the settings panel shows
that same count to the user as "push, N subscriptions".

**Defect D1 — C2 can produce wrong values, not only missing ones.** `subscribe()` does
`self._observe_tokens[tok] = href` (`:647`). On a wrapped token that is an *overwrite*:
the map now points that token at the new href while the appliance may still be pushing
the old href's rep under it. The reader looks the token up (`:458`), finds the new href,
and `_dispatch` merges the old resource's rep into `_resources[wrong_href]`. Different
shapes yield `None` and nothing visible; **same-shaped siblings — this hardware has
several temperature resources — put a real value on the wrong capability.** C2 is
therefore silent corruption as well as silence, which raises its priority over C1.

### C3. The notification arrived and this app discarded it. (new)

Three drop paths sit between the 2.05 and a capability update, none observable today:

- `Session._dispatch` (`lib/session.py:49-60`) returns silently on an **empty payload**,
  a **CBOR failure**, and a **non-dict rep**. The last is not hypothetical:
  `read_resource` (`:150-160`) has its current form *because* non-dict reps occur — it
  wraps them as `{"value": decoded}`. `_dispatch` has no such branch.
- The library's reader drops any observe response that is not 2.05 with
  `logger.warning("observe %s: non-2.05 %s", ...)` (`dtls_session.py:460-463`). There is
  no `homey app log`, so that goes nowhere a person can read.
- The same reader logs and swallows exceptions from our callback (`:468-470`).

C3 predicts the same symptom as C1 and C2 and needs a different fix. Instrumented in
item 0; in the pre-mortem.

**Defect D2 — `_on_notification` drops rather than defers during `_settling`.**
`device.py:314-318` returns inside the window, discarding the rep. `_notified.add(href)`
happens first, so the health verdict still counts the notification; the **value** is
lost until the next read. The next reader is the 300 s sweep, which then sees a change
push "did not deliver" — so the settle window can manufacture the signal a demotion rule
would watch for. This is part of why demotion left the plan, and it is what item 5 must
bound.

---

## What `_observing == true` is allowed to claim

Three surfaces read the flag: `/diagnostics` → `"observing"` (`api.py:365`); the device
settings panel, where `_sync_settings` writes `status = "push, N subscriptions"` with
N = `len(Session._subscribed)` (`device.py:486-488`); and the `is_pushing` Flow condition
(`device.py:874-876` → `driver.py:136-138`).

After item −1 it claims exactly this: *at the last verdict — up to `OBSERVE_REFRESH_S`
(6 h) ago — at least `OBSERVE_SUCCESS_FRACTION` of that round's registrations produced
their initial 2.05 inside `OBSERVE_GRACE_S`.*

It does **not** claim push is alive now, that anything has arrived since, or that a given
href is really observed — one whose registration silently no-oped stays in
`_observe_hrefs`. All three surfaces render it in the present tense, and the panel's
"N subscriptions" cannot show the C2 leak, so it overstates too. This plan relabels
nothing; the only present-tense claim it makes available is item 0's `notifications`
advancing while `_observing` is true. Relabelling goes with demotion, in the re-plan.

---

## Principles

1. **An ACK is not evidence, and neither is a send.** `subscribe()` returning a token
   proves a datagram left the host; a 2.04 proves a request was parsed. Neither is a
   claim about device state. Every item that changes behaviour has a read-back as its
   acceptance test, not a return code.
2. **Silence about a change is not a fault; silence at registration is.** A value that
   never changes never notifies again, and the 300 s sweep covers that. But the initial
   2.05 fires on registration regardless of activity, so a registration that produced
   nothing is a failed registration. 27/26/3/6 is evidence of a broken channel on two
   units, not of two quiet appliances. Item −1 implements this correction.
3. **Measure the instrument before the change.** The one field that could have revealed
   C2 cannot, by construction, and all three of C3's drop paths are invisible. Counters
   first, or "it got better" is unfalsifiable.
4. **Cost is correctness here.** At `BLOCK_SZX = 6` an 11 KB `/device/0` is ~11 round
   trips, so nine of them is ~100 requests of a shared budget. **Corrected:** the earlier
   "≥2.0 s of mandatory inter-block pacing" is wrong — `pace()` sleeps only
   `_min_req_interval - (now - _last_send_ts)`, and only if positive (`:175-180`), so on
   a transfer whose round trips exceed 200 ms it sleeps **zero**. 2.0 s is a ceiling, not
   a floor; the measured 2-8 s per read is round-trip time, not pacing.
5. **A documented divergence is a measurement someone already paid for.** Source-port
   pinning, appending rather than promoting the rescued probe ports, swallowing `/oic/d`
   failures — each has its cost model written down, and none are in scope. (`needed = 1`
   was on this list in the previous draft. It does not belong: it is an inference from a
   misread measurement, which is what item −1 is for.)

## Decision drivers

1. **Push either works or is honestly reported.** Today a device can be recorded as
   pushing with a dead channel; under 0.6.3 a live channel could be recorded as never
   notifying. Both are failures of the same subsystem.
2. **Request budget per session.** One session per appliance carries poll, sweep, write
   verification and subscribe. The AC card costs ~100 requests per run *by the block
   model* — an estimate until item 0's `gets` counter exists, labelled as one throughout.
3. **Blast radius on real hardware.** Nine paired appliances; verification writes change
   the user's home. Prefer zero-write verification, and confine the write-path change to
   one unit in an empty room with a recorded restore.

---

## Options

### For the AC card's nine full reads

**Option A — targeted single-href verification.** Add `refresh_href(href)`: read that
resource via `Session.read_resource`, fold it into `_resources`, `_apply(only_href=…)`.
`_apply_step` and `_reconcile` verify against the one href each setting reads from.

- Pro: 7 small single-block resources — 1 request instead of 11 per verification;
  ~100 → ~32 (model in item 3).
- Pro: **verified safe for this card.** All seven readers take `(rep, _resources)` and
  ignore the second argument (`_read_power`, `_read_mode`, `_read_target_temp`,
  `_read_fan`, `_read_airpurify`, and the `_read_enum`/`_read_flag` factories). The only
  AC reader that uses `resources` is `_read_meter_kwh`, which is not a card step.
- Con: a future spec cross-reading two hrefs would silently verify against a stale
  sibling. Needs a guard.
- Con: it removes wall-clock time between write and verification, and how much settle
  margin that provided is **unmeasured** — which is why item 5 now runs first.

**Option B — keep `/device/0`, verify once at the end.** No new read path, no per-spec
assumption; but it gives up the property the card was built for — each step deciding from
what the appliance holds *now*, added because steps racing the appliance was the original
bug — and still costs 11 requests per remaining read.

**Option C — trust the write's echoed response.** *Invalidated.* CLAUDE.md's "an
acknowledgement is not evidence" plus three recorded bugs (mode overwritten during
power-on restore; comfort mode silently leaving AI Comfort; list-shaped payload
truncating the cache). The card exists *because* the echo lies.

**Chosen: A.** B's "skip the redundant up-front read" sub-change is **cut** (see
*Removed from this plan*).

### For push demotion

Deferred to a re-plan. Option A (demote on a sweep-detected miss on an observed href)
stays the recorded direction in `docs/BACKLOG.md`, but D2 shows the settle window can
manufacture that signal and the 27/26/3/6 reading behind it has been overturned. What
survives here is the `sweep_detected_misses` counter and a 24 h baseline — a measurement,
not a verdict.

**Option C — call `_push_is_healthy()` as written.** *Invalidated, but not for the reason
previously given.* "Device-wide silence is the signal" is the same misreading as
`needed = 1`: it treats absence of *change* traffic as the only evidence, when
registration traffic is evidence too and is the part that is failing. The function is
deleted in item −1, uncalled, rather than wired up.

---

# The plan

## Bucket A — measured evidence already in hand

### Item −1. Narrow 0.6.4: restore the verdict, and make the backoff engage

**Sequenced first among code changes.**

**Problem.** 0.6.4 replaced `OBSERVE_SUCCESS_FRACTION` with `needed = 1` on the reading
that 3/27 and 6/27 were idle appliances sending nothing. Per `subscribe()`'s docstring
those rounds had 24 and 21 *failed registrations*. The verdict now passes on one
notification out of 27 and cannot fail — and this repo's own standard is that a check
which cannot fail reads as evidence.

Separately, `device.py:295` reads `if got:`. With `got = 3` that is truthy, so
`_observe_silent_rounds` resets and `_observe_retry_after()` stays at `OBSERVE_RETRY_S`
(600 s) forever. **The backoff never engages on a partial round.** That — not the 80%
threshold — is why the living-room AC re-subscribed 27 hrefs every ten minutes under
0.6.3. Confirmed by reading the code. 0.6.4 removed the threshold and kept the bug, so it
fixed the waste by making the verdict unfalsifiable instead of by fixing the lever.

**Evidence.** `dtls_session.py:633-639`; `device.py:262-296`; `const.py:83-96`;
`tests/test_reference_sync.py:887-914`.

**Change.**
1. Restore `OBSERVE_SUCCESS_FRACTION` in `const.py` at its 0.6.3 value (0.8) and
   `needed = max(1, int(len(hrefs) * OBSERVE_SUCCESS_FRACTION))`. Replace the comment at
   `device.py:262-274` with the registration reading, citing `subscribe()`'s docstring —
   the old comment argues from a measurement since reinterpreted, and leaving it would
   re-justify the removal.
2. `if got:` → `if got >= needed:`, so a **partial** round widens the retry as a silent
   one does. This kills the measured waste at the correct lever and restores
   `notified_hrefs` to an interpretable per-round count out of that round's registration
   count — which is what makes experiment E1 readable.
3. Delete `_push_is_healthy()` (`device.py:300-308`) — defined, called from nowhere, and
   its docstring states the same misreading. Remove `PUSH_HEALTH_WINDOW_S`
   (`const.py:96`) with it if nothing else references it.
4. Tests. Four in `tests/test_reference_sync.py` pin 0.6.4's reading; the amendment named
   the first, the other three fail or mislead once this lands:
   - `test_one_notification_is_enough_to_earn_push` (`:887`), asserting `needed = 1` and
     no `OBSERVE_SUCCESS_FRACTION` — **delete**.
   - `test_the_activity_threshold_is_gone_entirely` (`:911`), asserting `const` has no
     such attribute — **delete**.
   - `test_the_verdict_resets_the_counter_when_anything_arrived` (`:859`), asserting
     `"if got:" in body` — **rewrite** to pin `got >= needed` as the gate on the reset.
   - `test_a_partial_channel_keeps_the_normal_cadence` (`:849`) — still passes as written
     (it sets the counter by hand) but its name and docstring assert the opposite of the
     new rule; **rewrite** to a partial round incrementing.
   Keep `test_silence_still_disqualifies` and both backoff tests unchanged.
5. Add the guard test: `OBSERVE_REFRESH_S == 6 * 3600`. E1 and item 2 both lower it in a
   dev install, and shipping the lowered value is a 36x subscribe-cost regression across
   nine devices.

**Risk — stated plainly, because it looks like a regression.** The two ACs at 27/27 and
26/27 keep push; the two at 3/27 and 6/27 lose it, and their interval returns from
`OBSERVE_SWEEP_INTERVAL_S` (300 s) to `POLL_INTERVAL_S` (30 s) — by the block model ~288
to ~2,880 full `/device/0` reads a day each, ~10x more read volume on those units.
Relative to 0.6.3 nothing changes; relative to the **deployed** build it is a real cost
increase, and it is the price of a verdict that can fail. The widened backoff pays part
of it back: those units stop re-subscribing 27 hrefs every ten minutes. Record the `gets`
delta once item 0 lands, and say so in the changelog so "push lost" does not read as
breakage. The 0.8 value is inherited from the reference and unmeasured here — in open
questions.

**Hardware verification (non-destructive, zero writes).** Install; read `/diagnostics`
after one poll cycle plus `OBSERVE_GRACE_S`.

**Acceptance criteria.**
- `observing` is `false` on the two units last judged 3/27 and 6/27, `true` on the two at
  27/27 and 26/27. The flip is the expected outcome, not a bug.
- On a unit with a partial round, `observe_retry_after_s` is strictly greater than 600 on
  the second consecutive partial round. Under the old code it is exactly 600 forever;
  that inequality is the fix, read numerically.
- `_push_is_healthy` no longer exists anywhere in the tree.
- A test pins `OBSERVE_REFRESH_S == 6 * 3600`; the four tests above are deleted or
  rewritten as listed.
- `ruff`, `pytest`, `check_reference_coverage.py`, `homey app validate --level publish`
  all clean.

---

### Item 0. Instrument the transport before changing it (slim)

**Problem.** The only observe instrument is `Session.subscription_count`, and because
`_subscribed` is a set it cannot show C2's leak. All three C3 drop paths are invisible.
There is no request counter and no notification total. Items 1, 2, 3 and the demotion
re-plan are unfalsifiable without these.

**Evidence.** `lib/session.py:36,49-60,139,142`; `api.py:359-385`;
`dtls_session.py:460-470`.

**Change.** Counters incremented where the work happens, and nothing more — the previous
draft's `blocks_received`, `posts`, `polls` and `reconnects` are dropped, because no
surviving item reads them and `gets` carries the cost delta.

- On `Session`: `gets`, `subscribe_sends`, `notifications`, `last_notify_monotonic`, and
  `dispatch_drops` **split by reason** — `empty_payload`, `cbor_error`, `non_dict_rep`,
  one per `return` in `_dispatch`.
- C3's other two paths are inside the vendored library, on its reader thread, in a file
  this app does not own. Get them without forking it: attach a counting
  `logging.Handler` to the `smartthings_local.protocol.dtls_session` logger, bucketed by
  message prefix — `observe_non_205` (`"observe "`), `refresh_dereg_failures`
  (`"refresh dereg"`), `notification_callback_errors` (`"notification callback"`). This
  is the only readable route: there is no `homey app log`, and `homey app run` would
  replace the installed app.
- On `ApplianceDevice`: `last_poll_duration_s`, and `sweep_detected_misses` — all that
  survives of the demotion item.
- Surface them in `_device_report`. Rename nothing; `subscription_count` stays, with
  `subscribe_sends` beside it so the gap between the two *is* the leak readout.

**Risk.** Near zero; additive and read-only. Two hazards: counters touched from the
library's reader thread (`notifications`, `last_notify_monotonic`, `dispatch_drops`, every
logging bucket) must be plain int/float stores — GIL-atomic — and must not touch the event
loop; and the logging handler must never raise, or a diagnostic becomes a new drop path.

**Hardware verification (non-destructive, zero writes).** Install, wait 15 min,
`homey api raw --path /api/app/com.lomohome.localthings/diagnostics`. Commit the
nine-device table to `.omc/plans/` as the baseline every later item is compared against.

**Acceptance criteria.**
- Across ≥2 **forced refresh** rounds (`OBSERVE_REFRESH_S` lowered in a dev install),
  `subscribe_sends` > `subscriptions` on a device whose href set did not change. That
  inequality is C2's leak, numerically. (The previous draft said "≥2 observe retry
  rounds"; retry rounds are unreachable on a channel that works and item −1's widened
  backoff makes them rare on one that does not, so it was untestable as written.)
- `notifications` on at least one device exceeds `notified_hrefs`, proving the total is a
  total and not a set size.
- `dispatch_drops` and `observe_non_205` present, per reason, on all nine devices. A zero
  is a finding; an absent field is not.
- Unit test: a fake session driven through N gets / M subscribes / K dispatches reports
  exactly N, M, K, and one dispatch per drop reason lands in the right bucket (empty
  payload, undecodable bytes, a CBOR list rep).
- Nine-device baseline table exists in `.omc/plans/`.

---

### Item 1. Pace the subscribe burst

**Problem.** 27 CON registrations with no inter-send delay into an appliance whose input
ceiling has never been measured. See **C1**.

**Evidence.** `dtls_session.py:633-654` (sends and returns, no `pace()`); `:338`;
`:58-63` (5 req/s is a conservative untuned default; dryer ~14, oven ~8, AC unmeasured);
`:604-631` (the library paces its own bulk path).

**Change.** In `Session._subscribe_unlocked`, call `self._session.pace()` inside the
executor before `subscribe()`. `pace()` is public, uses the session's own
`_last_send_ts`, and sleeps on `_stop` so teardown wakes it — the intended tool. 27
subscribes then take ~5.4 s of wall time, which is acceptable: `_try_observe` is awaited
inside `_poll_once`, and the lock is released between each one, so a concurrent write
still gets a slot.

**Risk.** A poll that includes a subscribe round takes ~5.4 s longer. Fine at 30 s, and
commit 1 has already removed the coupling that let a Flow card inherit that cost.

**Forcing mechanism.** Waiting six hours for a refresh round is not a test loop. Lower
`OBSERVE_REFRESH_S` to ~10 min in a **dev install** to force rounds on demand, and
restore it before publishing — item −1's guard test is what stops the lowered value
shipping.

**Hardware verification (non-destructive, zero writes).** The living-room AC: 27
subscribed, 0 notifications, repeatedly. Install, force one round, wait past
`OBSERVE_GRACE_S`, read `/diagnostics`, and compare `notifications`, `notified_hrefs`,
`dispatch_drops` and `observe_non_205` against item 0's baseline for that unit.

**Acceptance criteria.**
- The living-room AC records ≥1 notification where the baseline recorded 0, **or** it
  still records 0 and C1 is **falsified for that unit** — written into `docs/BACKLOG.md`
  with the numbers. Either outcome closes the item; only one keeps the change. A non-zero
  `dispatch_drops` or `observe_non_205` in the same reading reassigns the cause to C3
  rather than leaving it open.
- Across nine devices, initial-notification counts after a round are ≥ baseline. No
  device regresses.
- Unit test: 27 subscribes issue 27 `pace()` calls, one before each send, in order.
- A poll cycle including a subscribe round completes without raising and without the
  poll-failure counter advancing.

---

### Item 2. Deregister before re-registering

**Problem.** Re-subscription mints fresh tokens and abandons the old ones, growing the
appliance's observer table until a new token collides with one it still holds — the
registration then silently no-ops, and per **D1** a notification can be applied under the
wrong href in the meantime. See **C2**.

**Evidence.** `device.py:_try_observe`; `session.py:136-143` (set semantics hide it);
`dtls_session.py:325-336` (1-byte token, random seed, `& 0xFF`) and `:647` (the
overwrite); `:604-631` (`refresh_observes`, unused).

**Change.**
1. Expose `Session.refresh_observes(paths)` delegating to the library method.
2. In `_try_observe`, when the branch taken is the `OBSERVE_REFRESH_S` refresh (already
   `_observing`), call `refresh_observes` instead of re-`subscribe`.

The previous draft's step 3 — `unsubscribe_all()` on demotion — is **cut**: demotion left
this plan and the dereg belongs with whatever re-plans it.

**Risk.** `refresh_observes` has a stated race: a notification on an old token between
dereg and re-subscribe is dropped as stale. At a 6 h cadence that is the trade the library
author already accepted, and it is strictly better than D1's mis-attribution. It sleeps on
the calling thread (0.1 s + 0.05 s × N ≈ 1.5 s for 27 hrefs), so it must stay inside
`_run`.

**Hardware verification (non-destructive, zero writes).** Read-only but slow: the leak
only shows across rounds. With `OBSERVE_REFRESH_S` lowered to ~10 min, run ~1 h (≈6
rounds) and confirm from `/diagnostics` that `subscribe_sends - subscriptions` stops
growing and notifications keep arriving at round 6. Restore the constant before
publishing.

**Acceptance criteria.**
- With the constant lowered, `notified_hrefs` on a device at full count in round 1 is
  still at full count in round 6. E1 predicts decay on the current build; the test is that
  it does not happen.
- Unit test: two consecutive refresh rounds issue N deregisters then N subscribes, in that
  order, and `Session._subscribed` ends with exactly the requested paths.
- `refresh_observes` runs on the executor, not the event loop (test asserts `_run`).
- `ruff`, `pytest`, `check_reference_coverage.py`, `homey app validate --level publish`
  all clean.

---

### Item 3. Stop the AC card reading `/device/0` nine times

**Problem.** `_on_set_ac_settings` for a 7-setting run performs **9 full `/device/0`
reads** on the happy path — 1 up front, 1 per `_apply_step`, 2 in `_reconcile` — and up to
**25** if steps retry (`_AC_ATTEMPTS = 3`). At `BLOCK_SZX = 6` an 11 KB dump is ~11 round
trips, measured at 2-8 s per read. Plus 7 × `_AC_SETTLE_S` (2.5 s). Happy path: **~100
requests, ≥36 s, plausibly ~90 s** — a block-model estimate until `gets` confirms it.

**A second, separate defect in the same call path.** `refresh_now()` is literally
`_poll_once()` (`device.py:394-403`), so each of those nine "refreshes" also runs
`_sync_capabilities`, `_sync_capability_options`, a full `_apply`, `set_available`,
`_evaluate_observe`, **`_try_observe`** and `_sync_settings`. A Flow card can therefore
fire a 27-href subscribe round *mid-card* and flip the device into or out of push mode
while it applies settings — a lifecycle problem, not a cost problem: observe management
belongs to the poll loop and nothing else should trigger it.

**Evidence.** `driver.py:220,224,279,291,323`; `device.py:394-403,552-594,620-656`;
`coap.py:38`; `dtls_session.py:492`, `:175-180`.

**Change.**
1. **(Commit 1, shipped alone and first.)** Split read from lifecycle. `_poll_once()`
   keeps everything. `refresh_now()` becomes read + identity check +
   `_sync_capability_options` + `_apply` + `set_available` — **no `_evaluate_observe`, no
   `_try_observe`**.
   **`_sync_capabilities` is deliberately excluded too.** It is a device-shape mutation,
   not a value read: it calls `add_capability`/`remove_capability`, which Homey documents
   as expensive, and a removal firing mid-card can delete the capability the card is
   writing, turning a working Flow into an error. What it reacts to — a convertible
   refrigerator changing compartment, a cooktop's probe appearing
   (`device.py:582-587`) — never changes inside one card run, so the 30 s poll loop is the
   right owner. `_sync_capability_options` **stays**, because option ranges (setpoint
   min/max) gate the value the card is about to write. `_sync_settings` is excluded:
   everything it writes is static or the observe state `refresh_now` no longer changes.
   Pin the answer with a test in the existing `ast` style: the `refresh_now` path
   references `_sync_capability_options` and **not** `_sync_capabilities`,
   `_evaluate_observe`, `_try_observe` or `_sync_settings`; `_poll_once` references all
   of them.
2. Add `refresh_href(href)`: `Session.read_resource`, fold into `_resources`,
   `_apply(only_href=href)`.
3. `_apply_step` and `_reconcile` verify via `refresh_href(spec.href)`.
4. Guard the assumption: a spec whose `read` needs sibling resources must not be verified
   single-href. Add a `Spec` flag or explicit allowlist, asserted by a test, so a future
   cross-reading spec fails the suite instead of silently verifying against a stale
   sibling. A `None` read falls back to a full `/device/0` rather than counting as a
   mismatch.

The previous draft's step 4 — skip the up-front read when a poll landed recently — is
**cut**: it trades the card's fresh-state property for ~11 requests, and
`_drop_what_the_mode_will_not_take` is exactly the consumer that must not read a stale
mode.

**Request model after steps 2-4**, stated so the target can be checked against it: 11
(one up-front `/device/0`) + 7 writes + 7 verification reads + 7 reconcile reads = **32**
on the happy path. The previous draft's "≤ 30" target contradicted this model; corrected
below.

**Risk.** Highest blast radius here — the write path on real appliances, and the card
exists because of three measured bugs.
- The single-href rep may not carry what the batch rep carried. `/device/0` is a
  Collection and its entries are *not guaranteed identical* to a direct GET — `/oic/d` is
  standing proof the views differ. Measured per href before the code is trusted.
- Removing the full read removes wall-clock time between write and verification. **How
  much margin that was worth is unmeasured**, and whether RT-OCF regenerates a
  Collection's representation per Block2 block — whether a later block already reflects a
  newer state — is unknown. The previous draft asserted "2-8 s of accidental settle
  margin"; the 2-8 s is a measured *read duration*, the margin it implies is not. Both go
  to open questions, and item 5 now runs **before** steps 2-4.

**Gate before writing any code for steps 2-4.** Non-destructive, read-only. Note `host` —
without it `/read-resource` fans out to all nine appliances (`api.py:311,322-325`):

```sh
homey api raw -X POST --path /api/app/com.lomohome.localthings/read-resource \
  --body '{"host":"<GUEST_ROOM_IP>","path":"/power/vs/0"}'
```

Repeat for all seven card hrefs — `/power/vs/0`, `/mode/vs/0`, `/temperatures/vs/0`,
`/wind/strength/vs/0`, `/wind/direction/vs/0`, `/option/airpurify/vs/0`,
`/mode/convenient/vs/0` — and diff each against the same href inside
`/resources?host=<IP>&raw=1`. If any direct GET is missing a field the spec's reader
needs, that href stays on the full-read path and the reason goes in `docs/BACKLOG.md`.
**This is the item's real dependency, not a formality.**

**Hardware verification (writes; restore protocol mandatory).** One unit only: the
guest-room AC, an empty room per `docs/BACKLOG.md`. Do not run this while it is occupied.

1. `homey api raw --path "/api/app/com.lomohome.localthings/resources?host=<IP>&raw=1"`
   → `before.json`.
2. Run the card once with all seven arguments differing from `before`. Record wall time
   and `gets` before and after.
3. Run the card again with the seven values from `before.json`, restoring it.
4. Re-read → `after.json`; `diff` against `before.json`. The seven card-controlled fields
   must match field-for-field.
5. Report the before/after state and the restoration, per CLAUDE.md.

**Acceptance criteria.**
- Commit 1 alone: `subscribe_sends` does not advance during a card run and `observing` is
  unchanged across it. That is the acceptance test for the lifecycle defect, independent
  of the cost win.
- Commit 1 alone: the `ast` test pinning what `refresh_now` may and may not call passes,
  including the `_sync_capabilities` exclusion.
- Steps 2-4: measured `gets` delta for one 7-setting happy-path run is **≤ 35** and
  consistent with the 11+7+7+7 = 32 model; wall time at most half the baseline. Both from
  item 0's counters, not inferred.
- `after.json` equals `before.json` on all seven card-controlled fields.
- Unit test: a 7-step card issues exactly one `/device/0` read and seven single-href reads
  on the happy path.
- Unit test: a spec needing sibling resources is refused by `refresh_href` and falls back;
  a `None` single-href read falls back rather than counting as a mismatch.
- Behaviour preserved: `_drop_what_the_mode_will_not_take`, reconcile-drift and
  settings-conflict tests pass unchanged.

---

## Bucket B — needs a measurement first

### Item 5. The settle window protects push but not poll — measure, then decide

**Sequenced before item 3's steps 2-4.**

**Problem, not yet a change.** `_settling` is consulted only in `_on_notification`.
`WRITE_SETTLE_S = 4.0` declares that for 4 s after a write the appliance's own report may
still be the old value and must be ignored. But `_apply_step` writes, sleeps
`_AC_SETTLE_S = 2.5`, then **polls**, which is not gated — so `_apply` can push a stale
device value over the optimistic one, `_value_matches` fails, and the step re-sends a
write that had already taken. The app distrusts a notification at t+2.5 s and trusts a
poll at t+2.5 s for the same resource. One of those is wrong. Per **D2** the notification
path does not merely distrust, it **discards**, so a value arriving inside the window is
lost until the next read — a second reason to get these numbers.

**The measurement — method corrected.** The previous draft read the curve from
`/write-resource`'s `after`. That cannot work: `after` comes from a full
`session.read_device0()` issued after the write returns, in the **Collection** view
(`api.py:284-287`), so its timestamp is an 11-block read of unknown duration in the 2-8 s
range — it cannot produce t = 0.5/1/2 s points at all. Instead:

1. On the guest-room AC, record state (`/resources?host=<IP>&raw=1`).
2. `POST /write-resource` with `host` set, one href. Use `response` and `accepted` only;
   **ignore `after`**.
3. Issue timed single-href `POST /read-resource` calls with `host` set at t ≈ 0.5, 1, 2,
   3, 4, 6 s from the write's return, and record the first t at which the appliance
   reports the new value. Single-href reads are one round trip, so the sample time is the
   measurement's resolution rather than a confound.
4. Restore, re-read, diff, report.

Watch the Homey API rate limit: back off in single long waits, never poll to see whether
it cleared.

**What this measures, and what it does not.** `/write-resource` goes straight to
`Session.write` and **does not set `_settling`** (that happens only in the capability
write path, `device.py:918`), so this measures the *appliance's* settle time cleanly with
no app-side gating in the way — which is what is wanted. It says nothing about the
app-level race, because `_apply_step`'s sequence (optimistic apply → `_settling` set →
poll at t+2.5 s → `_value_matches`) is a different path. **A second experiment is
required** for that: run the card on one setting with item 0's counters live and record
whether `_apply_step` re-sends a write the appliance had already taken. Only the first
experiment gates item 3.

**What the measurement decides.**
- Settle consistently < 2.5 s → `_AC_SETTLE_S` is safe and `WRITE_SETTLE_S = 4.0` is
  over-conservative; set both from the curve and gate the poll path too.
- Settle > 2.5 s for any href → `_apply_step` is racing the appliance today, its retries
  are partly self-inflicted, and the fix is to gate the poll path on `_settling` as well,
  or raise `_AC_SETTLE_S` per href.
- Either way the number is recorded **per href** in `docs/BACKLOG.md`, because one global
  constant for seven resources is itself an inference.

**Why it gates item 3.** Steps 2-4 remove wall-clock time between write and verification.
Without the curve there is no way to say whether that time was load bearing, and the card
would be tuned by feel on the user's air conditioners.

**Acceptance criteria.**
- A per-href settle table in `docs/BACKLOG.md`, with the method (timed single-href reads,
  `host` scoped) and the restore recorded.
- `WRITE_SETTLE_S` and `_AC_SETTLE_S` each either changed to a measured value or kept with
  a comment citing the measurement that justifies keeping them.
- The D2 decision recorded: does `_on_notification` keep dropping inside the window, or
  defer the rep and apply it when the window closes? Either is defensible; leaving it
  undecided is not, for a value-loss path.
- Guest-room AC state restored and diffed.

---

## Removed from this plan

- **Item 4 (demote on a positive observation of a miss) — killed.** Its evidence base
  moved (27/26/3/6 no longer reads as "idle but healthy") and D2 shows the settle window
  can manufacture the exact signal it would watch. What survives: `sweep_detected_misses`
  in item 0 and a **24 h idle baseline** across nine devices, recorded as data. Then
  re-plan demotion with that number and item 5's decision in hand. `_push_is_healthy()` is
  still deleted — in item −1, as dead code, not as a rewrite.
- **Item 6 (poll-loop alignment) — moved to open questions.** Sessions are per host with
  per-host locks, so no appliance-side limit is violated; any cost is Homey CPU and LAN
  concurrency, and that is unmeasured. `last_poll_duration_s` ships anyway, so the
  measurement stays available at no cost.
- **Item 3 step 4 (skip the up-front read)** — trades the card's fresh-state property for
  ~11 requests.
- **Item 2 step 3 (dereg on demotion)** — belongs with the demotion re-plan.

---

## Not worth changing — and why

- **`ping()` as an observe keepalive.** The library offers it and says the send
  "tickles Samsung's observer state". But the 300 s summary sweep already puts CoAP
  traffic on every session, and the library's own docstring records that RT-OCF never
  reliably returns the RST, so the ping cannot detect a half-open session either.
  It would add one unpaced datagram per device per interval for no readable signal.
- **Source-port pinning and the escalation ladder** (`const.py:48-67`,
  `probe.py:41-60`, `session.py:86-99`). RFC 6347 §4.2.8 grounded, measured against
  RT-OCF, and the reason `check_now()` deliberately refuses to open a second session.
  This is the layer's most load-bearing divergence.
- **Appending rather than promoting the rescued preferred probe ports**
  (`probe.py:129`). Deliberate divergence from the reference with a written cost
  model: the reference probes one user-typed host, this app sweeps a /24.
- **Swallowing every `/oic/d` failure** (`device.py:596`, `probe.py:182`). A
  supplementary signal must not become a new way for pairing to fail, least of all
  on the unfamiliar hardware it exists to help.
- **`OBSERVE_GRACE_S = 45`.** Generous on purpose and it costs nothing — the verdict is
  reached on a later poll, so waiting longer blocks nothing, and 27 initial notifications
  need well over 15 s to land. Tightening it re-creates the bug where a device with 21 of
  22 resources notifying was recorded push-unavailable.
- **`_observe_retry_after()`'s doubling backoff.** The right structure; item −1 fixes only
  the condition that decides when it engages.
- **A shared scheduler or a global session pool.** The natural "real fix" for poll
  alignment, and entirely speculative until that measurement exists. Large blast radius
  across nine live devices for an unmeasured problem.
- **The discovery sweep** (`discovery.py`, 2286 host/port pairs in ~15 s at
  `CONCURRENCY = 192`). Measured, off the steady-state path, and correctly built on
  "only actual replies count" rather than the single-host probe's silence-is-maybe.

---

## Ordering — as commits and experiments

**E1 (no shipped code, first). The round-decay experiment.** This replaces the previous
draft's restart discriminator, which relied on `on_uninit` having run — `const.py:51`
records unclean shutdown as routine, so "push works after a restart" is not a controlled
observation.

Method: on the **current build**, with `OBSERVE_REFRESH_S` lowered to ~10 min in a dev
install, pick one AC and record `notified_hrefs` from `/diagnostics` once per round,
sampling at a fixed offset inside each round (after `OBSERVE_GRACE_S`, before the next
round; `_notified` is cleared at the start of each round, so the sample is exactly that
round's count). Cross-check `observe_silent_rounds`. One read per ten minutes stays clear
of the Homey rate limit. Restore the constant afterwards.

- **Monotonic decay across rounds on one session ⇒ C2.** The token space is filling and
  registrations are being silently no-oped.
- **Flat and low from round 1 ⇒ C1 or C3.** Nothing is aging; registrations are lost at
  the appliance's input or at ours. Commit 3's counters separate those two.

```
E1 (round decay, no code)
  │
  ├─► commit 1: refresh_now lifecycle split, alone      (item 3 step 1)
  ├─► commit 2: narrow 0.6.4                            (item −1)
  ├─► commit 3: slim instrumentation + C3 counters      (item 0)  ─► nine-device baseline
  │                                                                 + 24 h idle baseline
  ├─► then, as E1 decides:  item 2 steps 1-2 (dereg)  OR  item 1 (pacing)
  ├─► then item 5 (settle curve, revised method)
  ├─► then item 3 steps 2-4 (href gate ─► targeted reads ─► Spec guard)
  └─► then re-plan demotion, with sweep_detected_misses and item 5's answer in hand
```

**What must NOT be in commit 1.** It is a two-line lifecycle split plus its `ast` test,
shipped alone so that "a card no longer touches the observe lifecycle" is attributable to
one commit. It must not contain: `refresh_href` or any single-href read; the
skip-the-up-front-read change; any counter; the verdict or backoff change;
`refresh_observes` or any dereg; any change to `_sync_capabilities` itself, to
`_AC_SETTLE_S`/`WRITE_SETTLE_S`, or to the order of calls inside `_poll_once`.

Commits 2 and 3 are separable; commit 2 first is preferred, so the baseline in commit 3 is
recorded against the corrected verdict rather than one that cannot fail.

---

## Pre-mortem — three ways this goes wrong

**1. E1 comes back flat-low, pacing ships, nothing changes — and the cause was C3.** C1,
C2 and C3 all predict "subscribed, no notifications". E1 separates C2 from the other two
but not C1 from C3, and C3 is invisible today: three bare `return`s in `_dispatch` plus a
library warning nobody can read, on a drop reason (`non_dict_rep`) that is known to occur.
The tempting read after a null result is "pacing was pointless, revert", when the
notifications may have been arriving and being discarded all along. *Mitigation:* commit 3
ships `dispatch_drops` (by reason) and the library-logger counters **before** either
behaviour change, and item 1's criteria read them in the same breath as the notification
count.

**2. Item 3's targeted reads verify against a resource that is not the same as its batch
entry, and the card silently re-sends writes that already took.** If one of the seven
hrefs returns a thinner rep on a direct GET, its reader returns `None`,
`_value_matches(None, wanted)` is `False`, and `_apply_step` burns three attempts and then
**raises** — turning a working Flow into a failing one, on the user's air conditioners.
*Mitigation:* the host-scoped read-only href diff gate is a hard prerequisite, not a check
afterwards; plus the `Spec` guard; plus the test that a `None` read falls back to a full
`/device/0`; plus item 5 landing first so the removed wall-clock time is a known quantity.

**3. Item −1 reads as a regression and gets reverted for the wrong reason.** Two ACs flip
from "push" to "polling" in the panel and in the `is_pushing` condition, and their read
volume rises ~10x. Nothing broke — the verdict became falsifiable and two channels failed
it — but a revert would restore a check that cannot fail. *Mitigation:* the changelog says
which units flip and why, in both locales; the `gets` delta is recorded against item 0's
baseline rather than left to impression, with the backoff saving beside it; and the deleted
tests are replaced by tests pinning the *new* rule, so the next reader finds the reasoning
in the suite rather than in this file.

---

## Test plan

**Unit** (`pytest`, fake session — no such harness exists for this layer; there is no
`test_session.py`, `test_observe.py` or `test_ac_settings_card.py`, so commit 3 creates
the fake-session fixture the rest reuse):
- Verdict: `got >= needed` with `needed` from `OBSERVE_SUCCESS_FRACTION`; a partial round
  increments `_observe_silent_rounds`, a silent round increments it, a passing round
  resets it. Guard: `OBSERVE_REFRESH_S == 6 * 3600`.
- Counters: N gets / M subscribes / K dispatches report exactly N, M, K; one dispatch per
  drop reason lands in the right `dispatch_drops` bucket.
- `ast`: the `refresh_now` path references `_sync_capability_options` and not
  `_sync_capabilities`, `_evaluate_observe`, `_try_observe` or `_sync_settings`;
  `_poll_once` references all of them.
- Pacing: 27 subscribes → 27 `pace()` calls, one before each send, in order.
- Dereg: two refresh rounds → N deregs then N subscribes, in that order, on the executor.
- AC card: happy path issues one `/device/0` and 7 single-href reads; `subscribe_sends`
  unchanged across a card run; `refresh_href` refuses a sibling-reading spec and a `None`
  read falls back.
- Deleted or rewritten as listed in item −1 step 4.

**Integration** (fixtures in `tests/fixtures/`, real dumps):
- `airconditioner_TP1X_DA-AC-CAC-01001.json` replayed through the card, asserting the
  request *sequence*, not just the final state.
- `test_repair.py` / `test_source_port_escalation.py` pass unchanged — nothing here
  touches the source-port or relocation paths. Note `test_repair.py:207` asserts the
  six-hour non-resubscribe property; item 2 changes *what* the refresh branch does, not
  when it fires, so that test must stay green as written.
- `_fold_write_into` list-shape behaviour unchanged (single-href reads must not
  reintroduce the truncation bug it fixed).

**End-to-end on hardware:**
- Read-only, nine devices: E1's round-decay series; commit 3's baseline; the 24 h idle
  baseline for `sweep_detected_misses`; item −1's verdict flip; item 1's notification and
  drop-counter deltas; item 2 across lowered-refresh rounds.
- Writing, one unit, guest-room AC (empty room per `docs/BACKLOG.md`), with `before.json`
  → run → restore → `after.json` diff and the restoration reported: item 5's settle curve
  and its second app-level experiment, item 3's card run.
- No write test on the three refrigerators, the cooktop, the hood, or an occupied room's
  AC. None are needed for anything above.

**Observability** (via `/diagnostics`, because there is no readable app log and
`homey app run` replaces the installed app):
- Per device: `observing`, `subscriptions`, `subscribe_sends`, `notifications`,
  `notified_hrefs`, `last_notify_age_s`, `dispatch_drops` (by reason), `observe_non_205`,
  `refresh_dereg_failures`, `notification_callback_errors`, `sweep_detected_misses`,
  `observe_silent_rounds`, `observe_retry_after_s`, `gets`, `last_poll_duration_s`.
- The three derived readings that carry the plan: `subscribe_sends - subscriptions`
  (C2's leak); `notifications` advancing while `observing` is true (push actually alive —
  the only present-tense claim available); `dispatch_drops + observe_non_205` non-zero
  (C3 — the channel works and this app is losing the result).

**CI gate, every commit, per CLAUDE.md — all four, not just the tests:**

```sh
uv run ruff check . --exclude python_packages
uv run pytest tests/ -q
uv run python scripts/check_reference_coverage.py
homey app validate --level publish
```

---

## ADR

**Decision.** Make the push verdict falsifiable again before optimising anything around
it; diagnose the missing initial notifications with instruments rather than by choosing
between untested hypotheses; de-amplify the AC card only after the settle curve is
measured. Sequence: round-decay experiment (no code) → lifecycle split alone → narrow
0.6.4 → slim instrumentation with the discard counters and two baselines → dereg or pacing
as the experiment decides → settle curve → targeted single-href verification → re-plan
demotion.

**Drivers.** (1) Push must either work or be honestly reported; 0.6.4's verdict cannot
fail, and this repo's standard is that such a check reads as evidence. (2) The scarce
resource is requests per session, and the AC card spends ~100 per run — an estimate that
becomes a measurement in commit 3. (3) Nine appliances in a lived-in home: prefer
zero-write verification, and confine the write-path change to one unit in an empty room
with a recorded restore.

**Alternatives considered.**
- *Keep `needed = 1`, treating 3/27 as an idle appliance* — invalidated by `subscribe()`'s
  docstring: the initial 2.05 fires on registration, so 3/27 is 24 failed registrations.
- *Fix the ten-minute re-subscribe waste by removing the threshold* — what 0.6.4 did. The
  lever was `if got:`; removing the threshold suppressed the symptom and cost the verdict
  its ability to fail.
- *Wire `_push_is_healthy()` up as written* — same misreading; deleted as dead code.
- *Use "push works after a restart" as the C1/C2 discriminator* — assumes `on_uninit` ran,
  and unclean shutdown is documented as routine (`const.py:51`). Replaced by round decay.
- *Read the settle curve from `/write-resource`'s `after`* — that field is a full
  `/device/0` read at an unknown time in the 2-8 s range, in the Collection view. Replaced
  by timed single-href reads.
- *Trust the write echo instead of reading back* — invalidated by CLAUDE.md and three
  recorded bugs.
- *Keep full `/device/0` reads and just do fewer of them* — gives back the
  per-step-fresh-state property the card exists to provide; the narrow "skip the up-front
  read" version is cut for the same reason.
- *Demote on a sweep-detected miss now* — deferred: D2 shows the settle window can
  manufacture that signal, and the measurement behind it has been reinterpreted. The
  counter ships; the verdict waits.
- *`ping()` keepalives; a shared poll scheduler; poll-loop jitter* — rejected or deferred
  behind measurements that do not exist yet.

**Why chosen.** Every surviving item is an instrument, an experiment, or a change whose
acceptance test is a read-back from the appliance. The two items most confident about
their own diagnosis in the previous draft — pacing and demotion — are the two a single
verified docstring moved. Sequencing the cheap, reversible, read-only work first is what
keeps that from happening on the user's hardware instead of on paper.

**Consequences.**
- Two air conditioners will be reported as polling rather than pushing, and will read
  `/device/0` roughly 10x more often, until the channel is actually fixed. That is the
  honest state, and it belongs in the changelog in both locales.
- One new read path (`refresh_href`) whose safety rests on a per-href measured claim about
  direct GET vs. Collection entry, guarded at the `Spec` level and tested, or it decays as
  specs are added.
- `_push_is_healthy()` and probably `PUSH_HEALTH_WINDOW_S` are deleted; two tests are
  deleted and two rewritten, because they pin a reading that has been withdrawn.
- Diagnostics grows about a dozen fields, including a counting logging handler on the
  vendored library's logger — the only readable route to two of C3's three drop paths.
- A new fake-session test fixture, which this layer has never had.
- Items may end in a **recorded null result** (pacing, if C1 is falsified; poll alignment,
  if it costs nothing). A falsified hypothesis written into `docs/BACKLOG.md` with its
  numbers is a deliverable here, not a failure.

**Follow-ups.**
- Re-plan demotion once `sweep_detected_misses` has a 24 h idle baseline and item 5 has
  decided whether `_on_notification` defers or drops inside the settle window.
- `OBSERVE_SUCCESS_FRACTION = 0.8` is inherited from the reference and unmeasured here.
  Derive it from the per-round counts E1 and commit 3 produce.
- `Session._subscribed` as a set is load-bearing for reconnect but hides multiplicity;
  once `subscribe_sends` exists, reconsider a per-href count.
- D1: `_observe_tokens[tok] = href` overwrites on wrap. Even with item 2's dereg, a 1-byte
  token space against 27 hrefs a round is thin — worth raising upstream, alongside a
  request that non-dict reps be reported rather than dropped.
- `OBSERVE_REFRESH_S = 6 h` is the library's suggested cadence, not a measured one. Once
  E1 has run, derive the interval at which registrations actually age out.
- If item 3's href gate finds a direct GET thinner than its Collection entry, that is worth
  contributing upstream — the same class as `x.com.st.d.hood` (#230) and the auto-dry cycle
  status (#255).
- Nothing here touches the subdevice gap (`#177`/`#205`/`#214`) and it should stay that
  way: no hardware exhibits the signal, re-confirmed on all nine.
