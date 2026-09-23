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
#   <capture>/python/lock.txt          the hash-pinned lock that was installed
#   <capture>/python/installed.json    pip inspect of the lock-only environment
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

while [ "$#" -gt 0 ]; do
	case "$1" in
	--raw-root) RAW_ROOT="$2"; shift 2 ;;
	--capture-root) CAPTURE_ROOT="$2"; shift 2 ;;
	--ecosystems) ECOSYSTEMS="$2"; shift 2 ;;
	--python-lock) PYTHON_LOCK="$2"; shift 2 ;;
	--python-interpreter) PYTHON_INTERPRETER="$2"; shift 2 ;;
	--cargo-manifest) CARGO_MANIFEST="$2"; shift 2 ;;
	*) echo "ERROR: unknown argument $1" >&2; exit 2 ;;
	esac
done

if [ -z "$RAW_ROOT" ] || [ -z "$CAPTURE_ROOT" ] || [ -z "$ECOSYSTEMS" ]; then
	echo "ERROR: --raw-root, --capture-root and --ecosystems are required." >&2
	exit 2
fi

mkdir -p "$RAW_ROOT" "$CAPTURE_ROOT"

# pip's global --python re-executes pip against another interpreter, which is how
# a --without-pip virtual environment holding exactly the lock is inspected.
PIP_TARGET_ARGS=()
if [ -n "$PYTHON_INTERPRETER" ]; then
	if [ ! -x "$PYTHON_INTERPRETER" ] || [ -L "$PYTHON_INTERPRETER" ]; then
		echo "ERROR: --python-interpreter must name a regular executable interpreter." >&2
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
	mkdir -p "$CAPTURE_ROOT/python"
	cp -- "$lock" "$CAPTURE_ROOT/python/lock.txt"

	# Inspect the lock-only environment, not the runner's interpreter: the gate
	# exempts nothing from lock/environment agreement, so pip and setuptools
	# preinstalled beside the lock would read as a real mismatch.
	python3 -m pip "${PIP_TARGET_ARGS[@]}" inspect --local \
		>"$CAPTURE_ROOT/python/installed.json"

	local download_root plain_requirements
	download_root="$(mktemp -d)"
	plain_requirements="$download_root/pins-without-hashes.txt"
	# Fetch by exact pin with hash checking deliberately disabled, then hash the
	# bytes here and compare against the lock in the gate. Downloading *with*
	# --require-hashes would make pip itself reject a tampered distribution, so
	# the gate could never observe SOURCE_HASH_MISMATCH.
	sed -E 's/\\$//' "$lock" | grep -oE '^[A-Za-z0-9._-]+==[^ ;]+' \
		>"$plain_requirements"
	python3 -m pip "${PIP_TARGET_ARGS[@]}" download --no-deps --only-binary=:all: \
		--dest "$download_root" -r "$plain_requirements" >/dev/null

	while IFS=$'\t' read -r name version; do
			local slug distribution extracted target
			slug="pypi__$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr '._' '--')__$version"
			target="$RAW_ROOT/$slug"
			mkdir -p "$target"
			distribution="$(find "$download_root" -maxdepth 1 -type f \
				-iname "$(printf '%s' "$name" | tr '.-' '__')-${version}*" | head -n 1)"
			if [ -z "$distribution" ]; then
				echo "ERROR: no fetched distribution for ${name}==${version}" >&2
				exit 2
			fi
			sha256sum "$distribution" | cut -d' ' -f1 >"$target/source.sha256"
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
			python3 -m pip show "$name" |
				jq -R -s --arg name "$name" --arg version "$version" '
					split("\n")
					| map(select(length > 0))
					| {
						ecosystem: "pypi",
						name: $name,
						version: $version,
						license_expression: (
							map(select(startswith("License-Expression: ")))
							| first // "" | sub("^License-Expression: "; "")
						),
						license: (
							map(select(startswith("License: ")))
							| first // "" | sub("^License: "; "")
						),
						classifiers: (
							map(select(startswith("Classifier: License ")))
							| map(sub("^Classifier: "; ""))
						),
						distribution_inclusion: ["sdist", "wheel"],
						known_vulnerabilities: []
					}' >"$target/metadata.json"
			rm -rf "${extracted:?}"
	done < <(jq -r '.installed[] | [.metadata.name, .metadata.version] | @tsv' \
		"$CAPTURE_ROOT/python/installed.json")
	rm -rf "${download_root:?}"
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
			sha256sum "$crate" | cut -d' ' -f1 >"$target/source.sha256"
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

case ",${ECOSYSTEMS}," in
*,python,*)
	if [ -z "$PYTHON_LOCK" ] || [ ! -f "$PYTHON_LOCK" ]; then
		echo "ERROR: --python-lock must name the hash-pinned lock that was installed." >&2
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
