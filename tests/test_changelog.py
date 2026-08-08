"""Each release note says what that release changed, and nothing else.

Between 1.0.3 and 1.0.6 the entries were cumulative: every version prepended its
new paragraphs to the whole of the previous version's text. Nothing enforced it and
nothing objected, so it simply grew — 1.0.6 reached ten paragraphs and 3,970
characters, of which two paragraphs were about 1.0.6. A user opening the store saw
the app's entire history under the heading of the version they were about to
install, with the new part buried at the top of it.

The invariant below is the whole fix. It is mechanical on purpose: "remember not to
paste the previous entry" is exactly the kind of rule that survives two releases.

Carrying a paragraph forward deliberately would have to be argued for here, and the
argument is weak — Homey shows the changelog per version, so a reader who wants the
earlier text can reach it, and repeating it costs them the ability to tell what
actually changed.
"""

import json
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).parent.parent / ".homeychangelog.json"
LANGUAGES = ("en", "ko")


@pytest.fixture(scope="module")
def entries():
    return json.loads(CHANGELOG.read_text(encoding="utf-8"))


def _paragraphs(text):
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def test_every_entry_carries_both_languages(entries):
    for version, entry in entries.items():
        assert set(entry) >= set(LANGUAGES), f"{version} is missing a translation"


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_entry_repeats_a_paragraph_from_an_earlier_one(entries, language):
    """The accumulation check. A paragraph that already shipped under an earlier
    version is not news, and pasting it forward is how the entry grew tenfold."""
    seen = {}
    for version, entry in entries.items():
        for paragraph in _paragraphs(entry[language]):
            previous = seen.get(paragraph)
            assert previous is None, (
                f"{version} ({language}) repeats a paragraph first published in "
                f"{previous}: {paragraph[:70]}..."
            )
            seen[paragraph] = version


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_entry_stays_short_enough_to_read(entries, language):
    """Not a style rule — a ceiling far above any honest single-release note, so it
    catches accumulation creeping back in some form the paragraph check misses (a
    reworded recap, say). 1.0.3 is the largest legitimate entry at ~1,500
    characters; the cumulative 1.0.6 was 3,970."""
    limit = 2500
    for version, entry in entries.items():
        size = len(entry[language])
        assert size <= limit, (
            f"{version} ({language}) is {size} characters. If this release really "
            f"did that much, split the news; if it is a recap of earlier versions, "
            f"drop it."
        )
