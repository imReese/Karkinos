"""DataStore — Parquet(行情) + SQLite(元数据) 存储引擎。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.types import BarFrequency, Symbol


class DataStore:
    """数据存储引擎。

    - Parquet 文件存储行情数据（按标的/频率分目录）
    - SQLite 存储元数据（上次更新时间、数据范围等）
    """

    def __init__(self, root: str | Path = "data/store") -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._meta_path = self._root / "meta.db"
        self._init_meta_db()

    def _init_meta_db(self) -> None:
        with sqlite3.connect(self._meta_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bar_meta (
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    last_updated TEXT,
                    row_count INTEGER DEFAULT 0,
                    PRIMARY KEY (symbol, frequency)
                )
            """
            )

    # ---------- 行情数据 ----------

    def save_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        df: pd.DataFrame,
    ) -> None:
        """保存 K 线数据到 Parquet。"""
        freq_dir = self._root / "bars" / frequency.value
        freq_dir.mkdir(parents=True, exist_ok=True)
        path = freq_dir / f"{symbol}.parquet"
        df.to_parquet(path, index=False)

        # 更新元数据
        if "timestamp" in df.columns and len(df) > 0:
            start = str(df["timestamp"].min())
            end = str(df["timestamp"].max())
        else:
            start = end = ""

        with sqlite3.connect(self._meta_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bar_meta
                   (symbol, frequency, start_date, end_date, last_updated, row_count)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    str(symbol),
                    frequency.value,
                    start,
                    end,
                    datetime.now().isoformat(),
                    len(df),
                ),
            )

    def load_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency = BarFrequency.DAILY,
    ) -> pd.DataFrame | None:
        """从 Parquet 加载 K 线数据。"""
        path = self._root / "bars" / frequency.value / f"{symbol}.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df

    def append_bars(
        self,
        symbol: Symbol,
        frequency: BarFrequency,
        new_df: pd.DataFrame,
    ) -> None:
        """追加 K 线数据到已有 Parquet，按 timestamp 去重排序。"""
        existing = self.load_bars(symbol, frequency)

        if existing is None or existing.empty:
            self.save_bars(symbol, frequency, new_df)
            return

        combined = pd.concat([existing, new_df], ignore_index=True)
        if "timestamp" in combined.columns:
            combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)

        self.save_bars(symbol, frequency, combined)

    def get_meta(self, symbol: Symbol, frequency: BarFrequency) -> dict | None:
        """获取行情元数据。"""
        with sqlite3.connect(self._meta_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM bar_meta WHERE symbol=? AND frequency=?",
                (str(symbol), frequency.value),
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    # ---------- 辅助 ----------

    def list_symbols(
        self, frequency: BarFrequency = BarFrequency.DAILY
    ) -> list[Symbol]:
        """列出已存储的标的。"""
        freq_dir = self._root / "bars" / frequency.value
        if not freq_dir.exists():
            return []
        return [Symbol(p.stem) for p in freq_dir.glob("*.parquet")]
