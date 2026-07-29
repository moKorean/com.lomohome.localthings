"""Translation for messages raised from Python.

Homey's own server-side i18n cannot be used for this. `homey.i18n.get_language()`
returns the *app's* language, which resolves to 'en' on this firmware even with
`locales/ko.json` loaded, so `translate()` there would hand back English regardless of
who is looking (see docs/PORTING.md section 8). The webviews do know the UI language,
so they report it and it is stored; this module reads the same `locales/*.json` files
Homey uses and formats from them.

English is the fallback at every step: an unknown language, a missing key, or a bad
placeholder all fall back rather than raise. A user-facing error message is the worst
possible place to add a second failure.
"""

import json
from pathlib import Path

DEFAULT = "en"
_LOCALES = Path(__file__).parent.parent / "locales"
_cache: dict[str, dict] = {}


def _strings(language: str) -> dict:
    if language in _cache:
        return _cache[language]
    path = _LOCALES / f"{language}.json"
    try:
        loaded = json.loads(path.read_text())
    except Exception:
        loaded = {}
    _cache[language] = loaded
    return loaded


def _lookup(table: dict, key: str):
    node = table
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def translate(key: str, language: str = DEFAULT, **params) -> str:
    """The string for `key`, in `language` where available and English otherwise.

    Returns the key itself if it exists in neither, which is ugly but traceable — far
    better than an empty message the user cannot report.
    """
    code = (language or DEFAULT)[:2].lower()
    template = _lookup(_strings(code), key)
    if template is None and code != DEFAULT:
        template = _lookup(_strings(DEFAULT), key)
    if template is None:
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except Exception:
        # A placeholder mismatch must not turn a diagnostic into a crash.
        return template
