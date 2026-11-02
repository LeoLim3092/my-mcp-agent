"""Read-only hardware telemetry visible to the MCP server process."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import psutil
from mcp.server.mcpserver import MCPServer

from my_mcp_agent.config import DAILY_BUDGET_USD
from my_mcp_agent.ledger import get_budget_summary

WINDOWS_DRIVE_PATH = Path("/mnt/c")


def _disk_usage(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return {"available": False, "reason": "Disk usage could not be read."}
    return {
        "available": True,
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
    }


def get_hardware_telemetry() -> dict:
    """Sample CPU over 0.1 seconds; report RAM/disk capacities in bytes.

    System measurements describe the environment visible to this process, not
    necessarily the entire Windows host. Under standard WSL mounts, Windows C:
    is reported separately; an absent drive is explicitly marked unavailable.
    No workspace creation, shell commands, or file content reads are required.
    """
    memory = psutil.virtual_memory()
    disks = {"system": _disk_usage(Path(Path.home().anchor))}
    if os.name != "nt" and os.path.ismount(WINDOWS_DRIVE_PATH):
        disks["windows_c"] = _disk_usage(WINDOWS_DRIVE_PATH)
    else:
        disks["windows_c"] = {
            "available": False,
            "reason": "A separate Windows C: mount is not available at /mnt/c.",
        }
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cpu": {
            "usage_percent": psutil.cpu_percent(interval=0.1),
            "logical_count": psutil.cpu_count(logical=True),
            "sample_interval_seconds": 0.1,
        },
        "memory": {
            "total_bytes": memory.total,
            "available_bytes": memory.available,
            "usage_percent": memory.percent,
        },
        "disks": disks,
    }


def register_telemetry_resources(mcp: MCPServer) -> None:
    @mcp.resource("studio://telemetry/status")
    def get_studio_status() -> str:
        """Basic studio health check."""
        return f"Telemetry online. Daily budget cap: ${DAILY_BUDGET_USD:.2f}"

    @mcp.resource("studio://telemetry/hardware", mime_type="application/json")
    def hardware_resource() -> str:
        """Live CPU usage, available RAM, and system/WSL Windows disk space."""
        return json.dumps(get_hardware_telemetry(), indent=2, allow_nan=False)

    @mcp.resource("studio://telemetry/budget", mime_type="application/json")
    def budget_resource() -> str:
        """Today's recorded token usage and spend against the UTC daily limit."""
        return json.dumps(get_budget_summary(), indent=2, allow_nan=False)
