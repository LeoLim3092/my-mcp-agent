"""Hardware sampling tests without dependence on the developer's hardware."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp.server.mcpserver import MCPServer

from my_mcp_agent.resources import telemetry


class TelemetryTests(unittest.TestCase):
    def sample(self, mounted):
        with (
            patch.object(telemetry.psutil, "virtual_memory", return_value=SimpleNamespace(
                total=1000, available=600, percent=40.0)),
            patch.object(telemetry.psutil, "cpu_percent", return_value=12.5) as cpu,
            patch.object(telemetry.psutil, "cpu_count", return_value=8),
            patch.object(telemetry.os.path, "ismount", return_value=mounted),
            patch.object(telemetry.shutil, "disk_usage", return_value=SimpleNamespace(
                total=2000, used=500, free=1500)),
        ):
            result = telemetry.get_hardware_telemetry()
            cpu.assert_called_once_with(interval=0.1)
            return result

    def test_hardware_units_and_missing_windows_mount(self):
        result = self.sample(False)
        self.assertEqual(result["cpu"]["usage_percent"], 12.5)
        self.assertEqual(result["cpu"]["logical_count"], 8)
        self.assertEqual(result["memory"]["available_bytes"], 600)
        self.assertEqual(result["disks"]["system"]["free_bytes"], 1500)
        self.assertFalse(result["disks"]["windows_c"]["available"])
        self.assertTrue(result["timestamp_utc"].endswith("+00:00"))

    @unittest.skipIf(telemetry.os.name == "nt", "Separate WSL mount is Linux-only")
    def test_windows_mount_is_sampled(self):
        self.assertEqual(self.sample(True)["disks"]["windows_c"]["free_bytes"], 1500)

    def test_disk_error_does_not_report_fake_capacity(self):
        with patch.object(telemetry.shutil, "disk_usage", side_effect=PermissionError):
            result = telemetry._disk_usage(telemetry.WINDOWS_DRIVE_PATH)
        self.assertFalse(result["available"])
        self.assertNotIn("free_bytes", result)

    def test_json_resource_registration_and_callback(self):
        class Registry:
            def __init__(self):
                self.resources = {}

            def resource(self, uri, **kwargs):
                def register(callback):
                    self.resources[uri] = (callback, kwargs)
                    return callback
                return register

        registry = Registry()
        telemetry.register_telemetry_resources(registry)
        callback, metadata = registry.resources["studio://telemetry/hardware"]
        self.assertEqual(metadata["mime_type"], "application/json")
        with patch.object(telemetry, "get_hardware_telemetry", return_value={"cpu": {"usage_percent": 5}}):
            self.assertEqual(json.loads(callback()), {"cpu": {"usage_percent": 5}})
        # Exercise real SDK registration and URI handling without async dispatch.
        telemetry.register_telemetry_resources(MCPServer("TelemetryTest"))


if __name__ == "__main__":
    unittest.main()
