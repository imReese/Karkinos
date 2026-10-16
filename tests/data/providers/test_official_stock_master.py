"""Official master raw replay preserves members, real times and dated statuses."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace

import pandas as pd
import pytest

from data.dataset.manifest import (
    bind_stock_master_observation,
    publish_daily_bar_dataset_manifest,
)
from data.dataset.reader import DatasetReaderIntegrityError, read_daily_bar_dataset
from data.providers.eastmoney import (
    capture_official_stock_master,
    read_official_stock_master_captures,
)
from data.store import DataStore, require_stock_master_capture_evidence
from server.services.market_universe_truth import (
    MarketUniversePolicy,
    market_master_buy_instruments,
    normalize_a_share_members,
)
from tests.server.test_deployment_scope_datasets import _composed
from tests.server.test_verified_interval_dataset import DAYS, NOW


def _capture(objects):
    calls = []
    buffer = BytesIO()
    pd.DataFrame(
        {
            "A股代码": ["000001", "300001"],
            "A股简称": ["普通银行", "普通创业板"],
            "A股上市日期": ["2000-01-01", "2000-01-01"],
        }
    ).to_excel(buffer, index=False)

    def request(method, url, **kwargs):
        params = kwargs["params"] if method == "GET" else kwargs["data"]
        calls.append((url, dict(params), kwargs["headers"]["Referer"]))
        if "sse.com.cn" in url:
            symbols = (
                ["600000", "600001", "601059"]
                if params["STOCK_TYPE"] == "1"
                else ["688001"]
            )
            rows = [
                {
                    "A_STOCK_CODE": symbol,
                    "SEC_NAME_CN": "拟合并公司" if symbol == "601059" else "普通股票",
                    "LIST_DATE": "20000101",
                    "DELIST_DATE": "20260921" if symbol == "601059" else None,
                }
                for symbol in symbols
            ]
            body = json.dumps(
                {"result": rows, "pageHelp": {"total": len(rows)}}
            ).encode()
        elif "szse.cn" in url:
            body = buffer.getvalue()
        else:
            page = int(params["page"])
            body = json.dumps(
                [
                    {
                        "number": page,
                        "totalPages": 2,
                        "totalElements": 2,
                        "content": [
                            {
                                "xxzqdm": "92000" + str(page + 1),
                                "xxzqjc": "普通北交所",
                                "fxssrq": "2000-01-01",
                            }
                        ],
                    }
                ]
            ).encode()
        return SimpleNamespace(content=body, raise_for_status=lambda: None)

    class Result:
        error_code = "0"
        fields = ["code", "tradeStatus", "code_name"]
        rows = iter([["sz.000001", "0", "普通银行"], ["sh.600000", "1", "普通股票"]])

        def next(self):
            self.current = next(self.rows, None)
            return self.current is not None

        def get_row_data(self):
            return self.current

    class Bao:
        def login(self):
            return SimpleNamespace(error_code="0")

        def logout(self):
            return SimpleNamespace(error_code="0")

        def query_all_stock(self, *, day):
            assert day == DAYS[-1].isoformat()
            return Result()

    result = capture_official_stock_master(
        objects,
        trade_date=DAYS[-1].isoformat(),
        request_fn=request,
        clock=lambda: NOW,
        bao_client=Bao(),
    )
    assert len(calls) == 5  # Two SSE boards, SZSE and exactly two BSE pages.
    assert "szse.cn" in calls[2][2]
    return result


def _bound(tmp_path):
    objects, original = _composed(tmp_path)
    rows, refs, started, completed = _capture(objects)
    market = DataStore(tmp_path)
    master = market.save_market_universe_snapshot(
        trade_date=DAYS[-1].isoformat(),
        provider_name="akshare",
        members=normalize_a_share_members([row["symbol"] for row in rows]),
        capture_started_at=started,
        capture_completed_at=completed,
        source_metadata=rows,
        source_capture_ids=refs,
    )
    identity = bind_stock_master_observation(objects, master)
    memberships = (
        *original.snapshot.session_memberships[:-1],
        replace(
            original.snapshot.session_memberships[-1],
            available_at=completed,
            decision_at=completed,
            source_observation_ids=(identity,),
        ),
    )
    snapshot = replace(
        original.snapshot, session_memberships=memberships, cutoff=completed
    )
    return objects, snapshot, master


def test_official_master_replays_complete_sources_and_real_dated_halt(tmp_path):
    objects, snapshot, master = _bound(tmp_path)
    require_stock_master_capture_evidence(objects, master)
    assert master["member_count"] == 8
    rows, started, completed = read_official_stock_master_captures(
        objects, master["source_capture_ids"], trade_date=DAYS[-1].isoformat()
    )
    assert started == completed == NOW
    eligible = {
        key.symbol
        for key in market_master_buy_instruments(
            master, MarketUniversePolicy(minimum_master_member_count=1)
        )
    }
    assert "000001" not in eligible
    assert "601059" in eligible  # Future delisting does not remove today's member.
    assert (
        next(row for row in rows if row["symbol"] == "000001")["status_session_date"]
        == DAYS[-1].isoformat()
    )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    assert read_daily_bar_dataset(objects, ref).row_count == 3


@pytest.mark.parametrize(
    "case",
    [
        "raw_corrupt",
        "wrong_time",
        "omitted_member",
        "false_halt",
        "wrong_session",
        "missing_page",
    ],
)
def test_official_master_reader_rejects_false_projection_and_corrupt_evidence(
    tmp_path, case
):
    objects, snapshot, master = _bound(tmp_path)
    if case == "raw_corrupt":
        capture = json.loads(
            objects.read_bytes(objects.resolve_ref(master["source_capture_ids"][0]))
        )
        raw = objects.resolve_ref(capture["raw_object"]["object_id"])
        path = objects._path_for(raw.object_id)
        path.chmod(0o644)
        path.write_bytes(b"corrupt public source")
    else:
        master = json.loads(json.dumps(master))
        if case == "wrong_time":
            master["capture_started_at"] = (NOW - timedelta(seconds=1)).isoformat()
        elif case == "omitted_member":
            master["members"] = master["members"][:-1]
            master["member_count"] -= 1
            master["member_metadata"] = master["member_metadata"][:-1]
        elif case == "false_halt":
            halt = next(
                row for row in master["member_metadata"] if row["symbol"] == "000001"
            )
            target = next(
                row for row in master["member_metadata"] if row["symbol"] == "600000"
            )
            target.update(
                {
                    key: halt[key]
                    for key in (
                        "trade_status",
                        "status_session_date",
                        "status_capture_id",
                    )
                }
            )
        elif case == "wrong_session":
            master["trade_date"] = DAYS[0].isoformat()
        else:
            master["source_capture_ids"] = master["source_capture_ids"][:-1]
        core = dict(master)
        core.pop("snapshot_id")
        # Re-hashing a false derived projection cannot turn it into raw proof.
        ref = objects.put_bytes(
            json.dumps(
                core, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        )
        membership = replace(
            snapshot.session_memberships[-1], source_observation_ids=(ref.object_id,)
        )
        snapshot = replace(
            snapshot,
            session_memberships=(*snapshot.session_memberships[:-1], membership),
        )
    ref = publish_daily_bar_dataset_manifest(objects, snapshot)
    with pytest.raises(
        DatasetReaderIntegrityError, match="membership_evidence_invalid"
    ):
        read_daily_bar_dataset(objects, ref)
