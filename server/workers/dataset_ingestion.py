"""项目数据准备的隔离执行入口，由 Server 启动并管理，不是检查脚本。

请求从标准输入接收，凭据由父进程准备的私有 INI 提供。成功数据写到
持久研究目录；这里只有调用结果使用临时文件。原生 SDK 的日志不外传。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from core.types import InstrumentKey, InstrumentType
from data.market.contracts import DailyBarRequest
from data.market.ingestion import DailyBarIngestionNoData
from data.providers.tdx import TdxDailyBarProvider
from server.services.research_datasets import (
    ResearchDatasetError,
    prepare_daily_dataset,
)


def main() -> int:
    payload = json.load(sys.stdin)
    report = Path(payload["report"])
    raw = payload["request"]
    request = DailyBarRequest(
        instruments=tuple(
            InstrumentKey(item["symbol"], InstrumentType(item["instrument_type"]))
            for item in raw["instruments"]
        ),
        start_date=date.fromisoformat(raw["start_date"]),
        end_date=date.fromisoformat(raw["end_date"]),
    )
    try:
        ref = prepare_daily_dataset(
            Path(payload["root"]),
            request=request,
            dates=tuple(date.fromisoformat(item) for item in payload["dates"]),
            provider=TdxDailyBarProvider(),
            refresh=payload["refresh"],
        )
        result = {"status": "ok", "dataset_id": ref.dataset_id}
    except DailyBarIngestionNoData:
        result = {"status": "error", "error_code": "dataset_provider_no_data"}
    except ResearchDatasetError:
        result = {
            "status": "error",
            "error_code": "dataset_quality_or_checkpoint_invalid",
        }
    except Exception:
        result = {"status": "error", "error_code": "dataset_preparation_failed"}
    report.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
