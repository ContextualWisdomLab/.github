#!/usr/bin/env bash
# Collect raw pre-publish dependency evidence for the central release gate (#2342).
#
# This script only *runs tools and writes their output verbatim*. Every decision
# — license policy, lock/environment reconciliation, archive-escape and
# install-hook detection, Strix binding validation — lives in the unit-tested
# scripts/ci/release_dependency_gate.py, which reads what this writes. Keeping
# the split that way means no untested shell ever decides whether a release may
# publish.
#
# It requires a runner: pip, cargo, readelf, and network access to the indexes.
# It is therefore exercised in GitHub Actions only; see
# .github/workflows/release-dependency-license-strix-gate.yml.
#
# Output layout (consumed by `release_dependency_gate.py capture` and `gate`):
#
#   <capture>/python/lock.txt          the hash-pinned lock that was collected
#   <capture>/python/installed.json    declared identity/licence per fetched
#                                      distribution, in `pip inspect` shape
#   <capture>/cargo/Cargo.lock         the committed Cargo lock
#   <capture>/cargo/metadata.json      cargo metadata --format-version 1 --locked
#   <raw>/<slug>/metadata.json         declared identity + license fields
#   <raw>/<slug>/source.sha256         sha256 of the distribution as fetched
#   <raw>/<slug>/members.txt           "<type>\t<name>\t<linkname>" per member
#   <raw>/<slug>/licenses/*            bundled LICENSE/COPYING/NOTICE verbatim
#   <raw>/<slug>/hooks/*               setup.py / build.rs sources verbatim
#   <raw>/<slug>/native.json           dynamic/static link targets per shipped .so
#   <raw>/<slug>/parsed_inputs.txt     file names the dependency parses

set -euo pipefail

RAW_ROOT=""
CAPTURE_ROOT=""
ECOSYSTEMS=""
PYTHON_LOCK=""
PYTHON_INTERPRETER=""
CARGO_MANIFEST=""
DOWNLOAD_ROOT=""
LICENSE_REPORT=""
MODE="capture"

while [ "$#" -gt 0 ]; do
	case "$1" in
	--raw-root) RAW_ROOT="$2"; shift 2 ;;
	--capture-root) CAPTURE_ROOT="$2"; shift 2 ;;
	--ecosystems) ECOSYSTEMS="$2"; shift 2 ;;
	--python-lock) PYTHON_LOCK="$2"; shift 2 ;;
	--python-interpreter) PYTHON_INTERPRETER="$2"; shift 2 ;;
	--cargo-manifest) CARGO_MANIFEST="$2"; shift 2 ;;
	--download-root) DOWNLOAD_ROOT="$2"; shift 2 ;;
	--license-report) LICENSE_REPORT="$2"; shift 2 ;;
	--install-gated) MODE="install"; shift ;;
	*) echo "ERROR: unknown argument $1" >&2; exit 2 ;;
	esac
done

if [ "$MODE" = "install" ]; then
	if [ -z "$PYTHON_LOCK" ] || [ ! -f "$PYTHON_LOCK" ] || [ -z "$DOWNLOAD_ROOT" ]; then
		echo "ERROR: --install-gated requires --python-lock and --download-root." >&2
		exit 2
	fi
	if [ -z "$LICENSE_REPORT" ] || [ -z "$CAPTURE_ROOT" ]; then
		echo "ERROR: --install-gated requires --license-report and --capture-root." >&2
		exit 2
	fi
else
	if [ -z "$RAW_ROOT" ] || [ -z "$CAPTURE_ROOT" ] || [ -z "$ECOSYSTEMS" ]; then
		echo "ERROR: --raw-root, --capture-root and --ecosystems are required." >&2
		exit 2
	fi
	mkdir -p "$RAW_ROOT" "$CAPTURE_ROOT"
fi

# The pip entry point is a variable only so the wiring can be regression-tested
# without a network: a test points RELEASE_GATE_PIP at a recorder and asserts
# which pip invocations happened, and in what order, for a refused release.
PIP=(python3 -m pip)
if [ -n "${RELEASE_GATE_PIP:-}" ]; then
	PIP=("${RELEASE_GATE_PIP}")
fi

# Resolved from this script's own directory, never from the caller's cwd or an
# environment variable, so the trusted gate cannot be swapped by a PR.
GATE_SCRIPT="$(cd -- "$(dirname -- "$0")" && pwd)/release_dependency_gate.py"

# pip's global --python re-executes pip against another interpreter, which is how
# the lock-only virtual environment is installed into by the gated install mode.
PIP_TARGET_ARGS=()
if [ -n "$PYTHON_INTERPRETER" ]; then
	# `python3 -m venv` uses symlinks by default on POSIX, so a normal virtual
	# environment's bin/python *is* a symlink; refusing symlinks outright rejected
	# every real venv and made this path unreachable. What must be refused is a
	# target that is not a regular executable file, or a dangling link, so the link
	# is resolved and the resolved target is checked.
	resolved_interpreter="$(cd -- "$(dirname -- "$PYTHON_INTERPRETER")" 2>/dev/null && pwd -P)/$(basename -- "$PYTHON_INTERPRETER")"
	while [ -L "$resolved_interpreter" ]; do
		link_target="$(readlink -- "$resolved_interpreter")"
		case "$link_target" in
		/*) resolved_interpreter="$link_target" ;;
		*) resolved_interpreter="$(dirname -- "$resolved_interpreter")/$link_target" ;;
		esac
	done
	if [ ! -f "$resolved_interpreter" ] || [ ! -x "$resolved_interpreter" ]; then
		echo "ERROR: --python-interpreter must resolve to a regular executable interpreter." >&2
		exit 2
	fi
	PIP_TARGET_ARGS=(--python "$PYTHON_INTERPRETER")
fi

# Record one archive's members as "<type>\t<name>\t<linkname>". Symlink and
# hardlink targets are preserved verbatim so the gate can detect escapes.
record_members() {
	local archive="$1" destination="$2"
	case "$archive" in
	*.whl | *.zip)
		unzip -Z1 "$archive" | while IFS= read -r member; do
			printf 'file\t%s\t\n' "$member"
		done
		;;
	*)
		tar -tvf "$archive" | while IFS= read -r line; do
			local permissions name link type
			permissions="${line%% *}"
			name="$(printf '%s' "$line" | sed -E 's/^.* [0-9]{2}:[0-9]{2} //')"
			link=""
			type="file"
			case "$permissions" in
			l*) type="symlink"; link="${name#* -> }"; name="${name%% -> *}" ;;
			h*) type="hardlink"; link="${name#* link to }"; name="${name%% link to *}" ;;
			d*) type="directory" ;;
			esac
			printf '%s\t%s\t%s\n' "$type" "$name" "$link"
		done
		;;
	esac >"$destination"
}

# Record every bundled license-like file verbatim, flattened into one directory.
record_license_files() {
	local root="$1" destination="$2"
	mkdir -p "$destination"
	find "$root" -maxdepth 4 -type f \
		\( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'NOTICE*' \) -print0 |
		while IFS= read -r -d '' found; do
			cp -- "$found" "$destination/$(printf '%s' "${found#"$root"/}" | tr '/' '_')"
		done
}

# Record install/build hook sources verbatim so the gate can inspect them.
record_hook_sources() {
	local root="$1" destination="$2"
	mkdir -p "$destination"
	find "$root" -maxdepth 3 -type f \
		\( -name 'setup.py' -o -name 'build.rs' -o -name 'conanfile.py' \) -print0 |
		while IFS= read -r -d '' found; do
			cp -- "$found" "$destination/$(printf '%s' "${found#"$root"/}" | tr '/' '_')"
		done
}

# Record dynamic NEEDED entries and shipped static archives for native libraries.
record_native_libraries() {
	local root="$1" destination="$2"
	local entries="[]"
	while IFS= read -r library; do
		local needed
		needed="$(readelf -d "$library" 2>/dev/null |
			sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' |
			jq -R . | jq -s .)"
		entries="$(jq --arg path "${library#"$root"/}" --argjson needed "${needed:-[]}" \
			'. + [{"path": $path, "needed": $needed, "static_archives": []}]' <<<"$entries")"
	done < <(find "$root" -type f \( -name '*.so' -o -name '*.so.*' -o -name '*.pyd' \))
	printf '%s\n' "$entries" >"$destination"
}

capture_python() {
	local lock="$1"
	mkdir -p "$CAPTURE_ROOT/python" "$DOWNLOAD_ROOT"
	cp -- "$lock" "$CAPTURE_ROOT/python/lock.txt"

	local plain_requirements
	plain_requirements="$DOWNLOAD_ROOT/pins-without-hashes.txt"
	# Fetch by exact pin with hash checking deliberately disabled, then hash the
	# bytes here and compare against the lock in the gate. Downloading *with*
	# --require-hashes would make pip itself reject a tampered distribution, so
	# the gate could never observe SOURCE_HASH_MISMATCH. The install of these same
	# bytes happens later, offline and *with* --require-hashes, in install_gated.
	sed -E 's/\\$//' "$lock" | grep -oE '^[A-Za-z0-9._-]+==[^ ;]+' \
		>"$plain_requirements"
	# The real lock may carry --index-url, --extra-index-url or --find-links,
	# while this reconstructed plain file has none of them. Dropping them silently
	# made collection resolve from a different source than install. The trusted
	# gate therefore parses and *validates* those directives — allowed HTTPS
	# origin, no userinfo, bounded relative path — and emits them one per line;
	# anything unsupported or untrusted fails here rather than being dropped.
	# mapfile keeps each value a single argv element, so no lock content is ever
	# word-split or re-interpreted by this shell. This runs before the first
	# network action, so a refused directive means nothing was ever fetched.
	local -a source_options=()
	if [ ! -f "$GATE_SCRIPT" ] || [ -L "$GATE_SCRIPT" ]; then
		echo "ERROR: trusted gate script is missing beside this script." >&2
		exit 2
	fi
	# Deliberately not `mapfile < <(python3 ...)`: inside process substitution the
	# validator's exit status is discarded by set -e, so a refusal would be read as
	# "no options" and collection would continue from the default index — the same
	# silent drop this fix exists to remove. The status is checked explicitly.
	local options_file="$DOWNLOAD_ROOT/validated-source-options.txt"
	if ! python3 -I "$GATE_SCRIPT" lock-source-options \
		--lock "$lock" --permitted-root "$(dirname -- "$lock")" >"$options_file"; then
		echo "ERROR: lock source directives failed validation; refusing to collect." >&2
		exit 2
	fi
	mapfile -t source_options <"$options_file"
	# --only-binary=:all: is not only a build-hook guard for the gate environment:
	# `pip download` executes an sdist's build backend to get its metadata even
	# with --no-deps, so a wheel-only collection is what keeps unadjudicated
	# dependency code from running before the licence stage.
	"${PIP[@]}" download --no-deps --only-binary=:all: \
		"${source_options[@]}" \
		--dest "$DOWNLOAD_ROOT" -r "$plain_requirements" >/dev/null

	# The enumeration and the licence fields both come from the *fetched
	# distributions*, never from `pip inspect` of an installed environment: the
	# closure is not installed yet at this point, and must not be until the
	# licence stage has passed. The file keeps the `pip inspect` shape the gate
	# already reconciles against the lock.
	local installed="$CAPTURE_ROOT/python/installed.json"
	printf '{"installed": []}\n' >"$installed"
	while IFS= read -r pin; do
		[ -n "$pin" ] || continue
		local name version slug target distribution extracted
		name="${pin%%==*}"
		version="${pin#*==}"
		slug="pypi__$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr '._' '--')__$version"
		target="$RAW_ROOT/$slug"
		mkdir -p "$target"
		distribution="$(find "$DOWNLOAD_ROOT" -maxdepth 1 -type f \
			-iname "$(printf '%s' "$name" | tr '.-' '__')-${version}*" | head -n 1)"
		if [ -z "$distribution" ]; then
			echo "ERROR: no fetched distribution for ${name}==${version}" >&2
			exit 2
		fi
		cp -- "$distribution" "$target/source.archive"
		sha256sum "$target/source.archive" | cut -d' ' -f1 >"$target/source.sha256"
		record_members "$distribution" "$target/members.txt"
		extracted="$(mktemp -d)"
		case "$distribution" in
		*.whl) unzip -qq -o "$distribution" -d "$extracted" ;;
		*) tar -xf "$distribution" -C "$extracted" ;;
		esac
		record_license_files "$extracted" "$target/licenses"
		record_hook_sources "$extracted" "$target/hooks"
		record_native_libraries "$extracted" "$target/native.json"
		find "$extracted" -maxdepth 3 -type f -name '*.py' -printf '%P\n' |
			LC_ALL=C sort >"$target/parsed_inputs.txt"
		printf '{}\n' >"$target/bundled_library_licenses.json"
		# Licence metadata is read out of the distribution's own METADATA/PKG-INFO
		# by the trusted gate, which also re-checks that the archive declares the
		# pinned name and version. A file whose metadata names another project
		# fails here instead of being adjudicated under the wrong identity.
		python3 -I "$GATE_SCRIPT" distribution-metadata \
			--distribution "$distribution" --name "$name" --version "$version" \
			>"$target/metadata.json"
		jq --slurpfile declared "$target/metadata.json" \
			'.installed += [{"metadata": $declared[0]}]' "$installed" \
			>"$installed.next"
		mv -- "$installed.next" "$installed"
		rm -rf "${extracted:?}"
	done <"$plain_requirements"
}

# Install exactly the distributions the licence stage already judged: offline,
# from the collected bytes, with --require-hashes so pip itself proves each file
# matches the lock. No index is consulted and nothing is re-resolved or
# re-downloaded, so the installed bytes are the inspected bytes by construction —
# which a second hash-less download could not establish for a multi-hash lock.
install_gated() {
	local lock="$1"
	if [ -z "$LICENSE_REPORT" ]; then
		echo "ERROR: --install-gated requires --license-report." >&2
		exit 2
	fi
	if [ ! -f "$GATE_SCRIPT" ] || [ -L "$GATE_SCRIPT" ]; then
		echo "ERROR: trusted gate script is missing beside this script." >&2
		exit 2
	fi
	if [ ! -d "$DOWNLOAD_ROOT" ]; then
		echo "ERROR: no collected distributions to install from: $DOWNLOAD_ROOT" >&2
		exit 2
	fi
	if [ -z "$CAPTURE_ROOT" ]; then
		echo "ERROR: --install-gated requires --capture-root to bind the judged lock." >&2
		exit 2
	fi
	# The report alone is not permission: bind-install refuses unless the lock still
	# digests to what the verdict read, every judged artifact is present in the
	# collected root by digest, and the root holds nothing else. It then pins each
	# project to the single judged digest, so a lock recording several hashes for one
	# project cannot admit an artifact whose licence and contents were never judged.
	local bound_requirements="$DOWNLOAD_ROOT/gated-requirements.txt"
	if ! python3 -I "$GATE_SCRIPT" bind-install \
		--report "$LICENSE_REPORT" \
		--capture "$CAPTURE_ROOT" \
		--download-root "$DOWNLOAD_ROOT" \
		--output "$bound_requirements" >/dev/null; then
		echo "ERROR: the licence verdict does not authorize installing these bytes." >&2
		exit 2
	fi
	"${PIP[@]}" "${PIP_TARGET_ARGS[@]}" install \
		--require-hashes --only-binary=:all: --no-index \
		--find-links "$DOWNLOAD_ROOT" \
		-r "$bound_requirements"
}

capture_cargo() {
	local manifest="$1" manifest_dir
	manifest_dir="$(dirname -- "$manifest")"
	mkdir -p "$CAPTURE_ROOT/cargo"
	cp -- "$manifest_dir/Cargo.lock" "$CAPTURE_ROOT/cargo/Cargo.lock"
	cargo metadata --format-version 1 --locked --manifest-path "$manifest" \
		>"$CAPTURE_ROOT/cargo/metadata.json"
	cargo fetch --locked --manifest-path "$manifest" >/dev/null

	while IFS=$'\t' read -r name version license; do
			local slug target crate extracted
			slug="cargo__${name}__${version}"
			target="$RAW_ROOT/$slug"
			mkdir -p "$target"
			crate="$(find "${CARGO_HOME:-$HOME/.cargo}/registry/cache" -type f \
				-name "${name}-${version}.crate" | head -n 1)"
			if [ -z "$crate" ]; then
				echo "ERROR: no fetched crate for ${name} ${version}" >&2
				exit 2
			fi
			cp -- "$crate" "$target/source.archive"
			sha256sum "$target/source.archive" | cut -d' ' -f1 >"$target/source.sha256"
			record_members "$crate" "$target/members.txt"
			extracted="$(mktemp -d)"
			tar -xf "$crate" -C "$extracted"
			record_license_files "$extracted" "$target/licenses"
			record_hook_sources "$extracted" "$target/hooks"
			printf '[]\n' >"$target/native.json"
			printf '{}\n' >"$target/bundled_library_licenses.json"
			find "$extracted" -maxdepth 3 -type f -name '*.rs' -printf '%P\n' |
				LC_ALL=C sort >"$target/parsed_inputs.txt"
			jq -n --arg name "$name" --arg version "$version" --arg license "$license" '{
				ecosystem: "cargo",
				name: $name,
				version: $version,
				license_expression: $license,
				license: "",
				classifiers: [],
				distribution_inclusion: ["wheel"],
				known_vulnerabilities: []
			}' >"$target/metadata.json"
			rm -rf "${extracted:?}"
	done < <(jq -r '.packages[] | select(.source != null) | [.name, .version, (.license // "")] | @tsv' \
		"$CAPTURE_ROOT/cargo/metadata.json")
}

if [ "$MODE" = "install" ]; then
	install_gated "$PYTHON_LOCK"
	echo "Installed the prescreened release closure from collected bytes."
	exit 0
fi

case ",${ECOSYSTEMS}," in
*,python,*)
	if [ -z "$PYTHON_LOCK" ] || [ ! -f "$PYTHON_LOCK" ]; then
		echo "ERROR: --python-lock must name the hash-pinned release lock." >&2
		exit 2
	fi
	if [ -z "$DOWNLOAD_ROOT" ]; then
		echo "ERROR: --download-root is required so the gated install reuses these bytes." >&2
		exit 2
	fi
	capture_python "$PYTHON_LOCK"
	;;
esac

case ",${ECOSYSTEMS}," in
*,cargo,*)
	if [ -z "$CARGO_MANIFEST" ] || [ ! -f "$CARGO_MANIFEST" ]; then
		echo "ERROR: --cargo-manifest must name the release Cargo.toml." >&2
		exit 2
	fi
	capture_cargo "$CARGO_MANIFEST"
	;;
esac

echo "Raw dependency capture complete: $(find "$RAW_ROOT" -mindepth 1 -maxdepth 1 -type d | wc -l) dependencies."
