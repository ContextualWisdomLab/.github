"""Validate machine-readable DDD contracts in product-development workflows."""

from __future__ import annotations

import re
import shlex
import textwrap
from collections.abc import Iterable

DDD_ENTRYPOINT_MARKER = "# cwl-ddd-architecture-audit: required"
DDD_PROMPT_BINDING_MARKER = "# cwl-ddd-prompt-binding: v1"
DDD_CONTRACT_VERSION_ENVIRONMENT = "CWL_DDD_CONTRACT_VERSION"
DDD_PROMPT_ENVIRONMENT = "CWL_PRODUCT_AGENT_PROMPT"
DDD_CAPABILITY_ENVIRONMENT = "CWL_DDD_CONTRACT_CAPABILITIES"
DDD_PROMPT_OPTION = "--prompt-env"
DDD_CAPABILITY_OPTION = "--architecture-contract-env"
DDD_CONTRACT_VERSION = "1"
DDD_CONTRACT_CAPABILITIES = frozenset(
    {
        "aggregate",
        "anti_corruption_layer",
        "bounded_context",
        "context_map",
        "directory_ownership",
        "domain_event",
        "domain_service",
        "entity",
        "invariant",
        "minimal_shared_kernel",
        "product_gap_baseline",
        "repository",
        "subdomain_classification",
        "ubiquitous_language",
        "value_object",
    }
)
DDD_CONTRACT_TERMS = tuple(sorted(DDD_CONTRACT_CAPABILITIES))
_CAPABILITY_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]*")
_BLOCK_HEADER_TEMPLATE = r"^(?P<indent> *){key}: *[>|][+-]? *$"
_VERSION_RE = re.compile(
    rf"^{DDD_CONTRACT_VERSION_ENVIRONMENT}: *(?:"
    r'"(?P<double>[0-9]+)"|'
    r"'(?P<single>[0-9]+)'|"
    r"(?P<plain>[0-9]+)) *$"
)
_COMMAND_OPERATORS = frozenset({";", "&&", "||", "&", "|"})
_NON_AGENT_EXECUTABLES = frozenset(
    {":", "[", "echo", "export", "false", "printf", "test", "true"}
)
_YAML_MAPPING_KEY_RE = re.compile(
    r'^(?:"(?P<double>[^"]+)"|\'(?P<single>[^\']+)\'|(?P<plain>[A-Za-z0-9_.-]+))'
    r":\s*(?:#.*)?$"
)
_HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(?P<delimiter>[A-Za-z_][A-Za-z0-9_]*)")


def _top_level_mapping_bodies(source: str, key: str) -> tuple[str, ...]:
    """Return bodies of top-level YAML mappings with an exact key."""
    lines = source.splitlines()
    bodies: list[str] = []
    for index, line in enumerate(lines):
        if line != f"{key}:":
            continue
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip() and not candidate.startswith(" "):
                break
            body.append(candidate)
        bodies.append(textwrap.dedent("\n".join(body)))
    return tuple(bodies)


def _block_scalars(source: str, key: str) -> tuple[str, ...]:
    """Return YAML literal or folded block scalar bodies for an exact key."""
    header = re.compile(_BLOCK_HEADER_TEMPLATE.format(key=re.escape(key)))
    lines = source.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        match = header.fullmatch(line)
        if match is None:
            continue
        base_indent = len(match.group("indent"))
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            if candidate.strip():
                candidate_indent = len(candidate) - len(candidate.lstrip(" "))
                if candidate_indent <= base_indent:
                    break
            body.append(candidate)
        blocks.append(textwrap.dedent("\n".join(body)).strip("\n"))
    return tuple(blocks)


def _step_run_blocks(source: str) -> tuple[str, ...]:
    """Return block ``run`` values structurally nested below job steps."""
    lines = source.splitlines()
    candidates = _block_scalars(source, "run")
    accepted: list[str] = []
    candidate_index = 0
    header = re.compile(_BLOCK_HEADER_TEMPLATE.format(key="run"))
    for index, line in enumerate(lines):
        match = header.fullmatch(line)
        if match is None:
            continue
        block = candidates[candidate_index]
        candidate_index += 1
        run_indent = len(match.group("indent"))
        ancestors: list[tuple[int, str]] = []
        ceiling = run_indent
        for previous in reversed(lines[:index]):
            if not previous.strip():
                continue
            indent = len(previous) - len(previous.lstrip(" "))
            if indent < ceiling:
                ancestors.append((indent, previous.strip()))
                ceiling = indent
                if indent == 0:
                    break
        for ancestor_index, steps in enumerate(ancestors):
            remaining = ancestors[ancestor_index + 1 :]
            if len(remaining) < 2:
                break
            job, jobs = remaining[:2]
            steps_key = _yaml_mapping_key(steps[1])
            job_key = _yaml_mapping_key(job[1])
            jobs_key = _yaml_mapping_key(jobs[1])
            if (
                steps_key == "steps"
                and job_key is not None
                and jobs[0] == 0
                and jobs_key == "jobs"
            ):
                accepted.append(block)
                break
    return tuple(accepted)


def _yaml_mapping_key(line: str) -> str | None:
    """Return a simple YAML mapping key while allowing quotes and comments."""
    match = _YAML_MAPPING_KEY_RE.fullmatch(line)
    if match is None:
        return None
    return next(value for value in match.groups() if value is not None)


def _reachable_shell(block: str) -> str:
    """Remove heredoc bodies and conditional regions from a shell block."""
    reachable: list[str] = []
    heredoc_delimiter: str | None = None
    control_depth = 0
    for line in block.splitlines():
        stripped = line.strip()
        if heredoc_delimiter is not None:
            if stripped == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        if control_depth:
            if re.match(r"^(?:if|case|while|until)\b", stripped):
                control_depth += 1
            if re.match(r"^(?:fi|esac|done)\b", stripped):
                control_depth -= 1
            continue
        if re.match(r"^(?:if|case|while|until)\b", stripped):
            control_depth = 1
            continue
        if match := _HEREDOC_RE.search(stripped):
            heredoc_delimiter = match.group("delimiter")
            continue
        reachable.append(line)
    return "\n".join(reachable)


def _contract_version(environment: str) -> str | None:
    """Return the unique scalar contract version from a root environment body."""
    matches = [
        next(value for value in match.groups() if value is not None)
        for line in environment.splitlines()
        if (match := _VERSION_RE.fullmatch(line)) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def _shell_segments(block: str) -> Iterable[tuple[str, ...]]:
    """Yield non-comment shell command segments with continuations joined."""
    commands: list[str] = []
    fragments: list[str] = []
    for line in block.splitlines():
        fragment = line.strip()
        if not fragment or fragment.startswith("#"):
            continue
        continued = fragment.endswith("\\")
        fragments.append(fragment[:-1].rstrip() if continued else fragment)
        if not continued:
            commands.append(" ".join(fragments))
            fragments = []
    if fragments:
        return
    for command in commands:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        try:
            tokens = tuple(lexer)
        except ValueError:
            continue
        segment: list[str] = []
        for token in tokens:
            if token in _COMMAND_OPERATORS:
                if segment:
                    yield tuple(segment)
                    segment = []
            else:
                segment.append(token)
        if segment:
            yield tuple(segment)


def _option_value(tokens: tuple[str, ...], option: str) -> str | None:
    """Return one unique shell option value from a command segment."""
    values: list[str] = []
    for index, token in enumerate(tokens):
        if token == option and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        elif token.startswith(f"{option}="):
            values.append(token.split("=", 1)[1])
    return values[0] if len(values) == 1 else None


def _executable(tokens: tuple[str, ...]) -> str | None:
    """Return the executable after optional environment assignments."""
    for token in tokens:
        if token == "env" or ("=" in token and not token.startswith("--")):
            continue
        executable = token.rsplit("/", 1)[-1]
        return None if executable.startswith("-") else executable
    return None


def _has_bound_agent_invocation(source: str) -> bool:
    """Return whether one nontrivial command receives both contract inputs."""
    for run_block in _step_run_blocks(source):
        if DDD_PROMPT_BINDING_MARKER not in run_block:
            continue
        for tokens in _shell_segments(_reachable_shell(run_block)):
            executable = _executable(tokens)
            if executable is None or executable in _NON_AGENT_EXECUTABLES:
                continue
            if (
                _option_value(tokens, DDD_PROMPT_OPTION) == DDD_PROMPT_ENVIRONMENT
                and _option_value(tokens, DDD_CAPABILITY_OPTION)
                == DDD_CAPABILITY_ENVIRONMENT
            ):
                return True
    return False


def has_domain_driven_development_contract(source: str) -> bool:
    """Return whether a workflow binds a scoped versioned DDD contract."""
    if DDD_ENTRYPOINT_MARKER not in source:
        return False
    environments = _top_level_mapping_bodies(source, "env")
    if len(environments) != 1:
        return False
    environment = environments[0]
    if _contract_version(environment) != DDD_CONTRACT_VERSION:
        return False
    prompts = _block_scalars(environment, DDD_PROMPT_ENVIRONMENT)
    capabilities = _block_scalars(environment, DDD_CAPABILITY_ENVIRONMENT)
    if len(prompts) != 1 or not prompts[0].strip() or len(capabilities) != 1:
        return False
    declared = frozenset(_CAPABILITY_TOKEN_RE.findall(capabilities[0]))
    if declared != DDD_CONTRACT_CAPABILITIES:
        return False
    return _has_bound_agent_invocation(source)
