"""Protocol and timing constants.

Ported from the reference integration's const.py. The values here are measured
against real hardware, not preferences — see docs/PORTING.md before changing any
of them.
"""

# App-level settings keys. The client certificate is stored once for the whole
# app: its UUID comes from Samsung's cloud gateway rather than from any
# appliance, so one certificate authenticates to every appliance on the network.
SETTING_LEAF_CERT = "leaf_cert_pem"
SETTING_LEAF_KEY = "leaf_key_pem"
# Where the stored certificate came from: SOURCE_MINTED if the app issued it
# itself, SOURCE_PASTED if the user supplied one. Kept so that re-issuing never
# silently discards a certificate the user went to the trouble of obtaining.
SETTING_CERT_SOURCE = "cert_source"
SOURCE_MINTED = "minted"
SOURCE_PASTED = "pasted"
# Last environment report from the pairing webview. Diagnostic only; lets the
# view's own view of the SDK be inspected from an installed app.
SETTING_PAIR_ENV = "pair_env"
# UI language, as reported by a webview. Homey's server-side i18n resolves the *app's*
# language rather than the user's, so this is the only way a message raised from Python
# can be in the user's language.
SETTING_UI_LANGUAGE = "ui_language"

# Per-device store keys. Credentials are not duplicated here — the device reads
# the app-level certificate at runtime, so rotating it fixes every device at once
# instead of needing each one re-paired.
STORE_HOST = "host"
STORE_PORT = "port"
STORE_SERIAL = "serial"

# The DTLS/CoAP local API binds somewhere in this ephemeral range; which port
# depends on firmware. Newer builds answer on 49154/49155, but older ones have
# been seen as low as 49153, so sweep the whole range for a live UDP port before
# attempting the (expensive) DTLS handshake.
PROBE_PORT_RANGE = list(range(49152, 49161))

# Ports historically seen completing a DTLS handshake. When more than one port
# in the range looks live, these are tried first.
PREFERRED_PROBE_PORTS = [49154, 49155]

# Per-port timeout for the cheap UDP liveness sweep. Closed ports return an
# ICMP port-unreachable almost immediately; a live-but-silent port is only
# detected by this timeout elapsing, so keep it short.
LIVENESS_PROBE_TIMEOUT_S = 1.5

# Deadline for the blockwise /device/0 GET. The slowest device observed returns
# a full dump in ~8s, so 10s leaves headroom without stalling pairing.
PROBE_GET_TIMEOUT_S = 10.0

# Bases for the local (client-side) DTLS source port, distinct from the
# destination probe ports above. Binding the same source port on every
# reconnect keeps the client on one 5-tuple, so the appliance evicts an
# orphaned session left by a previous run (unclean shutdown -> no
# close_notify) at handshake time per RFC 6347 4.2.8, instead of holding it
# for 5-15 min while the new session's reads hang.
#
# That eviction is a MAY, not a MUST, and some firmware does not do it: it
# instead reads the plaintext ClientHello as a record inside the epoch it still
# believes is live, fails to parse it, and answers with a fatal alert
# ("tlsv1 alert decode error", alert 50). Retrying on the same port replays the
# same mistake forever, so the port is only the *first* choice — a peer that
# rejects the handshake this way gets retried from the next base, which is an
# unambiguously new association it has no stale state for.
#
# Each base reserves a 256-wide window (offset = last IP octet), and the
# windows do not overlap, so no retry port can collide with another device's
# first-choice port.
DTLS_LOCAL_PORT_BASES = (49700, 50000, 50300)
DTLS_LOCAL_PORT_BASE = DTLS_LOCAL_PORT_BASES[0]

# How often to re-read the full /device/0 summary.
POLL_INTERVAL_S = 30.0

# --- OBSERVE (push) mode. Values follow the reference integration's observe.py.
#
# After subscribing, the device sends an initial notification per resource. If most
# of them arrive inside the grace period, push is working and the summary poll
# drops to a slow safety sweep; otherwise stay on polling and retry later. Starting
# in poll mode and earning push is deliberate — a device that accepts a
# subscription and then never notifies would otherwise look healthy while going
# silently stale.
# Generous because it no longer blocks anything: the verdict is reached on a later
# poll, so waiting longer costs nothing and a device subscribing 22 resources needs
# well over 15s for its initial notifications to all land.
OBSERVE_GRACE_S = 45.0
# What share of the subscribed resources must have notified for push to be
# considered working.
#
# This is a fair test of the channel, but read `_notified` carefully before tuning
# it, because it counts two different things at once. A registration's response *is*
# its first notification, as the transport library's `subscribe` docstring says —
# two switched-off air conditioners read 27/27 minutes after a fresh install, and a
# unit that makes no state changes has no other way to reach that number. But
# `_notified` is only cleared at re-subscribe, so it also accumulates real changes:
# switching an idle unit on took it 0 -> 7 in 70s with `silent_rounds` and the retry
# window untouched, proving those observations had been live all along.
#
# The consequence is that two devices' counts are comparable only at the same offset
# from their last re-subscribe. Ignoring that produced every contradiction chased on
# 2026-08-03, in both directions — first "the burst loses the initial
# notifications", then an over-correction to "the appliances send none at all".
#
# Tuning this is close to pointless, and that is the measured conclusion rather than
# a guess. Delivery of the initial notifications is simply variable: one switched-off
# air conditioner, sampled 90s after four separate app starts, read 27/27, 27/27,
# 27/27 and 8/27. A unit making no state changes cannot explain that with activity,
# so no threshold survives it — a device reads healthy one round and fails badly the
# next with nothing having changed. docs/BACKLOG.md has the four rounds, and the two
# hypotheses they ruled out (accumulating orphaned observations from killed app
# instances; how recently the app was reinstalled).
#
# What needs replacing is the single-round snapshot, not the fraction. Left as it is
# meanwhile: `_observing` only selects the poll interval (30s vs the 300s sweep), so
# failing this test costs polling and never correctness.
OBSERVE_SUCCESS_FRACTION = 0.8

# Gap between OBSERVE registrations. The transport library's `subscribe()` is
# fire-and-forget and unpaced — its `pace()` has a single call site, inside the
# Block2 loop — so 27 registrations otherwise leave in microseconds.
#
# Added to fix "the registration burst loses the initial notifications each one
# should answer with". Whether it does is still unproven, and the evidence once
# offered for it does not hold: the 26/27 that appeared to vindicate it was measured
# while the unit was being operated for the experiment, so most of those were real
# state changes rather than initial notifications.
#
# The underlying loss is real — a switched-off unit has read anywhere from 8/27 to
# 27/27 across four app starts — but nothing has pinned it on the burst. Four rounds
# in docs/BACKLOG.md ruled out two other explanations and established only that
# delivery is variable, which a burst alone does not account for either.
#
# Kept regardless, on grounds that do not depend on which it is: 1.35 s per device,
# and it matches what the library itself does in `refresh_observes()`, its own paced
# bulk path. Deliberately not the 0.2 s that `pace()` would impose — this app
# subscribes nine appliances at once, and 27 x 0.2 s each would occupy the shared
# executor for five seconds per device at every start.
OBSERVE_SUBSCRIBE_SPACING_S = 0.05

OBSERVE_RETRY_S = 600.0
# Summary sweep interval while push is healthy. Still polled, because a missed
# notification is invisible otherwise.
OBSERVE_SWEEP_INTERVAL_S = 300.0
# Re-subscribe periodically; observations expire device-side.
OBSERVE_REFRESH_S = 6 * 3600.0
# After a write, ignore notifications for that resource this long, so a device that
# settles slowly doesn't revert the value just set.
WRITE_SETTLE_S = 4.0

# Consecutive poll failures before searching the network for this appliance by
# serial. Three rather than one: a single timeout is usually the appliance being
# briefly busy, and a full sweep is far more expensive than waiting one interval.
RELOCATE_AFTER_FAILURES = 3

# How many consecutive poll failures before the device is shown as unavailable.
#
# One above RELOCATE_AFTER_FAILURES, so relocation gets its attempt first — marking
# the device unavailable and then recovering on the same cycle would flash a fault
# the user never needed to see.
#
# Transient failures are normal and are not the user's problem. A restarted app
# leaves the appliance holding an orphaned DTLS association for minutes, and the
# first handshake into it is refused; the app recovers by itself from a different
# source port. Surfacing that immediately put "DTLS handshake error" on a tile for
# something that fixes itself, so the first few failures are logged and retried
# quietly and only a persistent one is reported.
UNAVAILABLE_AFTER_FAILURES = RELOCATE_AFTER_FAILURES + 1

SAMSUNG_CLOUD_HOST = "connect-v2.samsungiotcloud.com"
SAMSUNG_CLOUD_PORT = 443
