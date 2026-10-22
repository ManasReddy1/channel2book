"""Tests for cost estimation."""

import pytest

from channel2book.utils.cost import estimate_cost, format_cost, estimate_pipeline_cost


def test_estimate_cost_sonnet():
    cost = estimate_cost(1_000_000, 500_000, "claude-sonnet-4-20250514")
    # Input: 1M * $3/M = $3.00, Output: 0.5M * $15/M = $7.50
    assert cost == pytest.approx(10.50)


def test_estimate_cost_haiku():
    cost = estimate_cost(1_000_000, 500_000, "claude-haiku-4-5-20251001")
    # Input: 1M * $0.80/M = $0.80, Output: 0.5M * $4/M = $2.00
    assert cost == pytest.approx(2.80)


def test_estimate_cost_unknown_model():
    cost = estimate_cost(1000, 500, "unknown-model")
    assert cost == 0.0


def test_format_cost_small():
    assert format_cost(0.001) == "$0.0010"


def test_format_cost_normal():
    assert format_cost(1.23) == "$1.23"


def test_estimate_pipeline_cost():
    costs = estimate_pipeline_cost(100_000, "claude-sonnet-4-20250514", 10)
    assert "writer" in costs
    assert "checker" in costs
    assert "book_parts" in costs
    assert "total" in costs
    assert costs["total"] > 0
    assert costs["total"] == pytest.approx(
        costs["writer"] + costs["book_parts"] + costs["checker"]
    )
