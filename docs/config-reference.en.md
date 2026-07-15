# Karkinos configuration guide

[中文](config-reference.zh.md) | [Documentation](README.en.md)

Karkinos configuration includes program defaults, `config.json`, process environment variables, and command-line arguments. Runtime capital authority, Account Truth, session budgets, risk evidence, and order state are dynamic SQLite facts, not static configuration.

Neither `config.json` nor `.env` should be committed. The JSON file holds ordinary local settings; environment variables provide deployment overrides and credentials.

## Quick start

```bash
cp config.example.json config.json
# Optional: create the environment template used by Docker Compose
cp .env.example .env
python -m server
```

A direct `python -m server` process does not load `.env` automatically. Export the variables before starting the process, or use Docker Compose, which uses the project `.env` file for variable substitution.

## Sources and precedence

When the same setting is supplied more than once, the effective precedence is:

```text
CLI arguments > environment variables > config.json > program defaults
```

| Source | Intended content | Commit it? |
| --- | --- | --- |
| Program defaults | Safe and development defaults | Maintained in code |
| `config.json` | Local runtime settings, fee model, sanitized connectors | No |
| Environment / `.env` | Secrets, container paths, deployment overrides | No |
| CLI | One-start `--host`, `--port`, and `--no-live` overrides | Not persisted |
| SQLite | Account facts, watchlists, authority, evidence, sessions, orders | Runtime data |

`KARKINOS_CONFIG_PATH` selects the file to load. `KARKINOS_DATA_DIR` selects the runtime data directory. Neither is a field inside `config.json`.

## config.json structure

The recommended configuration has four groups. See the repository-root [`config.example.json`](../config.example.json) for a safe complete example.

| Group | Purpose |
| --- | --- |
| `server` | Web server, CORS, scheduler, and notification |
| `data_source` | Market-data provider, legacy TuShare token entry, and polling |
| `broker_fee` | Broker fee modeling |
| `ai` | External-model connection settings; credentials default to environment variables |

Unknown top-level fields, unknown group fields, and fields supplied in both grouped and legacy-flat forms stop startup. Misspellings are not silently ignored.

### server

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `host` | string | `0.0.0.0` | API bind address; local development may use `127.0.0.1`. |
| `port` | integer | `8000` | API bind port. |
| `live_auto_start` | boolean | `true` | Starts the built-in market scheduler with the Web service; grants no order authority. |
| `cors_allowed_origins` | string[] | local frontend origins | Browser origins allowed to call the API. |
| `notification` | object | `{"type":"console"}` | Notifier configuration. |

### data_source

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `provider` | string | `akshare` | `akshare` or `tushare`. |
| `tushare_token` | string | empty | Compatibility input; prefer `TUSHARE_TOKEN` for new deployments. |
| `live_poll_interval` | integer | `60` | Market and scheduler polling interval in seconds. |

The interactive setup script preserves the grouped shape:

```bash
uv run python scripts/configure_data_source.py --provider akshare
uv run python scripts/configure_data_source.py --provider tushare
```

The TuShare token is read through a hidden prompt and is never accepted as a CLI argument. The script writes the Git-ignored `config.json`; environment variables remain preferable for containers and long-lived deployments.

### broker_fee

`broker_fee` is a local estimation input. Broker statements and Account Truth remain authoritative.

| Field | Type | Description |
| --- | --- | --- |
| `account_profile_id` | string | Sanitized profile id, never a full brokerage account number. |
| `broker_name` | string | Broker display name. |
| `schedule_id` | string | Fee-rule identifier. |
| `stock_a_commission_rate` | number/string | A-share commission rate. |
| `stock_a_min_commission` | number/string | A-share minimum commission. |
| `fund_etf_commission_rate` | number/string | ETF/exchange-fund commission rate. |
| `fund_etf_min_commission` | number/string | ETF/exchange-fund minimum commission. |
| `stamp_tax_rate` | number/string | Stock sell-side stamp-tax rate. |
| `transfer_fee_rate` | number/string | Default transfer-fee rate. |
| `exchange_transfer_fee_rates` | object | Per-exchange transfer-fee overrides. |
| `other_fee_rate` | number/string | Other fee rate. |
| `rules` | array | Detailed rules by asset, market, side, and fee component. |
| `limitations` | string[] | Known assumptions and review items. |

`account_identifier_saved`, `screenshots_saved`, and `private_exports_saved` must remain `false`. Full account identifiers, screenshots, statements, and real exports are forbidden.

`broker_fee_schedule`, `account_commission_rate`, and `account_min_commission` are migration-only inputs. New writes use `broker_fee`.

### ai

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Allows an explicitly human-started configured external-model boundary. |
| `provider` | string | empty | Provider id such as `deepseek` or an internal compatible service. |
| `model` | string | empty | Provider model name. |
| `base_url` | string | empty | Credential-free HTTPS API base URL. |
| `adapter_kind` | string | `openai_compatible_https` | Currently reviewed adapter type. |
| `timeout_seconds` | number | `20` | Per-request timeout in the range (0, 60]. |
| `api_key_env` | string | `KARKINOS_AI_API_KEY` | Name of the environment variable holding the key, not the key itself. |

`ai.api_keys` remains a legacy ignored-local-config migration input but is omitted from the recommended example. Do not commit API keys.

`allow_financial_context` is no longer a recommended global switch. Each external evidence flow is constrained by its exact human confirmation, immutable evidence scope, and API contract; one boolean cannot widen that boundary.

AI credentials resolve in this order:

1. `KARKINOS_AI_API_KEY`;
2. the environment variable named by `ai.api_key_env`;
3. the provider-derived `<PROVIDER>_API_KEY`;
4. the legacy local `ai.api_keys` value.

## Environment variables

### Runtime and market data

| Environment variable | Field / purpose |
| --- | --- |
| `KARKINOS_CONFIG_PATH` | `config.json` path, default `./config.json` |
| `KARKINOS_DATA_DIR` | data directory, default `./data/store` |
| `KARKINOS_HOST` | `server.host` |
| `KARKINOS_PORT` | `server.port` |
| `KARKINOS_LIVE_AUTO_START` | `server.live_auto_start` |
| `KARKINOS_CORS_ALLOWED_ORIGINS` | comma-separated `server.cors_allowed_origins` |
| `KARKINOS_DATA_SOURCE` | `data_source.provider` |
| `KARKINOS_LIVE_POLL_INTERVAL` | `data_source.live_poll_interval` |
| `TUSHARE_TOKEN` | `data_source.tushare_token` |

Booleans accept `true/false`, `1/0`, `yes/no`, and `on/off`. Misspellings stop startup. Ports, polling intervals, and empty CORS lists are also validated.

### AI

| Environment variable | Purpose |
| --- | --- |
| `KARKINOS_AI_ENABLED` | Overrides `ai.enabled` |
| `KARKINOS_AI_PROVIDER` | Overrides `ai.provider` |
| `KARKINOS_AI_MODEL` | Overrides `ai.model` |
| `KARKINOS_AI_BASE_URL` | Overrides `ai.base_url` |
| `KARKINOS_AI_ADAPTER_KIND` | Overrides `ai.adapter_kind` |
| `KARKINOS_AI_TIMEOUT_SECONDS` | Overrides `ai.timeout_seconds` |
| `KARKINOS_AI_API_KEY` | Recommended AI API-key source |

## Advanced and compatibility settings

The runtime still accepts these advanced top-level fields, but the minimal example does not enable them:

- `broker_connectors`: read-only broker-fact connectors; password, secret, token, and credential fields are forbidden.
- `controlled_bridge_policy`: controlled-bridge review allowlist; `per_order_confirmation_required` must be `true` and `automation_allowed` must be `false`.
- `trusted_operator_identities`: Ed25519 public-key allowlist; public keys only.
- Backtest compatibility fields: `initial_cash`, `start_date`, `end_date`, `assets`, `instruments`, `strategy`, `short_period`, `long_period`, and `commission_rate`.

`assets` and `instruments` are legacy-migration or standalone-backtest inputs. The live watchlist and instrument metadata belong in SQLite.

## Not static configuration

Neither `config.json` nor environment variables can grant:

- broker submission, cancellation, or automatic execution authority;
- capital authority, session budgets, or runtime tokens;
- Account Truth, positions, fills, reconciliation, or risk evidence;
- permission for AI output to become account fact, Decision input, or a trading instruction.

Those boundaries are controlled by runtime storage, explicit human confirmation, and the controlled-execution contracts. See [`CONTROLLED_EXECUTION_PLAN.md`](CONTROLLED_EXECUTION_PLAN.md).

## Security rules

- Never commit `config.json`, `.env`, API keys, broker credentials, or private keys.
- Do not pass tokens as CLI arguments; shell history may retain them.
- Do not store full account numbers, screenshots, statements, real account exports, or runtime databases in configuration.
- Configure explicit production CORS origins; avoid uncontrolled wildcards.
- Fix configuration errors before startup; do not catch them and fall back to defaults.

