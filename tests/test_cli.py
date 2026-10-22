"""Tests for the CLI interface."""

import pytest
from typer.testing import CliRunner

from channel2book.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "channel2book v" in result.output


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "channel2book" in result.output


def test_build_requires_url():
    result = runner.invoke(app, ["build"])
    assert result.exit_code != 0


def test_status_runs(tmp_path):
    result = runner.invoke(app, ["status", "--output", str(tmp_path)])
    # Should not crash even without a database
    assert result.exit_code == 0
