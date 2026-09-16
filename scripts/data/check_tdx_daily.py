"""手动检查一只股票、一个交易日的 TDX 采集与离线重放。

默认只做预检查，不加载原生 SDK、不联网、不创建数据文件。
真实调用需要 --allow-network；认证沿用 SDK 自己的 TdxAiData.ini。
不读取 .env，不接受命令行 Key，也不推断或改写 SDK 配置文件。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timezone
from importlib import metadata
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[2]


def _session_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("日期必须采用 YYYY-MM-DD 格式") from None
    if result.isoformat() != value:
        raise argparse.ArgumentTypeError("日期必须采用 YYYY-MM-DD 格式")
    return result


def _symbol(value: str) -> str:
    if re.fullmatch(r"[0-9]{6}", value) is None:
        raise argparse.ArgumentTypeError("只接受一个六位股票代码，不接受列表或后缀")
    return value


def _timeout(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("超时必须是 1 到 300 秒的整数") from None
    if not 1 <= result <= 300:
        raise argparse.ArgumentTypeError("超时必须是 1 到 300 秒的整数")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", type=_symbol, default="600000")
    parser.add_argument("--date", type=_session_date, required=True)
    parser.add_argument(
        "--allow-network", action="store_true", help="允许一次 SDK 日线调用，可能消耗积分"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="可选：将检查数据保留到仓库外的新目录；不得已存在"
    )
    parser.add_argument("--timeout", type=_timeout, default=60, help="检查超时秒数")
    parser.add_argument("--_worker-report", type=Path, help=argparse.SUPPRESS)
    return parser


def _failure(stage: str, code: str) -> dict[str, object]:
    # 不拼接 SDK 异常文本、原始响应或环境变量，防止认证信息进入诊断输出。
    return {"status": "error", "stage": stage, "error_code": code}


def _run_pipeline(symbol: str, session_date: date, root: Path) -> dict[str, object]:
    """在隔离子进程中执行真实管线，只返回白名单字段。"""
    stage = "dependencies"
    try:
        # 只有明确允许真实检查后才导入项目和原生 SDK。
        from core.types import InstrumentKey, InstrumentType
        from data.dataset.catalog import DatasetCatalog
        from data.dataset.manifest import publish_daily_bar_dataset_manifest
        from data.dataset.reader import read_daily_bar_dataset
        from data.dataset.resolver import (
            DailyBarDatasetResolverPolicy,
            DailyBarResolutionCandidate,
            resolve_daily_bar_dataset,
        )
        from data.market.contracts import DailyBarRequest
        from data.market.ingestion import DailyBarIngestionNoData, ingest_daily_bars
        from data.market.quality import RESEARCH_STRICT_DAILY, MarketQualityStatus
        from data.providers.tdx import TdxDailyBarProvider, TdxProviderUnavailableError
        from data.storage.objects import ContentAddressedObjectStore

        request = DailyBarRequest(
            instruments=(
                InstrumentKey(symbol=symbol, instrument_type=InstrumentType.STOCK),
            ),
            start_date=session_date,
            end_date=session_date,
        )
        store = ContentAddressedObjectStore(root / "objects")
        stage = "ingestion"
        try:
            result = ingest_daily_bars(
                TdxDailyBarProvider(),
                store,
                request=request,
                quality_policy=RESEARCH_STRICT_DAILY,
                normalizer_version="karkinos.market.normalize.v1",
            )
        except DailyBarIngestionNoData:
            return _failure(stage, "no_data_check_session_permissions_and_sdk_config")
        except TdxProviderUnavailableError:
            return _failure(
                stage, "sdk_unavailable_check_installation_and_native_library"
            )

        stage = "quality"
        if result.quality.status is not MarketQualityStatus.PASS:
            return _failure(stage, "quality_blocked")

        stage = "publication"
        # 没有源端发布时间证据，不把历史行情伪装成历史当时已经可用。
        snapshot = resolve_daily_bar_dataset(
            store,
            candidates=(
                DailyBarResolutionCandidate(
                    result.revision, result.materialization, result.quality
                ),
            ),
            start_date=session_date,
            end_date=session_date,
            cutoff=result.capture.completed_at,
            instruments=request.instruments,
            expected_partition_dates=(session_date,),
            policy=DailyBarDatasetResolverPolicy(
                policy_id="karkinos.dataset.pit.strict.v1",
                provider_priority=("tdx",),
                required_quality_policy_id=RESEARCH_STRICT_DAILY.policy_id,
            ),
        )
        ref = publish_daily_bar_dataset_manifest(store, snapshot)
        catalog = DatasetCatalog(root / "index")
        catalog.register(store, ref)

        stage = "replay"
        first = read_daily_bar_dataset(store, ref)
        reopened = ContentAddressedObjectStore(store.root)
        indexed_ref = DatasetCatalog(catalog.root).get(ref.dataset_id).ref
        replayed = read_daily_bar_dataset(reopened, indexed_ref)
        if replayed != first or replayed.row_count != 1:
            return _failure(stage, "replay_mismatch")
        bar = replayed.bars[0]
        if bar.instrument != request.instruments[0] or bar.session_date != session_date:
            return _failure(stage, "replay_identity_mismatch")
        if bar.available_at != result.capture.completed_at:
            return _failure(stage, "availability_mismatch")

        return {
            "status": "ok",
            "stage": "replay",
            "dataset_id": ref.dataset_id,
            "capture_id": result.capture.capture_id,
            "revision_id": result.revision.ref.revision_id,
            "materialization_id": result.materialization.materialization_id,
            "quality": result.quality.status.value,
            "row_count": replayed.row_count,
            "offline_replay": True,
            "bar": {
                "symbol": bar.instrument.symbol,
                "session_date": bar.session_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume),
                "amount_cny": str(bar.amount),
                "event_time": bar.event_time.isoformat(),
                "available_at": bar.available_at.isoformat(),
                "captured_at": bar.captured_at.isoformat(),
            },
            "independent_market_accuracy_check": False,
        }
    except Exception:
        # SDK 及 ingestion 可能记录带异常链的日志；父进程丢弃子进程输出。
        # 这里只返回失败阶段，不用错误字符串猜测“认证失败”或“市场休市”。
        return _failure(stage, "check_failed")


def _run_worker(
    args: argparse.Namespace, root: Path, report: Path
) -> dict[str, object]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--symbol",
        args.symbol,
        "--date",
        args.date.isoformat(),
        "--allow-network",
        "--output-dir",
        str(root),
        "--_worker-report",
        str(report),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _failure("worker", "timeout")
    # 即使原生 SDK 直接写 stdout/stderr 或进程崩溃，也不把原始日志带回终端。
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _failure("worker", "worker_failed")
    if not isinstance(payload, dict) or payload.get("status") not in {"ok", "error"}:
        return _failure("worker", "worker_report_invalid")
    if completed.returncode != 0 and payload["status"] == "ok":
        return _failure("worker", "worker_failed")
    return payload


def _emit(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 1 if payload["status"] == "error" else 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    session_close = datetime.combine(args.date, time(15), ZoneInfo("Asia/Shanghai"))
    if datetime.now(timezone.utc) < session_close:
        parser.error("只允许检查已经收盘的日期；请显式选择一个已结束的交易日")

    if args._worker_report is not None:
        if not args.allow_network or args.output_dir is None:
            parser.error("内部检查进程必须显式允许联网并指定隔离目录")
        sys.path.insert(0, str(REPO_ROOT))
        payload = _run_pipeline(args.symbol, args.date, args.output_dir)
        args._worker_report.write_text(
            json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8"
        )
        return 0 if payload["status"] == "ok" else 1

    root = args.output_dir.expanduser().resolve() if args.output_dir else None
    if root is not None and (root.exists() or root.is_relative_to(REPO_ROOT)):
        parser.error("输出目录必须是仓库外尚不存在的新目录，不得覆盖现有数据")

    try:
        installed = importlib.util.find_spec("tdxaidata") is not None
        try:
            sdk_version = metadata.version("tdxaidata")
        except metadata.PackageNotFoundError:
            sdk_version = None
    except (ImportError, ValueError):
        installed, sdk_version = False, None
    common = {
        "symbol": args.symbol,
        "session_date": args.date.isoformat(),
        "sdk_module": "tdxaidata",
        "sdk_version": sdk_version,
        "credential_source": "SDK-managed TdxAiData.ini; not preverified",
    }
    if not installed:
        return _emit({**common, **_failure("preflight", "sdk_not_installed")})
    if not args.allow_network:
        return _emit({**common, "status": "preflight", "network_attempted": False})

    try:
        with tempfile.TemporaryDirectory(prefix="karkinos-tdx-check-") as temporary:
            workspace = root if root is not None else Path(temporary) / "data"
            workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
            payload = _run_worker(args, workspace, Path(temporary) / "result.json")
    except OSError:
        payload = _failure("workspace", "workspace_or_process_unavailable")
    return _emit(
        {
            **common,
            **payload,
            "artifacts_retained": root is not None,
            "output_dir": str(root) if root is not None else None,
        }
    )


if __name__ == "__main__":
    raise SystemExit(main())
