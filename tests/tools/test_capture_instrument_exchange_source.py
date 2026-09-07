"""The explicit capture CLI reports evidence without granting qualification."""

import json

import pytest

from data.instrument_exchange_source import SseSourceCaptureRejected
from tests.data.test_instrument_exchange_source import Response, _body, _transport
from tools import capture_instrument_exchange_source as cli


def test_cli_captures_only_explicit_selected_notice(tmp_path, monkeypatch, capsys):
    _transport(monkeypatch, Response(_body()))
    assert cli.main(["--source", "stock-688802", "--output-dir", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["source_id"] == "stock-688802"
    assert output["capture_status"] == "captured"
    assert output["qualification"] == "blocked"
    assert output["verified_supported_dates"] == []
    assert output["human_verification_status"] == "not_performed"
    assert output["authorizes_metadata_publication"] is False
    assert (tmp_path / "captures" / (output["receipt_sha256"] + ".json")).is_file()


def test_cli_failure_is_not_reported_as_a_success(tmp_path, monkeypatch, capsys):
    def rejected(*args, **kwargs):
        raise SseSourceCaptureRejected("source_tls_verification_failed")

    monkeypatch.setattr(cli, "capture_sse_listing_source", rejected)
    assert cli.main(["--source", "stock-688802", "--output-dir", str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "failed",
        "reason": "source_tls_verification_failed",
    }
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--source", "stock-688802"],
        ["--source", "not-an-allowed-notice", "--output-dir", "unused"],
    ],
)
def test_cli_requires_explicit_allowlisted_source_and_destination(monkeypatch, args):
    def unexpected(*args, **kwargs):
        raise AssertionError("invalid invocation must not fetch")

    monkeypatch.setattr(cli, "capture_sse_listing_source", unexpected)
    with pytest.raises(SystemExit) as result:
        cli.main(args)
    assert result.value.code == 2
