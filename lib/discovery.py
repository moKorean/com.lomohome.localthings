"""Find Samsung appliances on the local subnet.

Homey's own discovery strategies are no help here: these appliances advertise
nothing over mDNS or SSDP (checked against a real network — the only service types
present belonged to Matter/Thread and unrelated vendors). ARP can confirm one
address at a time but cannot enumerate. So discovery is an active sweep.

The single-host liveness probe in probe.py treats silence as "maybe live", which is
useless across a whole subnet because absent hosts are silent too. What makes a
sweep possible is that a live appliance *answers* a junk datagram on its DTLS port
with an alert record. Only actual replies count as candidates here, so absent hosts
and closed ports both drop out and there are no false positives to chase with
expensive handshakes.

Measured on a real /24: 2286 host/port pairs in about 15s.
"""

import asyncio
import socket

from .const import PROBE_PORT_RANGE

REPLY_TIMEOUT_S = 1.0
CONCURRENCY = 192


def local_subnet(default: str = "192.168.1") -> tuple[str, str]:
    """(subnet_base, own_address) for the interface facing the LAN.

    Connecting a UDP socket picks the outbound route without sending anything.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 53))
        own = sock.getsockname()[0]
    except OSError:
        return default, ""
    finally:
        sock.close()
    parts = own.split(".")
    if len(parts) != 4:
        return default, own
    return ".".join(parts[:3]), own


async def _probe(host: str, port: int, sem: asyncio.Semaphore, timeout: float):
    """(host, port) if the address answered, else None."""
    async with sem:
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, (host, port))
            # Contents are irrelevant — the appliance answers with a DTLS alert
            # whatever it receives, and that reply is the whole signal.
            await loop.sock_sendall(sock, b"\x00")
            try:
                await asyncio.wait_for(loop.sock_recv(sock, 2048), timeout)
                return host, port
            except (TimeoutError, ConnectionRefusedError, OSError):
                return None
        except (ConnectionRefusedError, OSError):
            return None
        finally:
            sock.close()


async def sweep(
    subnet: str | None = None,
    ports=None,
    timeout: float = REPLY_TIMEOUT_S,
    skip=(),
) -> list[tuple[str, int]]:
    """Addresses on `subnet` that answered on a DTLS port, lowest host first.

    `skip` drops addresses that need no probing — Homey's own address, and hosts
    already paired.
    """
    base, own = local_subnet() if subnet is None else (subnet, "")
    excluded = {own, *(skip or ())} - {""}
    sem = asyncio.Semaphore(CONCURRENCY)

    targets = [
        (f"{base}.{n}", port)
        for n in range(1, 255)
        for port in (ports or PROBE_PORT_RANGE)
        if f"{base}.{n}" not in excluded
    ]
    results = await asyncio.gather(
        *(_probe(host, port, sem, timeout) for host, port in targets)
    )

    # One entry per host: a device answering on two ports is still one appliance,
    # and the port that answered first in range order is the one to try.
    found: dict[str, int] = {}
    for item in results:
        if item and item[0] not in found:
            found[item[0]] = item[1]
    return sorted(found.items(), key=lambda kv: [int(p) for p in kv[0].split(".")])


# Samsung OUI prefixes seen on appliances here plus well-known Samsung blocks. This
# list is *deliberately not* used to decide whether to probe an address: it is
# necessarily incomplete, and skipping a host because its prefix is missing would
# hide a real appliance. It only labels a responder that failed to identify, so the
# user can tell "not a Samsung appliance" from "a Samsung appliance this app can't
# talk to" — two very different situations that look identical otherwise.
SAMSUNG_OUIS = frozenset({
    "34:55:e5", "34:fc:99", "1c:e8:9e",   # observed on appliances
    "00:12:fb", "00:15:b9", "00:16:32", "00:17:c9", "00:1a:8a", "00:21:19",
    "00:24:54", "08:08:c2", "10:2b:41", "24:4b:81", "38:16:d1", "40:16:3b",
    "4c:3c:16", "50:32:75", "54:88:0e", "5c:0a:5b", "5c:49:7d", "68:27:37",
    "6c:2f:2c", "70:2a:d5", "78:1f:db", "78:bd:bc", "84:25:db", "8c:71:f8",
    "8c:c8:cd", "94:35:0a", "9c:02:98", "a0:07:98", "a8:db:03", "ac:5f:3e",
    "b4:79:a7", "bc:14:85", "c0:bd:d1", "c8:19:f7", "cc:07:ab", "d0:22:be",
    "d4:e8:b2", "e8:50:8b", "ec:1f:72", "f0:5a:03", "f4:7b:5e", "fc:8f:90",
})


def oui(mac: str) -> str:
    """Normalised three-octet prefix, or '' if this isn't a MAC."""
    parts = str(mac or "").strip().lower().replace("-", ":").split(":")
    if len(parts) < 3:
        return ""
    return ":".join(part.zfill(2) for part in parts[:3])


def vendor_hint(mac: str) -> dict:
    """{oui, is_samsung} for a responder that would not identify.

    `is_samsung` False means "not in our list", not "not Samsung" — the wording shown
    to the user has to keep that distinction, because the list cannot be complete.
    """
    prefix = oui(mac)
    if not prefix:
        return {"oui": "", "is_samsung": None}
    return {"oui": prefix, "is_samsung": prefix in SAMSUNG_OUIS}
