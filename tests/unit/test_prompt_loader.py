"""The system prompt loader: comments stripped, every placeholder filled."""

from datetime import date

import pytest

from intake.agent.prompts.loader import PROMPT_FILE, render_prompt, spoken_caller_number

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
    ("caller_number", "spoken"),
    [
        ("5125550143", "five one two, five five five, zero one four three"),
        (None, "unknown"),
        ("+442079460000", "+442079460000"),  # not a US number: shown as the carrier sent it
    ],
)
def test_the_caller_number_is_given_as_spoken_digits(caller_number: str | None, spoken: str):
    assert spoken_caller_number(caller_number) == spoken
    assert f"The caller's number is {spoken}." in _render(caller_number)


def test_a_multi_line_comment_is_removed_whole():
    template = "Hello {{agent_name}}.\n<!-- a note\nover two lines -->\n\n\n\nBye."

    assert _render(template=template) == "Hello Maya.\n\nBye.\n"


def test_an_unknown_placeholder_fails_loudly():
    with pytest.raises(KeyError, match="patient_name"):
        _render(template="Hi {{patient_name}}")
