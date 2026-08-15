"""Primitive, schema, and bounded-I/O tests for the CWL catalogue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catalogue_test_helpers import CATALOG, ROOT, load_catalog, validator, write_catalog_tree
from cwl_catalog_contract import (
    CATALOG_FIELDS,
    DATA_FLOW_CLASSES,
    INTEGRATION_MODES,
    SERVICE_FIELDS,
    CatalogValidationError,
    require_array,
    require_boolean,
    require_closed_object,
    require_enum,
    require_identifier,
    require_immutable_reference,
    require_manifest_path,
    require_nonempty_string,
    require_repository,
    require_semver,
    require_unique_strings,
)
from cwl_catalog_io import load_json, resolve_manifest_path, validate_bounded_value

SERVICE_SCHEMA = ROOT / "schemas/cwl-service-capability-v1.schema.json"
CATALOG_SCHEMA = ROOT / "schemas/cwl-ecosystem-catalog-v1.schema.json"


def test_schemas_and_positive_catalogue_align_with_production_constants() -> None:
    """Closed schemas and production field constants must remain aligned."""

    service_schema = json.loads(SERVICE_SCHEMA.read_text(encoding="utf-8"))
    catalog_schema = json.loads(CATALOG_SCHEMA.read_text(encoding="utf-8"))
    assert service_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert catalog_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert service_schema["additionalProperties"] is False
    assert catalog_schema["additionalProperties"] is False
    assert set(service_schema["required"]) == set(SERVICE_FIELDS)
    assert set(catalog_schema["required"]) == set(CATALOG_FIELDS)
    assert set(service_schema["properties"]["integration_mode"]["enum"]) == set(INTEGRATION_MODES)
    assert set(catalog_schema["$defs"]["relationship"]["properties"]["data_flow_class"]["enum"]) == set(DATA_FLOW_CLASSES)
    validator.validate_catalog(CATALOG)


def test_strict_json_rejects_missing_symlink_oversized_encoding_syntax_duplicates_and_nonfinite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The filesystem boundary must reject every ambiguous JSON input class."""

    missing = tmp_path / "missing.json"
    with pytest.raises(CatalogValidationError, match="regular file"):
        load_json(missing)
    target = tmp_path / "target.json"; target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"; link.symlink_to(target)
    with pytest.raises(CatalogValidationError, match="symbolic link"):
        load_json(link)
    monkeypatch.setattr("cwl_catalog_io.MAX_FILE_BYTES", 1)
    with pytest.raises(CatalogValidationError, match="input limit"):
        load_json(target)
    monkeypatch.setattr("cwl_catalog_io.MAX_FILE_BYTES", 2 * 1024 * 1024)
    bad_utf8 = tmp_path / "utf8.json"; bad_utf8.write_bytes(b"\xff")
    with pytest.raises(CatalogValidationError, match="strict UTF-8"):
        load_json(bad_utf8)
    for text, message in (("{", "valid JSON"), ('{"a":1,"a":2}', "duplicate JSON key"), ('{"a":NaN}', "non-finite JSON")):
        candidate = tmp_path / "bad.json"; candidate.write_text(text, encoding="utf-8")
        with pytest.raises(CatalogValidationError, match=message):
            load_json(candidate)


def test_bounded_shape_rejects_depth_cardinality_and_string_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recursive input limits must reject depth, collection, and string abuse."""

    validate_bounded_value({"ok": ["value"]})
    with pytest.raises(CatalogValidationError, match="maximum depth"):
        validate_bounded_value("x", depth=21)
    monkeypatch.setattr("cwl_catalog_io.MAX_STRING_LENGTH", 1)
    with pytest.raises(CatalogValidationError, match="string limit"):
        validate_bounded_value("xx")
    monkeypatch.setattr("cwl_catalog_io.MAX_STRING_LENGTH", 8192)
    monkeypatch.setattr("cwl_catalog_io.MAX_COLLECTION_ITEMS", 1)
    for value in ([1, 2], {"a": 1, "b": 2}):
        with pytest.raises(CatalogValidationError, match="collection limit"):
            validate_bounded_value(value)


def test_manifest_resolution_is_rooted_and_symlink_safe(tmp_path: Path) -> None:
    """Manifest paths must remain below the catalogue directory."""

    catalog = tmp_path / "catalog.json"; catalog.write_text("{}", encoding="utf-8")
    service_dir = tmp_path / "services"; service_dir.mkdir()
    manifest = service_dir / "valid_service.json"; manifest.write_text("{}", encoding="utf-8")
    assert resolve_manifest_path(catalog, "services/valid_service.json") == manifest
    outside = tmp_path.parent / "outside.json"; outside.write_text("{}", encoding="utf-8")
    with pytest.raises(CatalogValidationError, match=r"services/\*\.json"):
        require_manifest_path("../outside.json", "manifest_path")
    with pytest.raises(CatalogValidationError, match="escapes"):
        resolve_manifest_path(catalog, "../outside.json")
    escaped = tmp_path / "escape"; escaped.symlink_to(tmp_path.parent, target_is_directory=True)
    with pytest.raises(CatalogValidationError, match="symbolic link"):
        resolve_manifest_path(catalog, "escape/outside.json")
    internal_target = tmp_path / "target"; internal_target.mkdir()
    (internal_target / "inside.json").write_text("{}", encoding="utf-8")
    internal_link = tmp_path / "inside_link"; internal_link.symlink_to(internal_target, target_is_directory=True)
    with pytest.raises(CatalogValidationError, match="symbolic link"):
        resolve_manifest_path(catalog, "inside_link/inside.json")


def test_primitive_contract_helpers_cover_success_and_failure_paths() -> None:
    """Primitive helpers must reject type confusion and uncontrolled values."""

    assert require_closed_object({"a": 1}, "value", ("a",)) == {"a": 1}
    with pytest.raises(CatalogValidationError, match="must be an object"):
        require_closed_object([], "value", ("a",))
    with pytest.raises(CatalogValidationError, match="unknown properties"):
        require_closed_object({"a": 1, "b": 2}, "value", ("a",))
    with pytest.raises(CatalogValidationError, match="missing properties"):
        require_closed_object({}, "value", ("a",))
    assert require_array([], "array") == []
    with pytest.raises(CatalogValidationError, match="must be an array"):
        require_array({}, "array")
    assert require_nonempty_string("x", "text") == "x"
    with pytest.raises(CatalogValidationError, match="non-empty"):
        require_nonempty_string("", "text")
    assert require_identifier("two_words", "id") == "two_words"
    assert require_repository("ContextualWisdomLab/.github", "repo").endswith("/.github")
    assert require_semver("1.0.0", "version") == "1.0.0"
    assert require_enum("planned", "maturity", ("planned",)) == "planned"
    assert require_boolean(False, "flag") is False
    assert require_immutable_reference("contract:cwl/example@1.0.0", "ref").endswith("@1.0.0")
    assert require_manifest_path("services/two_words.json", "path").endswith(".json")
    failures = (
        (require_identifier, ("single", "id"), "snake_case"),
        (require_repository, ("other/repo", "repo"), "canonical"),
        (require_semver, ("0.1.0", "version"), "semantic version"),
        (require_enum, ("other", "maturity", ("planned",)), "controlled"),
        (require_boolean, (1, "flag"), "boolean"),
        (require_immutable_reference, ("mutable", "ref"), "immutable"),
        (require_manifest_path, ("service.json", "path"), "services/"),
    )
    for function, args, message in failures:
        with pytest.raises(CatalogValidationError, match=message):
            function(*args)
    assert require_unique_strings(["a", "b"], "items") == ["a", "b"]
    with pytest.raises(CatalogValidationError, match="at least"):
        require_unique_strings([], "items", minimum=1)
    with pytest.raises(CatalogValidationError, match="duplicate"):
        require_unique_strings(["a", "a"], "items")
    with pytest.raises(CatalogValidationError, match="non-empty"):
        require_unique_strings([""], "items")


def test_catalogue_root_rejects_shape_identity_and_manifest_reference_errors(tmp_path: Path) -> None:
    """Root identity and manifest references must remain closed and unique."""

    cases: list[tuple[dict[str, object], str]] = []
    base = load_catalog(); base["extra"] = True; cases.append((base, "unknown properties"))
    base = load_catalog(); base.pop("catalog_id"); cases.append((base, "missing properties"))
    base = load_catalog(); base["schema_version"] = "2.0.0"; cases.append((base, "schema_version"))
    base = load_catalog(); base["catalog_id"] = "single"; cases.append((base, "catalog_id"))
    base = load_catalog(); base["catalog_version"] = "v1"; cases.append((base, "catalog_version"))
    base = load_catalog(); base["maturity"] = "complete"; cases.append((base, "controlled"))
    base = load_catalog(); base["service_manifests"] = []; cases.append((base, "at least one"))
    base = load_catalog(); base["service_manifests"] = "bad"; cases.append((base, "must be an array"))
    base = load_catalog(); base["relationships"] = "bad"; cases.append((base, "must be an array"))
    for index, (catalog, message) in enumerate(cases):
        path = write_catalog_tree(tmp_path / str(index), catalog)
        with pytest.raises(CatalogValidationError, match=message):
            validator.validate_catalog(path)
