import re

import pytest

from keyboards.reply import CLIENT_BUTTONS
from locales.messages import LATE_WARNING, MESSAGES, get_message
from services.users import LANGUAGES

PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_every_message_has_all_languages(key):
    for lang in LANGUAGES:
        assert MESSAGES[key].get(lang), f"{key}: нет текста на '{lang}'"


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_placeholders_match_between_languages(key):
    sets = {lang: set(PLACEHOLDER.findall(MESSAGES[key][lang])) for lang in LANGUAGES}
    assert len({frozenset(s) for s in sets.values()}) == 1, f"{key}: разные подстановки {sets}"


def test_client_buttons_have_all_languages_and_are_unique():
    for key, texts in CLIENT_BUTTONS.items():
        for lang in LANGUAGES:
            assert texts.get(lang), f"кнопка {key}: нет текста на '{lang}'"
    all_texts = [t for texts in CLIENT_BUTTONS.values() for t in texts.values()]
    assert len(all_texts) == len(set(all_texts)), "тексты кнопок должны быть уникальны"


def test_late_warning_has_all_languages():
    assert set(LATE_WARNING) >= set(LANGUAGES)


def test_unknown_language_falls_back_to_russian():
    assert get_message("no_meetings_to_cancel", "en") == MESSAGES["no_meetings_to_cancel"]["ru"]
