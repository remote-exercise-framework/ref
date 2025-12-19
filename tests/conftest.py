"""
REF E2E Test Configuration and Fixtures

All E2E tests automatically start and manage their own REF instance.
The instance is started once per test session and cleaned up afterwards.

No manual startup is required - tests are fully self-contained.
"""

from __future__ import annotations

import atexit
import os
import re
import signal

# Enable standalone testing mode BEFORE any ref imports
# This allows unit tests to import ref.* modules without requiring
# environment variables like POSTGRES_USER to be set
os.environ.setdefault("REF_STANDALONE_TESTING", "1")
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any, Callable, Dict, Generator, List, Optional

import pytest
from pytest import Config, Item, Session, TempPathFactory

if TYPE_CHECKING:
    from helpers.ssh_client import REFSSHClient
    from helpers.web_client import REFWebClient

# Add the webapp directory to the path for imports
WEBAPP_DIR = Path(__file__).parent.parent / "webapp"
sys.path.insert(0, str(WEBAPP_DIR))

# Import REF instance management (must be after sys.path modification)
from helpers.ref_instance import (  # noqa: E402
    REFInstance,
    REFInstanceConfig,
    REFInstanceManager,
    cleanup_docker_resources_by_prefix,
)
from test_config import generate_test_prefix  # noqa: E402

# =============================================================================
# Emergency Cleanup on Unexpected Exit
# =============================================================================

# Track the active REF instance for emergency cleanup
_cleanup_instance: Optional[REFInstance] = None
_cleanup_registered: bool = False
# Track the current session's prefix for cleanup at session end
_current_session_prefix: Optional[str] = None


def _emergency_cleanup(
    signum: Optional[int] = None, frame: Optional[FrameType] = None
) -> None:
    """Emergency cleanup on signal or exit.

    This function is called when:
    - SIGTERM/SIGINT is received
    - The process exits via atexit

    It ensures Docker resources are cleaned up even if pytest crashes
    or is killed unexpectedly.
    """
    global _cleanup_instance
    if _cleanup_instance is not None:
        try:
            print(
                f"\n[REF E2E] Emergency cleanup triggered: {_cleanup_instance.prefix}"
            )
            _cleanup_instance.cleanup()
        except Exception as e:
            print(f"[REF E2E] Emergency cleanup failed: {e}")
            # Try prefix-based cleanup as fallback
            try:
                cleanup_docker_resources_by_prefix(_cleanup_instance.prefix)
            except Exception:
                pass
        finally:
            _cleanup_instance = None

    if signum is not None:
        # Re-raise the signal after cleanup
        sys.exit(128 + signum)


def _register_cleanup_handlers() -> None:
    """Register signal handlers and atexit for emergency cleanup.

    Only registers once, even if called multiple times.
    """
    global _cleanup_registered
    if _cleanup_registered:
        return

    # Register signal handlers for graceful termination
    signal.signal(signal.SIGTERM, _emergency_cleanup)
    signal.signal(signal.SIGINT, _emergency_cleanup)

    # Register atexit handler for unexpected exits
    atexit.register(_emergency_cleanup)

    _cleanup_registered = True


# =============================================================================
# PID-Based Orphaned Resource Cleanup
# =============================================================================

# Regex pattern for extracting PID from test prefixes
# Matches: ref_test_20251218_193859_12345_abc123 or ref_e2e_20251218_193859_12345_abc123
# Groups: (full_prefix, pid)
_PREFIX_PID_PATTERN = re.compile(r"(ref_(?:test|e2e)_\d{8}_\d{6}_(\d+)_[a-f0-9]+)")


def _is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists, False otherwise.
    """
    try:
        # Sending signal 0 doesn't actually send a signal, but checks if process exists
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        # Process doesn't exist
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True


def cleanup_orphaned_resources_by_pid() -> int:
    """Remove test resources whose creator process is no longer running.

    This handles cleanup when tests are killed with SIGKILL or crash
    without running cleanup code. Resources are identified by their
    embedded PID in the prefix.

    Returns:
        Number of orphaned prefixes cleaned up.
    """
    orphaned_prefixes: set[str] = set()

    # Find orphaned containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for name in result.stdout.strip().split("\n"):
            if not name:
                continue
            match = _PREFIX_PID_PATTERN.search(name)
            if match:
                prefix = match.group(1)
                pid = int(match.group(2))
                if not _is_process_alive(pid):
                    orphaned_prefixes.add(prefix)
    except subprocess.CalledProcessError:
        pass

    # Find orphaned networks
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for name in result.stdout.strip().split("\n"):
            if not name:
                continue
            match = _PREFIX_PID_PATTERN.search(name)
            if match:
                prefix = match.group(1)
                pid = int(match.group(2))
                if not _is_process_alive(pid):
                    orphaned_prefixes.add(prefix)
    except subprocess.CalledProcessError:
        pass

    # Find orphaned volumes
    try:
        result = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for name in result.stdout.strip().split("\n"):
            if not name:
                continue
            match = _PREFIX_PID_PATTERN.search(name)
            if match:
                prefix = match.group(1)
                pid = int(match.group(2))
                if not _is_process_alive(pid):
                    orphaned_prefixes.add(prefix)
    except subprocess.CalledProcessError:
        pass

    # Clean up all orphaned prefixes
    for prefix in orphaned_prefixes:
        print(f"[REF E2E] Cleaning orphaned resources (PID dead): {prefix}")
        cleanup_docker_resources_by_prefix(prefix)

    return len(orphaned_prefixes)


# =============================================================================
# Coverage Collection
# =============================================================================

COVERAGE_OUTPUT_DIR = Path(__file__).parent / "coverage_reports"

# =============================================================================
# Container Log Collection for Debugging
# =============================================================================

LOG_OUTPUT_DIR = Path(__file__).parent / "container_logs"
FAILURE_LOG_DIR = Path(__file__).parent / "failure_logs"


def save_container_logs(instance: "REFInstance") -> None:
    """Save container logs to files for debugging failed tests.

    Logs are saved to tests/container_logs/{prefix}_{service}.log
    """
    LOG_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    services = ["web", "sshserver", "db", "ssh-proxy"]

    for service in services:
        try:
            logs = instance.logs(tail=1000)
            log_file = LOG_OUTPUT_DIR / f"{instance.prefix}_{service}.log"
            log_file.write_text(logs)
            print(f"[REF E2E] Saved {service} logs to {log_file}")
        except Exception as e:
            print(f"[REF E2E] Warning: Failed to save {service} logs: {e}")

    # Also save combined logs
    try:
        logs = instance.logs(tail=5000)
        log_file = LOG_OUTPUT_DIR / f"{instance.prefix}_all.log"
        log_file.write_text(logs)
        print(f"[REF E2E] Saved combined logs to {log_file}")
    except Exception as e:
        print(f"[REF E2E] Warning: Failed to save combined logs: {e}")


def save_failure_logs(
    test_name: str,
    test_error: str,
    instance: Optional["REFInstance"],
) -> Path:
    """Save test failure information and container logs for post-mortem analysis.

    Creates a timestamped directory containing:
    - error.txt: The test error/traceback
    - container_logs.txt: Container logs at time of failure

    Args:
        test_name: Name of the failed test
        test_error: The error message and traceback
        instance: The REF instance (if available)

    Returns:
        Path to the failure log directory
    """
    from datetime import datetime

    FAILURE_LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Create a unique directory for this failure
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize test name for filesystem
    safe_test_name = re.sub(r"[^\w\-]", "_", test_name)[:100]
    failure_dir = FAILURE_LOG_DIR / f"{timestamp}_{safe_test_name}"
    failure_dir.mkdir(parents=True, exist_ok=True)

    # Save test error/traceback
    error_file = failure_dir / "error.txt"
    error_content = f"Test: {test_name}\nTimestamp: {timestamp}\n\n{'=' * 60}\nERROR:\n{'=' * 60}\n\n{test_error}"
    error_file.write_text(error_content)
    print(f"[REF E2E] Saved test error to {error_file}")

    # Save container logs if instance is available
    if instance is not None:
        try:
            logs = instance.logs(tail=2000)
            log_file = failure_dir / "container_logs.txt"
            log_content = f"Container logs for test: {test_name}\nInstance prefix: {instance.prefix}\nTimestamp: {timestamp}\n\n{'=' * 60}\nLOGS:\n{'=' * 60}\n\n{logs}"
            log_file.write_text(log_content)
            print(f"[REF E2E] Saved container logs to {log_file}")
        except Exception as e:
            # Save error message if logs couldn't be retrieved
            log_file = failure_dir / "container_logs.txt"
            log_file.write_text(f"Failed to retrieve container logs: {e}")
            print(f"[REF E2E] Warning: Failed to save container logs: {e}")

    return failure_dir


# Track collected container coverage files for merging at session end
_container_coverage_files: List[Path] = []


def collect_coverage_from_containers(instance: REFInstance) -> Path:
    """Copy coverage files from Docker volume and student containers to host.

    Coverage files are copied to the main coverage_reports directory so they
    can be merged with pytest-cov coverage from unit tests.
    """
    COVERAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Collect from infrastructure containers (shared Docker volume)
    volume_name = f"{instance.prefix}_coverage_data"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{volume_name}:/coverage-data:ro",
                "-v",
                f"{COVERAGE_OUTPUT_DIR}:/output:rw",
                "alpine",
                "sh",
                "-c",
                "cp /coverage-data/.coverage* /output/ 2>/dev/null || true",
            ],
            check=False,
            capture_output=True,
        )
    except Exception as e:
        print(f"[Coverage] Warning: Failed to collect from volume: {e}")

    # 2. Collect from student container shared folders
    # Student coverage is written to /shared/.coverage.* which maps to
    # {data_dir}/persistance/*/instances/*/shared-folder/.coverage.*
    data_dir = instance.data_dir
    try:
        for cov_file in data_dir.glob(
            "persistance/*/instances/*/shared-folder/.coverage*"
        ):
            dest = COVERAGE_OUTPUT_DIR / cov_file.name
            shutil.copy(cov_file, dest)
            _container_coverage_files.append(dest)
    except Exception as e:
        print(f"[Coverage] Warning: Failed to collect from student containers: {e}")

    # Track infrastructure coverage files
    for cov_file in COVERAGE_OUTPUT_DIR.glob(".coverage.*"):
        if cov_file not in _container_coverage_files:
            _container_coverage_files.append(cov_file)

    return COVERAGE_OUTPUT_DIR


def combine_all_coverage() -> None:
    """Combine all coverage files (unit tests + container coverage) and generate reports.

    This is called at the end of the test session to merge:
    - pytest-cov coverage from unit tests (host)
    - Container coverage from e2e tests (Docker)
    """
    if not COVERAGE_OUTPUT_DIR.exists():
        return

    coverage_files = list(COVERAGE_OUTPUT_DIR.glob(".coverage*"))
    if not coverage_files:
        print("[Coverage] No coverage data found to combine")
        return

    print(f"[Coverage] Found {len(coverage_files)} coverage files to combine")

    orig_dir = os.getcwd()
    try:
        os.chdir(COVERAGE_OUTPUT_DIR)

        # Combine all coverage files
        try:
            result = subprocess.run(
                ["coverage", "combine", "--keep"],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print("[Coverage] Warning: 'coverage' command not found in PATH")
            return
        if result.returncode != 0:
            # Try without --keep for older coverage versions
            result = subprocess.run(
                ["coverage", "combine"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                print(f"[Coverage] Warning: coverage combine failed: {result.stderr}")
                return

        # Generate HTML report
        subprocess.run(
            ["coverage", "html", "-d", "htmlcov"],
            check=False,
            capture_output=True,
        )

        # Generate XML report (Cobertura format)
        subprocess.run(
            ["coverage", "xml", "-o", "coverage.xml"],
            check=False,
            capture_output=True,
        )

        # Print summary report
        result = subprocess.run(
            ["coverage", "report"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"\n[Coverage] Combined Coverage Summary:\n{result.stdout}")
        else:
            print(f"[Coverage] Warning: coverage report failed: {result.stderr}")

    finally:
        os.chdir(orig_dir)


# =============================================================================
# Managed REF Instance - Automatically started for E2E tests
# =============================================================================


@pytest.fixture(scope="session")
def ref_instance(
    tmp_path_factory: TempPathFactory,
) -> Generator[REFInstance, None, None]:
    """
    Provides a managed REF instance for the test session.

    The instance is automatically:
    - Started before E2E tests run
    - Cleaned up after tests complete

    All E2E test fixtures use this instance for:
    - web_url
    - ssh_host / ssh_port
    - admin_password
    - exercises_path
    """
    global _cleanup_instance, _current_session_prefix

    # Register emergency cleanup handlers (signal handlers + atexit)
    _register_cleanup_handlers()

    # Create temp directories for this test session
    session_id = generate_test_prefix()
    exercises_dir = tmp_path_factory.mktemp("exercises")
    data_dir = tmp_path_factory.mktemp("data")

    config = REFInstanceConfig(
        prefix=f"ref_e2e_{session_id}",
        exercises_dir=exercises_dir,
        data_dir=data_dir,
        testing=True,
        debug=True,
        disable_telegram=True,
        startup_timeout=180.0,  # Allow more time for initial startup
    )

    instance = REFInstance(config)

    # Track instance for emergency cleanup (SIGTERM, SIGINT, atexit)
    _cleanup_instance = instance
    _current_session_prefix = instance.prefix

    try:
        # Build and start the instance
        print(f"\n[REF E2E] Starting managed REF instance: {instance.prefix}")
        print(f"[REF E2E] Web URL will be: {instance.web_url}")
        print(f"[REF E2E] SSH port will be: {instance.ssh_port}")
        print(f"[REF E2E] Exercises dir: {exercises_dir}")

        instance.start(build=True, wait=True)

        print("[REF E2E] Instance started successfully")
        yield instance

    except Exception as e:
        print(f"[REF E2E] Failed to start instance: {e}")
        # Try to get logs for debugging
        try:
            logs = instance.logs(tail=100)
            print(f"[REF E2E] Container logs:\n{logs}")
        except Exception:
            pass
        raise
    finally:
        # Save container logs before stopping for debugging
        print("[REF E2E] Saving container logs for debugging...")
        save_container_logs(instance)

        print(
            f"[REF E2E] Stopping instance gracefully for coverage flush: {instance.prefix}"
        )
        # Stop gracefully to allow coverage data to be flushed
        instance.stop(timeout=10)
        time.sleep(3)  # Allow time for coverage data to be written

        # Collect coverage from containers (will be merged at session end)
        print("[REF E2E] Collecting container coverage data...")
        collect_coverage_from_containers(instance)

        print(f"[REF E2E] Cleaning up instance: {instance.prefix}")
        instance.cleanup()

        # Clear emergency cleanup tracking (normal cleanup completed)
        _cleanup_instance = None


# =============================================================================
# Core Fixtures - Use managed instance
# =============================================================================


@pytest.fixture(scope="session")
def web_url(ref_instance: REFInstance) -> str:
    """Returns the web interface URL from the managed instance."""
    return ref_instance.web_url


@pytest.fixture(scope="session")
def ssh_host(ref_instance: REFInstance) -> str:
    """Returns the SSH server host from the managed instance."""
    return ref_instance.ssh_host


@pytest.fixture(scope="session")
def ssh_port(ref_instance: REFInstance) -> int:
    """Returns the SSH server port from the managed instance."""
    return ref_instance.ssh_port


@pytest.fixture(scope="session")
def admin_password(ref_instance: REFInstance) -> str:
    """Returns the admin password from the managed instance."""
    return ref_instance.admin_password


@pytest.fixture(scope="session")
def exercises_path(ref_instance: REFInstance) -> Path:
    """Returns the path to the exercises directory."""
    return ref_instance.exercises_dir


@pytest.fixture(scope="session")
def test_config(ref_instance: REFInstance) -> Dict[str, Any]:
    """Returns the test configuration dictionary."""
    return {
        "web_url": ref_instance.web_url,
        "ssh_host": ref_instance.ssh_host,
        "ssh_port": ref_instance.ssh_port,
        "admin_password": ref_instance.admin_password,
        "exercises_path": str(ref_instance.exercises_dir),
        "resource_prefix": ref_instance.prefix,
    }


# =============================================================================
# Client Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def web_client(ref_instance: REFInstance) -> Generator["REFWebClient", None, None]:
    """
    Creates an HTTP client for interacting with the REF web interface.
    """
    from helpers.web_client import REFWebClient

    client = REFWebClient(ref_instance.web_url)
    yield client
    client.close()


@pytest.fixture(scope="session")
def admin_client(
    web_client: "REFWebClient", admin_password: str
) -> Generator["REFWebClient", None, None]:
    """
    Creates an authenticated admin client.
    """
    # Login as admin (mat_num=0)
    success = web_client.login("0", admin_password)
    if not success:
        pytest.fail("Failed to login as admin")
    yield web_client


@pytest.fixture(scope="function")
def ssh_client_factory(
    ssh_host: str, ssh_port: int
) -> Generator[Callable[[str, str], "REFSSHClient"], None, None]:
    """
    Factory fixture for creating SSH clients.
    Returns a function that creates SSH connections with given credentials.
    """
    from helpers.ssh_client import REFSSHClient

    clients: List[REFSSHClient] = []

    def _create_client(private_key: str, exercise_name: str) -> REFSSHClient:
        client = REFSSHClient(ssh_host, ssh_port)
        client.connect(private_key, exercise_name)
        clients.append(client)
        return client

    yield _create_client

    # Cleanup: close all clients
    for client in clients:
        try:
            client.close()
        except Exception:
            pass


# =============================================================================
# Test Helpers
# =============================================================================


@pytest.fixture(scope="session")
def sample_exercise_path(
    tmp_path_factory: TempPathFactory, exercises_path: Path
) -> Path:
    """
    Creates a sample exercise for testing.
    Returns the path to the exercise directory.
    """
    from helpers.exercise_factory import create_sample_exercise

    exercise_dir = exercises_path / "sample_test_exercise"
    create_sample_exercise(exercise_dir)
    return exercise_dir


@pytest.fixture(scope="function")
def unique_test_id() -> str:
    """
    Returns a unique ID for each test.
    Useful for creating unique usernames, exercise names, etc.
    """
    import uuid

    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def resource_prefix(ref_instance: REFInstance) -> str:
    """Returns the unique resource prefix for this test run."""
    return ref_instance.prefix


# =============================================================================
# Pytest Configuration
# =============================================================================


def pytest_configure(config: Config) -> None:
    """
    Configure pytest markers.
    """
    config.addinivalue_line("markers", "e2e: end-to-end tests")
    config.addinivalue_line("markers", "unit: unit tests")
    config.addinivalue_line("markers", "slow: slow running tests")
    config.addinivalue_line(
        "markers", "offline: tests that do not require REF to be running"
    )
    config.addinivalue_line(
        "markers", "needs_ref: tests that require REF to be running"
    )


def pytest_collection_modifyitems(config: Config, items: List[Item]) -> None:
    """
    Automatically mark all tests based on directory.
    """
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
        elif "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)


# =============================================================================
# REF Instance Management Fixtures (for advanced use cases)
# =============================================================================


@pytest.fixture(scope="session")
def ref_instance_manager() -> Generator[REFInstanceManager, None, None]:
    """
    Provides a session-scoped instance manager for creating additional REF instances.

    Use this when you need to run multiple instances in parallel for isolation testing.

    Usage:
        def test_something(ref_instance_manager):
            instance = ref_instance_manager.create_instance("my_test")
            instance.start()
            # ... tests ...
    """
    manager = REFInstanceManager(base_prefix="ref_test")
    yield manager
    manager.cleanup_all()


@pytest.fixture(scope="function")
def fresh_ref_instance(
    ref_instance_manager: REFInstanceManager, unique_test_id: str
) -> Generator[REFInstance, None, None]:
    """
    Provides a fresh REF instance for each test function.

    WARNING: This is expensive! Each test gets its own instance.
    Use only when tests need complete isolation.

    Usage:
        @pytest.mark.slow
        def test_with_isolation(fresh_ref_instance):
            instance = fresh_ref_instance
            instance.start()
            # ... tests with clean state ...
    """
    instance = ref_instance_manager.create_instance(name=unique_test_id)
    yield instance
    try:
        instance.cleanup()
    except Exception:
        pass


@pytest.fixture(scope="session")
def ref_instance_factory(
    ref_instance_manager: REFInstanceManager,
) -> Callable[..., REFInstance]:
    """
    Factory fixture for creating REF instances with custom configurations.

    Usage:
        def test_something(ref_instance_factory):
            instance = ref_instance_factory(
                name="custom",
                debug=True,
                exercises_dir=Path("/custom/exercises"),
            )
            instance.start()
            # ... tests ...
            instance.cleanup()
    """

    def _create_instance(
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> REFInstance:
        return ref_instance_manager.create_instance(name=name, **kwargs)

    return _create_instance


# =============================================================================
# Cleanup Utilities
# =============================================================================


def pytest_sessionstart(session: Session) -> None:
    """
    Called at the start of the test session.

    Cleans up stale resources and ensures coverage directory exists.
    """
    # Clean up orphaned Docker resources from previous test runs
    # This catches resources from crashed/killed test runs (SIGKILL, OOM, etc.)
    # by checking if the creator PID is still alive
    print("\n[REF E2E] Cleaning up orphaned Docker resources before tests...")

    orphaned_count = cleanup_orphaned_resources_by_pid()
    if orphaned_count > 0:
        print(f"[REF E2E] Cleaned up {orphaned_count} orphaned resource prefixes")

    # Also clean any legacy resources without timestamps
    cleanup_docker_resources_by_prefix("ref-ressource-")

    # Prune unused Docker networks to avoid IP pool exhaustion
    print("[REF E2E] Pruning unused Docker networks...")
    try:
        subprocess.run(
            ["docker", "network", "prune", "-f"],
            check=False,
            capture_output=True,
        )
    except Exception as e:
        print(f"[REF E2E] Warning: Failed to prune networks: {e}")

    COVERAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def pytest_sessionfinish(session: Session, exitstatus: int) -> None:
    """
    Called after the test session finishes.

    Combines all coverage data and ensures resources are cleaned up.
    """
    # Combine coverage from all sources (unit tests + e2e container coverage)
    print("\n[Coverage] Combining all coverage data...")
    combine_all_coverage()

    # Final cleanup pass for resources
    if os.environ.get("REF_CLEANUP_ON_EXIT", "1") == "1":
        # Clean up current session's resources (safety net if fixture cleanup failed)
        if _current_session_prefix:
            print(f"[REF E2E] Final cleanup for session: {_current_session_prefix}")
            cleanup_docker_resources_by_prefix(_current_session_prefix)

        # Also clean up orphaned resources from crashed runs (PID-based)
        cleanup_orphaned_resources_by_pid()


# =============================================================================
# Test Failure Logging for Post-Mortem Analysis
# =============================================================================


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(
    item: Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, None]:
    """
    Capture test failures and save container logs for post-mortem analysis.

    This hook runs after each test phase (setup, call, teardown) and saves
    failure information including:
    - Test name and location
    - Full error traceback
    - Container logs at the time of failure
    """
    # Execute all other hooks to get the report
    outcome = yield
    report: pytest.TestReport = outcome.get_result()

    # Only process actual test failures (not setup/teardown issues, unless they fail)
    if report.failed:
        # Get the test name
        test_name = item.nodeid

        # Build error message with traceback
        error_parts = []
        error_parts.append(f"Phase: {report.when}")
        error_parts.append(f"Location: {item.location}")

        if report.longreprtext:
            error_parts.append(f"\n{report.longreprtext}")

        error_message = "\n".join(error_parts)

        # Try to get the REF instance from the session
        instance = _cleanup_instance

        # Save failure logs
        try:
            failure_dir = save_failure_logs(test_name, error_message, instance)
            print(f"\n[REF E2E] Test failure logged to: {failure_dir}")
        except Exception as e:
            print(f"\n[REF E2E] Warning: Failed to save failure logs: {e}")
