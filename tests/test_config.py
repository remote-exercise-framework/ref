"""
Test Configuration

Configuration for running E2E tests with isolated REF instances.
Each test run uses unique prefixes for Docker resources to enable cleanup.

This module provides:
- REFTestConfig: Legacy configuration class (for backward compatibility)
- Integration with REFInstance for managing test instances
- Command-line utilities for cleanup
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# Import the new REFInstance infrastructure
from helpers.ref_instance import (
    REFInstance,
    REFInstanceConfig,
    REFInstanceManager,
    cleanup_docker_resources_by_prefix,
)


def generate_test_prefix() -> str:
    """Generate a unique prefix for this test run.

    Format: {timestamp}_{pid}_{unique_id}
    The PID is embedded to allow detecting orphaned resources from dead processes.
    """
    import os

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pid = os.getpid()
    unique_id = uuid.uuid4().hex[:6]
    return f"{timestamp}_{pid}_{unique_id}"


@dataclass
class REFTestConfig:
    """
    Configuration for a REF test instance.

    All Docker resources (containers, networks, volumes) will be prefixed
    with `resource_prefix` to enable easy cleanup after tests.

    Note: This class is maintained for backward compatibility.
    For new code, use REFInstanceConfig directly.
    """

    # Unique prefix for this test run - used for Docker resources
    resource_prefix: str = field(default_factory=generate_test_prefix)

    # Database settings
    postgres_user: str = "ref_test"
    postgres_password: str = "ref_test_password"
    postgres_db: str = "ref_test"

    # Web interface settings
    web_host: str = "localhost"
    web_port: int = 0  # 0 = auto-allocate

    # SSH settings
    ssh_host: str = "localhost"
    ssh_port: int = 0  # 0 = auto-allocate

    # Admin credentials
    admin_password: str = "TestAdmin123!"
    secret_key: str = field(default_factory=lambda: uuid.uuid4().hex)
    ssh_to_web_key: str = field(default_factory=lambda: uuid.uuid4().hex)

    # Paths
    base_dir: Optional[Path] = None
    exercises_path: Optional[Path] = None

    # Docker settings
    docker_network_name: str = field(init=False)
    container_cpu_limit: float = 0.5
    container_mem_limit: str = "256m"
    container_pids_limit: int = 256

    def __post_init__(self):
        """Initialize computed fields."""
        self.docker_network_name = f"{self.resource_prefix}_network"

    @property
    def web_url(self) -> str:
        """Full URL for the web interface."""
        port = self.web_port if self.web_port != 0 else 8000
        return f"http://{self.web_host}:{port}"

    @property
    def database_uri(self) -> str:
        """SQLAlchemy database URI."""
        return f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@db/{self.postgres_db}"

    def to_ref_instance_config(self) -> REFInstanceConfig:
        """Convert to REFInstanceConfig for use with REFInstance."""
        return REFInstanceConfig(
            prefix=self.resource_prefix,
            http_port=self.web_port,
            ssh_port=self.ssh_port,
            admin_password=self.admin_password,
            secret_key=self.secret_key,
            ssh_to_web_key=self.ssh_to_web_key,
            postgres_password=self.postgres_password,
            data_dir=self.base_dir,
            exercises_dir=self.exercises_path,
            testing=True,
            debug=True,
        )

    def create_instance(self) -> REFInstance:
        """Create a REFInstance from this configuration."""
        config = self.to_ref_instance_config()
        return REFInstance(config)

    def to_env_dict(self) -> dict[str, str]:
        """
        Convert configuration to environment variables for docker-compose.

        Returns:
            Dictionary of environment variables
        """
        return {
            "POSTGRES_USER": self.postgres_user,
            "POSTGRES_PASSWORD": self.postgres_password,
            "POSTGRES_DB": self.postgres_db,
            "ADMIN_PASSWORD": self.admin_password,
            "SECRET_KEY": self.secret_key,
            "SSH_TO_WEB_KEY": self.ssh_to_web_key,
            "SSH_HOST_PORT": str(self.ssh_port) if self.ssh_port != 0 else "2222",
            "DEBUG": "1",
            "DOCKER_RESSOURCE_PREFIX": f"{self.resource_prefix}-",
            "INSTANCES_CGROUP_PARENT": "",
            "MAINTENANCE_ENABLED": "0",
            "DISABLE_TELEGRAM": "1",
            "DEBUG_TOOLBAR": "0",
            "DISABLE_RESPONSE_CACHING": "1",
        }

    def write_env_file(self, path: Path) -> Path:
        """
        Write configuration to a .env file.

        Args:
            path: Directory to write the file in

        Returns:
            Path to the created .env file
        """
        env_file = path / f"{self.resource_prefix}.env"
        env_dict = self.to_env_dict()

        with open(env_file, "w") as f:
            for key, value in env_dict.items():
                f.write(f"{key}={value}\n")

        return env_file

    def get_docker_compose_project_name(self) -> str:
        """Get the docker-compose project name for this test run."""
        return self.resource_prefix


@dataclass
class REFResourceManager:
    """
    Manages REF Docker resources for testing.

    This class wraps REFInstanceManager for backward compatibility.
    """

    config: REFTestConfig
    _instance_manager: REFInstanceManager = field(init=False)

    def __post_init__(self):
        """Initialize the instance manager."""
        self._instance_manager = REFInstanceManager(
            base_prefix=self.config.resource_prefix
        )

    def cleanup_all(self, force: bool = True) -> dict[str, str]:
        """
        Clean up all registered resources.

        Args:
            force: If True, force removal even if resources are in use

        Returns:
            Dictionary with cleanup results
        """
        self._instance_manager.cleanup_all()
        return {"status": "cleaned"}

    def cleanup_by_prefix(self) -> dict[str, str]:
        """
        Clean up all Docker resources matching the test prefix.

        Returns:
            Dictionary with cleanup results
        """
        cleanup_docker_resources_by_prefix(self.config.resource_prefix)
        return {"status": "cleaned"}


def cleanup_test_resources(prefix: str) -> dict[str, str]:
    """
    Standalone function to clean up test resources by prefix.

    Can be called from command line or after test failures.

    Args:
        prefix: The resource prefix to clean up

    Returns:
        Cleanup results
    """
    cleanup_docker_resources_by_prefix(prefix)
    return {"status": "cleaned", "prefix": prefix}


def list_test_resources() -> dict[str, list[dict[str, str]]]:
    """
    List all test resources (containers, networks, volumes).

    Returns:
        Dictionary with lists of resources
    """
    import subprocess

    results: dict[str, list[dict[str, str]]] = {
        "containers": [],
        "networks": [],
        "volumes": [],
    }

    # List containers
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line and "ref_test_" in line:
                parts = line.split("\t")
                results["containers"].append(
                    {
                        "name": parts[0],
                        "status": parts[1] if len(parts) > 1 else "unknown",
                    }
                )
    except subprocess.CalledProcessError:
        pass

    # List networks
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line and "ref_test_" in line:
                results["networks"].append({"name": line})
    except subprocess.CalledProcessError:
        pass

    # List volumes
    try:
        result = subprocess.run(
            ["docker", "volume", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line and "ref_test_" in line:
                results["volumes"].append({"name": line})
    except subprocess.CalledProcessError:
        pass

    return results


if __name__ == "__main__":
    """
    Command-line cleanup utility.

    Usage:
        python test_config.py --list           # List test resources
        python test_config.py --cleanup <prefix>  # Clean up by prefix
        python test_config.py --cleanup-all    # Clean up all ref_test_ resources
    """
    import argparse

    parser = argparse.ArgumentParser(description="REF Test Resource Manager")
    parser.add_argument("--list", action="store_true", help="List test resources")
    parser.add_argument(
        "--cleanup", metavar="PREFIX", help="Clean up resources by prefix"
    )
    parser.add_argument(
        "--cleanup-all", action="store_true", help="Clean up all ref_test_ resources"
    )

    args = parser.parse_args()

    if args.list:
        resources = list_test_resources()
        print("Test containers:")
        for c in resources["containers"]:
            print(f"  {c['name']} ({c['status']})")
        print("\nTest networks:")
        for n in resources["networks"]:
            print(f"  {n['name']}")
        print("\nTest volumes:")
        for v in resources["volumes"]:
            print(f"  {v['name']}")

    elif args.cleanup:
        prefix = args.cleanup
        print(f"Cleaning up resources with prefix: {prefix}")
        cleanup_docker_resources_by_prefix(prefix)
        print("Done.")

    elif args.cleanup_all:
        print("Cleaning up all ref_test_ resources...")
        cleanup_docker_resources_by_prefix("ref_test_")
        print("Done.")

    else:
        parser.print_help()
