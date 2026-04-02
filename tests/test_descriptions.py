"""Tests for metric descriptions and tooltip components."""

from __future__ import annotations

import html as _html

import pytest

from abides_ui.components import glassmorphism_card, metric_row
from abides_ui.descriptions import METRIC_DESCRIPTIONS, get_description

# ── Description registry tests ────────────────────────────────────────────────


class TestMetricDescriptions:
    """Ensure the description dictionary is complete and well-formed."""

    # Every label used in app.py metric_row() calls must have a description.
    EXPECTED_LABELS = [
        # Summary KPI
        "Mid Price",
        "Bid-Ask Spread",
        "VWAP",
        "Volume",
        "Realized Vol (σ)",
        "Price Range",
        "Wall-Clock",
        # Spread statistics
        "Mean Spread",
        "Median Spread",
        "Max Spread",
        "Spread Std",
        "Mean Spread %",
        "Median Spread %",
        # Market quality
        "% Time No Bid",
        "% Time No Ask",
        "% Time Two-Sided",
        "Last Trade",
        # Returns distribution
        "Mean Return",
        "Std Dev",
        "Skewness",
        "Excess Kurtosis",
        # Advanced microstructure
        "Mean Spread (¢)",
        "Ann. Volatility",
        "Sharpe Ratio",
        "Avg Bid Depth",
        "Avg Ask Depth",
        "LOB Imbalance μ",
        "LOB Imbalance σ",
        "VPIN",
        "Resilience (ms)",
        # Execution summary
        "Exec Agents",
        "Total Filled",
        "Avg Fill Rate",
        "Avg VWAP Slippage",
        "Max Drawdown",
        # Order flow
        "Orders Submitted",
        "Executions",
        "Cancellations",
        "Fill Rate",
        "Cancel Rate",
        # Trade attribution
        "Total Trades",
        "Maker Types",
        "Taker Types",
    ]

    @pytest.mark.parametrize("label", EXPECTED_LABELS)
    def test_description_exists(self, label: str) -> None:
        desc = get_description(label)
        assert desc, f"Missing description for metric '{label}'"

    @pytest.mark.parametrize("label", EXPECTED_LABELS)
    def test_description_is_nontrivial(self, label: str) -> None:
        """Each description should be a meaningful sentence (>30 chars)."""
        desc = get_description(label)
        assert len(desc) > 30, f"Description for '{label}' is too short: {desc!r}"

    def test_get_description_unknown_returns_empty(self) -> None:
        assert get_description("nonexistent_metric") == ""

    def test_all_descriptions_are_strings(self) -> None:
        for label, desc in METRIC_DESCRIPTIONS.items():
            assert isinstance(desc, str), f"Description for '{label}' is not a string"


# ── Component rendering tests ─────────────────────────────────────────────────


class TestGlassmorphismCardDescription:
    """Verify the glassmorphism card renders description tooltips correctly."""

    def test_card_without_description(self) -> None:
        html = glassmorphism_card(label="Test", value="42")
        assert "ⓘ" not in html
        assert 'title=' not in html.split('style=')[0]  # no title on card div

    def test_card_with_description(self) -> None:
        html = glassmorphism_card(label="VWAP", value="$100.00", description="Volume-Weighted Average Price")
        assert "ⓘ" in html
        assert 'title="Volume-Weighted Average Price"' in html
        assert _html.escape("Volume-Weighted Average Price") in html

    def test_description_is_html_escaped(self) -> None:
        malicious = '<script>alert("xss")</script>'
        html = glassmorphism_card(label="X", value="1", description=malicious)
        assert malicious not in html  # raw script tag must NOT appear
        assert _html.escape(malicious) in html

    def test_empty_description_omits_tooltip(self) -> None:
        html = glassmorphism_card(label="X", value="1", description="")
        assert "ⓘ" not in html


class TestMetricRowAutoEnrich:
    """Verify metric_row auto-enriches cards with descriptions."""

    def test_auto_enrich_known_label(self) -> None:
        html = metric_row([{"label": "VWAP", "value": "$100"}])
        expected_desc = _html.escape(METRIC_DESCRIPTIONS["VWAP"])
        assert expected_desc in html
        assert "ⓘ" in html

    def test_auto_enrich_unknown_label_no_tooltip(self) -> None:
        html = metric_row([{"label": "Unknown Metric", "value": "0"}])
        assert "ⓘ" not in html

    def test_explicit_description_not_overridden(self) -> None:
        custom = "Custom description override"
        html = metric_row([{"label": "VWAP", "value": "$100", "description": custom}])
        assert _html.escape(custom) in html

    def test_style_tag_not_inlined(self) -> None:
        """Tooltip uses native title attr, no <style> needed."""
        html = metric_row([{"label": "Volume", "value": "1000"}])
        assert "<style>" not in html
        assert 'title=' in html
