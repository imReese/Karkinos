#!/usr/bin/env bash

# Standalone, source-checkout-free entrypoint for bootstrap and protocol handoff.
# Distribute this file as a stable, attested GitHub Release asset before use.

set -euo pipefail
umask 077
export LC_ALL=C

REPOSITORY="imReese/Karkinos"
DEFAULT_HOME=""
if [[ -n "${HOME:-}" ]]; then
	DEFAULT_HOME="${HOME}/Library/Application Support/Karkinos"
fi
TAG=""
ARCHITECTURE=""
LEGACY_WORKDIR=""
LEGACY_PLIST=""
CONFIRMATION=""
SERVICE_PORT=""
HEALTH_TIMEOUT=""
INSTALL_MODE=""
KARKINOS_HOME_PATH="${KARKINOS_HOME:-${DEFAULT_HOME}}"
TEMP_ROOT=""
TEMP_PARENT=""

die() {
	echo "Error: $*" >&2
	exit 1
}

usage() {
	cat <<'EOF'
Usage:
	# Managed release-control protocol transition (first required for v0.3.7):
	bootstrap_installer.sh \
	    --tag vX.Y.Z \
	    --confirm "UPDATE vX.Y.Z" \
	    [--architecture arm64|x86_64] \
	    [--service-port 1..65535] \
	    [--health-timeout 1..3600] \
	    [--home "/absolute/runtime/path"]

	# One-time legacy source-service handoff:
	bootstrap_installer.sh \
	    --tag vX.Y.Z \
	    --legacy-workdir /absolute/path/to/Karkinos \
	    --legacy-plist /absolute/path/to/com.karkinos.daily-candidate.plist \
	    --confirm "BOOTSTRAP vX.Y.Z" \
	    [--architecture arm64|x86_64] \
	    [--service-port 1..65535] \
	    [--health-timeout 1..3600] \
	    [--home "/absolute/runtime/path"]

This installer downloads one published stable macOS release, verifies its
checksum and GitHub stable-release attestation, extracts it in a disposable
private directory, and delegates activation to that target package's
bin/karkinosctl. Omit both legacy options for a managed protocol transition; or
provide both for the one-time source-service handoff. It does not build or
execute code from a source checkout.
EOF
}

cleanup() {
	if [[ -n "${TEMP_ROOT}" && -n "${TEMP_PARENT}" &&
		"${TEMP_ROOT}" == "${TEMP_PARENT%/}/karkinos-bootstrap."* &&
		-d "${TEMP_ROOT}" && ! -L "${TEMP_ROOT}" ]]; then
		rm -rf -- "${TEMP_ROOT}"
	fi
}

require_absolute_path() {
	local value="$1"
	local label="$2"
	[[ "${value}" == /* && "${value}" != *[[:cntrl:]]* &&
		"${value}" != *"//"* && ("${value}" == "/" || "${value}" != */) &&
		"/${value#/}/" != *"/../"* && "/${value#/}/" != *"/./"* ]] ||
		die "${label} must be a normalized absolute path without control characters."
}

require_no_symlink_ancestors() {
	local value="$1"
	local cursor="${value}"
	while [[ "${cursor}" != "/" ]]; do
		[[ ! -L "${cursor}" ]] || die "path contains a symlink: ${value}"
		cursor="$(dirname -- "${cursor}")"
	done
}

resolve_tag_commit() {
	local record ref object_type object_sha extra tag_name depth seen
	record="$(gh api "repos/${REPOSITORY}/git/ref/tags/${TAG}" \
		--jq '[.ref, .object.type, .object.sha] | @tsv')" ||
		die "unable to resolve stable tag ${TAG}."
	IFS=$'\t' read -r ref object_type object_sha extra <<<"${record}"
	[[ -z "${extra:-}" && "${ref}" == "refs/tags/${TAG}" ]] ||
		die "stable tag metadata is invalid."
	seen=""
	depth=0
	while [[ "${object_type}" == "tag" ]]; do
		[[ "${object_sha}" =~ ^[0-9a-f]{40}$ ]] ||
			die "stable tag target is invalid."
		[[ ":${seen}:" != *":${object_sha}:"* ]] || die "stable tag cycle detected."
		seen="${seen}:${object_sha}"
		((depth += 1))
		((depth <= 8)) || die "stable tag indirection is too deep."
		record="$(gh api "repos/${REPOSITORY}/git/tags/${object_sha}" \
			--jq '[.tag, .object.type, .object.sha] | @tsv')" ||
			die "unable to resolve annotated stable tag ${TAG}."
		IFS=$'\t' read -r tag_name object_type object_sha extra <<<"${record}"
		[[ -z "${extra:-}" ]] || die "annotated stable tag metadata is invalid."
		if ((depth == 1)); then
			[[ "${tag_name}" == "${TAG}" ]] ||
				die "annotated stable tag name is invalid."
		fi
	done
	[[ "${object_type}" == "commit" && "${object_sha}" =~ ^[0-9a-f]{40}$ ]] ||
		die "stable tag does not resolve to a commit."
	printf '%s\n' "${object_sha}"
}

TAG_SET=0
ARCH_SET=0
WORKDIR_SET=0
PLIST_SET=0
CONFIRM_SET=0
SERVICE_PORT_SET=0
HEALTH_TIMEOUT_SET=0
HOME_SET=0

while (($# > 0)); do
	case "$1" in
	--tag)
		((TAG_SET == 0)) || die "--tag may be provided only once."
		(($# >= 2)) || die "--tag requires a value."
		TAG="$2"
		TAG_SET=1
		shift 2
		;;
	--architecture)
		((ARCH_SET == 0)) || die "--architecture may be provided only once."
		(($# >= 2)) || die "--architecture requires a value."
		ARCHITECTURE="$2"
		ARCH_SET=1
		shift 2
		;;
	--legacy-workdir)
		((WORKDIR_SET == 0)) || die "--legacy-workdir may be provided only once."
		(($# >= 2)) || die "--legacy-workdir requires a value."
		LEGACY_WORKDIR="$2"
		WORKDIR_SET=1
		shift 2
		;;
	--legacy-plist)
		((PLIST_SET == 0)) || die "--legacy-plist may be provided only once."
		(($# >= 2)) || die "--legacy-plist requires a value."
		LEGACY_PLIST="$2"
		PLIST_SET=1
		shift 2
		;;
	--confirm)
		((CONFIRM_SET == 0)) || die "--confirm may be provided only once."
		(($# >= 2)) || die "--confirm requires a value."
		CONFIRMATION="$2"
		CONFIRM_SET=1
		shift 2
		;;
	--service-port)
		((SERVICE_PORT_SET == 0)) || die "--service-port may be provided only once."
		(($# >= 2)) || die "--service-port requires a value."
		SERVICE_PORT="$2"
		SERVICE_PORT_SET=1
		shift 2
		;;
	--health-timeout)
		((HEALTH_TIMEOUT_SET == 0)) || die "--health-timeout may be provided only once."
		(($# >= 2)) || die "--health-timeout requires a value."
		HEALTH_TIMEOUT="$2"
		HEALTH_TIMEOUT_SET=1
		shift 2
		;;
	--home)
		((HOME_SET == 0)) || die "--home may be provided only once."
		(($# >= 2)) || die "--home requires a value."
		KARKINOS_HOME_PATH="$2"
		HOME_SET=1
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		die "unknown argument: $1"
		;;
	esac
done

((TAG_SET == 1)) || die "--tag is required."
((CONFIRM_SET == 1)) || die "--confirm is required."
((WORKDIR_SET == PLIST_SET)) ||
	die "--legacy-workdir and --legacy-plist must be provided together."
if ((WORKDIR_SET == 1)); then
	INSTALL_MODE="bootstrap"
else
	INSTALL_MODE="managed-update"
fi

[[ "$(uname -s)" == "Darwin" ]] || die "bootstrap is supported only on macOS."
case "$(uname -m)" in
arm64 | aarch64) HOST_ARCHITECTURE="arm64" ;;
x86_64 | amd64) HOST_ARCHITECTURE="x86_64" ;;
*) die "unsupported macOS architecture." ;;
esac
if ((ARCH_SET == 0)); then
	ARCHITECTURE="${HOST_ARCHITECTURE}"
else
	[[ "${ARCHITECTURE}" == "arm64" || "${ARCHITECTURE}" == "x86_64" ]] ||
		die "--architecture must be arm64 or x86_64."
	[[ "${ARCHITECTURE}" == "${HOST_ARCHITECTURE}" ]] ||
		die "requested architecture does not match this Mac."
fi
[[ "${TAG}" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
	die "--tag must be a stable SemVer tag such as v0.3.2."
if [[ "${INSTALL_MODE}" == "bootstrap" ]]; then
	[[ "${CONFIRMATION}" == "BOOTSTRAP ${TAG}" ]] ||
		die "--confirm must equal: BOOTSTRAP ${TAG}"
else
	[[ "${CONFIRMATION}" == "UPDATE ${TAG}" ]] ||
		die "--confirm must equal: UPDATE ${TAG}"
fi
if ((SERVICE_PORT_SET == 1)); then
	[[ "${SERVICE_PORT}" =~ ^[1-9][0-9]{0,4}$ ]] ||
		die "--service-port must be an integer from 1 through 65535."
	((SERVICE_PORT <= 65535)) ||
		die "--service-port must be an integer from 1 through 65535."
fi
if ((HEALTH_TIMEOUT_SET == 1)); then
	[[ "${HEALTH_TIMEOUT}" =~ ^[1-9][0-9]{0,3}$ ]] ||
		die "--health-timeout must be an integer from 1 through 3600 seconds."
	((HEALTH_TIMEOUT <= 3600)) ||
		die "--health-timeout must be an integer from 1 through 3600 seconds."
fi
require_absolute_path "${KARKINOS_HOME_PATH}" "--home"
[[ "${KARKINOS_HOME_PATH}" != "/" ]] || die "--home must not be the filesystem root."
require_no_symlink_ancestors "${KARKINOS_HOME_PATH}"
if [[ "${INSTALL_MODE}" == "bootstrap" ]]; then
	require_absolute_path "${LEGACY_WORKDIR}" "--legacy-workdir"
	require_absolute_path "${LEGACY_PLIST}" "--legacy-plist"
	[[ "${LEGACY_WORKDIR}" != "/" ]] ||
		die "--legacy-workdir must not be the filesystem root."
	require_no_symlink_ancestors "${LEGACY_WORKDIR}"
	require_no_symlink_ancestors "${LEGACY_PLIST}"
	[[ -d "${LEGACY_WORKDIR}" && ! -L "${LEGACY_WORKDIR}" ]] ||
		die "--legacy-workdir must be an existing ordinary directory."
	[[ -f "${LEGACY_PLIST}" && ! -L "${LEGACY_PLIST}" ]] ||
		die "--legacy-plist must be an existing ordinary file."
fi
if [[ -e "${KARKINOS_HOME_PATH}" || -L "${KARKINOS_HOME_PATH}" ]]; then
	[[ -d "${KARKINOS_HOME_PATH}" && ! -L "${KARKINOS_HOME_PATH}" ]] ||
		die "--home must be an ordinary directory when it already exists."
fi
if [[ "${INSTALL_MODE}" == "managed-update" ]]; then
	[[ -d "${KARKINOS_HOME_PATH}" && ! -L "${KARKINOS_HOME_PATH}" ]] ||
		die "--home must contain an existing managed runtime for UPDATE."
fi

command -v gh >/dev/null 2>&1 || die "gh is required."
command -v tar >/dev/null 2>&1 || die "tar is required."
command -v shasum >/dev/null 2>&1 || die "shasum is required."
command -v sleep >/dev/null 2>&1 || die "sleep is required."
export GH_HOST=github.com
gh auth status --hostname github.com >/dev/null 2>&1 ||
	die "gh must be authenticated to github.com."

RELEASE_STATE="$(gh release view "${TAG}" --repo "${REPOSITORY}" \
	--json tagName,isDraft,isPrerelease \
	--jq '[.tagName, (.isDraft | tostring), (.isPrerelease | tostring)] | @tsv')" ||
	die "unable to read stable release ${TAG}."
[[ "${RELEASE_STATE}" == "${TAG}"$'\tfalse\tfalse' ]] ||
	die "the selected GitHub release is not a published stable release."
TAG_COMMIT="$(resolve_tag_commit)"

RELEASE_ASSET_METADATA="$(gh release view "${TAG}" --repo "${REPOSITORY}" \
	--json assets --jq '.assets[] | [.name, (.size | tostring)] | @tsv')" ||
	die "unable to read stable release asset metadata."

release_asset_size() {
	local target="$1"
	local asset_name asset_size extra
	local selected=""
	local count=0
	while IFS=$'\t' read -r asset_name asset_size extra; do
		if [[ "${asset_name}" == "${target}" ]]; then
			[[ -z "${extra:-}" && "${asset_size}" =~ ^(0|[1-9][0-9]*)$ ]] ||
				die "stable release asset metadata is invalid: ${target}"
			selected="${asset_size}"
			((count += 1))
		fi
	done <<<"${RELEASE_ASSET_METADATA}"
	((count == 1)) || die "stable release asset metadata is missing or ambiguous: ${target}"
	printf '%s\n' "${selected}"
}

VERSION="${TAG#v}"
ARCHIVE_NAME="karkinos-${VERSION}-macos-${ARCHITECTURE}.tar.gz"
CHECKSUM_NAME="${ARCHIVE_NAME}.sha256"
ARCHIVE_ROOT="Karkinos-${VERSION}-macos-${ARCHITECTURE}"
ARCHIVE_DECLARED_SIZE="$(release_asset_size "${ARCHIVE_NAME}")"
CHECKSUM_DECLARED_SIZE="$(release_asset_size "${CHECKSUM_NAME}")"
((ARCHIVE_DECLARED_SIZE > 0 && ARCHIVE_DECLARED_SIZE <= 536870912)) ||
	die "native archive metadata size is invalid."
((CHECKSUM_DECLARED_SIZE > 0 && CHECKSUM_DECLARED_SIZE <= 4096)) ||
	die "checksum metadata size is invalid."

TEMP_PARENT_INPUT="${TMPDIR:-/tmp}"
while [[ "${TEMP_PARENT_INPUT}" != "/" && "${TEMP_PARENT_INPUT}" == */ ]]; do
	TEMP_PARENT_INPUT="${TEMP_PARENT_INPUT%/}"
done
require_absolute_path "${TEMP_PARENT_INPUT}" "TMPDIR"
[[ -d "${TEMP_PARENT_INPUT}" ]] || die "TMPDIR must be an existing directory."
TEMP_PARENT="$(CDPATH= cd -P -- "${TEMP_PARENT_INPUT}" && pwd -P)" ||
	die "unable to resolve TMPDIR."
require_absolute_path "${TEMP_PARENT}" "resolved TMPDIR"
[[ -d "${TEMP_PARENT}" && ! -L "${TEMP_PARENT}" ]] ||
	die "resolved TMPDIR must be an ordinary directory."
TEMP_ROOT="$(mktemp -d "${TEMP_PARENT%/}/karkinos-bootstrap.XXXXXX")" ||
	die "unable to create a private temporary directory."
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
[[ "${TEMP_ROOT}" == "${TEMP_PARENT%/}/karkinos-bootstrap."* &&
	-d "${TEMP_ROOT}" && ! -L "${TEMP_ROOT}" ]] ||
	die "temporary directory identity is invalid."

DOWNLOAD_DIR="${TEMP_ROOT}/download"
EXTRACT_DIR="${TEMP_ROOT}/extract"
mkdir -m 700 "${DOWNLOAD_DIR}" "${EXTRACT_DIR}"

for asset in "${ARCHIVE_NAME}" "${CHECKSUM_NAME}"; do
	gh release download "${TAG}" --repo "${REPOSITORY}" \
		--dir "${DOWNLOAD_DIR}" --pattern "${asset}" ||
		die "failed to download stable release asset: ${asset}"
done

ARCHIVE_PATH="${DOWNLOAD_DIR}/${ARCHIVE_NAME}"
CHECKSUM_PATH="${DOWNLOAD_DIR}/${CHECKSUM_NAME}"
for asset_path in "${ARCHIVE_PATH}" "${CHECKSUM_PATH}"; do
	[[ -f "${asset_path}" && ! -L "${asset_path}" ]] ||
		die "downloaded release asset is missing or unsafe."
done
[[ "$(find "${DOWNLOAD_DIR}" -mindepth 1 -maxdepth 1 | wc -l | tr -d '[:space:]')" == "2" ]] ||
	die "downloaded release asset set is unexpected."
[[ "$(wc -c <"${CHECKSUM_PATH}" | tr -d '[:space:]')" -le 4096 ]] ||
	die "checksum file is too large."
[[ "$(wc -c <"${ARCHIVE_PATH}" | tr -d '[:space:]')" -le 536870912 ]] ||
	die "native archive is too large."
[[ "$(wc -c <"${ARCHIVE_PATH}" | tr -d '[:space:]')" == "${ARCHIVE_DECLARED_SIZE}" &&
"$(wc -c <"${CHECKSUM_PATH}" | tr -d '[:space:]')" == "${CHECKSUM_DECLARED_SIZE}" ]] ||
	die "downloaded release asset size does not match its metadata."

CHECKSUM_LINES="$(awk 'END { print NR }' "${CHECKSUM_PATH}")"
[[ "${CHECKSUM_LINES}" == "1" ]] || die "checksum file must contain exactly one line."
IFS=$' \t' read -r EXPECTED_CHECKSUM CHECKSUM_FILENAME CHECKSUM_EXTRA <"${CHECKSUM_PATH}"
[[ -z "${CHECKSUM_EXTRA:-}" && "${EXPECTED_CHECKSUM}" =~ ^[0-9a-f]{64}$ &&
	"${CHECKSUM_FILENAME}" == "${ARCHIVE_NAME}" ]] ||
	die "checksum file is invalid."
ACTUAL_CHECKSUM="$(shasum -a 256 -- "${ARCHIVE_PATH}" | awk '{print $1}')"
[[ "${ACTUAL_CHECKSUM}" == "${EXPECTED_CHECKSUM}" ]] ||
	die "native archive checksum mismatch."

verify_archive_attestation() {
	local attempt
	for attempt in 1 2 3; do
		if gh attestation verify "${ARCHIVE_PATH}" \
			--repo "${REPOSITORY}" \
			--signer-workflow "${REPOSITORY}/.github/workflows/release.yml" \
			--source-ref "refs/tags/${TAG}" \
			--source-digest "${TAG_COMMIT}" \
			--deny-self-hosted-runners >/dev/null; then
			return 0
		fi
		((attempt < 3)) || return 1
		sleep "$((2 ** attempt))"
	done
	return 1
}

verify_archive_attestation || die "stable release attestation verification failed."

CONFIRMED_STATE="$(gh release view "${TAG}" --repo "${REPOSITORY}" \
	--json tagName,isDraft,isPrerelease \
	--jq '[.tagName, (.isDraft | tostring), (.isPrerelease | tostring)] | @tsv')" ||
	die "unable to recheck stable release ${TAG}."
[[ "${CONFIRMED_STATE}" == "${RELEASE_STATE}" ]] ||
	die "stable release state changed during verification."
[[ "$(resolve_tag_commit)" == "${TAG_COMMIT}" ]] ||
	die "stable tag changed during verification."

MEMBER_LIST="${TEMP_ROOT}/archive-members.txt"
tar -tzf "${ARCHIVE_PATH}" >"${MEMBER_LIST}" || die "native archive is unreadable."
[[ -s "${MEMBER_LIST}" ]] || die "native archive is empty."
while IFS= read -r member; do
	[[ "${member}" == "${ARCHIVE_ROOT}" || "${member}" == "${ARCHIVE_ROOT}/" ||
		"${member}" == "${ARCHIVE_ROOT}/"* ]] ||
		die "native archive contains an unexpected path."
	[[ "${member}" != /* && "${member}" != *"/../"* && "${member}" != *"/./"* &&
		"${member}" != *"\\"* ]] ||
		die "native archive contains an unsafe path."
done <"${MEMBER_LIST}"
if tar -tvzf "${ARCHIVE_PATH}" | awk '
    substr($1, 1, 1) != "-" && substr($1, 1, 1) != "d" { found=1 }
    END { exit !found }
'; then
	die "native archive contains a link or special entry."
fi
tar -xzf "${ARCHIVE_PATH}" -C "${EXTRACT_DIR}" ||
	die "native archive extraction failed."

RELEASE_ROOT="${EXTRACT_DIR}/${ARCHIVE_ROOT}"
CONTROLLER="${RELEASE_ROOT}/bin/karkinosctl"
[[ -d "${RELEASE_ROOT}" && ! -L "${RELEASE_ROOT}" ]] ||
	die "extracted release root is invalid."
[[ -f "${RELEASE_ROOT}/release.json" && ! -L "${RELEASE_ROOT}/release.json" ]] ||
	die "extracted release manifest is invalid."
[[ -f "${CONTROLLER}" && ! -L "${CONTROLLER}" && -x "${CONTROLLER}" ]] ||
	die "packaged release controller is invalid."
[[ -z "$(find "${RELEASE_ROOT}" -type l -print -quit)" ]] ||
	die "extracted release contains a symlink."
[[ -z "$(find "${RELEASE_ROOT}" ! -type d ! -type f -print -quit)" ]] ||
	die "extracted release contains a special file."

if [[ "${INSTALL_MODE}" == "bootstrap" ]]; then
	CONTROLLER_ARGUMENTS=(
		--home "${KARKINOS_HOME_PATH}"
		bootstrap
		--tag "${TAG}"
		--legacy-workdir "${LEGACY_WORKDIR}"
		--legacy-plist "${LEGACY_PLIST}"
		--confirm "${CONFIRMATION}"
		--release-archive "${ARCHIVE_PATH}"
	)
else
	CONTROLLER_ARGUMENTS=(
		--home "${KARKINOS_HOME_PATH}"
		update
		--tag "${TAG}"
		--confirm "${CONFIRMATION}"
		--release-archive "${ARCHIVE_PATH}"
	)
fi
if ((SERVICE_PORT_SET == 1)); then
	CONTROLLER_ARGUMENTS+=(--service-port "${SERVICE_PORT}")
fi
if ((HEALTH_TIMEOUT_SET == 1)); then
	CONTROLLER_ARGUMENTS+=(--health-timeout "${HEALTH_TIMEOUT}")
fi
KARKINOS_HOME="${KARKINOS_HOME_PATH}" "${CONTROLLER}" "${CONTROLLER_ARGUMENTS[@]}"
