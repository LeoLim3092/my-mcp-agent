"""Regression tests for hard links, symlink replacement, and atomic writes."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_mcp_agent import security, workspace_io
from my_mcp_agent.tools import filesystem as fs


class WorkspaceIOTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "workspace"
        self.root.mkdir()
        override = patch.object(security, "ALLOWED_WORKSPACE", self.root)
        override.start()
        self.addCleanup(override.stop)

    def test_hardlink_read_write_patch_rejected_and_outside_unchanged(self):
        outside = self.base / "outside.txt"
        outside.write_text("fake private content")
        (self.root / "alias.txt").hardlink_to(outside)
        for operation in (
            lambda: fs.read_file("alias.txt"),
            lambda: fs.write_file("alias.txt", "overwrite"),
            lambda: fs.patch_file("alias.txt", "private", "changed"),
        ):
            with self.assertRaises(security.SandboxViolationError):
                operation()
            self.assertEqual(outside.read_text(), "fake private content")
        self.assertNotIn("alias.txt", fs.list_directory())

    def test_parent_symlink_inserted_after_validation_is_not_followed(self):
        original_open = os.open
        for operation in ("read", "write"):
            with self.subTest(operation=operation):
                scripts = self.root / operation
                scripts.mkdir()
                (scripts / "file.txt").write_text("inside")
                outside = self.base / (operation + "-outside")
                outside.mkdir()
                (outside / "file.txt").write_text("outside")
                swapped = False

                def swap_parent(
                    path,
                    flags,
                    *args,
                    operation=operation,
                    scripts=scripts,
                    outside=outside,
                    **kwargs,
                ):
                    nonlocal swapped
                    if path == operation and (not swapped):
                        swapped = True
                        scripts.rename(self.root / (operation + "-held"))
                        scripts.symlink_to(outside, target_is_directory=True)
                    return original_open(path, flags, *args, **kwargs)

                with (
                    patch.object(workspace_io.os, "open", side_effect=swap_parent),
                    self.assertRaises(security.SandboxViolationError),
                ):
                    if operation == "read":
                        fs.read_file(operation + "/file.txt")
                    else:
                        fs.write_file(operation + "/file.txt", "bad")
                self.assertTrue(swapped)
                self.assertEqual((outside / "file.txt").read_text(), "outside")

    def test_final_symlink_inserted_after_validation_is_not_followed(self):
        outside = self.base / "outside.txt"
        outside.write_text("outside")
        target = self.root / "file.txt"
        target.write_text("inside")
        original_open = os.open

        def swap_file(path, flags, *args, **kwargs):
            if path == "file.txt":
                target.unlink()
                target.symlink_to(outside)
            return original_open(path, flags, *args, **kwargs)

        with (
            patch.object(workspace_io.os, "open", side_effect=swap_file),
            self.assertRaises(security.SandboxViolationError),
        ):
            fs.read_file("file.txt")
        self.assertEqual(outside.read_text(), "outside")

    def test_failed_atomic_replace_preserves_existing_content_and_cleans_temporary(
        self,
    ):
        fs.write_file("file.txt", "original")
        with (
            patch.object(
                workspace_io.os, "replace", side_effect=OSError("simulated failure")
            ),
            self.assertRaises(OSError),
        ):
            fs.write_file("file.txt", "replacement")
        self.assertEqual((self.root / "file.txt").read_text(), "original")
        self.assertEqual([path.name for path in self.root.iterdir()], ["file.txt"])

    def test_write_replaces_inode_and_preserves_executable_mode(self):
        fs.write_file("script.py", "old")
        target = self.root / "script.py"
        target.chmod(493)
        original = target.stat().st_ino
        fs.write_file("script.py", "new")
        self.assertNotEqual(target.stat().st_ino, original)
        self.assertEqual(target.stat().st_mode & 511, 493)
        self.assertEqual(target.read_text(), "new")

    def test_fifo_read_and_write_rejected_without_blocking(self):
        os.mkfifo(self.root / "fifo")
        with self.assertRaises(ValueError):
            fs.read_file("fifo")
        with self.assertRaises(ValueError):
            fs.write_file("fifo", "bad")


if __name__ == "__main__":
    unittest.main()
