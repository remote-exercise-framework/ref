"""
REF Instance Manager

Manages REF (Remote Exercise Framework) instances for testing and production.
This module provides a Python abstraction for starting, stopping, and managing
REF instances with configurable prefixes for resource isolation.

Features:
- Multiple parallel instances with unique prefixes
- Automatic port allocation
- Docker resource cleanup by prefix
- Support for both testing and production modes

Eventually intended to replace ctrl.sh.
"""

import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

import jinja2

T = TypeVar("T")


def find_free_port(start: int = 10000, end: int = 65000) -> int:
    """Find a free port in the given range."""
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{end}")


def generate_secret(length: int = 32) -> str:
    """Generate a cryptographically secure secret string."""
    return secrets.token_urlsafe(length)


def get_docker_group_id() -> int:
    """Get the docker group ID from the system."""
    try:
        result = subprocess.run(
            ["getent", "group", "docker"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Format: docker:x:GID:members
        return int(result.stdout.strip().split(":")[2])
    except (subprocess.CalledProcessError, IndexError, ValueError):
        raise RuntimeError("Could not determine docker group ID")


@dataclass
class REFInstanceConfig:
    """
    Configuration for a REF instance.

    All instance-specific files are stored in work_dir:
    - work_dir/
      - ssh-keys/           # Container SSH keys
      - ssh-server-keys/    # SSH server host keys
      - data/               # PostgreSQL data, submissions
      - exercises/          # Exercise files
      - docker-compose.yml  # Generated compose file
      - settings.env        # Environment configuration

    This allows multiple instances to run in parallel without conflicts.
    """

    # Instance identification
    prefix: str = field(default_factory=lambda: f"ref_test_{uuid.uuid4().hex[:8]}")
    project_name: Optional[str] = None  # Docker compose project name

    # Paths
    # ref_root points to the REF source code directory
    ref_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)
    # work_dir contains all instance-specific files (auto-created if not specified)
    work_dir: Optional[Path] = None
    # Legacy support - these override work_dir subdirectories if specified
    data_dir: Optional[Path] = None
    exercises_dir: Optional[Path] = None

    # Ports (0 = auto-allocate)
    http_port: int = 0
    ssh_port: int = 0

    # Secrets (auto-generated if not specified)
    admin_password: Optional[str] = None
    secret_key: Optional[str] = None
    ssh_to_web_key: Optional[str] = None
    postgres_password: Optional[str] = None

    # Docker settings
    docker_group_id: Optional[int] = None

    # Mode settings
    testing: bool = True
    debug: bool = True
    maintenance_enabled: bool = False
    disable_telegram: bool = True
    debug_toolbar: bool = False
    hot_reloading: bool = False
    disable_response_caching: bool = False
    binfmt_support: bool = False
    ratelimit_enabled: bool = False  # Disable rate limiting for tests by default

    # Timeouts
    startup_timeout: float = 120.0
    shutdown_timeout: float = 30.0

    def __post_init__(self):
        """Initialize derived values."""
        if self.project_name is None:
            self.project_name = self.prefix

        if self.docker_group_id is None:
            self.docker_group_id = get_docker_group_id()

        # Auto-generate secrets
        if self.admin_password is None:
            self.admin_password = generate_secret(16)
        if self.secret_key is None:
            self.secret_key = generate_secret(32)
        if self.ssh_to_web_key is None:
            self.ssh_to_web_key = generate_secret(32)
        if self.postgres_password is None:
            self.postgres_password = generate_secret(32)


class REFInstance:
    """
    Manages a REF instance lifecycle.

    This class handles:
    - Configuration generation
    - Docker compose file generation
    - Starting/stopping services
    - Port allocation
    - Resource cleanup

    Usage:
        config = REFInstanceConfig(prefix="test_run_1")
        instance = REFInstance(config)

        # Start the instance
        instance.start()

        # Get connection URLs
        print(f"Web: {instance.web_url}")
        print(f"SSH: {instance.ssh_host}:{instance.ssh_port}")

        # Stop and cleanup
        instance.stop()
        instance.cleanup()

    Or use as context manager:
        with REFInstance.create() as instance:
            # instance is started
            ...
        # instance is stopped and cleaned up
    """

    COMPOSE_TEMPLATE = "docker-compose.template.yml"

    def __init__(self, config: Optional[REFInstanceConfig] = None):
        """
        Initialize a REF instance.

        Args:
            config: Instance configuration. If None, uses defaults.
        """
        self.config = config or REFInstanceConfig()
        self._started = False
        self._temp_dirs: List[Path] = []
        self._compose_file: Optional[Path] = None

        # Resolve paths
        self._ref_root = self.config.ref_root.resolve()
        self._setup_directories()
        self._allocate_ports()

    def _setup_directories(self):
        """
        Set up the work directory structure.

        work_dir/
        ├── data/           # Database and persistent data
        ├── exercises/      # Exercise files
        ├── ssh-keys/       # Container SSH keys
        └── ssh-server-keys/# SSH server host keys
        """
        # Set up work directory
        if self.config.work_dir is None:
            self._work_dir = Path(tempfile.gettempdir()) / f"ref_{self.config.prefix}"
            self._work_dir.mkdir(parents=True, exist_ok=True)
            self._temp_dirs.append(self._work_dir)
            self._owns_work_dir = True
        else:
            self._work_dir = self.config.work_dir
            self._work_dir.mkdir(parents=True, exist_ok=True)
            self._owns_work_dir = False

        # Set up subdirectories within work_dir
        # Use explicit config paths if provided, otherwise use work_dir subdirs
        if self.config.data_dir is not None:
            self._data_dir = self.config.data_dir
        else:
            self._data_dir = self._work_dir / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)

        if self.config.exercises_dir is not None:
            self._exercises_dir = self.config.exercises_dir
        else:
            self._exercises_dir = self._work_dir / "exercises"
        self._exercises_dir.mkdir(parents=True, exist_ok=True)

        # SSH keys directories (always in work_dir for isolation)
        self._ssh_keys_dir = self._work_dir / "ssh-keys"
        self._ssh_keys_dir.mkdir(parents=True, exist_ok=True)

        self._ssh_server_keys_dir = self._work_dir / "ssh-server-keys"
        self._ssh_server_keys_dir.mkdir(parents=True, exist_ok=True)

    def _allocate_ports(self):
        """Allocate HTTP and SSH ports.

        Uses worker-specific port ranges when running under pytest-xdist to avoid
        race conditions where multiple workers find the same "free" port.
        """
        # Get pytest-xdist worker ID for deterministic port allocation
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
        try:
            worker_num = int(worker_id.replace("gw", "").replace("master", "0"))
        except ValueError:
            worker_num = 0

        # Each worker gets a range of 100 ports (supports up to 64 workers)
        http_base = 18000 + (worker_num * 100)
        ssh_base = 12000 + (worker_num * 100)

        if self.config.http_port == 0:
            self._http_port = find_free_port(start=http_base, end=http_base + 100)
        else:
            self._http_port = self.config.http_port

        if self.config.ssh_port == 0:
            self._ssh_port = find_free_port(start=ssh_base, end=ssh_base + 100)
        else:
            self._ssh_port = self.config.ssh_port

    @property
    def prefix(self) -> str:
        """Get the instance prefix."""
        return self.config.prefix

    @property
    def project_name(self) -> str:
        """Get the Docker compose project name."""
        assert self.config.project_name is not None  # Set in __post_init__
        return self.config.project_name

    @property
    def http_port(self) -> int:
        """Get the allocated HTTP port."""
        return self._http_port

    @property
    def ssh_port(self) -> int:
        """Get the allocated SSH port."""
        return self._ssh_port

    @property
    def web_url(self) -> str:
        """Get the web interface URL."""
        return f"http://localhost:{self._http_port}"

    @property
    def ssh_host(self) -> str:
        """Get the SSH host."""
        return "localhost"

    @property
    def data_dir(self) -> Path:
        """Get the data directory path."""
        return self._data_dir

    @property
    def exercises_dir(self) -> Path:
        """Get the exercises directory path."""
        return self._exercises_dir

    @property
    def admin_password(self) -> str:
        """Get the admin password."""
        assert self.config.admin_password is not None  # Set in __post_init__
        return self.config.admin_password

    @property
    def is_running(self) -> bool:
        """Check if the instance is running."""
        return self._started

    def _generate_settings_env(self) -> str:
        """Generate the settings.env file content."""
        # Use test prefix for Docker resources so they can be identified and cleaned up
        # The trailing hyphen ensures clean resource names like "ref_e2e_...-entry-123"
        docker_prefix = f"{self.config.prefix}-"
        return f"""# Auto-generated settings for REF test instance: {self.config.prefix}
DEBUG={1 if self.config.debug else 0}
MAINTENANCE_ENABLED={1 if self.config.maintenance_enabled else 0}
RATELIMIT_ENABLED={1 if self.config.ratelimit_enabled else 0}

ADMIN_PASSWORD={self.config.admin_password}
DOCKER_GROUP_ID={self.config.docker_group_id}
SSH_HOST_PORT={self._ssh_port}
HTTP_HOST_PORT={self._http_port}
SECRET_KEY={self.config.secret_key}
SSH_TO_WEB_KEY={self.config.ssh_to_web_key}
POSTGRES_PASSWORD={self.config.postgres_password}
DOCKER_RESSOURCE_PREFIX={docker_prefix}
"""

    def _generate_docker_compose(self) -> str:
        """Generate the docker-compose.yml content."""
        import yaml

        template_path = self._ref_root / self.COMPOSE_TEMPLATE
        if not template_path.exists():
            raise FileNotFoundError(f"Compose template not found: {template_path}")

        template_loader = jinja2.FileSystemLoader(searchpath=str(self._ref_root))
        template_env = jinja2.Environment(loader=template_loader)
        template = template_env.get_template(self.COMPOSE_TEMPLATE)

        # Use prefix-based cgroup names
        cgroup_base = self.config.prefix
        cgroup_parent = f"{cgroup_base}-core.slice"
        instances_cgroup_parent = f"{cgroup_base}-instances.slice"

        # Extract unique bridge ID from prefix (last 6 hex chars) for test network names
        # This allows cleanup of leaked networks while keeping names under 15 char limit
        bridge_id = self.config.prefix[-6:] if self.config.testing else ""

        rendered = template.render(
            testing=self.config.testing,
            prefix=self.config.prefix,
            bridge_id=bridge_id,
            data_path=str(self._data_dir.resolve()),
            exercises_path=str(self._exercises_dir.resolve()),
            cgroup_parent=cgroup_parent,
            instances_cgroup_parent=instances_cgroup_parent,
            binfmt_support=self.config.binfmt_support,
        )

        # For testing, we need to add port mappings that the template skips
        if self.config.testing:
            compose_dict = yaml.safe_load(rendered)

            # Add web port mapping
            if "web" in compose_dict.get("services", {}):
                compose_dict["services"]["web"]["ports"] = [f"{self._http_port}:8000"]

            # Add ssh-reverse-proxy port mapping
            if "ssh-reverse-proxy" in compose_dict.get("services", {}):
                compose_dict["services"]["ssh-reverse-proxy"]["ports"] = [
                    f"{self._ssh_port}:2222"
                ]

            # Add IPAM configuration with smaller subnets (/28) to allow many parallel instances
            # Default Docker uses /16 subnets which limits us to ~15 networks total
            # With /28 subnets (14 usable IPs) we can run many more parallel instances
            if "networks" in compose_dict:
                # Find free subnets by querying existing Docker networks
                free_subnets = self._find_free_subnets(len(compose_dict["networks"]))

                for i, network_name in enumerate(compose_dict["networks"].keys()):
                    subnet, gateway = free_subnets[i]
                    compose_dict["networks"][network_name]["ipam"] = {
                        "config": [{"subnet": subnet, "gateway": gateway}]
                    }

            return yaml.dump(compose_dict, default_flow_style=False)

        return rendered

    def _find_free_subnets(self, count: int) -> List[tuple[str, str]]:
        """Allocate /28 subnets for this instance.

        Uses the 172.80.0.0/12 range (172.80.0.0 - 172.95.255.255) which is
        outside Docker's default pools (172.17-31.x.x).

        To avoid race conditions with concurrent pytest-xdist workers, subnets
        are allocated deterministically based on:
        1. Worker ID (gw0, gw1, etc.) - gives each worker a separate range
        2. Prefix hash - spreads allocations within the worker's range

        Args:
            count: Number of subnets needed

        Returns:
            List of (subnet, gateway) tuples
        """
        import ipaddress

        # Use 172.80.0.0/12 range (outside Docker's default 172.17-31 range)
        # This gives us 172.80.0.0 - 172.95.255.255 (65536 /28 subnets)
        base_network = ipaddress.ip_network("172.80.0.0/12")
        total_subnets = 2 ** (28 - 12)  # 65536 /28 subnets in /12

        # Get pytest-xdist worker ID (gw0, gw1, etc.) or default to "gw0"
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
        # Extract worker number (0, 1, 2, ...)
        try:
            worker_num = int(worker_id.replace("gw", "").replace("master", "0"))
        except ValueError:
            worker_num = 0

        # Divide subnet space among workers (support up to 64 workers)
        max_workers = 64
        subnets_per_worker = total_subnets // max_workers  # 1024 subnets per worker

        # Calculate this worker's subnet range
        worker_base = worker_num * subnets_per_worker

        # Use hash of prefix to pick position within worker's range
        # This ensures different instances on the same worker get different subnets
        prefix_hash = int(hashlib.md5(self.config.prefix.encode()).hexdigest(), 16)
        offset_within_worker = prefix_hash % (subnets_per_worker - count)

        # Allocate consecutive subnets starting from calculated position
        free_subnets: List[tuple[str, str]] = []
        for i in range(count):
            subnet_idx = worker_base + offset_within_worker + i
            addr_int = int(base_network.network_address) + (subnet_idx * 16)
            subnet = ipaddress.ip_network(f"{ipaddress.IPv4Address(addr_int)}/28")
            gateway = str(subnet.network_address + 1)
            free_subnets.append((str(subnet), gateway))

        return free_subnets

    def _generate_ssh_keys(self):
        """Generate SSH keys needed for container communication."""
        container_keys_dir = self._ref_root / "container-keys"
        ref_docker_base_keys = self._ref_root / "ref-docker-base" / "container-keys"

        container_keys_dir.mkdir(parents=True, exist_ok=True)

        for key_name in ["root_key", "user_key"]:
            key_path = container_keys_dir / key_name
            if not key_path.exists():
                subprocess.run(
                    ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key_path)],
                    check=True,
                    capture_output=True,
                )

        # Copy keys to ref-docker-base if it exists
        if ref_docker_base_keys.parent.exists():
            ref_docker_base_keys.mkdir(parents=True, exist_ok=True)
            for key_file in container_keys_dir.iterdir():
                if key_file.name != ".gitkeep":
                    shutil.copy2(key_file, ref_docker_base_keys / key_file.name)

    def _write_config_files(self):
        """Write the configuration files."""
        # Generate SSH keys if they don't exist
        self._generate_ssh_keys()

        # Write settings.env to work dir
        settings_path = self._work_dir / "settings.env"
        settings_path.write_text(self._generate_settings_env())

        # Write docker-compose.yml to work dir (not repo root)
        # The --project-directory flag in _run_compose ensures relative paths
        # in the compose file resolve correctly relative to _ref_root
        self._compose_file = self._work_dir / "docker-compose.yml"
        self._compose_file.write_text(self._generate_docker_compose())

    def _get_docker_compose_cmd(self) -> List[str]:
        """Get the docker compose command."""
        # Try docker compose (v2) first, then docker-compose (v1)
        try:
            subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                check=True,
            )
            return ["docker", "compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        try:
            subprocess.run(
                ["docker-compose", "version"],
                capture_output=True,
                check=True,
            )
            return ["docker-compose"]
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("Docker Compose not found")

    def _run_compose(
        self,
        *args: str,
        check: bool = True,
        capture_output: bool = False,
        env: Optional[Dict[str, str]] = None,
        input: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run a docker compose command."""
        compose_cmd = self._get_docker_compose_cmd()
        settings_file = self._work_dir / "settings.env"

        cmd = [
            *compose_cmd,
            "-p",
            self.project_name,
            "--project-directory",
            str(self._ref_root),
            "-f",
            str(self._compose_file),
            "--env-file",
            str(settings_file),
            *args,
        ]

        # Set up environment
        run_env = os.environ.copy()
        # Use a local docker config directory to avoid read-only filesystem issues
        # with Docker buildx in sandboxed environments
        docker_cache_dir = self._ref_root / ".docker-cache"
        docker_cache_dir.mkdir(exist_ok=True)
        run_env["DOCKER_CONFIG"] = str(docker_cache_dir)
        run_env["REAL_HOSTNAME"] = socket.gethostname()
        run_env["DEBUG"] = "true" if self.config.debug else "false"
        run_env["MAINTENANCE_ENABLED"] = (
            "true" if self.config.maintenance_enabled else "false"
        )
        run_env["DISABLE_TELEGRAM"] = (
            "true" if self.config.disable_telegram else "false"
        )
        run_env["DEBUG_TOOLBAR"] = "true" if self.config.debug_toolbar else "false"
        run_env["HOT_RELOADING"] = "true" if self.config.hot_reloading else "false"
        run_env["DISABLE_RESPONSE_CACHING"] = (
            "true" if self.config.disable_response_caching else "false"
        )
        run_env["RATELIMIT_ENABLED"] = (
            "true" if self.config.ratelimit_enabled else "false"
        )

        if env:
            run_env.update(env)

        # Always capture output when check=True so we can log errors
        should_capture = capture_output or check or input is not None
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._ref_root),
                check=False,  # We'll check manually to include output in errors
                capture_output=should_capture,
                text=True,
                env=run_env,
                input=input,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            # Print captured output on timeout for debugging
            print(f"\n[REF E2E] Command timed out after {timeout}s: {' '.join(cmd)}")
            if e.stdout:
                stdout_str = (
                    e.stdout.decode("utf-8", errors="replace")
                    if isinstance(e.stdout, bytes)
                    else e.stdout
                )
                print(f"\n=== PARTIAL STDOUT ===\n{stdout_str}")
            if e.stderr:
                stderr_str = (
                    e.stderr.decode("utf-8", errors="replace")
                    if isinstance(e.stderr, bytes)
                    else e.stderr
                )
                print(f"\n=== PARTIAL STDERR ===\n{stderr_str}")
            raise

        if check and result.returncode != 0:
            # Log the error output for debugging
            error_msg = f"Command failed with exit code {result.returncode}\n"
            error_msg += f"Command: {' '.join(cmd)}\n"
            if result.stdout:
                error_msg += f"\n=== STDOUT ===\n{result.stdout}"
            if result.stderr:
                error_msg += f"\n=== STDERR ===\n{result.stderr}"
            print(f"[REF E2E] Docker compose error:\n{error_msg}")

            # Raise with output attached
            exc = subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
            raise exc

        return result

    def remote_exec(
        self,
        func: Callable[[], T],
        timeout: float = 30.0,
    ) -> T:
        """
        Execute a Python function inside the webapp container with Flask app context.

        This enables tests to directly query or modify database state, system settings,
        and other server-side state that would otherwise be difficult to test.

        Args:
            func: A callable (function or lambda) to execute inside the container.
                  Must not require arguments.
            timeout: Maximum execution time in seconds (default: 30)

        Returns:
            The return value of the function

        Raises:
            RemoteExecutionError: If serialization, execution, or deserialization fails

        Example:
            # Query a system setting
            value = ref_instance.remote_exec(
                lambda: SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value
            )

            # Modify a setting and commit
            def enable_forwarding():
                from ref.model.settings import SystemSettingsManager
                from flask import current_app
                SystemSettingsManager.ALLOW_TCP_PORT_FORWARDING.value = True
                current_app.db.session.commit()
                return True

            result = ref_instance.remote_exec(enable_forwarding)
        """
        from helpers.remote_exec import remote_exec as _remote_exec

        return _remote_exec(self, func, timeout)

    def build(self, no_cache: bool = False) -> None:
        """
        Build the Docker images.

        Args:
            no_cache: If True, build without using cache.
        """
        self._write_config_files()

        args = ["build"]
        if no_cache:
            args.append("--no-cache")

        self._run_compose(*args)

    def start(self, build: bool = False, wait: bool = True) -> None:
        """
        Start the REF instance.

        Args:
            build: If True, build images before starting.
            wait: If True, wait for services to be ready.
        """
        if self._started:
            return

        self._write_config_files()

        # Build images if requested
        if build:
            self._run_compose("build")

        # Start all services - the webapp auto-initializes the database
        # when running under uwsgi if the database is empty
        self._run_compose("up", "-d")
        self._started = True

        if wait:
            self._wait_for_ready()

    def _wait_for_db(self, timeout: float = 60.0) -> None:
        """Wait for the database to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = self._run_compose(
                    "exec",
                    "-T",
                    "db",
                    "pg_isready",
                    "-U",
                    "ref",
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    return
            except Exception:
                pass
            time.sleep(1.0)
        raise TimeoutError(f"Database did not become ready within {timeout}s")

    def _run_db_migrations(self) -> None:
        """Run database migrations using a temporary web container."""
        self._run_compose(
            "run",
            "--rm",
            "-T",
            "web",
            "bash",
            "-c",
            "DB_MIGRATE=1 FLASK_APP=ref python3 -m flask db upgrade",
            check=True,
        )

    def _wait_for_ready(self) -> None:
        """Wait for the instance to be ready."""
        import httpx

        start_time = time.time()
        while time.time() - start_time < self.config.startup_timeout:
            try:
                response = httpx.get(f"{self.web_url}/login", timeout=5.0)
                if response.status_code == 200:
                    return
            except httpx.RequestError:
                pass
            time.sleep(1.0)

        raise TimeoutError(
            f"REF instance did not become ready within {self.config.startup_timeout}s"
        )

    def stop(self, timeout: int = 10) -> None:
        """Stop the REF instance without removing containers.

        Args:
            timeout: Seconds to wait for graceful shutdown (allows coverage flush).
        """
        if not self._started:
            return

        self._run_compose("stop", "-t", str(timeout), check=False)
        self._started = False

    def down(self) -> None:
        """Stop and remove all containers and networks."""
        self._run_compose("down", "-v", "--remove-orphans", check=False)
        self._started = False

    def restart(self, service: Optional[str] = None) -> None:
        """
        Restart services.

        Args:
            service: Specific service to restart. If None, restarts all.
        """
        args = ["restart"]
        if service:
            args.append(service)
        self._run_compose(*args)

    def logs(self, follow: bool = False, tail: Optional[int] = None) -> str:
        """
        Get logs from services.

        Args:
            follow: If True, follow log output (blocking).
            tail: Number of lines to show from the end.

        Returns:
            Log output as string.
        """
        args = ["logs"]
        if follow:
            args.append("-f")
        if tail is not None:
            args.extend(["--tail", str(tail)])

        result = self._run_compose(*args, capture_output=True, check=False)
        return result.stdout + result.stderr

    def ps(self) -> str:
        """List running containers."""
        result = self._run_compose("ps", capture_output=True, check=False)
        return result.stdout

    def exec(self, service: str, command: str) -> subprocess.CompletedProcess[str]:
        """
        Execute a command in a running service container.

        Args:
            service: Service name (web, db, sshserver, etc.)
            command: Command to execute.

        Returns:
            CompletedProcess with output.
        """
        return self._run_compose(
            "exec", "-T", service, "bash", "-c", command, capture_output=True
        )

    def run_flask_cmd(self, command: str) -> subprocess.CompletedProcess[str]:
        """
        Run a Flask CLI command.

        Args:
            command: Flask command (e.g., "db upgrade").

        Returns:
            CompletedProcess with output.
        """
        return self._run_compose(
            "run",
            "--rm",
            "web",
            "bash",
            "-c",
            f"FLASK_APP=ref python3 -m flask {command}",
            capture_output=True,
        )

    def db_upgrade(self) -> None:
        """Run database migrations."""
        self._run_compose(
            "run",
            "--rm",
            "web",
            "bash",
            "-c",
            "DB_MIGRATE=1 FLASK_APP=ref python3 -m flask db upgrade",
        )

    def cleanup(self) -> None:
        """
        Clean up all resources associated with this instance.

        This removes:
        - Docker containers, networks, and volumes
        - Temporary directories and files
        """
        # Stop and remove Docker resources
        self.down()

        # Clean up Docker resources by prefix
        self.cleanup_docker_resources()

        # Remove temporary directories and files
        for temp_path in self._temp_dirs:
            if temp_path.exists():
                if temp_path.is_dir():
                    shutil.rmtree(temp_path, ignore_errors=True)
                else:
                    temp_path.unlink(missing_ok=True)

    def cleanup_docker_resources(self) -> None:
        """
        Clean up Docker resources matching this instance's prefix.

        Removes containers, networks, volumes, and images with matching names.
        """
        prefix = self.config.prefix

        # Remove containers
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={prefix}", "-q"],
                capture_output=True,
                text=True,
                check=True,
            )
            container_ids = result.stdout.strip().split()
            if container_ids:
                subprocess.run(
                    ["docker", "rm", "-f"] + container_ids,
                    capture_output=True,
                    check=False,
                )
        except subprocess.CalledProcessError:
            pass

        # Remove networks
        try:
            result = subprocess.run(
                ["docker", "network", "ls", "--filter", f"name={prefix}", "-q"],
                capture_output=True,
                text=True,
                check=True,
            )
            network_ids = result.stdout.strip().split()
            if network_ids:
                subprocess.run(
                    ["docker", "network", "rm"] + network_ids,
                    capture_output=True,
                    check=False,
                )
        except subprocess.CalledProcessError:
            pass

        # Remove volumes
        try:
            result = subprocess.run(
                ["docker", "volume", "ls", "--filter", f"name={prefix}", "-q"],
                capture_output=True,
                text=True,
                check=True,
            )
            volume_ids = result.stdout.strip().split()
            if volume_ids:
                subprocess.run(
                    ["docker", "volume", "rm"] + volume_ids,
                    capture_output=True,
                    check=False,
                )
        except subprocess.CalledProcessError:
            pass

    @classmethod
    def create(
        cls,
        prefix: Optional[str] = None,
        **kwargs: Any,
    ) -> "REFInstance":
        """
        Create a new REF instance with optional configuration.

        Args:
            prefix: Instance prefix for resource naming.
            **kwargs: Additional configuration options.

        Returns:
            New REFInstance.
        """
        if prefix is not None:
            kwargs["prefix"] = prefix
        config = REFInstanceConfig(**kwargs)
        return cls(config)

    @classmethod
    @contextmanager
    def running(
        cls,
        prefix: Optional[str] = None,
        build: bool = False,
        **kwargs: Any,
    ):
        """
        Context manager that starts and stops a REF instance.

        Args:
            prefix: Instance prefix for resource naming.
            build: If True, build images before starting.
            **kwargs: Additional configuration options.

        Yields:
            Running REFInstance.

        Example:
            with REFInstance.running(prefix="test_1") as instance:
                print(f"Web URL: {instance.web_url}")
                # Do testing...
            # Instance is automatically stopped and cleaned up
        """
        instance = cls.create(prefix=prefix, **kwargs)
        try:
            instance.start(build=build)
            yield instance
        finally:
            instance.cleanup()


class REFInstanceManager:
    """
    Manages multiple REF instances for parallel testing.

    Features:
    - Track all created instances
    - Batch cleanup
    - Port coordination
    """

    def __init__(self, base_prefix: str = "ref_test"):
        """
        Initialize the instance manager.

        Args:
            base_prefix: Base prefix for all instances.
        """
        self.base_prefix = base_prefix
        self._instances: Dict[str, REFInstance] = {}
        self._next_http_port = 18000
        self._next_ssh_port = 12222

    def create_instance(
        self,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> REFInstance:
        """
        Create a new managed instance.

        Args:
            name: Instance name (used with base_prefix).
            **kwargs: Additional configuration options.

        Returns:
            New REFInstance.
        """
        if name is None:
            name = uuid.uuid4().hex[:8]

        prefix = f"{self.base_prefix}_{name}"

        if prefix in self._instances:
            raise ValueError(f"Instance with prefix '{prefix}' already exists")

        # Allocate ports
        http_port = kwargs.pop("http_port", self._next_http_port)
        ssh_port = kwargs.pop("ssh_port", self._next_ssh_port)

        self._next_http_port = http_port + 1
        self._next_ssh_port = ssh_port + 1

        config = REFInstanceConfig(
            prefix=prefix,
            http_port=http_port,
            ssh_port=ssh_port,
            **kwargs,
        )
        instance = REFInstance(config)
        self._instances[prefix] = instance
        return instance

    def get_instance(self, name: str) -> Optional[REFInstance]:
        """Get an instance by name."""
        prefix = f"{self.base_prefix}_{name}"
        return self._instances.get(prefix)

    def cleanup_all(self) -> None:
        """Clean up all managed instances."""
        for instance in self._instances.values():
            try:
                instance.cleanup()
            except Exception:
                pass
        self._instances.clear()

    def cleanup_by_prefix(self, prefix: Optional[str] = None) -> None:
        """
        Clean up Docker resources by prefix.

        Args:
            prefix: Prefix to match. If None, uses base_prefix.
        """
        prefix = prefix or self.base_prefix
        cleanup_docker_resources_by_prefix(prefix)


def cleanup_docker_resources_by_prefix(prefix: str) -> None:
    """
    Clean up all Docker resources matching a prefix.

    This is a utility function for cleaning up after tests.

    Args:
        prefix: Prefix to match in resource names.
    """
    # Remove containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        containers = [
            name
            for name in result.stdout.strip().split("\n")
            if name and prefix in name
        ]
        if containers:
            subprocess.run(
                ["docker", "rm", "-f"] + containers,
                capture_output=True,
                check=False,
            )
    except subprocess.CalledProcessError:
        pass

    # Remove networks
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        networks = [
            name
            for name in result.stdout.strip().split("\n")
            if name and prefix in name
        ]
        if networks:
            subprocess.run(
                ["docker", "network", "rm"] + networks,
                capture_output=True,
                check=False,
            )
    except subprocess.CalledProcessError:
        pass

    # Remove volumes
    try:
        result = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        volumes = [
            name
            for name in result.stdout.strip().split("\n")
            if name and prefix in name
        ]
        if volumes:
            subprocess.run(
                ["docker", "volume", "rm"] + volumes,
                capture_output=True,
                check=False,
            )
    except subprocess.CalledProcessError:
        pass

    # Remove images
    try:
        result = subprocess.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        images = [
            name
            for name in result.stdout.strip().split("\n")
            if name and prefix in name
        ]
        if images:
            subprocess.run(
                ["docker", "rmi", "-f"] + images,
                capture_output=True,
                check=False,
            )
    except subprocess.CalledProcessError:
        pass
