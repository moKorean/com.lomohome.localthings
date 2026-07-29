"""Homey Python SDK accessors that tolerate either calling contract.

The SDK's Python surface is only partly documented, and the reference Python app
exercises neither app settings nor i18n, so there is no ground truth for whether
these return values or coroutines. Rather than betting on one, await whatever
comes back if it is awaitable. Getting this wrong is silent: an un-awaited
`settings.set()` coroutine looks like a successful write and stores nothing.
"""

import inspect


async def resolve(value):
    """Return `value`, awaiting it first if it is awaitable."""
    if inspect.isawaitable(value):
        return await value
    return value


async def setting_get(homey, key: str, default: str = "") -> str:
    try:
        value = await resolve(homey.settings.get(key))
    except Exception:
        return default
    return default if value is None else value


async def setting_set(homey, key: str, value) -> None:
    await resolve(homey.settings.set(key, value))


async def setting_unset(homey, key: str) -> None:
    """Remove a setting, falling back to an empty value.

    Not every build exposes unset(); an empty string reads the same to every
    consumer in this app.
    """
    try:
        await resolve(homey.settings.unset(key))
    except Exception:
        await resolve(homey.settings.set(key, ""))


async def language(homey, default: str = "en") -> str:
    """Two-letter UI language, or `default` if it can't be determined.

    Tries the documented i18n manager first, then a couple of shapes seen on the
    JS side, because none of them is confirmed for Python.
    """
    for get in (
        lambda: homey.i18n.get_language(),
        lambda: homey.i18n.getLanguage(),
        lambda: homey.language,
    ):
        try:
            value = await resolve(get())
        except Exception:
            continue
        if isinstance(value, str) and value:
            return value[:2].lower()
    return default
