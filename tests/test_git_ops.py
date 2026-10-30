"""Integration tests using disposable Git repositories."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_mcp_agent import security
from my_mcp_agent.tools import git_ops as git


class GitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for module in (git, security):
            workspace = patch.object(module, "ALLOWED_WORKSPACE", self.root)
            workspace.start()
            self.addCleanup(workspace.stop)
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.invalid")
        (self.root / "game.txt").write_text("initial\n")
        self.run_git("add", "game.txt")
        self.run_git("commit", "-m", "Initial")

    def run_git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout

    def test_status_and_unstaged_diff(self):
        (self.root / "game.txt").write_text("changed\n")
        (self.root / ".env").write_text("secret")
        status = git.git_status()
        self.assertIn("game.txt", status)
        self.assertNotIn(".env", status)
        self.assertIn("+changed", git.git_diff("game.txt"))
        for path in (".env", "../outside", "."):
            with self.subTest(path=path), self.assertRaises((ValueError, PermissionError)):
                git.git_diff(path)

    def test_checkpoint_creates_branch_and_commits_only_staged(self):
        (self.root / "game.txt").write_text("checkpoint\n")
        (self.root / "untracked.txt").write_text("leave unstaged")
        self.run_git("add", "game.txt")
        marker = self.root / "hook-ran"
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
        hook.chmod(0o755)
        git.git_checkpoint("feature/game", "Game checkpoint")
        self.assertFalse(marker.exists())
        self.assertEqual(self.run_git("branch", "--show-current").strip(), "feature/game")
        self.assertEqual(self.run_git("log", "-1", "--format=%s").strip(), "Game checkpoint")
        self.assertNotIn("untracked.txt", self.run_git("ls-files"))
        (self.root / "game.txt").write_text("second\n")
        self.run_git("add", "game.txt")
        git.git_checkpoint("feature/game", "Second")

    def test_protected_branches_and_invalid_input(self):
        for branch in ("main", "master", "MAIN", "--help", "bad name", ""):
            with self.subTest(branch=branch), self.assertRaises(ValueError):
                git.git_checkpoint(branch, "test")
        with self.assertRaises(ValueError):
            git.git_checkpoint("feature/game", " ")
        with self.assertRaises(ValueError):
            git.git_checkpoint("feature/game", "No staged changes")
        self.assertEqual(self.run_git("branch", "--show-current").strip(), "main")

    def test_sensitive_staging_is_rejected_before_branch_change(self):
        for name in (".env", "roles/writer.yaml"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("protected")
            self.run_git("add", "--", name)
            with self.assertRaises(security.SandboxViolationError):
                git.git_checkpoint("feature/game", "Blocked")
            self.run_git("reset", "--", name)
        self.assertEqual(self.run_git("branch", "--show-current").strip(), "main")

    def test_existing_branch_and_parent_repository_are_rejected(self):
        self.run_git("branch", "feature/existing")
        (self.root / "game.txt").write_text("change")
        self.run_git("add", "game.txt")
        with self.assertRaises(ValueError):
            git.git_checkpoint("feature/existing", "Blocked")
        nested = self.root / "nested"
        nested.mkdir()
        with patch.object(git, "ALLOWED_WORKSPACE", nested):
            with self.assertRaises(ValueError):
                git.git_status()

    def test_inherited_git_overrides_are_ignored(self):
        with patch.dict("os.environ", {"GIT_DIR": "/nonexistent", "GIT_WORK_TREE": "/"}):
            self.assertEqual(git.git_status(), "No visible changes.")


if __name__ == "__main__":
    unittest.main()
