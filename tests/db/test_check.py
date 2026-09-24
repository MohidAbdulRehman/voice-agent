"""intake.db.check against the local test database (docker compose up -d db)."""

import pytest

from intake.config import get_settings
from intake.db.check import check, main


async def test_check_connects_to_the_test_database():
    await check(get_settings().test_database_url.get_secret_value())


def test_main_prints_ok(capsys: pytest.CaptureFixture[str]):
    assert main(["--test"]) == 0
    assert capsys.readouterr().out == "ok\n"


def test_database_url_is_redirected_to_the_test_database(capsys: pytest.CaptureFixture[str]):
    settings = get_settings()

    assert settings.database_url == settings.test_database_url
    assert main([]) == 0
    assert capsys.readouterr().out == "ok\n"


def test_failure_is_reported_without_the_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://app:s3cret@127.0.0.1:1/nowhere")

    assert main(["--test"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: could not connect using TEST_DATABASE_URL (")
    assert "s3cret" not in captured.err
