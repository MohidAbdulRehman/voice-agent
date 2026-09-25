"""The system prompt: ``system_prompt.md`` with its comments stripped and placeholders filled.

The HTML comments explain the prompt to reviewers; stripping them means they
cost no tokens at runtime.
"""

import re
from datetime import date
from pathlib import Path

from intake.core.speech import say_phone

PROMPT_FILE = Path(__file__).with_name("system_prompt.md")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_BLANK_LINES = re.compile(r"\n{3,}")
BEST_NUMBER = "Is the number you're calling from the best one to reach you?"


def caller_line(caller_number: str | None) -> str:
    """What the prompt says about the caller's number.

    The "best number" question is written in only when there's a US number to offer.
    In testing, the model asked it even when the prompt said the number was unknown
    and the rule said not to.
    """
    if caller_number is None:
        return "The caller's number is unknown, so ask for their phone number."
    if len(caller_number) == 10 and caller_number.isdigit():
        spoken = say_phone(caller_number, "English")
        return (
            f"The caller is calling from {spoken} ({caller_number}). "
            f'When you get to the phone number, you may ask "{BEST_NUMBER}"'
        )
    return (
        f"The caller is calling from {caller_number}, which isn't a US number, "
        "so ask for their phone number."
    )


def render_prompt(
    *,
    agent_name: str,
    clinic_name: str,
    today: date,
    timezone: str,
    caller_number: str | None,
    template: str | None = None,
) -> str:
    """Strip ``<!-- -->`` comments from the prompt, then fill every ``{{placeholder}}``.

    ``today`` is the date at the clinic, e.g. "Thursday, September 24, 2026".

    Raises:
        KeyError: the template uses a placeholder this function doesn't know.
    """
    text = PROMPT_FILE.read_text(encoding="utf-8") if template is None else template
    values = {
        "agent_name": agent_name,
        "clinic_name": clinic_name,
        "today": f"{today:%A, %B} {today.day}, {today.year}",
        "timezone": timezone,
        "caller_line": caller_line(caller_number),
    }
    filled = _PLACEHOLDER.sub(lambda match: values[match.group(1)], _COMMENT.sub("", text))
    return _BLANK_LINES.sub("\n\n", filled).strip() + "\n"
