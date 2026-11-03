"""Phase 3 policies and real isolated QA/Blender integration."""

import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from my_mcp_agent import config, execution, security
from my_mcp_agent.resources.memory import get_architecture_memory
from my_mcp_agent.tools import external, qa_runner, web_docs


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="phase3-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for module in (config, security):
            override = patch.object(module, "ALLOWED_WORKSPACE", self.root)
            override.start()
            self.addCleanup(override.stop)

    def test_memory_is_explicit_dynamic_and_bounded(self):
        (self.root / "GDD.md").write_text("island design")
        (self.root / "secret.md").write_text("not approved")
        self.assertIn("island design", get_architecture_memory())
        self.assertNotIn("not approved", get_architecture_memory())
        (self.root / "GDD.md").write_text("updated")
        self.assertIn("updated", get_architecture_memory())
        with (
            patch.object(config, "MAX_FILE_READ_BYTES", 2),
            self.assertRaises(ValueError),
        ):
            get_architecture_memory()
        (self.root / "GDD.md").unlink()
        (self.root / "GDD.md").symlink_to(self.root / "secret.md")
        with self.assertRaises(security.SandboxViolationError):
            get_architecture_memory()

    def test_snapshot_excludes_secrets_links_and_metadata(self):
        (self.root / ".env").write_text("secret")
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_text("private")
        (self.root / "game.py").write_text("print('game')")
        (self.root / "link").symlink_to(self.root / "game.py")
        with tempfile.TemporaryDirectory() as target:
            execution.snapshot_workspace(Path(target))
            self.assertEqual([p.name for p in Path(target).iterdir()], ["game.py"])
        with (
            tempfile.TemporaryDirectory() as target,
            patch.object(config, "SNAPSHOT_MAX_BYTES", 1),
            self.assertRaises(ValueError),
        ):
            execution.snapshot_workspace(Path(target))

    def test_missing_isolation_fails_closed(self):
        with (
            patch.object(execution.shutil, "which", return_value=None),
            self.assertRaises(RuntimeError),
        ):
            execution.run_isolated(["true"], self.root, self.root)

    def test_live_linter_and_pytest(self):
        (self.root / "good.py").write_text("answer = 42\n")
        self.assertTrue(qa_runner.run_linter("good.py")["passed"])
        (self.root / "bad.py").write_text("import os\n")
        self.assertFalse(qa_runner.run_linter("bad.py")["passed"])
        (self.root / "test_game.py").write_text(
            "def test_game():\n    assert 2 + 2 == 4\n"
        )
        result = qa_runner.run_tests("test_game.py")
        self.assertTrue(result["passed"], result)
        (self.root / "test_game.py").write_text("def test_game():\n    assert False\n")
        self.assertFalse(qa_runner.run_tests("test_game.py")["passed"])

    def test_live_isolation_and_timeout(self):
        with tempfile.TemporaryDirectory() as destination:
            output = Path(destination)
            (self.root / ".env").write_text("fake secret")
            sentinel = self.root / "host-only"
            sentinel.write_text("outside sandbox")
            code = """import os, pathlib, socket
assert not pathlib.Path('/workspace/.env').exists()
assert not pathlib.Path(HOST).exists()
assert 'PHASE3_FAKE_SECRET' not in os.environ
try:
    pathlib.Path('/workspace/new').write_text('bad')
except OSError:
    pass
else:
    raise AssertionError('workspace writable')
try:
    socket.create_connection(('1.1.1.1', 443), timeout=0.2)
except OSError:
    pass
else:
    raise AssertionError('network available')
print('ISOLATION_OK')
""".replace("HOST", repr(str(sentinel)))
            with tempfile.TemporaryDirectory() as copied:
                workspace = Path(copied)
                execution.snapshot_workspace(workspace)
                with patch.dict(os.environ, {"PHASE3_FAKE_SECRET": "hidden"}):
                    result = execution.run_isolated(
                        ["/runtime/bin/python", "-I", "-c", code], workspace, output
                    )
                self.assertEqual(result["exit_code"], 0, result)
                self.assertIn("ISOLATION_OK", result["stdout"])
                with patch.object(config, "EXECUTION_TIMEOUT_SECONDS", 0.2):
                    timed = execution.run_isolated(
                        [
                            "/runtime/bin/python",
                            "-I",
                            "-c",
                            "import time; time.sleep(30)",
                        ],
                        workspace,
                        output,
                    )
                self.assertTrue(timed["timed_out"])

    def test_live_blender_export_and_failure(self):
        binary = os.environ.get("STUDIO_TEST_BLENDER") or shutil.which(
            config.BLENDER_EXECUTABLE
        )
        if not binary:
            self.skipTest("Set STUDIO_TEST_BLENDER to run the real Blender integration")
        script = """import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add()
mesh = bpy.context.object.data
print('POLYGONS', len(mesh.polygons))
bpy.ops.wm.save_as_mainfile(filepath='/output/cube.blend')
"""
        with patch.object(config, "BLENDER_EXECUTABLE", binary):
            result = external.run_blender_script(script)
            self.assertEqual(result["exit_code"], 0, result)
            self.assertIn("POLYGONS 6", result["stdout"])
            self.assertIn("assets/generated/cube.blend", result["exports"])
            self.assertTrue((self.root / "assets/generated/cube.blend").is_file())
            failed = external.run_blender_script(
                "raise RuntimeError('expected test failure')"
            )
            self.assertNotEqual(failed["exit_code"], 0)
            self.assertEqual(failed["exports"], [])
            loaded = external.run_blender_script(
                "import bpy; print('LOADED', len(bpy.data.objects))",
                "assets/generated/cube.blend",
            )
            self.assertEqual(loaded["exit_code"], 0, loaded)
            self.assertIn("LOADED 1", loaded["stdout"])

    def test_hardlinks_are_not_copied(self):
        with (
            tempfile.TemporaryDirectory() as outside,
            tempfile.TemporaryDirectory() as copied,
        ):
            secret = Path(outside) / "private"
            secret.write_text("outside secret")
            os.link(secret, self.root / "alias.txt")
            execution.snapshot_workspace(Path(copied))
            self.assertFalse((Path(copied) / "alias.txt").exists())

    def test_blender_rejects_symlink_exports(self):
        def fake_run(command, workspace, output, mounts):
            (output / "bad.blend").symlink_to("/etc/passwd")
            return {"exit_code": 0, "timed_out": False}

        with (
            patch.object(external.shutil, "which", return_value="/usr/bin/python3"),
            patch.object(external, "run_isolated", side_effect=fake_run),
            self.assertRaises(ValueError),
        ):
            external.run_blender_script("print('fake')")
        self.assertFalse((self.root / "assets").exists())

    def test_live_output_truncation(self):
        with (
            tempfile.TemporaryDirectory() as output,
            patch.object(config, "EXECUTION_OUTPUT_BYTES", 8),
        ):
            result = execution.run_isolated(
                ["/runtime/bin/python", "-I", "-c", "print('x' * 100)"],
                self.root,
                Path(output),
            )
        self.assertEqual(result["exit_code"], 0, result)
        self.assertTrue(result["output_truncated"])
        self.assertEqual(result["stdout"], "xxxxxxxx")


class WebTests(unittest.TestCase):
    def dns(self, address="93.184.216.34"):
        return patch.object(
            socket,
            "getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
        )

    def test_private_and_nonweb_destinations_rejected(self):
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "224.0.0.1"):
            with (
                self.subTest(address=address),
                self.dns(address),
                self.assertRaises(ValueError),
            ):
                web_docs.fetch_web_docs("https://example.com")
        for url in (
            "file:///etc/passwd",
            "https://user:password@example.com",
            "http://example.com:8080",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                web_docs.fetch_web_docs(url)

    def test_html_cleanup_and_size_limit(self):
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<nav>noise</nav><main><h1>Docs</h1><p>Hello</p><script>evil</script></main>",
            )
        )
        with (
            self.dns(),
            patch.object(web_docs, "PublicTransport", return_value=transport),
        ):
            result = web_docs.fetch_web_docs("https://example.com/docs")
            self.assertIn("# Docs", result)
            self.assertNotIn("noise", result)
            self.assertNotIn("evil", result)
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/plain"}, text="12345"
            )
        )
        with (
            self.dns(),
            patch.object(web_docs, "PublicTransport", return_value=transport),
            patch.object(web_docs, "WEB_MAX_BYTES", 4),
            self.assertRaises(ValueError),
        ):
            web_docs.fetch_web_docs("https://example.com")

    def test_redirect_to_private_is_blocked(self):
        def resolve(host, *args, **kwargs):
            address = "127.0.0.1" if host == "internal.invalid" else "93.184.216.34"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                302, headers={"location": "http://internal.invalid/secret"}
            )
        )
        with (
            patch.object(socket, "getaddrinfo", side_effect=resolve),
            patch.object(web_docs, "PublicTransport", return_value=transport),
            self.assertRaises(ValueError),
        ):
            web_docs.fetch_web_docs("https://example.com")

    def test_nontext_and_compressed_responses_are_rejected(self):
        import gzip

        for headers, content in (
            ({"content-type": "application/octet-stream"}, b"binary"),
            (
                {"content-type": "text/plain", "content-encoding": "gzip"},
                gzip.compress(b"text"),
            ),
        ):
            transport = httpx.MockTransport(
                lambda request, headers=headers, content=content: httpx.Response(
                    200, headers=headers, content=content
                )
            )
            with (
                self.dns(),
                patch.object(web_docs, "PublicTransport", return_value=transport),
                self.assertRaises(ValueError),
            ):
                web_docs.fetch_web_docs("https://example.com")

    def test_connection_uses_validated_numeric_ip(self):
        with (
            self.dns(),
            patch.object(
                web_docs.httpcore.SyncBackend, "connect_tcp", return_value="stream"
            ) as connect,
        ):
            self.assertEqual(
                web_docs.PublicNetworkBackend().connect_tcp("example.com", 443),
                "stream",
            )
            self.assertEqual(connect.call_args.args[0], "93.184.216.34")


class Phase3DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_qa_web_and_memory_dispatch(self):
        import asyncio
        import json

        from mcp.server.mcpserver import MCPServer

        from my_mcp_agent.resources.memory import register_memory_resources

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "sample.py").write_text("answer = 42\n")
            (root / "GDD.md").write_text("Milestone island game")
            with (
                patch.object(config, "ALLOWED_WORKSPACE", root),
                patch.object(security, "ALLOWED_WORKSPACE", root),
            ):
                server = MCPServer("Phase3Milestone")
                qa_runner.register_qa_tools(server)
                external.register_external_tools(server)
                register_memory_resources(server)
                names = {tool.name for tool in await server.list_tools()}
                self.assertTrue(
                    {"run_linter", "run_tests", "fetch_web_docs", "run_blender_script"}
                    <= names
                )
                result = await asyncio.wait_for(
                    server.call_tool("run_linter", {"rel_path": "sample.py"}), 40
                )
                self.assertFalse(result.is_error)
                text = next(
                    block.text for block in result.content if hasattr(block, "text")
                )
                self.assertTrue(json.loads(text)["passed"])
                transport = httpx.MockTransport(
                    lambda request: httpx.Response(
                        200,
                        headers={"content-type": "text/html"},
                        text="<main><h1>Milestone docs</h1></main>",
                    )
                )
                with (
                    patch.object(
                        socket,
                        "getaddrinfo",
                        return_value=[
                            (
                                socket.AF_INET,
                                socket.SOCK_STREAM,
                                6,
                                "",
                                ("93.184.216.34", 443),
                            )
                        ],
                    ),
                    patch.object(web_docs, "PublicTransport", return_value=transport),
                ):
                    docs = await asyncio.wait_for(
                        server.call_tool(
                            "fetch_web_docs", {"url": "https://example.com"}
                        ),
                        10,
                    )
                self.assertFalse(docs.is_error)
                self.assertIn("Milestone docs", docs.content[0].text)
                memory = list(
                    await asyncio.wait_for(
                        server.read_resource("studio://memory/architecture"), 10
                    )
                )
                self.assertEqual(memory[0].mime_type, "text/markdown")
                self.assertIn("Milestone island game", memory[0].content)


if __name__ == "__main__":
    unittest.main()
