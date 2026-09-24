"""Command-line plumbing shared by ``check``, ``migrate`` and ``seed``."""

import argparse
import sys

from intake.config import get_settings


def target_database(prog: str, description: str, argv: list[str] | None) -> tuple[str, str] | None:
    """Parse ``--test`` and return (variable name, URL), or print why not and return None.

    The URL holds a password: callers must never print it.
    """
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "--test", action="store_true", help="use TEST_DATABASE_URL instead of DATABASE_URL"
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    name = "TEST_DATABASE_URL" if args.test else "DATABASE_URL"
    url = settings.test_database_url if args.test else settings.database_url
    if url is None:
        print(f"error: {name} is not set", file=sys.stderr)
        return None
    return name, url.get_secret_value()
