# Security Policy

## Reporting a Vulnerability

Please report security issues privately to the maintainer before opening a
public issue. Do not include secrets, brokerage credentials, account data,
transaction history, database files, logs, or screenshots with private
financial information in a public GitHub issue.

If you are unsure whether a report contains sensitive data, redact it first and
share only the minimum reproduction details needed to understand the problem.

## Local Development Safety

Karkinos should be usable for local development with example configuration and
test data. You should not need real brokerage credentials, real account
balances, real transaction exports, or personal financial data to run tests or
work on the UI.

The default API CORS policy is scoped to local Vite development origins
(`http://localhost:5173` and `http://127.0.0.1:5173`). If you deploy the API,
configure exact trusted origins through `KARKINOS_CORS_ALLOWED_ORIGINS` or a
private runtime config. Do not use wildcard CORS for public or credentialed
deployments.

Do not commit:

- `.env*`
- `*.db`, `*.sqlite`, `*.duckdb`
- `data/store/`
- `logs/`
- `exports/`
- `screenshots/`
- `.agents/`
- `skills-lock.json`

## If a Secret Leaks

If a secret, token, broker credential, account export, or database dump is
committed or exposed:

1. Revoke or rotate the credential immediately.
2. Remove the file from the working tree.
3. Treat Git history as compromised until it has been cleaned or replaced.
4. Notify the maintainer with the affected commit, file path, and remediation
   status.

Do not rely on deleting a file in a later commit as sufficient remediation for
public repositories.
