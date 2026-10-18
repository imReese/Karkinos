"""Download historical daily bars for the core ETF universe using AKShare.

Skips ETFs with an existing local Parquet file.
Saves Parquet and CSV files into data/store/real_etfs/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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

DATA_DIR = Path("data/store/real_etfs")


def fetch_from_akshare(start_date: str = "20210101") -> dict[str, pd.DataFrame]:
    import time

    from data.providers.akshare_sdk import _provider_network_env

    print("Fetching from AKShare fund_etf_hist_em...")
    results = {}
    with _provider_network_env():
        import akshare as ak

        for sym, name, _, _ in CORE_ETFS:
            parquet_path = DATA_DIR / f"{sym}.parquet"
            if parquet_path.exists():
                print(f"Skipping {sym} ({name}): already exists locally.")
                continue

            print(f"Fetching {sym} ({name}) from AKShare...")
            for attempt in range(1, 4):
                try:
                    df = ak.fund_etf_hist_em(
                        symbol=sym, period="daily", start_date=start_date, adjust="hfq"
                    )
                    if df is not None and not df.empty:
                        df = df.rename(
                            columns={
                                "日期": "timestamp",
                                "开盘": "open",
                                "最高": "high",
                                "最低": "low",
                                "收盘": "close",
                                "成交量": "volume",
                                "成交额": "amount",
                            }
                        )
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        clean_df = df[
                            [
                                "timestamp",
                                "open",
                                "high",
                                "low",
                                "close",
                                "volume",
                                "amount",
                            ]
                        ].copy()
                        clean_df = clean_df.sort_values("timestamp").reset_index(
                            drop=True
                        )
                        results[sym] = clean_df
                        print(f"  Successfully fetched {sym}: {len(clean_df)} bars")
                        time.sleep(1.0)
                        break
                except Exception as e:
                    print(f"  AKShare error for {sym} (attempt {attempt}/3): {e}")
                    time.sleep(2.0)

    return results


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    missing = [
        sym for sym, _, _, _ in CORE_ETFS if not (DATA_DIR / f"{sym}.parquet").exists()
    ]
    if not missing:
        print("All target ETFs already downloaded locally in", DATA_DIR)
        return

    print(f"Missing ETFs to download: {missing}")
    results = fetch_from_akshare()

    if not results:
        print("No new ETF data was fetched.")
        return

    print(f"\nSaving {len(results)} ETF datasets to {DATA_DIR}...")
    for sym, df in results.items():
        out_path = DATA_DIR / f"{sym}.parquet"
        csv_path = DATA_DIR / f"{sym}.csv"
        df.to_parquet(out_path, index=False)
        df.to_csv(csv_path, index=False)
        print(f"Saved {sym} to {out_path} ({len(df)} rows)")

    print("\nDownload completed successfully!")


if __name__ == "__main__":
    main()
