"""Source-only health target registration; live activation is a separate gate."""

import hashlib
import json
from pathlib import Path
import unittest


HEALTH_TARGET = "ContextualWisdomLab/health-evidence"
BASELINE_TARGETS = (
    'ContextualWisdomLab/.github',
    'ContextualWisdomLab/ContextualWisdomLab.github.io',
    'ContextualWisdomLab/DiagramWeave',
    'ContextualWisdomLab/EgressWeave',
    'ContextualWisdomLab/EmbedRelay',
    'ContextualWisdomLab/IRT-bibliography-set',
    'ContextualWisdomLab/LineageWeave',
    'ContextualWisdomLab/OriginWeave',
    'ContextualWisdomLab/Orgmetra',
    'ContextualWisdomLab/RankWeave',
    'ContextualWisdomLab/TEPP',
    'ContextualWisdomLab/ThreadWeave',
    'ContextualWisdomLab/aFIPC',
    'ContextualWisdomLab/accounting-information-platform',
    'ContextualWisdomLab/appguardrail',
    'ContextualWisdomLab/bandscope',
    'ContextualWisdomLab/ccube-jco-potential-customer',
    'ContextualWisdomLab/clearfolio',
    'ContextualWisdomLab/codec-carver',
    'ContextualWisdomLab/context-graph-contracts',
    'ContextualWisdomLab/contextual-orchestrator',
    'ContextualWisdomLab/disksage',
    'ContextualWisdomLab/enterprise-architecture-core',
    'ContextualWisdomLab/fast-mlsirm',
    'ContextualWisdomLab/feelanet-adfs',
    'ContextualWisdomLab/four-pillars',
    'ContextualWisdomLab/governance-risk-compliance',
    'ContextualWisdomLab/gyeot',
    'ContextualWisdomLab/hyosung-itx-slogan-brief',
    'ContextualWisdomLab/inkspan',
    'ContextualWisdomLab/kaefa',
    'ContextualWisdomLab/keyverse',
    'ContextualWisdomLab/learning-management-platform',
    'ContextualWisdomLab/life-os',
    'ContextualWisdomLab/linux-cluster-ops',
    'ContextualWisdomLab/macos_utility_packs',
    'ContextualWisdomLab/metering-billing-platform',
    'ContextualWisdomLab/mhtml-etl-gateway',
    'ContextualWisdomLab/mightyETL',
    'ContextualWisdomLab/naruon',
    'ContextualWisdomLab/newsdom-api',
    'ContextualWisdomLab/noema',
    'ContextualWisdomLab/nonnest2',
    'ContextualWisdomLab/pg-erd-cloud',
    'ContextualWisdomLab/pg-llm-batch',
    'ContextualWisdomLab/psychometrics-commons',
    'ContextualWisdomLab/quarantine-sandbox-runtime',
    'ContextualWisdomLab/saju-caldav',
    'ContextualWisdomLab/scopeweave',
    'ContextualWisdomLab/semantic-data-portal',
    'ContextualWisdomLab/tokyo-travel-2026',
    'ContextualWisdomLab/wardnet',
    'ContextualWisdomLab/xtrm-lead-pi-outbound',
    'ContextualWisdomLab/xtrmLLMBatchPython',
)
BASELINE_METADATA_SHA256 = "3063be77dbb6274a6785cb530f04c3fdf3903d786f8cc8b3bd3dd2b53cf27b8d"


class HealthReviewTargetRegistrationTests(unittest.TestCase):
    def test_health_registration_preserves_existing_order_and_metadata(self):
        mirror_path = (
            Path(__file__).resolve().parents[1]
            / "scripts/ci/opencode_repository_dispatch_targets.json"
        )
        mirror = json.loads(mirror_path.read_text(encoding="utf-8"))
        targets = mirror["targets"]
        self.assertEqual(
            targets.count(HEALTH_TARGET),
            1,
            "health-evidence must be registered exactly once in the source mirror",
        )
        self.assertEqual(len(targets), len(BASELINE_TARGETS) + 1)
        self.assertEqual(len(set(targets)), len(targets))
        expected_targets: list[str] = list(BASELINE_TARGETS)
        insertion_index = expected_targets.index("ContextualWisdomLab/gyeot") + 1
        expected_targets.insert(insertion_index, HEALTH_TARGET)
        self.assertEqual(
            targets,
            expected_targets,
            "health target must follow gyeot without moving any existing target",
        )
        self.assertEqual(
            [target for target in targets if target != HEALTH_TARGET],
            list(BASELINE_TARGETS),
            "preexisting target order and membership must remain unchanged",
        )
        metadata = {key: value for key, value in mirror.items() if key != "targets"}
        digest = hashlib.sha256(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(digest, BASELINE_METADATA_SHA256)


if __name__ == "__main__":
    unittest.main()
