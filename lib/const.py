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

SAMSUNG_CLOUD_HOST = "connect-v2.samsungiotcloud.com"
SAMSUNG_CLOUD_PORT = 443
