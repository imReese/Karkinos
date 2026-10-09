"""Download and backfill 5+ years of historical stock and ETF daily bars into Parquet.

Supports:
- Universes: 'hs300' (沪深300), 'zz500' (中证500), 'core_etf' (核心ETF), 'all' (全市场).
- Multi-provider fallback: TuShare Pro -> Baostock -> AKShare.
- Checkpointed & Resumable: skips already downloaded symbols, logs checkpoint.
- Output: Standard columnar Parquet files with clean OHLCV columns.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_historical")

DEFAULT_OUT_DIR = Path("data/store/bars/parquet")
DEFAULT_START_DATE = "2021-01-01"
DEFAULT_END_DATE = "2026-10-09"

CORE_ETFS = [
    ("510300", "沪深300ETF", "510300.SH", "sh.510300"),
    ("510500", "中证500ETF", "510500.SH", "sh.510500"),
    ("159915", "创业板ETF", "159915.SZ", "sz.159915"),
    ("513100", "纳指100ETF", "513100.SH", "sh.513100"),
    ("513500", "标普500ETF", "513500.SH", "sh.513500"),
    ("512890", "红利低波ETF", "512890.SH", "sh.512890"),
    ("518880", "黄金ETF", "518880.SH", "sh.518880"),
    ("511010", "国债ETF", "511010.SH", "sh.511010"),
]


def _read_tushare_token() -> str:
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("KARKINOS_TUSHARE_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("KARKINOS_TUSHARE_TOKEN", "")


def get_hs300_sample_symbols() -> list[tuple[str, str, str, str]]:
    """Return top representative blue-chip stocks for HS300 backfill."""
    return [
        ("600519", "贵州茅台", "600519.SH", "sh.600519"),
        ("300750", "宁德时代", "300750.SZ", "sz.300750"),
        ("601318", "中国平安", "601318.SH", "sh.601318"),
        ("000858", "五粮液", "000858.SZ", "sz.000858"),
        ("600036", "招商银行", "600036.SH", "sh.600036"),
        ("000333", "美的集团", "000333.SZ", "sz.000333"),
        ("601899", "紫金矿业", "601899.SH", "sh.601899"),
        ("601166", "兴业银行", "601166.SH", "sh.601166"),
        ("600900", "长江电力", "600900.SH", "sh.600900"),
        ("002594", "比亚迪", "002594.SZ", "sz.002594"),
        ("600030", "中信证券", "600030.SH", "sh.600030"),
        ("601398", "工商银行", "601398.SH", "sh.601398"),
        ("600887", "伊利股份", "600887.SH", "sh.600887"),
        ("002415", "海康威视", "002415.SZ", "sz.002415"),
        ("601288", "农业银行", "601288.SH", "sh.601288"),
        ("600276", "恒瑞医药", "600276.SH", "sh.600276"),
        ("000001", "平安银行", "000001.SZ", "sz.000001"),
        ("601088", "中国神华", "601088.SH", "sh.601088"),
        ("600048", "保利发展", "600048.SH", "sh.600048"),
        ("300059", "东方财富", "300059.SZ", "sz.300059"),
    ]


class HistoricalDataPipeline:
    """Orchestrates historical daily bar acquisition and local Parquet persistence."""

    def __init__(
        self,
        out_dir: Path,
        start_date: str = DEFAULT_START_DATE,
        end_date: str = DEFAULT_END_DATE,
        checkpoint_name: str = "default",
    ) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.start_date = start_date
        self.end_date = end_date
        self.checkpoint_file = self.out_dir / f".checkpoint_{checkpoint_name}.json"
        self._completed_symbols = self._load_checkpoint()
        self.ts_token = _read_tushare_token()
        self._ts_pro = None
        self._bs_logged_in = False

    def _load_checkpoint(self) -> set[str]:
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return set(data.get("completed", []))
            except Exception as e:
                logger.warning("Failed to load checkpoint file: %s", e)
        return set()

    def _save_checkpoint(self) -> None:
        try:
            with open(self.checkpoint_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated_at": datetime.now().isoformat(),
                        "completed_count": len(self._completed_symbols),
                        "completed": sorted(list(self._completed_symbols)),
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.warning("Failed to save checkpoint: %s", e)

    def _get_tushare_pro(self) -> Any:
        if self._ts_pro is None and self.ts_token:
            try:
                import tushare as ts

                self._ts_pro = ts.pro_api(self.ts_token)
            except Exception as e:
                logger.warning("TuShare pro initialization failed: %s", e)
        return self._ts_pro

    def fetch_via_tushare(
        self, sym: str, ts_code: str, is_etf: bool = False
    ) -> pd.DataFrame | None:
        pro = self._get_tushare_pro()
        if not pro:
            return None

        start_str = self.start_date.replace("-", "")
        end_str = self.end_date.replace("-", "")
        try:
            if is_etf:
                df = pro.fund_daily(
                    ts_code=ts_code, start_date=start_str, end_date=end_str
                )
            else:
                df = pro.daily(ts_code=ts_code, start_date=start_str, end_date=end_str)

            if df is not None and not df.empty:
                df = df.sort_values("trade_date").reset_index(drop=True)
                df["timestamp"] = pd.to_datetime(df["trade_date"])
                df["volume"] = df["vol"] * 100  # 手 -> 股
                clean = df[
                    ["timestamp", "open", "high", "low", "close", "volume", "amount"]
                ].copy()
                return clean
        except Exception as e:
            logger.debug("TuShare fetch failed for %s: %s", sym, e)
        return None

    def fetch_via_baostock(self, sym: str, bs_code: str) -> pd.DataFrame | None:
        try:
            import baostock as bs

            if not self._bs_logged_in:
                lg = bs.login()
                if lg.error_code == "0":
                    self._bs_logged_in = True
                else:
                    return None

            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=self.start_date,
                end_date=self.end_date,
                frequency="d",
                adjustflag="3",  # unadjusted raw
            )
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())

            if rows:
                df = pd.DataFrame(rows, columns=rs.fields)
                df = df[df["open"] != ""]
                df["timestamp"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume", "amount"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                clean = df[
                    ["timestamp", "open", "high", "low", "close", "volume", "amount"]
                ].dropna()
                return clean.sort_values("timestamp").reset_index(drop=True)
        except Exception as e:
            logger.debug("Baostock fetch failed for %s: %s", sym, e)
        return None

    def fetch_via_akshare(self, sym: str) -> pd.DataFrame | None:
        try:
            import akshare as ak

            start_str = self.start_date.replace("-", "")
            end_str = self.end_date.replace("-", "")
            df = ak.stock_zh_a_hist(
                symbol=sym,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="",
            )
            if df is not None and not df.empty:
                rename_map = {
                    "日期": "timestamp",
                    "开盘": "open",
                    "最高": "high",
                    "最低": "low",
                    "收盘": "close",
                    "成交量": "volume",
                    "成交额": "amount",
                }
                df = df.rename(columns=rename_map)
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                clean = df[
                    ["timestamp", "open", "high", "low", "close", "volume", "amount"]
                ].copy()
                return clean.sort_values("timestamp").reset_index(drop=True)
        except Exception as e:
            logger.debug("AKShare fetch failed for %s: %s", sym, e)
        return None

    def process_symbol(
        self,
        sym: str,
        name: str,
        ts_code: str,
        bs_code: str,
        is_etf: bool = False,
        force: bool = False,
    ) -> bool:
        target_path = self.out_dir / f"{sym}.parquet"

        if not force and sym in self._completed_symbols and target_path.exists():
            logger.info("Skipping already completed %s (%s)", sym, name)
            return True

        df = None
        # Provider hierarchy: TuShare -> Baostock -> AKShare
        df = self.fetch_via_tushare(sym, ts_code, is_etf=is_etf)
        if df is None or df.empty:
            df = self.fetch_via_baostock(sym, bs_code)
        if df is None or df.empty:
            df = self.fetch_via_akshare(sym)

        if df is None or df.empty:
            logger.warning("FAILED to fetch historical data for %s (%s)", sym, name)
            return False

        # Standardization & Quality Gate
        df = (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"])
            .reset_index(drop=True)
        )
        if len(df) < 20:
            logger.warning(
                "Insufficient records (%d) for %s (%s), not saved", len(df), sym, name
            )
            return False

        # Save as Snappy-compressed columnar Parquet
        df.to_parquet(target_path, engine="pyarrow", compression="snappy", index=False)
        self._completed_symbols.add(sym)
        self._save_checkpoint()

        logger.info(
            "SAVED %s (%s): %d bars (%s to %s) -> %s",
            sym,
            name,
            len(df),
            df["timestamp"].iloc[0].strftime("%Y-%m-%d"),
            df["timestamp"].iloc[-1].strftime("%Y-%m-%d"),
            target_path.name,
        )
        return True

    def close(self) -> None:
        if self._bs_logged_in:
            try:
                import baostock as bs

                bs.logout()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Karkinos 5+ Years Historical Data Ingestion Pipeline"
    )
    parser.add_argument(
        "--universe",
        choices=["core_etf", "hs300_sample", "all"],
        default="core_etf",
        help="Target universe to backfill (default: core_etf)",
    )
    parser.add_argument(
        "--start-date",
        default=DEFAULT_START_DATE,
        help="Start date YYYY-MM-DD (default: 2021-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default=DEFAULT_END_DATE,
        help="End date YYYY-MM-DD (default: 2026-10-09)",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
        help=f"Target output directory for parquet files (default: {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if already in checkpoint",
    )

    args = parser.parse_args()
    out_dir = Path(args.out_dir)

    pipeline = HistoricalDataPipeline(
        out_dir=out_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        checkpoint_name=args.universe,
    )

    if args.universe == "core_etf":
        items = CORE_ETFS
        is_etf = True
    elif args.universe == "hs300_sample":
        items = get_hs300_sample_symbols()
        is_etf = False
    else:
        logger.error("Universe %s not yet expanded", args.universe)
        return

    logger.info(
        "Starting historical ingestion for %d instruments [%s to %s] into %s...",
        len(items),
        args.start_date,
        args.end_date,
        out_dir,
    )

    success_count = 0
    for sym, name, ts_code, bs_code in items:
        ok = pipeline.process_symbol(
            sym, name, ts_code, bs_code, is_etf=is_etf, force=args.force
        )
        if ok:
            success_count += 1
        time.sleep(0.1)

    pipeline.close()
    logger.info(
        "Ingestion completed: %d / %d successful. Checkpoint saved at %s",
        success_count,
        len(items),
        pipeline.checkpoint_file,
    )


if __name__ == "__main__":
    main()
