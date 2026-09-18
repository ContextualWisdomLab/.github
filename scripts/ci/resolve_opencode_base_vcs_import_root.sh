#!/usr/bin/env bash
# Resolve the single trusted Python import root for an immutable VCS checkout.
#
# Used by the OpenCode coverage tool image while materializing base VCS
# dependencies into opencode-base-vcs-dependencies.pth. The coverage builder
# already authenticated the repository, fetched an exact commit, and stripped
# .git; this helper only admits conventional source layouts and rejects
# ambiguous, namespaced, linked, compiled, or installed trees.
#
# Usage:
#   resolve_opencode_base_vcs_import_root.sh <destination> <import_name> <repository>
#
# On success, prints the python_root directory (parent that belongs on
# PYTHONPATH / .pth) to stdout. On failure, prints a diagnostic to stderr and
# exits non-zero with the same messages the trusted Dockerfile historically
# emitted for ContextualWisdomLab/.github#2157.
set -eu

destination=${1:?destination is required}
import_name=${2:?import_name is required}
repository=${3:?repository is required}

import_root=''
python_root=''
candidate_count=0
for candidate in \
  "$destination/python/$import_name" \
  "$destination/python/$import_name.py" \
  "$destination/src/$import_name" \
  "$destination/src/$import_name.py" \
  "$destination/$import_name" \
  "$destination/$import_name.py"; do
  if [ -e "$candidate" ] || [ -L "$candidate" ]; then
    import_root="$candidate"
    candidate_count=$((candidate_count + 1))
  fi
done
if [ "$candidate_count" -ne 1 ]; then
  printf 'locked VCS source %s has a missing or ambiguous import root for %s\n' \
    "$repository" "$import_name" >&2
  exit 1
fi
if [ -L "$import_root" ] \
  || { [ -d "$import_root" ] \
    && { [ ! -f "$import_root/__init__.py" ] \
      || [ -L "$import_root/__init__.py" ]; }; }; then
  printf 'locked VCS source %s has a namespace or linked import root for %s\n' \
    "$repository" "$import_name" >&2
  exit 1
fi
if find "$destination" -type l -print -quit | grep -q .; then
  printf 'locked VCS source %s contains a symbolic-link layout\n' \
    "$repository" >&2
  exit 1
fi
if find "$destination" -type f \
  \( -name '*.so' -o -name '*.pyd' -o -name '*.dll' -o -name '*.dylib' \) \
  -print -quit | grep -q .; then
  printf 'locked VCS source %s contains a compiled extension\n' \
    "$repository" >&2
  exit 1
fi
if find "$destination" -type d \
  \( -name '*.dist-info' -o -name '*.egg-info' \) \
  -print -quit | grep -q .; then
  printf 'locked VCS source %s contains installed distribution metadata\n' \
    "$repository" >&2
  exit 1
fi
case "$import_root" in
  "$destination/python/"*) python_root="$destination/python" ;;
  "$destination/src/"*) python_root="$destination/src" ;;
  *) python_root="$destination" ;;
esac
printf '%s\n' "$python_root"
