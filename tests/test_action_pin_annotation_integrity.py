"""Keep release annotations consistent for immutable GitHub Action pins."""

from collections import defaultdict
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
OSV_SCANNER_SHA = "8e5cf47b818121e8b405931c82126c2630b0b20d"
ACTION_PIN = re.compile(
    r"^\s*uses:\s+(?P<action>[^\s@]+)@(?P<sha>[0-9a-f]{40})\s+#\s*(?P<annotation>\S.*?)\s*$"
)
IMMUTABLE_PIN = re.compile(r"^\s*uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s|$)")
ACTION_REFERENCE = re.compile(r"^\s*uses:\s+(?P<action>[^\s@]+)@(?P<ref>[^\s#]+)")
RELEASE_ANNOTATION = re.compile(r"^v[0-9]+(?:\.[0-9]+)*(?:[-+][0-9A-Za-z.-]+)?$")


def _action_files() -> list[Path]:
    """Return workflow and composite-action YAML files."""

    return sorted(
        path
        for directory in (ROOT / ".github" / "workflows", ROOT / ".github" / "actions")
        for path in (*directory.rglob("*.yml"), *directory.rglob("*.yaml"))
    )


def test_each_action_pin_sha_has_one_release_annotation() -> None:
    """The same immutable action identity must not advertise different releases."""

    annotations: defaultdict[tuple[str, str], list[tuple[str, int, str]]] = defaultdict(
        list
    )
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = ACTION_PIN.match(line)
            if match:
                identity = (match["action"], match["sha"])
                annotations[identity].append(
                    (str(path.relative_to(ROOT)), line_number, match["annotation"])
                )

    contradictions = {
        identity: locations
        for identity, locations in annotations.items()
        if len({annotation for _, _, annotation in locations}) > 1
    }
    assert not contradictions, "contradictory immutable action annotations: " + repr(
        contradictions
    )


def test_each_immutable_action_pin_has_a_release_annotation() -> None:
    """Do not let an unlabelled immutable pin evade the integrity checks."""

    missing: list[tuple[str, int, str]] = []
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if IMMUTABLE_PIN.match(line) and not ACTION_PIN.match(line):
                missing.append((str(path.relative_to(ROOT)), line_number, line.strip()))

    assert not missing, "immutable action pins need release annotations: " + repr(missing)


def test_each_external_action_reference_is_immutable() -> None:
    """Do not permit mutable tags or branches for third-party actions."""

    mutable: list[tuple[str, int, str]] = []
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = ACTION_REFERENCE.match(line)
            if (
                match
                and not match["action"].startswith("./")
                and not re.fullmatch(r"[0-9a-f]{40}", match["ref"])
            ):
                mutable.append((str(path.relative_to(ROOT)), line_number, line.strip()))

    assert not mutable, "external actions must use immutable commit SHAs: " + repr(mutable)


def test_action_pin_annotations_are_release_shaped() -> None:
    """Reject labels that cannot identify a concrete released revision."""

    malformed: list[tuple[str, int, str]] = []
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = ACTION_PIN.match(line)
            if match and not RELEASE_ANNOTATION.fullmatch(match["annotation"]):
                malformed.append(
                    (str(path.relative_to(ROOT)), line_number, match["annotation"])
                )

    assert not malformed, "action pin annotations must identify a release: " + repr(
        malformed
    )


def test_action_subpaths_share_the_repository_sha_annotation() -> None:
    """Sub-actions from one immutable repository revision share one label."""

    annotations: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for directory in (ROOT / ".github" / "workflows", ROOT / ".github" / "actions"):
        for path in sorted((*directory.rglob("*.yml"), *directory.rglob("*.yaml"))):
            for line in path.read_text(encoding="utf-8").splitlines():
                match = ACTION_PIN.match(line)
                if match:
                    repository = "/".join(match["action"].split("/")[:2])
                    annotations[(repository, match["sha"])].add(match["annotation"])

    contradictions = {
        identity: sorted(values)
        for identity, values in annotations.items()
        if len(values) > 1
    }
    assert not contradictions, "contradictory repository pin annotations: " + repr(
        contradictions
    )


def test_upload_artifact_uses_the_reviewed_node24_pin() -> None:
    """Keep artifact uploads off the deprecated Node 20 action runtime."""

    upload_pins = []
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = ACTION_PIN.match(line)
            if match and match["action"] == "actions/upload-artifact":
                upload_pins.append((path, line_number, match["sha"]))

    assert upload_pins
    assert all(sha == UPLOAD_ARTIFACT_SHA for _, _, sha in upload_pins), upload_pins


def test_osv_action_subpaths_use_one_current_upstream_pin() -> None:
    """Keep scanner and reporter sub-actions on one fail-closed revision."""

    osv_pins = []
    for path in _action_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = ACTION_PIN.match(line)
            if match and match["action"].startswith("google/osv-scanner-action/"):
                osv_pins.append((path, line_number, match["action"], match["sha"]))

    assert osv_pins
    assert all(sha == OSV_SCANNER_SHA for _, _, _, sha in osv_pins), osv_pins
