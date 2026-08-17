"""English has to work as the fallback for every language that isn't declared.

Everything user-facing is authored in Korean and English together, which makes it easy
to add a Korean string and forget the English one. That failure is invisible to whoever
made it — the author sees Korean and everything looks fine — and it only shows up for
someone whose language isn't declared, as a blank label or the literal "undefined".
These checks are the only thing standing between that and a release.
"""

import json
import re
from pathlib import Path

import pytest

from lib import registry

APP_ROOT = Path(__file__).parent.parent
VIEWS = (
    "settings/index.html",
    "drivers/appliance/pair/configure.html",
    "drivers/appliance/repair/reconnect.html",
)
LANGUAGE_CODES = {
    "en", "ko", "nl", "de", "fr", "it", "sv", "no", "da", "es", "pl", "ru", "zh",
}


def _built_manifest() -> dict:
    path = APP_ROOT / ".homeybuild" / "app.json"
    if not path.is_file():
        pytest.skip("run `homey app build` first")
    return json.loads(path.read_text())


def _i18n_objects(node, path=""):
    """Every dict whose keys are all language codes, with where it was found."""
    if isinstance(node, dict):
        keys = set(node)
        if keys and keys <= LANGUAGE_CODES:
            yield path, node
            return
        for key, value in node.items():
            yield from _i18n_objects(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _i18n_objects(value, f"{path}[{index}]")


def test_every_manifest_string_has_english():
    """Homey falls back to English, so a Korean-only string renders as nothing."""
    manifest = _built_manifest()
    found = list(_i18n_objects(manifest))
    assert found, "no translated strings found — the walk is probably broken"
    missing = [path for path, obj in found if "en" not in obj]
    assert not missing, f"no English text at: {missing}"


def _view_strings(filename: str) -> dict:
    """The STRINGS table of a webview, as {language: set_of_keys}."""
    source = (APP_ROOT / filename).read_text()
    match = re.search(r"STRINGS\s*=\s*\{(.*?)\n\s{0,4}\};", source, re.DOTALL)
    assert match, f"{filename}: could not find STRINGS"
    body = match.group(1)
    tables = {}
    for language in ("en", "ko"):
        block = re.search(rf"\b{language}:\s*\{{(.*?)\n\s*\}},", body, re.DOTALL)
        assert block, f"{filename}: no {language} block"
        tables[language] = set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))
    return tables


@pytest.mark.parametrize("filename", VIEWS)
def test_view_has_english_for_every_korean_string(filename):
    """A key present only in Korean resolves to undefined for everyone else, and
    prints the word "undefined" into the page."""
    tables = _view_strings(filename)
    assert tables["en"], f"{filename}: no English strings at all"
    korean_only = tables["ko"] - tables["en"]
    assert not korean_only, f"{filename}: Korean-only keys {sorted(korean_only)}"


@pytest.mark.parametrize("filename", VIEWS)
def test_view_defaults_to_english_and_only_ever_switches_to_korean(filename):
    """English is the default and Korean is opted into.

    Checks the invariant rather than a spelling: LANG starts as 'en' and every
    assignment to it is the literal 'ko'. Assigning a resolved value directly —
    `LANG = lang` — would hand Korean, or a language with no table at all, to
    speakers of everything undeclared.
    """
    source = (APP_ROOT / filename).read_text()
    assert re.search(r"\bvar LANG = 'en';", source), f"{filename}: LANG must default to en"

    assignments = re.findall(r"\bLANG\s*=\s*([^;]+);", source)
    assert assignments, f"{filename}: LANG is never assigned, so Korean is unreachable"
    unexpected = [a.strip() for a in assignments if a.strip() not in ("'en'", "'ko'")]
    assert not unexpected, (
        f"{filename}: LANG assigned from a non-literal: {unexpected}"
    )
    assert "'ko'" in [a.strip() for a in assignments], (
        f"{filename}: nothing ever selects Korean"
    )


def test_locales_have_english_for_every_korean_key():
    def flatten(node, prefix=""):
        keys = set()
        for key, value in node.items():
            path = f"{prefix}.{key}"
            keys |= flatten(value, path) if isinstance(value, dict) else {path}
        return keys

    english = flatten(json.loads((APP_ROOT / "locales/en.json").read_text()))
    korean = flatten(json.loads((APP_ROOT / "locales/ko.json").read_text()))
    assert not korean - english, f"Korean-only locale keys: {sorted(korean - english)}"


def test_every_registry_has_an_english_title():
    for name, reg in registry._REGISTRY_BY_KEY.items():
        assert (reg.titles or {}).get("en"), f"{name}: no English title"


def test_every_sub_capability_title_has_english():
    for name, reg in registry._REGISTRY_BY_KEY.items():
        for spec in reg.specs:
            if spec.titles:
                assert spec.titles.get("en"), f"{name}.{spec.capability}: no English title"


def test_undeclared_languages_get_english_not_the_registry_key():
    """`title()` falls back to the registry name as a last resort, which would show
    'air_purifier' to a Dutch user. Every type must reach English before that."""
    for name, reg in registry._REGISTRY_BY_KEY.items():
        for language in ("nl", "de", "ja", "", None):
            title = reg.title(language)
            assert title != name, f"{name}: {language!r} falls through to the key"
            assert title == reg.titles["en"], f"{name}: {language!r} gave {title!r}"


def test_no_message_leaves_a_placeholder_unsubstituted():
    """`i18n.translate` formats with single braces. Doubled ones survive formatting
    and reach the user as literal `{capability}` — which shipped in 0.5.6 before
    this test existed."""
    import json
    from pathlib import Path
    root = Path(__file__).parent.parent
    for locale in ("en", "ko"):
        strings = json.loads((root / "locales" / f"{locale}.json").read_text())
        stack = [("", strings)]
        while stack:
            prefix, node = stack.pop()
            if isinstance(node, dict):
                stack.extend((f"{prefix}.{k}" if prefix else k, v) for k, v in node.items())
            elif isinstance(node, str):
                assert "{{" not in node and "}}" not in node, (
                    f"{locale}:{prefix} uses doubled braces, which render literally"
                )


def test_every_placeholder_a_message_declares_is_actually_filled():
    """A message naming a parameter the caller never passes raises KeyError at the
    moment it is needed — which is always while reporting another failure."""
    import json
    import re
    from pathlib import Path

    from lib import i18n
    root = Path(__file__).parent.parent
    strings = json.loads((root / "locales" / "en.json").read_text())
    source = "\n".join(
        (root / rel).read_text()
        for rel in ("lib/appliance/driver.py", "lib/appliance/device.py")
    )
    for key, template in (strings.get("error") or {}).items():
        if f'"error.{key}"' not in source:
            continue
        for name in set(re.findall(r"\{(\w+)\}", template)):
            assert f"{name}=" in source, (
                f"error.{key} expects {{{name}}} but no caller passes it"
            )
        # And it must format without raising when given what the callers pass.
        i18n.translate(f"error.{key}", "en", **{n: "x" for n in
                                                set(re.findall(r"\{(\w+)\}", template))})


def test_nothing_user_facing_asks_homey_for_the_app_s_language():
    """`compat.language` resolves the *app's* language and answers 'en' whatever the
    user has set (docs/PORTING.md section 8). `compat.ui_language` is the workaround,
    and anything a user reads has to go through it.

    This is not hypothetical tidiness. `_sync_capability_options` used the wrong one,
    so every sub-capability title shipped in English on a Korean Homey — the
    refrigerator's compartments read "Fridge" and "Freezer", and the Korean strings
    sitting in the specs were unreachable. The running app reports i18n.get_language
    'en' and ui_language 'ko' side by side, so the two are visibly different and the
    wrong one fails silently, which is why a test holds it rather than a comment.
    """
    import re
    from pathlib import Path

    root = Path(__file__).parent.parent
    for rel in ("lib/appliance/driver.py", "lib/appliance/device.py"):
        source = (root / rel).read_text()
        # `ui_language` contains `language`, so match the call site precisely.
        bare = re.findall(r"compat\.language\(", source)
        assert not bare, (
            f"{rel} calls compat.language() directly; user-facing text and "
            f"per-device titles must use compat.ui_language()"
        )
