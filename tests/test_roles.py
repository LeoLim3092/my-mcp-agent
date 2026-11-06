"""Trusted role loading and dispatcher authorization regressions."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml
from pydantic import ValidationError

from my_mcp_agent import roles
from my_mcp_agent.authorization import (
    RoleAccessDenied,
    RoleCallLimitError,
    RoleDispatcher,
)
from my_mcp_agent.roles import RoleName, RoleProfile, load_role


def fake_session():
    return SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(
                tools=[
                    SimpleNamespace(name=name)
                    for name in ("read_file", "write_file", "log_task_usage")
                ]
            )
        ),
        list_resources=AsyncMock(
            return_value=SimpleNamespace(
                resources=[
                    SimpleNamespace(uri=uri)
                    for uri in (
                        "studio://memory/architecture",
                        "studio://telemetry/budget",
                    )
                ]
            )
        ),
        call_tool=AsyncMock(return_value="tool-result"),
        read_resource=AsyncMock(return_value="resource-result"),
    )


class RoleLoadingTests(unittest.TestCase):
    def test_all_profiles_are_provider_neutral_and_within_ceiling(self):
        for name in RoleName:
            with self.subTest(role=name):
                profile = load_role(name)
                self.assertEqual(profile.name, name)
                self.assertTrue(profile.allowed_tools <= roles.TOOL_CEILINGS[name])
                self.assertNotIn("log_task_usage", profile.allowed_tools)
                self.assertNotIn("studio://telemetry/budget", profile.allowed_resources)
                self.assertNotIn("model", profile.model_dump())
                with self.assertRaises(ValidationError):
                    profile.max_tool_calls = 100
                self.assertIsInstance(profile.allowed_tools, frozenset)

    def test_role_names_do_not_accept_paths(self):
        with patch.object(roles.os, "open") as opened:
            for name in ("../writer", "/etc/passwd", "programmer.yaml", "unknown"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    load_role(name)
            opened.assert_not_called()

    def test_schema_rejects_escalation_providers_and_invalid_limits(self):
        original = load_role("qa").model_dump()
        for change in (
            {"allowed_tools": {"write_file"}},
            {"allowed_tools": {"log_task_usage"}},
            {"allowed_resources": {"studio://telemetry/budget"}},
            {"model": "chosen-model"},
            {"provider": "chosen-provider"},
            {"max_steps": 0},
            {"max_tool_calls": True},
            {"max_resource_reads": 101},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                RoleProfile.model_validate({**original, **change})

    def test_yaml_loader_rejects_unsafe_tags_name_mismatch_and_oversize(self):
        original = load_role("writer").model_dump(mode="json")
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(roles, "ROLE_DIRECTORY", Path(directory)),
        ):
            path = Path(directory) / "writer.yaml"
            path.write_text("!!python/object/apply:os.system ['exit 1']")
            with self.assertRaises(yaml.YAMLError):
                load_role("writer")
            path.write_text(yaml.safe_dump({**original, "name": "qa"}))
            with self.assertRaises(ValueError):
                load_role("writer")
            path.write_bytes(b" " * 65_537)
            with self.assertRaises(ValueError):
                load_role("writer")

    def test_yaml_loader_rejects_linked_profiles(self):
        data = yaml.safe_dump(load_role("writer").model_dump(mode="json"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.yaml"
            outside.write_text(data)
            profiles = root / "profiles"
            profiles.mkdir()
            path = profiles / "writer.yaml"
            with patch.object(roles, "ROLE_DIRECTORY", profiles):
                path.symlink_to(outside)
                with self.assertRaises(OSError):
                    load_role("writer")
                path.unlink()
                path.hardlink_to(outside)
                with self.assertRaises(ValueError):
                    load_role("writer")


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_is_filtered_and_forged_calls_never_reach_session(self):
        session = fake_session()
        dispatcher = RoleDispatcher(session, load_role("qa"))
        self.assertEqual(
            [tool.name for tool in await dispatcher.list_tools()], ["read_file"]
        )
        self.assertEqual(
            [str(resource.uri) for resource in await dispatcher.list_resources()],
            ["studio://memory/architecture"],
        )
        for name in (
            "write_file",
            "log_task_usage",
            "run_blender_script",
            "../write_file",
            "unknown",
        ):
            with self.subTest(name=name), self.assertRaises(RoleAccessDenied):
                await dispatcher.call_tool(name, {})
        session.call_tool.assert_not_awaited()
        for uri in (
            "studio://telemetry/budget",
            "studio://memory/architecture/../budget",
            "file:///etc/passwd",
        ):
            with self.subTest(uri=uri), self.assertRaises(RoleAccessDenied):
                await dispatcher.read_resource(uri)
        session.read_resource.assert_not_awaited()
        self.assertEqual(
            await dispatcher.call_tool("read_file", {"rel_path": "GDD.md"}),
            "tool-result",
        )
        self.assertEqual(
            await dispatcher.read_resource("studio://memory/architecture"),
            "resource-result",
        )

    async def test_scope_verification_rejects_operator_or_mismatched_server(self):
        session = fake_session()
        dispatcher = RoleDispatcher(session, load_role("qa"))
        with self.assertRaises(RoleAccessDenied):
            await dispatcher.verify_server_scope()
        profile = load_role("qa")
        session.list_tools.return_value = SimpleNamespace(
            tools=[SimpleNamespace(name=name) for name in profile.allowed_tools]
        )
        session.list_resources.return_value = SimpleNamespace(
            resources=[SimpleNamespace(uri=uri) for uri in profile.allowed_resources]
        )
        await dispatcher.verify_server_scope()

    async def test_role_argument_cannot_change_assigned_permissions(self):
        dispatcher = RoleDispatcher(fake_session(), load_role("qa"))
        await dispatcher.call_tool(
            "read_file", {"rel_path": "GDD.md", "role": "programmer"}
        )
        with self.assertRaises(RoleAccessDenied):
            await dispatcher.call_tool(
                "write_file", {"rel_path": "GDD.md", "content": "bad"}
            )
        self.assertEqual(dispatcher.profile.name, RoleName.QA)

    async def test_limits_are_atomic_and_failed_calls_count(self):
        profile = RoleProfile.model_validate(
            {
                **load_role("qa").model_dump(),
                "max_tool_calls": 2,
                "max_resource_reads": 1,
            }
        )
        session = fake_session()
        dispatcher = RoleDispatcher(session, profile)
        results = await asyncio.gather(
            *(dispatcher.call_tool("read_file", {}) for _ in range(10)),
            return_exceptions=True,
        )
        self.assertEqual(results.count("tool-result"), 2)
        self.assertEqual(
            sum(isinstance(result, RoleCallLimitError) for result in results), 8
        )
        self.assertEqual(session.call_tool.await_count, 2)
        session.read_resource.side_effect = RuntimeError("simulated failure")
        with self.assertRaises(RuntimeError):
            await dispatcher.read_resource("studio://memory/architecture")
        with self.assertRaises(RoleCallLimitError):
            await dispatcher.read_resource("studio://memory/architecture")
        self.assertEqual(session.read_resource.await_count, 1)

    async def test_dispatcher_revalidates_profiles_built_without_validation(self):
        tampered = load_role("qa").model_copy(
            update={"allowed_tools": frozenset({"write_file"})}
        )
        with self.assertRaises(ValidationError):
            RoleDispatcher(fake_session(), tampered)


if __name__ == "__main__":
    unittest.main()
