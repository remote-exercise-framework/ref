"""
Global counter for unique Docker bridge names in parallel tests.

Bridge names have a 15-character Linux kernel limit. This module provides
a file-based counter with locking to ensure unique bridge IDs across
parallel test instances.

Bridge naming scheme:
- Test: br-reft-XXX-YY (e.g., br-reft-001-ws)
- Prod: br-YY-ref (e.g., br-ws-ref)

The 'reft' prefix identifies test bridges for cleanup.
"""

import fcntl
import subprocess
from pathlib import Path

COUNTER_FILE = Path("/tmp/ref_test_bridge_counter")
LOCK_FILE = Path("/tmp/ref_test_bridge_counter.lock")


def get_next_bridge_id() -> int:
    """Get next unique bridge ID using file-based counter with locking."""
    LOCK_FILE.touch(exist_ok=True)
    with open(LOCK_FILE, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            if COUNTER_FILE.exists():
                count = int(COUNTER_FILE.read_text().strip() or "0")
            else:
                count = 0
            count += 1
            COUNTER_FILE.write_text(str(count))
            return count
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def reset_bridge_counter() -> None:
    """Reset the bridge counter to 0. Call at start of test session."""
    LOCK_FILE.touch(exist_ok=True)
    with open(LOCK_FILE, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            COUNTER_FILE.write_text("0")
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def cleanup_test_bridges() -> int:
    """
    Remove all Docker bridges with test prefix (br-reft-).
    Returns the number of bridges removed.
    """
    result = subprocess.run(
        ["ip", "link", "show", "type", "bridge"],
        capture_output=True,
        text=True,
    )

    removed = 0
    for line in result.stdout.split("\n"):
        if "br-reft-" in line:
            # Extract bridge name: "123: br-reft-001-ws: <..."
            parts = line.split(":")
            if len(parts) >= 2:
                name = parts[1].strip().split("@")[0]
                delete_result = subprocess.run(
                    ["sudo", "ip", "link", "delete", name],
                    capture_output=True,
                    check=False,
                )
                if delete_result.returncode == 0:
                    removed += 1

    return removed
