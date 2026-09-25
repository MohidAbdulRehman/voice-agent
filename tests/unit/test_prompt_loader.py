"""The system prompt loader: comments stripped, every placeholder filled."""

from datetime import date

import pytest

from intake.agent.prompts.loader import BEST_NUMBER, PROMPT_FILE, render_prompt

THURSDAY = date(2026, 9, 24)


def _render(caller_number: str | None = "5125550143", template: str | None = None) -> str:
    return render_prompt(
        agent_name="Maya",
        clinic_name="Riverside Family Clinic",
        today=THURSDAY,
        timezone="America/New_York",
        caller_number=caller_number,
        template=template,
    )


def test_the_real_prompt_has_no_comments_or_placeholders_left():
    source = PROMPT_FILE.read_text(encoding="utf-8")
    prompt = _render()

    for marker in ("<!--", "-->", "{{", "}}"):
        assert marker in source  # the file has comments and placeholders to process
        assert marker not in prompt
    assert "You are Maya, the virtual intake assistant at Riverside Family Clinic." in prompt
    assert "Today is Thursday, September 24, 2026 (America/New_York)." in prompt
    assert "\n\n\n" not in prompt


@pytest.mark.parametrize(
    ("caller_number", "sentence", "offers_it"),
    [
        (
            "5125550143",
            "The caller is calling from five one two, five five five, zero one four three "
            "(5125550143).",
            True,
        ),
        (None, "The caller's number is unknown, so ask for their phone number.", False),
        (
            "+442079460000",  # kept as the carrier sent it
            "The caller is calling from +442079460000, which isn't a US number, so ask for "
            "their phone number.",
            False,
        ),
    ],
)
def test_the_best_number_question_is_offered_only_for_a_us_number(
    caller_number: str | None, sentence: str, offers_it: bool
):
    prompt = _render(caller_number)

    assert sentence in prompt
    assert (BEST_NUMBER in prompt) is offers_it


def test_a_multi_line_comment_is_removed_whole():
    template = "Hello {{agent_name}}.\n<!-- a note\nover two lines -->\n\n\n\nBye."

    assert _render(template=template) == "Hello Maya.\n\nBye.\n"


def test_an_unknown_placeholder_fails_loudly():
    with pytest.raises(KeyError, match="patient_name"):
        _render(template="Hi {{patient_name}}")
