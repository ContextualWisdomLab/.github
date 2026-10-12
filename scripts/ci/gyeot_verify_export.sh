#!/usr/bin/env bash
# Verify production JS/asset bundles, not native signing or device behavior.
set -euo pipefail
helper_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${1:?Pass the admitted product checkout root}" && pwd)"
cd "$repository_root"
export CI=1 EXPO_NO_DOTENV=1
export_root="$(mktemp -d "${RUNNER_TEMP:?Provision a private runner temporary directory}/gyeot_export.XXXXXX")"
trap 'rm -rf "$export_root"' EXIT
for target_platform in android ios; do
  ./node_modules/.bin/expo export --platform "$target_platform" --output-dir "$export_root/$target_platform"
  node "$helper_directory/gyeot_check_export.cjs" "$export_root/$target_platform" "$target_platform" "$export_root"
done
