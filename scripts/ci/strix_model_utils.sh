#!/usr/bin/env bash
# Helper functions shared by the Strix CI gate and its self-test harness.
# Keep this dependency explicit so PR-scoped Strix scans include the full gate harness.

trim_whitespace() {
	local value="${1-}"
	# Collapse only the leading/trailing shell whitespace that can be introduced by
	# secret files or workflow inputs. Internal spacing remains meaningful for the
	# few callers that parse lists after trimming each token.
	value="${value#"${value%%[!$' \t\r\n']*}"}"
	value="${value%"${value##*[!$' \t\r\n']}"}"
	printf '%s\n' "$value"
}

sanitize_strix_source_dirs() {
	local raw_source_dirs
	raw_source_dirs="$(trim_whitespace "${1-}")"
	if [ -z "$raw_source_dirs" ]; then
		echo "ERROR: STRIX_SOURCE_DIRS must contain at least one safe direct directory name." >&2
		return 2
	fi

	python3 -I -S - "$raw_source_dirs" <<'PY'
from __future__ import annotations

import sys
import unicodedata

raw_source_dirs = sys.argv[1]
if len(raw_source_dirs.encode("utf-8")) > 8192 or any(
    character in "\x00\r\n\t" for character in raw_source_dirs
):
    print(
        "ERROR: STRIX_SOURCE_DIRS must be a bounded space-separated directory list.",
        file=sys.stderr,
    )
    raise SystemExit(2)
entries = raw_source_dirs.split(" ")
entries = [entry for entry in entries if entry]
if not entries or len(entries) > 32:
    print(
        "ERROR: STRIX_SOURCE_DIRS must contain between 1 and 32 safe direct directory names.",
        file=sys.stderr,
    )
    raise SystemExit(2)

allowed_ascii = frozenset("_.@+[]-")
normalized: list[str] = []
seen: set[str] = set()
for entry in entries:
    if entry == ".":
        pass
    elif (
        entry == ".."
        or len(entry.encode("utf-8")) > 255
        or entry.startswith("-")
        or "/" in entry
        or "\\" in entry
        or not all(
            (character.isascii() and (character.isalnum() or character in allowed_ascii))
            or (
                not character.isascii()
                and unicodedata.category(character)[0] in {"L", "M", "N"}
            )
            for character in entry
        )
    ):
        print(
            "ERROR: STRIX_SOURCE_DIRS accepts only '.' or safe direct directory names.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if entry not in seen:
        seen.add(entry)
        normalized.append(entry)

print(" ".join(normalized))
PY
}

# STRIX_SOURCE_DIRS is later split by the gate before joining each token to the
# already-canonical scan root. Freeze a lexical direct-child allowlist at source
# time so absolute paths, parent traversal, nested symlink chains, shell glob expansion,
# and option-like path ambiguity can never reach that join.
STRIX_SOURCE_DIRS_SANITIZED="$(
	sanitize_strix_source_dirs "${STRIX_SOURCE_DIRS-.}"
)" || {
	status=$?
	return "$status" 2>/dev/null || exit "$status"
}
readonly STRIX_SOURCE_DIRS="$STRIX_SOURCE_DIRS_SANITIZED"
unset STRIX_SOURCE_DIRS_SANITIZED

sanitize_provider_name() {
	local provider
	provider="$(trim_whitespace "${1-}")"
	if [ -z "$provider" ]; then
		return 1
	fi
	if [[ ! "$provider" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then
		echo "ERROR: STRIX_LLM_DEFAULT_PROVIDER contains unsupported characters: '$provider'." >&2
		return 2
	fi
	printf '%s\n' "$provider"
}

is_vertex_resource_path() {
	local path
	path="$(trim_whitespace "${1-}")"
	if [ -z "$path" ] || [[ "$path" =~ [[:space:][:cntrl:]] ]]; then
		return 1
	fi

	IFS='/' read -r -a parts <<<"$path"
	local part
	for part in "${parts[@]}"; do
		if [ -z "$part" ] || [ "$part" = "." ] || [ "$part" = ".." ] ||
			[[ ! "$part" =~ ^[A-Za-z0-9._-]+$ ]]; then
			return 1
		fi
	done

	case "${#parts[@]}" in
	2)
		[ "${parts[0]}" = "models" ]
		;;
	4)
		[ "${parts[0]}" = "publishers" ] && [ "${parts[2]}" = "models" ]
		;;
	6)
		[ "${parts[0]}" = "projects" ] && [ "${parts[2]}" = "locations" ] && [ "${parts[4]}" = "models" ]
		;;
	8)
		[ "${parts[0]}" = "projects" ] && [ "${parts[2]}" = "locations" ] && [ "${parts[4]}" = "publishers" ] && [ "${parts[6]}" = "models" ]
		;;
	*)
		return 1
		;;
	esac
}

extract_vertex_model_id() {
	local model
	model="$(trim_whitespace "${1-}")"
	if is_vertex_resource_path "$model"; then
		printf '%s\n' "${model##*/}"
	else
		printf '%s\n' "$model"
	fi
}

normalize_model() {
	local model
	model="$(trim_whitespace "${1-}")"
	if [ -z "$model" ]; then
		return 0
	fi

	if is_vertex_resource_path "$model"; then
		local provider
		provider="$(sanitize_provider_name "${DEFAULT_PROVIDER:-}")" || {
			echo "ERROR: Vertex resource paths require an explicit vertex_ai or vertex_ai_beta provider." >&2
			return 2
		}
		case "$provider" in
		vertex_ai | vertex_ai_beta) ;;
		*)
			echo "ERROR: Vertex resource paths require an explicit vertex_ai or vertex_ai_beta provider." >&2
			return 2
			;;
		esac
		printf '%s/%s\n' "$provider" "$(extract_vertex_model_id "$model")"
		return 0
	fi

	local provider="${DEFAULT_PROVIDER:-}"
	if [ -z "$provider" ]; then
		provider="vertex_ai"
	fi
	provider="$(sanitize_provider_name "$provider")" || return $?

	case "$model" in
	projects/* | models/* | publishers/*)
		printf '%s\n' "$model"
		return 0
		;;
	*/*)
		printf '%s\n' "$model"
		return 0
		;;
	*)
		printf '%s/%s\n' "$provider" "$model"
		return 0
		;;
	esac
}

model_requires_vertex_auth() {
	local model normalized_model
	model="$(trim_whitespace "${1-}")"
	if [ -z "$model" ]; then
		return 1
	fi

	normalized_model="$(normalize_model "$model")" || return $?
	case "$normalized_model" in
	vertex_ai/* | vertex_ai_beta/*)
		return 0
		;;
	*)
		return 1
		;;
	esac
}
