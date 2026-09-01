#!/usr/bin/env bash
set -euo pipefail

SUPERPOWERS_SHA="b36e0829c6d0140e93cfef2ca599b1b07d4a7797"
PONYTAIL_SHA="2ed6c52c9d7e5e56942508591085fd45dea277d3"
CODE_REVIEW_GRAPH_SHA="b58668751ab0c7670c078cf7cbd4d1f5b8e54f81"
UI_UX_PRO_MAX_SHA="f23267105ad1f4ccd94af45d382584ad45b586f7"
ANTI_SLOP_UI_SHA="ef9d06e9da3a7a902f89456b3a4c5c2601870eea"
CODEGRAPH_TRACKED_HEAD="b9ca4b7981116909900368cc1686a1074cd4d4c1"
CODEGRAPH_INSTALLED_VERSION="1.4.1"

TARGET_INPUT="${CWL_TOOLCHAIN_TARGET:-.}"
RUNTIME="${CWL_TOOLCHAIN_RUNTIME:?CWL_TOOLCHAIN_RUNTIME is required}"
CONFIG_INPUT="${CWL_TOOLCHAIN_OPENCODE_CONFIG:-}"

fail() {
  printf 'development-agent-toolchain: %s\n' "$*" >&2
  exit 1
}

TARGET="$(realpath "$TARGET_INPUT")"
[ -d "$TARGET" ] || fail "target workspace is not a directory: $TARGET"
GIT_ROOT="$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$GIT_ROOT" ] || fail "target workspace is not a git worktree"
GIT_ROOT="$(realpath "$GIT_ROOT")"
[ "$GIT_ROOT" = "$TARGET" ] || fail "target must be the exact git worktree root: $GIT_ROOT"

CENTRAL_ROOT="$(realpath "$GITHUB_ACTION_PATH/../../..")"
rm -rf "$RUNTIME"
mkdir -p "$RUNTIME/sources" "$RUNTIME/home" "$RUNTIME/packages"

EXCLUDE_FILE="$(git -C "$TARGET" rev-parse --git-path info/exclude)"
mkdir -p "$(dirname "$EXCLUDE_FILE")"
touch "$EXCLUDE_FILE"
for pattern in ".opencode/skills/" ".code-review-graph/" ".codegraph/"; do
  if ! grep -F -x "$pattern" "$EXCLUDE_FILE" >/dev/null 2>&1; then
    printf '%s\n' "$pattern" >> "$EXCLUDE_FILE"
  fi
done

for managed_dir in ".code-review-graph" ".codegraph"; do
  tracked="$(git -C "$TARGET" ls-files "$managed_dir" "$managed_dir/**")"
  [ -z "$tracked" ] || fail "$managed_dir contains tracked product files and cannot be used as a runtime index"
  rm -rf "$TARGET/$managed_dir"
done

SKILL_ROOT="$TARGET/.opencode/skills"
MARKER="$SKILL_ROOT/.cwl-development-agent-toolchain"
mkdir -p "$SKILL_ROOT"

if [ -f "$MARKER" ]; then
  while IFS= read -r old_skill; do
    [ -n "$old_skill" ] || continue
    case "$old_skill" in
      */*|..|.) fail "invalid prior runtime skill marker entry: $old_skill" ;;
    esac
    rm -rf "$SKILL_ROOT/$old_skill"
  done < "$MARKER"
  rm -f "$MARKER"
fi

INSTALLED_SKILLS=()
register_skill() {
  local name="$1"
  INSTALLED_SKILLS+=("$name")
}

assert_skill_destination_free() {
  local name="$1"
  local destination="$SKILL_ROOT/$name"
  [ ! -e "$destination" ] || fail "runtime skill destination already exists: $destination"
}

fetch_public_commit() {
  local repository="$1"
  local commit="$2"
  local destination="$3"
  local actual

  rm -rf "$destination"
  git init -q "$destination"
  git -C "$destination" remote add origin "https://github.com/$repository.git"
  env -u GITHUB_TOKEN -u GH_TOKEN GIT_TERMINAL_PROMPT=0 \
    git -C "$destination" \
      -c credential.helper= \
      -c http.https://github.com/.extraheader= \
      fetch --no-tags --depth=1 origin "$commit"
  git -C "$destination" checkout --detach --quiet FETCH_HEAD
  actual="$(git -C "$destination" rev-parse HEAD)"
  [ "$actual" = "$commit" ] || fail "$repository resolved to $actual instead of $commit"
}

copy_skill_tree() {
  local source_root="$1"
  local source_dir name destination

  [ -d "$source_root" ] || fail "missing upstream skill root: $source_root"
  while IFS= read -r -d '' source_dir; do
    [ -f "$source_dir/SKILL.md" ] || continue
    name="$(basename "$source_dir")"
    assert_skill_destination_free "$name"
    destination="$SKILL_ROOT/$name"
    cp -R "$source_dir" "$destination"
    register_skill "$name"
  done < <(find "$source_root" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
}

SUPERPOWERS_SRC="$RUNTIME/sources/superpowers"
fetch_public_commit "obra/superpowers" "$SUPERPOWERS_SHA" "$SUPERPOWERS_SRC"
copy_skill_tree "$SUPERPOWERS_SRC/skills"

PONYTAIL_SRC="$RUNTIME/sources/ponytail"
fetch_public_commit "DietrichGebert/ponytail" "$PONYTAIL_SHA" "$PONYTAIL_SRC"
copy_skill_tree "$PONYTAIL_SRC/skills"

# ContextualWisdomLab explicitly runs scheduled product development without
# interactive approval checkpoints when the governing user/scheduler directive
# says to proceed autonomously. This runtime-only policy overrides imported
# interactive checkpoints, but never branch protection, independent reviews,
# required checks, or other security gates.
assert_skill_destination_free "cwl-autonomous-development"
mkdir -p "$SKILL_ROOT/cwl-autonomous-development"
cat > "$SKILL_ROOT/cwl-autonomous-development/SKILL.md" <<'EOF'
---
name: cwl-autonomous-development
description: ContextualWisdomLab precedence rules for scheduled autonomous product development.
---

# ContextualWisdomLab autonomous development precedence

When the governing user or scheduler instruction explicitly requires autonomous
execution without questions or intermediate approval, do not stop at interactive
checkpoints imported from another skill. Resolve ambiguity from repository state,
PRD/ADR/architecture evidence, current reviews, checks, tests, and authoritative
sources, then continue with the safest evidence-backed action.

This precedence does not bypass branch protection, independent review, required
checks, credential boundaries, or destructive-operation safeguards.
EOF
register_skill "cwl-autonomous-development"

UIUX_SRC="$RUNTIME/sources/ui-ux-pro-max-skill"
fetch_public_commit "nextlevelbuilder/ui-ux-pro-max-skill" "$UI_UX_PRO_MAX_SHA" "$UIUX_SRC"
assert_skill_destination_free "ui-ux-pro-max"
(
  cd "$UIUX_SRC/cli"
  npm ci --ignore-scripts --no-audit --no-fund
  npm run build --if-present
)
(
  cd "$TARGET"
  node "$UIUX_SRC/cli/dist/index.js" init --ai opencode --offline --force
)
[ -f "$SKILL_ROOT/ui-ux-pro-max/SKILL.md" ] || fail "UI/UX Pro Max did not materialize its OpenCode skill"
register_skill "ui-ux-pro-max"

ANTI_SLOP_SRC="$RUNTIME/sources/Anti-Slop-UI"
fetch_public_commit "local-over/Anti-Slop-UI" "$ANTI_SLOP_UI_SHA" "$ANTI_SLOP_SRC"
assert_skill_destination_free "anti-slop-ui"
mkdir -p "$SKILL_ROOT/anti-slop-ui/Anti-Slop-UI"
cp "$ANTI_SLOP_SRC/public-skills/SKILL.md" "$SKILL_ROOT/anti-slop-ui/SKILL.md"
cp -R "$ANTI_SLOP_SRC/skills" "$SKILL_ROOT/anti-slop-ui/Anti-Slop-UI/skills"
register_skill "anti-slop-ui"

printf '%s\n' "${INSTALLED_SKILLS[@]}" > "$MARKER"

CRG_SRC="$RUNTIME/sources/code-review-graph"
fetch_public_commit "tirth8205/code-review-graph" "$CODE_REVIEW_GRAPH_SHA" "$CRG_SRC"
(
  cd "$CRG_SRC"
  uv sync --locked --no-dev
)
CRG_BIN="$CRG_SRC/.venv/bin/code-review-graph"
[ -x "$CRG_BIN" ] || fail "code-review-graph executable was not created"
CRG_HOME="$RUNTIME/home/code-review-graph"
mkdir -p "$CRG_HOME"
(
  cd "$TARGET"
  env -i \
    HOME="$CRG_HOME" \
    PATH="$CRG_SRC/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONUTF8=1 \
    PYTHONNOUSERSITE=1 \
    "$CRG_BIN" build
)
[ -f "$TARGET/.code-review-graph/graph.db" ] || fail "code-review-graph index was not created"
# Runtime MCP command: code-review-graph serve --repo <target>

CODEGRAPH_LOCK_ROOT="$CENTRAL_ROOT/scripts/ci/codegraph-package"
[ -f "$CODEGRAPH_LOCK_ROOT/package.json" ] || fail "missing central CodeGraph package manifest"
[ -f "$CODEGRAPH_LOCK_ROOT/package-lock.json" ] || fail "missing central CodeGraph package lock"
CODEGRAPH_PACKAGE_ROOT="$RUNTIME/packages/codegraph"
mkdir -p "$CODEGRAPH_PACKAGE_ROOT"
cp "$CODEGRAPH_LOCK_ROOT/package.json" "$CODEGRAPH_PACKAGE_ROOT/package.json"
cp "$CODEGRAPH_LOCK_ROOT/package-lock.json" "$CODEGRAPH_PACKAGE_ROOT/package-lock.json"
node - "$CODEGRAPH_PACKAGE_ROOT/package.json" "$CODEGRAPH_INSTALLED_VERSION" <<'NODE'
const fs = require('fs');
const [manifestPath, expected] = process.argv.slice(2);
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
if (manifest.dependencies?.['@colbymchenry/codegraph'] !== expected) {
  throw new Error(`central CodeGraph lock must pin @colbymchenry/codegraph exactly to ${expected}`);
}
NODE
(
  cd "$CODEGRAPH_PACKAGE_ROOT"
  npm ci --ignore-scripts --omit=dev --no-audit --no-fund
)
CODEGRAPH_BIN="$CODEGRAPH_PACKAGE_ROOT/node_modules/.bin/codegraph"
[ -x "$CODEGRAPH_BIN" ] || fail "CodeGraph executable was not created"
[ "$("$CODEGRAPH_BIN" --version)" = "$CODEGRAPH_INSTALLED_VERSION" ] || fail "unexpected CodeGraph version"
CODEGRAPH_HOME="$RUNTIME/home/codegraph"
mkdir -p "$CODEGRAPH_HOME"
(
  cd "$TARGET"
  env -i \
    HOME="$CODEGRAPH_HOME" \
    PATH="$CODEGRAPH_PACKAGE_ROOT/node_modules/.bin:/usr/local/bin:/usr/bin:/bin" \
    CI=1 \
    DO_NOT_TRACK=1 \
    CODEGRAPH_TELEMETRY=0 \
    CODEGRAPH_NO_DOWNLOAD=1 \
    CODEGRAPH_NO_DAEMON=1 \
    CODEGRAPH_TRUSTED_ROOT="$TARGET" \
    "$CODEGRAPH_BIN" init -i
)
[ -d "$TARGET/.codegraph" ] || fail "CodeGraph index was not created"
# Runtime MCP command: codegraph serve --mcp

MCP_SNIPPET="$RUNTIME/opencode-mcp.json"
export TARGET CRG_BIN CRG_HOME CRG_SRC CODEGRAPH_BIN CODEGRAPH_HOME CODEGRAPH_PACKAGE_ROOT MCP_SNIPPET
node <<'NODE'
const fs = require('fs');
const path = require('path');
const target = process.env.TARGET;
const crgBin = process.env.CRG_BIN;
const crgHome = process.env.CRG_HOME;
const crgPath = `${path.dirname(crgBin)}:/usr/local/bin:/usr/bin:/bin`;
const codegraphBin = process.env.CODEGRAPH_BIN;
const codegraphHome = process.env.CODEGRAPH_HOME;
const codegraphPath = `${path.dirname(codegraphBin)}:/usr/local/bin:/usr/bin:/bin`;
const entries = {
  'code-review-graph': {
    type: 'local',
    command: [
      'env', '-i',
      `HOME=${crgHome}`,
      `PATH=${crgPath}`,
      'PYTHONUTF8=1',
      'PYTHONNOUSERSITE=1',
      crgBin, 'serve', '--repo', target,
    ],
    enabled: true,
  },
  codegraph: {
    type: 'local',
    command: [
      'env', '-i',
      `HOME=${codegraphHome}`,
      `PATH=${codegraphPath}`,
      'CI=1',
      'DO_NOT_TRACK=1',
      'CODEGRAPH_TELEMETRY=0',
      'CODEGRAPH_NO_DOWNLOAD=1',
      'CODEGRAPH_NO_DAEMON=1',
      `CODEGRAPH_TRUSTED_ROOT=${target}`,
      '/bin/bash', '-c', 'cd "$1" && exec "$2" serve --mcp',
      'codegraph-mcp', target, codegraphBin,
    ],
    enabled: true,
  },
};
fs.writeFileSync(process.env.MCP_SNIPPET, `${JSON.stringify({ mcp: entries }, null, 2)}\n`, { mode: 0o600 });
NODE

if [ -n "$CONFIG_INPUT" ]; then
  CONFIG_PATH="$(realpath "$CONFIG_INPUT")"
  [ -f "$CONFIG_PATH" ] || fail "OpenCode config does not exist: $CONFIG_PATH"
  case "$CONFIG_PATH" in
    "$TARGET"/*)
      relative_config="${CONFIG_PATH#"$TARGET"/}"
      if git -C "$TARGET" ls-files --error-unmatch "$relative_config" >/dev/null 2>&1; then
        fail "refusing to mutate checked-in OpenCode config: $relative_config"
      fi
      ;;
  esac
  node - "$CONFIG_PATH" "$MCP_SNIPPET" <<'NODE'
const fs = require('fs');
const [configPath, snippetPath] = process.argv.slice(2);
const text = fs.readFileSync(configPath, 'utf8');
let config;
try {
  config = JSON.parse(text);
} catch (error) {
  throw new Error(`runtime OpenCode config must be strict JSON: ${error.message}`);
}
if (!config || typeof config !== 'object' || Array.isArray(config)) {
  throw new Error('runtime OpenCode config must contain a JSON object');
}
const snippet = JSON.parse(fs.readFileSync(snippetPath, 'utf8'));
if (config.mcp != null && (typeof config.mcp !== 'object' || Array.isArray(config.mcp))) {
  throw new Error('runtime OpenCode config mcp field must be an object when present');
}
config.mcp = config.mcp || {};
for (const [name, entry] of Object.entries(snippet.mcp)) {
  if (Object.prototype.hasOwnProperty.call(config.mcp, name)) {
    const before = JSON.stringify(config.mcp[name]);
    const after = JSON.stringify(entry);
    if (before !== after) throw new Error(`runtime OpenCode config already defines conflicting MCP server ${name}`);
  }
  config.mcp[name] = entry;
}
const mode = fs.statSync(configPath).mode & 0o777;
const temporary = `${configPath}.cwl-toolchain-${process.pid}`;
fs.writeFileSync(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode });
fs.renameSync(temporary, configPath);
fs.chmodSync(configPath, mode);
NODE
fi

PROVENANCE="$RUNTIME/provenance.json"
export PROVENANCE SUPERPOWERS_SHA PONYTAIL_SHA CODE_REVIEW_GRAPH_SHA UI_UX_PRO_MAX_SHA ANTI_SLOP_UI_SHA CODEGRAPH_TRACKED_HEAD CODEGRAPH_INSTALLED_VERSION
node <<'NODE'
const fs = require('fs');
const provenance = {
  schema_version: 1,
  installation_boundary: 'runtime-only development agent tooling; no third-party plugin hooks share the model process',
  target: process.env.TARGET,
  upstreams: {
    superpowers: { repository: 'obra/superpowers', commit: process.env.SUPERPOWERS_SHA, mode: 'static-skill-copy', license: 'MIT' },
    ponytail: { repository: 'DietrichGebert/ponytail', commit: process.env.PONYTAIL_SHA, mode: 'static-skill-copy', license: 'MIT' },
    code_review_graph: { repository: 'tirth8205/code-review-graph', commit: process.env.CODE_REVIEW_GRAPH_SHA, mode: 'locked-source-install-plus-sanitized-mcp', license: 'MIT' },
    ui_ux_pro_max: {
      repository: 'nextlevelbuilder/ui-ux-pro-max-skill',
      commit: process.env.UI_UX_PRO_MAX_SHA,
      mode: 'pinned-source-offline-opencode-generator',
      license_observation: 'root LICENSE and package lock metadata say MIT; cli README says CC-BY-NC-4.0; keep runtime-only pending upstream clarification',
    },
    anti_slop_ui: {
      repository: 'local-over/Anti-Slop-UI',
      commit: process.env.ANTI_SLOP_UI_SHA,
      mode: 'runtime-only-static-guidance-copy',
      license_observation: 'no repository LICENSE file observed at tracked commit; tracked commit is unsigned; do not vendor into product source',
    },
    codegraph: {
      repository: 'colbymchenry/codegraph',
      installed_version: process.env.CODEGRAPH_INSTALLED_VERSION,
      tracked_upstream_head: process.env.CODEGRAPH_TRACKED_HEAD,
      mode: 'central-lock-install-plus-sanitized-mcp',
      license: 'MIT',
      note: 'central trusted lock remains 1.4.1; upstream 1.6.0 upgrade is a separately testable dependency change',
    },
  },
};
fs.writeFileSync(process.env.PROVENANCE, `${JSON.stringify(provenance, null, 2)}\n`, { mode: 0o600 });
NODE

printf 'provenance=%s\n' "$PROVENANCE" >> "$GITHUB_OUTPUT"
printf 'mcp-snippet=%s\n' "$MCP_SNIPPET" >> "$GITHUB_OUTPUT"
printf 'development-agent-toolchain: installed %s runtime skills; indexes ready\n' "${#INSTALLED_SKILLS[@]}"
