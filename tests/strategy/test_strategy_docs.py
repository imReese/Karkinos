"""Strategy documentation coverage tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_strategy_docs_cover_builtins_extensions_parameters_and_boundaries() -> None:
    zh_doc = (REPO_ROOT / "docs/strategy/README.zh.md").read_text(encoding="utf-8")
    en_doc = (REPO_ROOT / "docs/strategy/README.en.md").read_text(encoding="utf-8")

    for text in (zh_doc, en_doc):
        assert "dual_ma" in text
        assert "monthly_rebalance" in text
        assert "bollinger" in text
        assert "rsi" in text
        assert "time_series_momentum" in text
        assert "donchian_breakout" in text
        assert "volatility_target_trend" in text
        assert "pairs_ratio_mean_reversion" in text
        assert "strategy/extensions/" in text
        assert "KARKINOS_STRATEGY_EXTENSION_DIR" in text
        assert "short_period" in text
        assert "target_weights" in text
        assert "bb_period" in text
        assert "rsi_period" in text
        assert "lookback_period" in text
        assert "entry_window" in text
        assert "target_annual_volatility" in text
        assert "entry_z" in text

    assert "风险" in zh_doc
    assert "不构成投资建议" in zh_doc
    assert "人工确认" in zh_doc
    assert "risk" in en_doc.lower()
    assert "not investment advice" in en_doc
    assert "manual confirmation" in en_doc
