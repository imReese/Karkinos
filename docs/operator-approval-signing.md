# Offline Operator Approval Signing

[中文](operator-approval-signing.zh.md) | [Controlled execution](CONTROLLED_EXECUTION_PLAN.md) | [Configuration](config-reference.en.md)

Karkinos verifies short-lived Ed25519 approvals for exact controlled-execution
artifacts. It stores public keys only. The private key stays in an
operator-selected local file and never enters `config.json`, the database, the
browser, or an API request.

This approval proves that one trusted operator reviewed one exact artifact. It
does not issue broker, OMS, risk, kill-switch, AI, strategy, or capital
authority.

## Provision one local identity

Choose a private-key path outside the repository:

```bash
uv run python scripts/operator_signer.py init \
  --private-key ~/.config/karkinos/operator-owner.pem \
  --operator-id local-owner \
  --key-id owner-key-1
```

The command refuses to overwrite an existing key, creates the private file
with mode `0600`, and prints a `trusted_operator_identities` JSON fragment that
contains only the raw public key. Merge that top-level fragment into the local,
ignored `config.json`, then run:

```bash
uv run python -m server --check-config
```

Do not commit the private key, the local configuration, or real approval
evidence. Back up the private key using the owner's normal encrypted secret
backup procedure. Disabling or removing its public identity prevents new
approvals; it does not delete audit history.

## Complete a terminal-clearance review

The Operations/Decision controlled-order journey exposes this action only when
the canonical next step is `preview_terminal_clearance`:

1. Open **Review signed terminal clearance**.
2. Generate the read-only preview and review the exact reconciliation run,
   terminal status, filled/cancelled quantities, Account Truth import,
   lifecycle and broker-evidence fingerprints, fills, costs, and clearance
   fingerprint. Any blocker stops the workflow.
3. Create the three-minute challenge for the matching trusted identity and
   copy its Base64 signing payload.
4. Run the local signer and end stdin after pasting only the payload:

   ```bash
   uv run python scripts/operator_signer.py sign \
     --private-key ~/.config/karkinos/operator-owner.pem \
     --operator-id local-owner \
     --key-id owner-key-1 \
     --expected-action clear_controlled_submission_reconciliation \
     --expected-artifact-type controlled_submission_reconciliation_clearance
   ```

5. Paste and verify only the detached Base64 signature, read the final
   acknowledgement, and record the exact terminal outcome once.
6. Continue to the separately signed ledger-posting review. Clearance records
   actual fill evidence, transitions the OMS to the reviewed terminal state,
   and releases this order's cross-order interlock. It does not post the
   production ledger, call a provider, or create submission/cancel authority.

Open partial fills, stale Account Truth, a non-latest reconciliation run,
identity drift, quantity mismatch, partial batches, or conflicting lifecycle
and statement evidence remain blocked. Refresh the canonical evidence and
generate a new preview/challenge; do not reuse a stale signature.

## Complete a ledger-posting review

The Operations/Decision controlled-order journey exposes this action only when
the canonical next step is `preview_reconciled_ledger_posting`:

1. Open **Review signed ledger posting**.
2. Generate the read-only preview and review its terminal outcome, exact ledger
   event count, Account Truth import, valuation snapshot, ledger cutoff, and
   fingerprint. Any blocker stops the workflow.
3. Create the three-minute challenge for the matching trusted identity.
4. Copy the displayed Base64 signing payload.
5. Run the signer, paste only that payload into stdin, then end stdin
   (`Ctrl-D` on macOS/Linux):

   ```bash
   uv run python scripts/operator_signer.py sign \
     --private-key ~/.config/karkinos/operator-owner.pem \
     --operator-id local-owner \
     --key-id owner-key-1 \
     --expected-action post_controlled_submission_ledger \
     --expected-artifact-type controlled_submission_ledger_posting
   ```

   The signer fails closed unless the canonical JSON, domain, operator/key,
   public-key fingerprint, allowlisted action/artifact pair, expiry, and
   no-authority declaration all match.
6. Paste the returned detached Base64 signature into the Web form and verify it.
   Never paste the private key.
7. Read and select the final acknowledgement, then apply the exact reconciled
   posting once.
8. Review Account Truth after the new ledger cutoff. A later correction is a
   separate signed compensating action and never deletes the original facts.

If the challenge expires, the evidence drifts, the ledger cutoff changes, the
Account Truth import becomes stale, or the service restarts before apply,
discard the old signature and generate a fresh preview and challenge. The
write transaction rechecks every bound identity; duplicate apply attempts
reuse the existing exact posting rather than creating another ledger effect.

## Safety properties

- Preview reads persisted facts and does not contact a provider.
- The signer performs no network I/O and never edits Karkinos configuration or
  database state.
- The browser receives a short-lived payload and detached signature, never the
  private key.
- Final apply cannot submit or cancel an order and cannot widen or restore
  execution or capital authority.
- No trusted public identity means the action remains disabled.
