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

# Base for the local (client-side) DTLS source port, distinct from the
# destination probe ports above. Binding the same source port on every
# reconnect keeps the client on one 5-tuple, so the appliance evicts an
# orphaned session left by a previous run (unclean shutdown -> no
# close_notify) at handshake time per RFC 6347 4.2.8, instead of holding it
# for 5-15 min while the new session's reads hang.
DTLS_LOCAL_PORT_BASE = 49700

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
OBSERVE_SUCCESS_FRACTION = 0.8
OBSERVE_RETRY_S = 600.0
# Summary sweep interval while push is healthy. Still polled, because a missed
# notification is invisible otherwise.
OBSERVE_SWEEP_INTERVAL_S = 300.0
# Re-subscribe periodically; observations expire device-side.
OBSERVE_REFRESH_S = 6 * 3600.0
# After a write, ignore notifications for that resource this long, so a device that
# settles slowly doesn't revert the value just set.
WRITE_SETTLE_S = 4.0
# Any notification inside this window is proof the push channel is alive, even if
# nothing else changed. Resources that never change never notify, so device-wide
# silence is the signal, not per-resource silence.
PUSH_HEALTH_WINDOW_S = 600.0

# Consecutive poll failures before searching the network for this appliance by
# serial. Three rather than one: a single timeout is usually the appliance being
# briefly busy, and a full sweep is far more expensive than waiting one interval.
RELOCATE_AFTER_FAILURES = 3

SAMSUNG_CLOUD_HOST = "connect-v2.samsungiotcloud.com"
SAMSUNG_CLOUD_PORT = 443
