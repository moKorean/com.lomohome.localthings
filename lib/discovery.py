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
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                return None
        except (ConnectionRefusedError, OSError):
            return None
        finally:
            sock.close()


async def sweep(
    subnet: str = None,
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
