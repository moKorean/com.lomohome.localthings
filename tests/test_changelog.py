"""A release note covers everything since the last version users could install.

Not "since the last version", which is the rule this file asserted when it was
written and which was wrong within a day. Publishing uploads a build; promoting it
to the store is a separate click on the developer dashboard, and a build that is
never promoted is a build nobody sees. Its changelog is never read by anyone. So
the news in it has to travel forward into the next entry that does go live, or it
is simply lost — 1.0.5 sat unpromoted while 1.0.4 was live, and trimming its
paragraph out of 1.0.6 would have meant the operation state code shipped to users
with no note at all.

That is the exception, and it is narrow. What it does not license is what happened
between 1.0.3 and 1.0.6, where every entry prepended its news to the whole of the
previous one whether or not that one had gone live: 1.0.6 reached ten paragraphs
of which two were about 1.0.6, so a user opening the store read the app's entire
history under the heading of the version they were about to install.

Hence `UNPROMOTED` below rather than dropping the check. A repeated paragraph has
to name the version it is covering for, and that version has to be one that really
never reached the store — which makes the exception a fact somebody wrote down,
not a hole.

Keep `UNPROMOTED` current: when a build is promoted, remove it from the set. An
entry left in it wrongly re-opens exactly the accumulation this guards against.
"""

import json
from pathlib import Path

import pytest

CHANGELOG = Path(__file__).parent.parent / ".homeychangelog.json"
LANGUAGES = ("en", "ko")

# Versions whose build was uploaded but never promoted to the store, so their notes
# legitimately travel into the next entry. Each needs the reason, because the whole
# value of the set is that it is checkable.
UNPROMOTED = {
    "1.0.5": "build uploaded 2026-08-07, never promoted; 1.0.4 was live through 1.0.6",
    "1.0.6": (
        "builds 15-17 uploaded 2026-08-08/10, never promoted. Athom refuses a second "
        "build under a version already published or in review, so work finished after "
        "build 17 could not join it and went to 1.0.7 instead"
    ),
    "1.0.9": (
        "build 20 uploaded 2026-08-13, never promoted; the store page still showed "
        "1.0.8 on 2026-08-17, so its news travels into 1.1.0"
    ),
}


@pytest.fixture(scope="module")
def entries():
    return json.loads(CHANGELOG.read_text(encoding="utf-8"))


def _paragraphs(text):
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def test_every_entry_carries_both_languages(entries):
    for version, entry in entries.items():
        assert set(entry) >= set(LANGUAGES), f"{version} is missing a translation"


def test_the_unpromoted_set_names_real_versions(entries):
    """A typo here would silently license a repeat it was never meant to."""
    for version, reason in UNPROMOTED.items():
        assert version in entries, f"UNPROMOTED names {version}, which has no entry"
        assert reason.strip(), f"{version} is in UNPROMOTED with no reason"


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_repeated_paragraph_is_covering_for_an_unpromoted_version(entries, language):
    seen = {}
    for version, entry in entries.items():
        for paragraph in _paragraphs(entry[language]):
            previous = seen.get(paragraph)
            if previous is not None:
                assert previous in UNPROMOTED, (
                    f"{version} ({language}) repeats a paragraph already published "
                    f"under {previous}, which went live. Users read it there; "
                    f"repeating it buries what is new in {version}. "
                    f"Paragraph: {paragraph[:70]}..."
                )
                continue  # covered for; the earlier version stays the owner
            seen[paragraph] = version


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_entry_stays_short_enough_to_read(entries, language):
    """A ceiling far above any honest note, so accumulation creeping back in a form
    the paragraph check misses — a reworded recap — still trips something. 1.0.3 is
    the largest legitimate entry at ~1,500 characters; the cumulative 1.0.6 was
    3,970."""
    limit = 2500
    for version, entry in entries.items():
        size = len(entry[language])
        assert size <= limit, (
            f"{version} ({language}) is {size} characters. If the release really did "
            f"that much, split the news; if it is a recap of versions users have "
            f"already seen, drop it."
        )
