# Source-checkout-free macOS bootstrap

`scripts/release/bootstrap_installer.sh` is the one-time user entry point for
migrating an existing source-based Karkinos service to managed stable releases.
It never builds the application and never executes Python or shell code from the
legacy checkout. The legacy worktree and plist are inputs to the packaged
controller's migration checks only.

Do not use this entry point for a tag whose GitHub Release does not contain an
attested `bootstrap_installer.sh` asset. Publishing and attesting that asset is a
release-workflow prerequisite, not a step the local script can manufacture.

## Obtain and verify the entry point

Install GitHub CLI, authenticate it to `github.com`, and choose an already
published, non-draft, non-prerelease stable tag:

```bash
REPOSITORY=imReese/Karkinos
TAG=v0.3.6
BOOTSTRAP_DOWNLOAD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/karkinos-installer.XXXXXX")"

export GH_HOST=github.com
gh auth status --hostname github.com
gh release download "$TAG" \
  --repo "$REPOSITORY" \
  --dir "$BOOTSTRAP_DOWNLOAD_DIR" \
  --pattern bootstrap_installer.sh

TAG_COMMIT="$(gh api "repos/$REPOSITORY/commits/$TAG" --jq .sha)"
[[ "$TAG_COMMIT" =~ ^[0-9a-f]{40}$ ]]
gh attestation verify "$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh" \
  --repo "$REPOSITORY" \
  --signer-workflow "$REPOSITORY/.github/workflows/release.yml" \
  --source-ref "refs/tags/$TAG" \
  --source-digest "$TAG_COMMIT" \
  --deny-self-hosted-runners
chmod 700 "$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh"
```

Verifying the installer before executing it is the initial trust boundary.
Self-verification inside a script would not protect against a modified script
whose verification code had also been removed.

## Run the one-time handoff

Pass the exact existing checkout and LaunchAgent plist. The installer selects
`arm64` on Apple Silicon and `x86_64` on Intel automatically:

```bash
"$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh" \
  --tag "$TAG" \
  --legacy-workdir "/absolute/path/to/Karkinos" \
  --legacy-plist "$HOME/Library/LaunchAgents/com.karkinos.daily-candidate.plist" \
  --confirm "BOOTSTRAP $TAG"
```

The installer requires macOS and authenticated `gh`, accepts only stable
`vMAJOR.MINOR.PATCH` tags, and requires normalized absolute non-symlink paths.
An optional explicit `--architecture arm64|x86_64` is accepted only when it
matches the detected host. For a non-default production listener, pass
`--service-port 8123` once during this bootstrap; the packaged controller records
that value and all later update/start/stop/status operations reuse it. Slow
machines may also pass an integer `--health-timeout 120` (maximum 3600 seconds)
to the packaged bootstrap controller. It then:

1. proves the selected GitHub Release is published and stable;
2. resolves its tag to an exact commit;
3. downloads the matching native archive and checksum once;
4. validates the checksum and verifies the archive's stable-workflow
   attestation against both the exact tag ref and commit before executing it;
5. rechecks the remote release and tag identities;
6. rejects unsafe archive entries, extracts into a private temporary directory,
   and invokes only the archive's `bin/karkinosctl bootstrap`, handing it the
   same downloaded archive rather than downloading the large payload again;
7. removes the temporary download and extraction directory on success or
   failure.

The packaged controller uses authenticated GitHub API access to recheck the
published Release and tag, validates its own release manifest and complete
payload, and still requires the candidate and stable provenance policies before
running the migration. It then performs the real journaled service handoff,
health checks, and rollback behavior. Therefore the command is an explicit
production mutation after `--confirm`; the installer's automated tests replace
the controller with a recorder and never touch a real service.

Remove the small installer download directory after the command returns:

```bash
rm -f "$BOOTSTRAP_DOWNLOAD_DIR/bootstrap_installer.sh"
rmdir "$BOOTSTRAP_DOWNLOAD_DIR"
```

## Stable workflow integration contract

Before documenting a stable tag as bootstrap-capable, the release workflow must:

- attest the exact tagged `scripts/release/bootstrap_installer.sh` bytes in the
  stable `actions/attest-build-provenance` subject set;
- upload those same bytes to the GitHub Release with the fixed asset name
  `bootstrap_installer.sh`, before publishing the draft release;
- include that fixed name in its exact release-asset inventory and retry checks;
- keep the signer identity `.github/workflows/release.yml` and tag-triggered
  source ref so the verification command above remains exact; and
- run the standalone installer contract tests and a Bash syntax check.

`tools/release_fetch.py` accepts either the historical exact stable asset set or
that same set plus `bootstrap_installer.sh`. This preserves immutable historical
tags while allowing new bootstrap-capable releases; any other extra asset still
fails closed. Adding a second installer checksum asset would require an explicit
corresponding control-plane change.
