# Security Policy

## Reporting a vulnerability

Report security issues privately to the maintainer before opening a public
issue. Share only the minimum reproduction details needed to understand the
problem.

Do not include secrets, brokerage credentials, account data, transaction
history, database files, logs, or screenshots containing private financial
information in a public issue.

## Local development safety

Karkinos should be usable for local development with example configuration and
synthetic test data. Real brokerage credentials, real account balances, real
transaction exports, and personal financial data are not required for ordinary
development or tests.

Use exact trusted CORS origins for any non-local deployment. Do not use wildcard
CORS for public or credentialed deployments.

Do not commit:

- real `.env` files (`.env.example` is the sanitized template);
- credentials or private keys;
- runtime databases;
- real account or broker exports;
- private logs;
- screenshots containing financial information.

## If a secret leaks

1. Revoke or rotate the credential immediately.
2. Remove the exposed file from the working tree.
3. Treat published Git history as compromised until the exposure is remediated.
4. Notify the maintainer with the affected commit, path, and remediation status.

Deleting the file only in a later commit is not sufficient remediation for a
public repository.
