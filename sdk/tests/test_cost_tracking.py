"""Tests for cost tracking functionality in sandbox sessions."""

import pytest

from harnessbox.cost import CostMetrics, ModelCost, accumulate_costs, parse_cost_data
from harnessbox.sandbox import Sandbox
from tests.conftest import MockProvider

# ---------------------------------------------------------------------------
# 0. Text output parsing
# ---------------------------------------------------------------------------


def test_parse_cost_data_from_text_output():
    """Verify parsing cost from plain text /cost output."""
    cost_data = {
        "output": """<local-command-stdout>Total cost:            $0.1132
Total duration (API):  3s
Total duration (wall): 7s
Total code changes:    0 lines added, 0 lines removed
Usage by model:
   claude-sonnet-4-5:  3 input, 48 output, 0 cache read, 17.9k cache write ($0.1132)</local-command-stdout>"""
    }
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert metrics.total_cost_usd == 0.1132
    assert metrics.turn_count == 1
    assert "claude-sonnet-4-5" in metrics.per_model
    model_cost = metrics.per_model["claude-sonnet-4-5"]
    assert model_cost.input_tokens == 3
    assert model_cost.output_tokens == 48
    assert model_cost.cost_usd == 0.1132


def test_parse_cost_data_text_multiple_models():
    """Verify parsing multiple models from text output."""
    cost_data = {
        "total_cost_usd": 0.15,
        "output": """Usage by model:
   claude-sonnet-4-5:  100 input, 200 output ($0.10)
   claude-haiku-4-5:  50 input, 75 output ($0.05)"""
    }
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert metrics.total_cost_usd == 0.15
    assert len(metrics.per_model) == 2
    assert metrics.per_model["claude-sonnet-4-5"].input_tokens == 100
    assert metrics.per_model["claude-haiku-4-5"].output_tokens == 75

# ---------------------------------------------------------------------------
# 1. CostMetrics initialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_metrics_initialized_in_init():
    """Verify sandbox._cost_metrics exists immediately after __init__."""
    sandbox = Sandbox(
        client=MockProvider(),
        harness="claude-code",
    )
    assert hasattr(sandbox, "_cost_metrics")
    assert isinstance(sandbox._cost_metrics, CostMetrics)


@pytest.mark.asyncio
async def test_cost_metrics_starts_at_zero():
    """Verify initial state: total=0, per_model={}, turn_count=0."""
    sandbox = Sandbox(
        client=MockProvider(),
        harness="claude-code",
    )
    metrics = sandbox.cost_metrics
    assert metrics.total_cost_usd == 0.0
    assert metrics.per_model == {}
    assert metrics.turn_count == 0
    assert metrics.last_updated is None


@pytest.mark.asyncio
async def test_cost_metrics_property_returns_frozen_snapshot():
    """Verify sandbox.cost_metrics returns immutable CostMetrics."""
    sandbox = Sandbox(
        client=MockProvider(),
        harness="claude-code",
    )
    metrics = sandbox.cost_metrics
    # Frozen dataclass should raise FrozenInstanceError on mutation
    with pytest.raises(AttributeError):
        metrics.total_cost_usd = 1.0  # type: ignore


# ---------------------------------------------------------------------------
# 2. modelUsage parsing
# ---------------------------------------------------------------------------


def test_parse_model_usage_happy_path():
    """Parse valid modelUsage with 2 models (Haiku + Sonnet)."""
    cost_data = {
        "total_cost_usd": 0.012,
        "modelUsage": {
            "claude-haiku-4.5": {
                "inputTokens": 123,
                "outputTokens": 52,
                "costUSD": 0.0004,
            },
            "claude-sonnet-4.5": {
                "inputTokens": 3,
                "outputTokens": 68,
                "costUSD": 0.0116,
            },
        },
    }
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert metrics.total_cost_usd == 0.012
    assert len(metrics.per_model) == 2
    assert "claude-haiku-4.5" in metrics.per_model
    assert metrics.per_model["claude-haiku-4.5"].input_tokens == 123
    assert metrics.per_model["claude-sonnet-4.5"].cost_usd == 0.0116


def test_parse_model_usage_missing_field():
    """modelUsage field absent → fallback to total_cost_usd only."""
    cost_data = {"total_cost_usd": 0.05}
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert metrics.total_cost_usd == 0.05
    assert metrics.per_model == {}


def test_parse_model_usage_empty_dict():
    """modelUsage present but empty {} → handle gracefully."""
    cost_data = {"total_cost_usd": 0.03, "modelUsage": {}}
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert metrics.total_cost_usd == 0.03
    assert metrics.per_model == {}


def test_parse_model_usage_malformed_model_entry():
    """One model entry missing costUSD → skip that model."""
    cost_data = {
        "total_cost_usd": 0.01,
        "modelUsage": {
            "model-a": {"inputTokens": 100, "outputTokens": 50, "costUSD": 0.005},
            "model-b": {"inputTokens": 100, "outputTokens": 50},  # Missing costUSD
        },
    }
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert len(metrics.per_model) == 1
    assert "model-a" in metrics.per_model
    assert "model-b" not in metrics.per_model


def test_parse_model_usage_null_cost():
    """Model entry with null costUSD → skip that model."""
    cost_data = {
        "total_cost_usd": 0.01,
        "modelUsage": {
            "model-a": {"inputTokens": 100, "outputTokens": 50, "costUSD": 0.005},
            "model-b": {"inputTokens": 100, "outputTokens": 50, "costUSD": None},
        },
    }
    metrics = parse_cost_data(cost_data)
    assert metrics is not None
    assert len(metrics.per_model) == 1
    assert "model-a" in metrics.per_model


def test_parse_cost_data_empty_response():
    """Empty cost_data → return None."""
    assert parse_cost_data({}) is None
    assert parse_cost_data(None) is None  # type: ignore


def test_parse_cost_data_missing_total():
    """cost_data missing total_cost_usd → return None."""
    cost_data = {"modelUsage": {"model-a": {"inputTokens": 100, "outputTokens": 50, "costUSD": 0.01}}}
    assert parse_cost_data(cost_data) is None


# ---------------------------------------------------------------------------
# 3. Cost accumulation
# ---------------------------------------------------------------------------


def test_accumulate_costs_single_model():
    """Accumulate costs for a single model across turns."""
    current = CostMetrics(
        total_cost_usd=0.01,
        per_model={
            "model-a": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.01),
        },
        turn_count=1,
        last_updated="2026-01-01T00:00:00Z",
    )

    new = CostMetrics(
        total_cost_usd=0.02,
        per_model={
            "model-a": ModelCost(input_tokens=50, output_tokens=25, cost_usd=0.02),
        },
        turn_count=1,
        last_updated="2026-01-01T00:01:00Z",
    )

    result = accumulate_costs(current, new)

    assert result.total_cost_usd == 0.03
    assert result.turn_count == 2
    assert result.per_model["model-a"].input_tokens == 150  # 100 + 50
    assert result.per_model["model-a"].cost_usd == 0.03  # 0.01 + 0.02


def test_accumulate_costs_multiple_models():
    """Accumulate costs across multiple models."""
    current = CostMetrics(
        total_cost_usd=0.01,
        per_model={
            "model-a": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.01),
        },
        turn_count=1,
        last_updated="2026-01-01T00:00:00Z",
    )

    new = CostMetrics(
        total_cost_usd=0.12,
        per_model={
            "model-a": ModelCost(input_tokens=50, output_tokens=25, cost_usd=0.02),
            "model-b": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.10),
        },
        turn_count=1,
        last_updated="2026-01-01T00:01:00Z",
    )

    result = accumulate_costs(current, new)

    assert result.total_cost_usd == 0.13
    assert result.turn_count == 2
    assert result.last_updated == "2026-01-01T00:01:00Z"
    assert "model-a" in result.per_model
    assert result.per_model["model-a"].input_tokens == 150  # 100 + 50
    assert result.per_model["model-a"].cost_usd == 0.03  # 0.01 + 0.02
    assert "model-b" in result.per_model
    assert result.per_model["model-b"].cost_usd == 0.10


def test_accumulate_costs_new_model_appears():
    """New model appears in second turn → added to per_model dict."""
    current = CostMetrics(
        total_cost_usd=0.01,
        per_model={
            "model-a": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.01),
        },
        turn_count=1,
        last_updated="2026-01-01T00:00:00Z",
    )

    new = CostMetrics(
        total_cost_usd=0.05,
        per_model={
            "model-b": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.05),
        },
        turn_count=1,
        last_updated="2026-01-01T00:01:00Z",
    )

    result = accumulate_costs(current, new)

    assert len(result.per_model) == 2
    assert "model-a" in result.per_model
    assert "model-b" in result.per_model
    assert result.per_model["model-a"].cost_usd == 0.01
    assert result.per_model["model-b"].cost_usd == 0.05


def test_accumulate_costs_zero_turn():
    """Accumulate zero-cost turn (edge case)."""
    current = CostMetrics(
        total_cost_usd=0.01,
        per_model={
            "model-a": ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.01),
        },
        turn_count=1,
        last_updated="2026-01-01T00:00:00Z",
    )

    new = CostMetrics(
        total_cost_usd=0.0,
        per_model={},
        turn_count=1,
        last_updated="2026-01-01T00:01:00Z",
    )

    result = accumulate_costs(current, new)

    assert result.total_cost_usd == 0.01
    assert result.turn_count == 2
    assert len(result.per_model) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_model_cost_immutable():
    """ModelCost is frozen (immutable)."""
    cost = ModelCost(input_tokens=100, output_tokens=50, cost_usd=0.01)
    with pytest.raises(AttributeError):
        cost.input_tokens = 200  # type: ignore


def test_cost_metrics_immutable():
    """CostMetrics is frozen (immutable)."""
    metrics = CostMetrics(total_cost_usd=0.01, turn_count=1)
    with pytest.raises(AttributeError):
        metrics.total_cost_usd = 0.02  # type: ignore
