"""Documentation contract for trusted uv network-boundary helpers."""

import ast
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "scripts/ci/materialize_base_python_requirements.py"
TARGETS = {
    "_https_default_port",
    "_is_trusted_uv_https_host",
    "_is_trusted_uv_release_request",
    "_is_trusted_uv_asset_location",
    "_is_trusted_uv_final_origin",
    "_TrustedUvReleaseAssetRedirects",
    "_is_candidate_lock_name",
    "_is_bounded_requirement_include",
    "_is_fully_hash_pinned_requirement",
    "_partition_uv_export",
    "_git",
    "_download_trusted_uv_archive",
    "_verified_uv_binary",
    "_install_trusted_uv",
    "_trusted_uv_export_environment",
    "_uv_pyproject_path",
    "_reject_unsupported_uv_workspace",
    "_reject_incompatible_uv_version",
    "_regular_base_blob_paths",
    "_base_python_inputs",
    "base_hash_locks",
    "_included_base_lock_blobs",
    "_rewrite_materialized_includes",
    "materialize",
    "main",
}


def test_network_boundary_symbols_have_explanatory_multiline_docstrings() -> None:
    """Security-sensitive URL checks explain their trust-boundary behavior."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    violations = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in TARGETS:
            docstring = ast.get_docstring(node, clean=False)
            if docstring is None or "\n" not in docstring:
                violations.append((node.name, node.lineno))

    assert not violations, f"network boundary symbols need explanatory docs: {violations}"
