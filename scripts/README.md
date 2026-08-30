# Karkinos scripts

Run these commands from the repository root. Ordinary users need only
`./scripts/start_server.sh` and `./scripts/stop_server.sh`. Specialized commands
are grouped by owner:

- `service/`: resident-service management and production-readiness inspection.
- `data/`: local data-source setup and market-data maintenance.
- `broker/`: broker-evidence, conformance, and offline approval tools.
- `ci/`: repository and release verification entry points.

These files are thin entry points; canonical financial and safety logic lives in
the application packages such as `data`, `account_truth`, `analytics`, and
`server`.

## Daily development

| Command | Purpose | Local writes or external contact |
| --- | --- | --- |
| `./scripts/start_server.sh dev` | Build the product bundle and start Vite on port 5173. It starts a reloadable backend only when the supervised LaunchAgent is not loaded; otherwise it reuses the healthy resident backend. The live scheduler is always part of the backend lifecycle. | Writes PID and log files for manually started processes; archives logs above 20 MiB by default; may install missing frontend dependencies. |
| `./scripts/start_server.sh prod` | Start the backend against the existing `web/dist` bundle without code hot reload, or report success when the healthy supervised LaunchAgent already owns the backend. | Writes a PID and server log only when launching a manual backend. |
| `./scripts/stop_server.sh` | Stop the tracked/manual backend and Vite processes, or explicitly uninstall the loaded Karkinos LaunchAgent. | Stops only the exact LaunchAgent when one is loaded; otherwise retains the existing manual PID/command/port cleanup behavior. |
| `./scripts/service/manage_launch_agent.sh print-plist` | Render the macOS user-level production service definition without installing it. | Read-only; prints local paths and process arguments to the current terminal. |
| `./scripts/service/manage_launch_agent.sh install\|status\|uninstall` | Explicitly install, inspect, or remove the current user's restartable Karkinos production service. | Writes or removes only `~/Library/LaunchAgents/com.karkinos.daily-candidate.plist`; starts or stops that exact service and writes its local log. |
| `python scripts/service/repair_legacy_fund_trade_duplicates.py` | Preview or explicitly repair the narrowly scoped legacy fund-trade duplicate correction. | Requires the script's explicit acknowledgement; remains provider-free and does not submit orders, change capital authority, or silently rewrite unrelated ledger facts. |
| `uv run python scripts/service/audit_daily_candidate_production.py --pretty` | Read the running local service's exact financial preflight, monitor, five-round research policy, 20-day / 50-order trial, and compact dependency-ordered operator checklist into one sanitized readiness report. | Loopback GET only; no provider/broker contact or database write. Repeated candidate blockers are counted instead of copied as operator noise, and invalid checklist authority fails closed. Exit `0` means ready to continue bounded forward paper/shadow collection, not GO, profit, execution, or capital authority; exit `2` is fail-closed non-ready. |
| `uv run python scripts/data/configure_data_source.py` | Select AKShare or Tushare without placing credentials in `config.json` or command history. | Updates ignored local `config.json` and `.env`; Tushare tokens are entered interactively. |

Use `http://127.0.0.1:5173` while editing the frontend in `dev` mode. Port 8000
continues to serve the product-style `web/dist` bundle and backend API.
Set `KARKINOS_LOG_MAX_BYTES` to a positive byte count to change the default
20 MiB startup log-archive threshold. Archives remain under `logs/`; the script
does not delete them.
Before building or launching, the start script checks the exact user-level
LaunchAgent and selected backend port. A resident service is reusable only when
both process liveness and the live scheduler are ready; it is then reused by
`dev` and treated as already running by `prod`. A loaded but unhealthy resident
service fails closed without launching a competing backend. Other listeners are
reported without being terminated. The stop script explicitly removes the exact
resident LaunchAgent when it is loaded.

For an owner-operated Mac that must keep the daily-candidate monitor alive
after the launching terminal exits, use `./scripts/service/manage_launch_agent.sh` instead of
relying on the background child created by `start_server.sh`. Inspect the
generated definition with `print-plist`, then run `install` explicitly. The
LaunchAgent uses direct process arguments, binds only `127.0.0.1`, restarts
after any process exit while loaded, and can be removed with `uninstall`. The
live scheduler starts with the service. Installation does not edit `config.json`
or `.env` and does not claim financial readiness. If another process already owns the backend
port, installation exits without terminating it.

## Market-data maintenance

| Command | Purpose | Safety boundary |
| --- | --- | --- |
| `uv run python scripts/data/sync_market_bars_to_db.py` | Import existing Parquet bar mirrors into `data/store/meta.db.market_bars`. | Does not fetch remote data. It updates the selected local `DataStore`. |
| `uv run python scripts/data/verify_market_bars.py --symbol SYMBOL --start YYYY-MM-DD --end YYYY-MM-DD` | Fetch one provider range and compare it with persisted local bars. | Contacts the selected market-data provider but does not overwrite local bars. |

These commands maintain or verify historical bars. They do not start the live
quote scheduler.

## Broker evidence and compatibility

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/preview_citic_history_xls.py --path FILE_OR_DIRECTORY` | Privacy-minimized, read-only schema and evidence-gap preview for local CITIC `历史成交` legacy XLS exports. It never prints event/account values or persists evidence. |
| `uv run python scripts/broker/import_broker_order_lifecycle.py --file FILE` | Validate one broker-neutral exact-order lifecycle export. |
| `uv run python scripts/broker/ingest_broker_order_lifecycle_collector_batch.py --file FILE` | Validate one broker-neutral collector batch and its cursor transition. |
| `uv run python scripts/broker/migrate_legacy_qmt_order_lifecycle.py --file FILE` | Explicitly convert the retired QMT v1 export schema into the canonical broker-neutral schema. It does not import the QMT SDK or contact a broker. |

The CITIC history command is preview-only and deliberately remains blocked
until itemized settlement components plus cash and position snapshots are
supplied through separately reviewed evidence. Preview is the default for the
other three commands. Persistence requires `--record`
and the exact acknowledgement printed by the command contract. Recording only
stores validated evidence; it does not submit or cancel orders, mutate the
production ledger, or grant execution authority.

The retired `scripts/broker/import_qmt_order_lifecycle.py` compatibility entry point
was removed. Use the explicit migration command for old QMT exports or the
canonical import command for current broker-neutral exports.

## Broker release validation and operator approval

| Command | Purpose |
| --- | --- |
| `uv run python scripts/broker/review_broker_adapter_release.py --file FILE --db DB` | Preview or explicitly record an adapter release decision. |
| `uv run python scripts/broker/run_broker_adapter_conformance.py --file FILE --db DB --run-id ID` | Run deterministic provider-neutral adapter fixtures. |
| `uv run python scripts/broker/run_broker_execution_edge_conformance.py --file FILE --db DB --run-id ID` | Run deterministic submit/query/cancel boundary fixtures without contacting a broker. |
| `uv run python scripts/broker/operator_signer.py init ...` | Create a local Ed25519 private key and print its public configuration fragment. |
| `uv run python scripts/broker/operator_signer.py sign ...` | Validate and sign one short-lived canonical challenge read from standard input. |

`operator_signer.py` never calls the Karkinos API or edits `config.json`. Keep
the private key outside the repository with permissions `0600` or stricter.

## CI and release checks

| Command | Purpose |
| --- | --- |
| `uv run python scripts/ci/check_docs_health.py` | Check core documentation budgets, local links, language pairs, and roadmap/test separation. |
| `uv run python scripts/ci/export_acceptance_audit.py --audit all` | Export acceptance manifests and optionally bind deterministic test evidence. |
| `uv run python scripts/ci/verify_docker_runtime.py` | Confirm a built container starts with the live scheduler running while broker and capital authority remain disabled. |

Do not delete or rename CI entry points without updating their workflow,
acceptance-registry, documentation, and test consumers.
