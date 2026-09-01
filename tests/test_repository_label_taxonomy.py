import json
from pathlib import Path


def test_repository_label_taxonomy_uses_existing_normalized_labels():
    taxonomy = json.loads(
        Path("config/repository-label-taxonomy.json").read_text(encoding="utf-8")
    )
    assert taxonomy == {
        "schema_version": 1,
        "type": {
            "feature": "enhancement",
            "bug": "bug",
            "documentation": "documentation",
        },
    }
