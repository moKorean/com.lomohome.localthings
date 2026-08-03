"""Reading and writing the app's client certificate.

One place, because two callers write it: `app.py` issues one on first run and the
settings API stores what the user pastes. Splitting that between them is how the
provenance flag and the read-back check end up disagreeing.

Storing is deliberately validate-then-write-then-read-back. A write that silently
stored nothing would otherwise surface much later as "set up required" during
pairing, with no clue that saving was what failed.
"""

from . import cert, compat
from .const import (
    SETTING_CERT_SOURCE,
    SETTING_LEAF_CERT,
    SETTING_LEAF_KEY,
    SOURCE_MINTED,
    SOURCE_PASTED,
)


async def stored(homey) -> bool:
    """Whether a usable pair is present. Both halves or neither counts."""
    cert_pem, key_pem = await pems(homey)
    return bool(cert_pem and key_pem)


async def pems(homey) -> tuple[str, str]:
    return (
        await compat.setting_get(homey, SETTING_LEAF_CERT),
        await compat.setting_get(homey, SETTING_LEAF_KEY),
    )


async def source(homey) -> str:
    """Where the stored certificate came from.

    Reports SOURCE_PASTED when a certificate is present but unlabelled: the only
    way to hold one without this flag is to have upgraded from a version that
    predates it, and every certificate then was pasted.
    """
    if not await stored(homey):
        return ""
    return await compat.setting_get(homey, SETTING_CERT_SOURCE) or SOURCE_PASTED


async def save(homey, cert_pem: str, key_pem: str, origin: str) -> dict:
    """Validate, store, and confirm it persisted. Returns `inspect_leaf`'s report.

    Raises InvalidCredentials if the pair is unusable — leaving whatever was
    stored before untouched, so a bad paste cannot cost the user a working setup.
    """
    info = await compat.run(cert.inspect_leaf, cert_pem, key_pem)

    await compat.setting_set(homey, SETTING_LEAF_CERT, cert_pem.rstrip() + "\n")
    await compat.setting_set(homey, SETTING_LEAF_KEY, key_pem.rstrip() + "\n")
    await compat.setting_set(homey, SETTING_CERT_SOURCE, origin)

    written_cert, written_key = await pems(homey)
    if not written_cert or not written_key:
        raise RuntimeError("credentials did not persist")
    return {**info, "source": origin, "cert_bytes": len(written_cert),
            "key_bytes": len(written_key)}


async def issue(homey, uuid: str) -> dict:
    """Issue a certificate for `uuid` and store it as app-issued."""
    cert_pem, key_pem = await compat.run(cert.mint_self_signed, uuid)
    return await save(homey, cert_pem, key_pem, SOURCE_MINTED)


async def accept_pasted(homey, cert_pem: str, key_pem: str) -> dict:
    """Store a certificate the user supplied, replacing whatever is there.

    Marked SOURCE_PASTED so that nothing later re-issues over it. A pasted
    certificate wins by intent, not by merit — the appliance checks the UUID and
    does not care who signed it (see `lib/cert.py`).
    """
    return await save(homey, cert_pem, key_pem, SOURCE_PASTED)


async def clear(homey) -> None:
    for key in (SETTING_LEAF_CERT, SETTING_LEAF_KEY, SETTING_CERT_SOURCE):
        await compat.setting_unset(homey, key)
