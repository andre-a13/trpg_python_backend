import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.sync_frontend_contract import sync_frontend


REVISION = "a" * 40


class ContractSyncTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.backend = Path(self.directory.name) / "backend"
        self.frontend = Path(self.directory.name) / "frontend"
        for root in (self.backend, self.frontend):
            (root / "contracts").mkdir(parents=True)
        self.schema = b'{"openapi":"3.1.0","paths":{},"components":{}}\n'
        (self.backend / "contracts/openapi.json").write_bytes(self.schema)
        self.calls = []
        self.existing = []
        self.prs_by_head = {}
        self.remote_branch = False
        self.latest = REVISION
        self.fail_generation = False

    def command(self, args, cwd):
        self.calls.append(args)
        if args[:3] == ["git", "rev-parse", "HEAD"]:
            return REVISION
        if args == ["git", "ls-remote", "origin", "refs/heads/master"]:
            return self.latest + "\trefs/heads/master"
        if args[:3] == ["gh", "pr", "list"]:
            head = args[args.index("--head") + 1]
            return json.dumps(self.prs_by_head.get(head, self.existing))
        if args[:3] == ["git", "ls-remote", "--heads"]:
            return "remote-branch" if self.remote_branch else ""
        if args[:3] == ["npm", "run", "api:generate"] and self.fail_generation:
            raise subprocess.CalledProcessError(1, args)
        return ""

    def sync(self):
        return sync_frontend(self.frontend, REVISION, backend=self.backend, run=self.command)

    def test_unchanged_contract_does_not_generate_or_open_pr(self):
        (self.frontend / "contracts/openapi.json").write_bytes(self.schema)
        (self.frontend / "contracts/source.json").write_text(json.dumps({
            "sha256": hashlib.sha256(self.schema).hexdigest(), "revision": REVISION,
            "repository": "andre-a13/trpg_python_backend", "source": "commit",
        }))
        self.assertIn("unchanged", self.sync())
        self.assertFalse(any(call[0] in {"gh", "npm", "node"} for call in self.calls))

    def test_existing_pr_preserves_manual_adaptations(self):
        self.existing = [{"number": 7, "state": "OPEN"}]
        self.assertIn("#7", self.sync())
        self.assertFalse(any(call[0] in {"npm", "node"} or "push" in call for call in self.calls))

    def test_changed_contract_imports_generates_and_creates_one_pr(self):
        self.assertIn("Created", self.sync())
        self.assertIn(["npm", "run", "api:generate"], self.calls)
        self.assertEqual(sum(call[:3] == ["gh", "pr", "create"] for call in self.calls), 1)
        staging = next(call for call in self.calls if call[:2] == ["git", "add"])
        self.assertEqual(staging[3:], ["contracts/openapi.json", "contracts/source.json", "src/api/generated"])
        self.assertFalse(any("--force" in call for call in self.calls))

    def test_generation_failure_never_pushes_or_creates_pr(self):
        self.fail_generation = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.sync()
        self.assertFalse(any(call[:2] == ["git", "push"] or call[:3] == ["gh", "pr", "create"] for call in self.calls))

    def test_superseded_backend_run_is_ignored(self):
        self.latest = "b" * 40
        self.assertIn("superseded", self.sync())
        self.assertFalse(any(call[0] == "gh" for call in self.calls))

    def test_reverted_contract_gets_a_new_pr_after_its_previous_pr_was_merged(self):
        self.existing = [{"number": 7, "state": "MERGED"}]
        digest = hashlib.sha256(self.schema).hexdigest()
        branch = f"automation/api-contract-{digest}-{REVISION}"
        self.prs_by_head[branch] = []
        self.assertIn("Created", self.sync())
        self.assertIn(["git", "checkout", "-b", branch], self.calls)

    def test_existing_revert_pr_is_preserved_on_retry(self):
        self.existing = [{"number": 7, "state": "MERGED"}]
        digest = hashlib.sha256(self.schema).hexdigest()
        branch = f"automation/api-contract-{digest}-{REVISION}"
        self.prs_by_head[branch] = [{"number": 8, "state": "OPEN"}]
        self.assertIn("#8", self.sync())
        self.assertFalse(any(call[0] in {"npm", "node"} or "push" in call for call in self.calls))

    def test_closed_pr_is_preserved(self):
        self.existing = [{"number": 7, "state": "CLOSED"}]
        self.assertIn("#7", self.sync())
        self.assertFalse(any(call[0] in {"npm", "node"} or "push" in call for call in self.calls))

    def test_pushed_branch_without_pr_resumes_creation_without_overwriting_it(self):
        self.remote_branch = True
        self.assertIn("Created", self.sync())
        self.assertFalse(any(call[0] in {"npm", "node"} or call[:2] == ["git", "push"] for call in self.calls))


if __name__ == "__main__":
    unittest.main()
