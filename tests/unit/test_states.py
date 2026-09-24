"""USPS codes and full-name lookup."""

import pytest

from intake.core.states import STATE_NAMES, state_code_for


def test_fifty_states_dc_and_five_territories():
    assert len(STATE_NAMES) == 56
    assert {"DC", "AS", "GU", "MP", "PR", "VI"} <= STATE_NAMES.keys()


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("texas", "TX"),
        ("NEW YORK", "NY"),
        ("  north   carolina ", "NC"),
        ("Washington", "WA"),
        ("Washington, D.C.", "DC"),
        ("U.S. Virgin Islands", "VI"),
        ("Atlantis", None),
        ("TX", None),  # codes aren't names; validation checks codes first
    ],
)
def test_state_code_for_names(name: str, code: str | None):
    assert state_code_for(name) == code
