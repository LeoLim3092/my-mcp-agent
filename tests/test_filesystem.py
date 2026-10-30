"""Exercise file tools against a disposable workspace, without an MCP client."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_mcp_agent import security
from my_mcp_agent.tools import filesystem as fs


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        workspace = patch.object(security, "ALLOWED_WORKSPACE", self.root)
        workspace.start()
        self.addCleanup(workspace.stop)

    def test_write_read_patch_preserves_utf8_and_newlines(self):
        fs.write_file("scripts/story.txt", "你好\r\nold\r\n")
        self.assertEqual(fs.read_file("scripts/story.txt"), "1: 你好\n2: old")
        fs.patch_file("scripts/story.txt", "old", "new")
        self.assertEqual((self.root / "scripts/story.txt").read_bytes(),
                         "你好\r\nnew\r\n".encode())

    def test_ambiguous_and_missing_patch_leave_file_unchanged(self):
        fs.write_file("text.txt", "aaa")
        for target in ("", "missing", "aa"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                fs.patch_file("text.txt", target, "replacement")
            self.assertEqual((self.root / "text.txt").read_text(), "aaa")

    def test_protected_paths_and_symlinks(self):
        (self.root / ".git").mkdir()
        (self.root / ".env").write_text("secret")
        (self.root / "assets").mkdir()
        (self.root / "alias").symlink_to(self.root / "assets", target_is_directory=True)
        fs.write_file("visible.txt", "hello")
        self.assertEqual(fs.list_directory(), ["assets/", "visible.txt"])
        for path in (".env", ".git/config", "alias/file", "../escape", "/etc/passwd"):
            with self.subTest(path=path):
                for operation in (lambda: fs.read_file(path),
                                  lambda: fs.write_file(path, "bad")):
                    with self.assertRaises(security.SandboxViolationError):
                        operation()
        with self.assertRaises(security.SandboxViolationError):
            fs.write_file("roles/writer.yaml", "bad")

    def test_read_limits_and_binary_detection(self):
        fs.write_file("large.txt", "12345")
        with patch.object(fs, "MAX_FILE_READ_BYTES", 4):
            with self.assertRaises(ValueError):
                fs.read_file("large.txt")
            with self.assertRaises(ValueError):
                fs.patch_file("large.txt", "1", "2")
        for data in (b"\xff", b"a\x00b"):
            (self.root / "binary").write_bytes(data)
            with self.assertRaises(ValueError):
                fs.read_file("binary")

    def test_invalid_file_types(self):
        with self.assertRaises(NotADirectoryError):
            fs.list_directory("missing")
        (self.root / "folder").mkdir()
        with self.assertRaises(ValueError):
            fs.read_file("folder")
        with self.assertRaises(ValueError):
            fs.write_file("folder", "bad")

    def test_registration(self):
        class Registry:
            def __init__(self):
                self.names = []

            def tool(self):
                def register(function):
                    self.names.append(function.__name__)
                    return function
                return register

        registry = Registry()
        fs.register_filesystem_tools(registry)
        self.assertEqual(set(registry.names), {
            "workspace_ping", "list_directory", "read_file", "write_file", "patch_file"
        })


if __name__ == "__main__":
    unittest.main()
