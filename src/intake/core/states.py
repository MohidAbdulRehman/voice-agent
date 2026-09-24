"""US states, DC and inhabited territories: USPS codes and full names.

The codes match the ``state_valid`` constraint in db/migrations/0001_init.sql
(tests/db/test_parity.py compares them).
"""

STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "District of Columbia",
    "AS": "American Samoa",
    "GU": "Guam",
    "MP": "Northern Mariana Islands",
    "PR": "Puerto Rico",
    "VI": "U.S. Virgin Islands",
}

# Other ways callers name places, keyed like _key() output.
_ALIASES = {
    "washington dc": "DC",
    "virgin islands": "VI",
    "united states virgin islands": "VI",
}


def _key(name: str) -> str:
    return " ".join(name.replace(".", "").replace(",", "").casefold().split())


_CODES_BY_NAME = {_key(name): code for code, name in STATE_NAMES.items()} | _ALIASES


def state_code_for(name: str) -> str | None:
    """Return the USPS code for a full state or territory name, e.g. ``"texas"`` → ``"TX"``."""
    return _CODES_BY_NAME.get(_key(name))
