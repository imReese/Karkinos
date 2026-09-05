"""Strategy documentation coverage tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_strategy_compatibility_docs_point_to_canonical_architecture_and_parameter_owners() -> (
    None
):
    zh_doc = (REPO_ROOT / "docs/strategy/README.zh.md").read_text(encoding="utf-8")
    en_doc = (REPO_ROOT / "docs/strategy/README.en.md").read_text(encoding="utf-8")

    for text in (zh_doc, en_doc):
        assert "legacy compatibility" in text
        assert "../ARCHITECTURE.md" in text
    assert "README.zh.md" in en_doc
    for text in (zh_doc,):
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
        assert "strategy/builtins/" in text
        assert "risk、paper/shadow 和 human gate" in text
        assert "不代表经过实盘验证的 Alpha" in text
