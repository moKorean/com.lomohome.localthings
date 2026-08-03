"""Protocol and timing constants.

Ported from the reference integration's const.py. The values here are measured
against real hardware, not preferences — see docs/PORTING.md before changing any
of them.
"""

# App-level settings keys. The client certificate is stored once for the whole
# app: its UUID comes from Samsung's cloud gateway rather than from any
# appliance, so one certificate authenticates to every appliance on the network.
# The AC14K_M CA that signed it is never given to the app.
SETTING_LEAF_CERT = "leaf_cert_pem"
SETTING_LEAF_KEY = "leaf_key_pem"
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
# Be aware of what this actually measures before tuning it. The transport library's
# `subscribe` docstring says a registration's response *is* its first notification,
# and this constant was reasoned about on that basis — but the appliances do not
# behave that way. A switched-off air conditioner answers **0 of 27** registrations,
# and switching it on produced 7 within 70s with no re-subscribe (`silent_rounds`
# and `retry` unchanged), so those 27 observations were live the whole time with
# nothing to report.
#
# So the counter tracks *state changes since the last re-subscribe* — `_notified` is
# only cleared there — and not the health of the channel. An idle appliance cannot
# reach any quorum, and the value of this fraction is close to irrelevant next to
# that. Every contradiction chased on 2026-08-03 came from comparing devices at
# different points in their re-subscribe cycle: three running refrigerators read
# 7-8/9 while five switched-off units read 0-17/27, and readings of 27/27 for an
# off unit were hours of accumulation, not a healthy burst.
#
# Left as it is on purpose. `_observing` only selects the poll interval (30s vs the
# 300s sweep), so failing this test costs polling and never correctness — the safe
# direction. Replacing it needs the miss-detection metric in docs/BACKLOG.md, which
# holds for idle appliances too.
OBSERVE_SUCCESS_FRACTION = 0.8

# Gap between OBSERVE registrations. The transport library's `subscribe()` is
# fire-and-forget and unpaced — its `pace()` has a single call site, inside the
# Block2 loop — so 27 registrations otherwise leave in microseconds.
#
# This was added to fix "the registration burst loses the initial notifications each
# one should answer with". That diagnosis was wrong: with this spacing in place a
# switched-off air conditioner still answers 0 of 27, so there are no initial
# notifications to lose. The 26/27 that appeared to vindicate it was measured while
# the unit was being operated for the experiment — 26 real state changes.
#
# Kept anyway, on the narrower grounds that it costs 1.35 s per device and matches
# what the library itself does in `refresh_observes()`, its own paced bulk path. Not
# claimed to have fixed anything. Deliberately not the 0.2 s that `pace()` would
# impose: this app subscribes nine appliances at once, and 27 x 0.2 s each would
# occupy the shared executor for five seconds per device at every start.
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
