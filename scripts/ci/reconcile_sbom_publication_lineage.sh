#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 PREVIOUS_HEAD GENERATED_INVENTORY_HEAD" >&2
  exit 64
fi

previous_head="$1"
generated_inventory_head="$2"
inventory_paths=(
  docs/sbom/inventory.json
  docs/sbom/inventory.md
)

if [ "$(git rev-parse HEAD)" != "$generated_inventory_head" ]; then
  echo "generated inventory head is not the checked-out head" >&2
  exit 1
fi

git cat-file -e "${previous_head}^{commit}"
git cat-file -e "${generated_inventory_head}^{commit}"

unexpected_worktree_status="$(
  git status --porcelain=v1 --untracked-files=all -- \
    . \
    ':(exclude)docs/sbom/inventory.json' \
    ':(exclude)docs/sbom/inventory.md'
)"
if [ -n "$unexpected_worktree_status" ]; then
  echo "working tree contains non-inventory change:" >&2
  echo "$unexpected_worktree_status" >&2
  exit 1
fi

generated_inventory_parent="$(git rev-parse "${generated_inventory_head}^")"
mapfile -d '' -t generated_change_paths < <(
  git diff --name-only -z "$generated_inventory_parent" "$generated_inventory_head"
)

for generated_change_path in "${generated_change_paths[@]}"; do
  case "$generated_change_path" in
    docs/sbom/inventory.json|docs/sbom/inventory.md) ;;
    *)
      echo "generated inventory head contains non-inventory change: $generated_change_path" >&2
      exit 1
      ;;
  esac
done

if git merge-base --is-ancestor "$previous_head" HEAD; then
  exit 0
fi

lineage_base="$(git merge-base "$previous_head" "$generated_inventory_head")"
mapfile -d '' -t prior_change_paths < <(
  git diff --name-only -z "$lineage_base" "$previous_head"
)

for prior_change_path in "${prior_change_paths[@]}"; do
  case "$prior_change_path" in
    docs/sbom/inventory.json|docs/sbom/inventory.md) ;;
    *)
      echo "prior publication head contains non-inventory change: $prior_change_path" >&2
      exit 1
      ;;
  esac
done

merge_completed=true
if ! git merge \
  --no-commit \
  --no-ff \
  "$previous_head"; then
  merge_completed=false
fi

mapfile -d '' -t conflict_paths < <(
  git diff --name-only --diff-filter=U -z
)

if [ "$merge_completed" = false ] && [ "${#conflict_paths[@]}" -eq 0 ]; then
  git merge --abort || true
  echo "publication lineage merge failed without resolvable inventory conflicts" >&2
  exit 1
fi

for conflict_path in "${conflict_paths[@]}"; do
  case "$conflict_path" in
    docs/sbom/inventory.json|docs/sbom/inventory.md) ;;
    *)
      git merge --abort || true
      echo "non-inventory conflict: $conflict_path" >&2
      exit 1
      ;;
  esac
done

git restore \
  --source="$generated_inventory_head" \
  --staged \
  --worktree \
  -- \
  "${inventory_paths[@]}"

if [ -n "$(git diff --name-only --diff-filter=U)" ]; then
  git merge --abort || true
  echo "publication lineage merge retained unresolved conflicts" >&2
  exit 1
fi

git diff --check
git commit -m "chore: preserve SBOM inventory publication lineage"
