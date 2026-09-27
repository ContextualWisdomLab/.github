"""Contract tests for the queue-draining merge scheduler runner image."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


WORKFLOW = Path('.github/workflows/pr-review-merge-scheduler.yml')
JOB_HEADER = re.compile(r'^  ([A-Za-z0-9_-]+):\n', re.MULTILINE)


def job_block(workflow: str, job_name: str) -> str:
    """Return one top-level job block from the merge scheduler workflow."""
    marker = f'  {job_name}:\n'
    start = workflow.index(marker)
    match = JOB_HEADER.search(workflow, start + len(marker))
    end = match.start() if match else len(workflow)
    return workflow[start:end]


class MergeSchedulerRunnerImageContract(unittest.TestCase):
    """Keep queue-draining control jobs off the starved floating image."""

    def test_queue_draining_jobs_use_explicit_supported_image(self) -> None:
        """Require dedicated control capacity for central and reusable callers."""
        workflow = WORKFLOW.read_text(encoding='utf-8')
        for job_name in ('scan-pr-queue',):
            block = job_block(workflow, job_name)
            self.assertIn("group: CWL central control", block, job_name)
            self.assertIn("labels: [self-hosted, linux, x64]", block, job_name)
            self.assertNotIn("fromJSON", block.split("steps:", 1)[0], job_name)
            self.assertNotIn('runs-on: ubuntu-latest', block, job_name)
        self.assertNotIn('runs-on: ubuntu-latest', workflow)


if __name__ == '__main__':
    unittest.main()
