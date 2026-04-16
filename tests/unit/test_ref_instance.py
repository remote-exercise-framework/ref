"""
Unit Tests for REFInstance

These tests verify the REFInstance infrastructure works correctly.
Tests marked with @pytest.mark.offline can run without Docker.
"""

import tempfile
from pathlib import Path

import pytest

from helpers.ref_instance import (
    REFInstance,
    REFInstanceConfig,
    REFInstanceManager,
    find_free_port,
    generate_secret,
    cleanup_docker_resources_by_prefix,
)


@pytest.mark.offline
class TestHelperFunctions:
    """Test helper utility functions."""

    def test_generate_secret_returns_string(self):
        """Test that generate_secret returns a string."""
        secret = generate_secret()
        assert isinstance(secret, str)
        assert len(secret) > 0

    def test_generate_secret_length(self):
        """Test that generate_secret respects length parameter."""
        secret = generate_secret(16)
        # URL-safe base64 encoding produces longer strings
        assert len(secret) >= 16

    def test_generate_secret_uniqueness(self):
        """Test that generate_secret produces unique values."""
        secrets = [generate_secret() for _ in range(10)]
        assert len(set(secrets)) == 10

    def test_find_free_port_returns_int(self):
        """Test that find_free_port returns an integer."""
        port = find_free_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535

    def test_find_free_port_respects_range(self):
        """Test that find_free_port respects the given range."""
        port = find_free_port(start=50000, end=50100)
        assert 50000 <= port < 50100


@pytest.mark.offline
class TestREFInstanceConfig:
    """Test REFInstanceConfig initialization and defaults."""

    def test_config_default_prefix(self):
        """Test that config generates a default prefix."""
        config = REFInstanceConfig()
        assert config.prefix.startswith("ref_test_")

    def test_config_custom_prefix(self):
        """Test that config accepts custom prefix."""
        config = REFInstanceConfig(prefix="my_custom_prefix")
        assert config.prefix == "my_custom_prefix"

    def test_config_auto_generates_secrets(self):
        """Test that config auto-generates secrets."""
        config = REFInstanceConfig()
        assert config.admin_password is not None
        assert config.secret_key is not None
        assert config.ssh_to_web_key is not None
        assert config.postgres_password is not None

    def test_config_custom_secrets(self):
        """Test that config accepts custom secrets."""
        config = REFInstanceConfig(
            admin_password="custom_admin",
            secret_key="custom_secret",
        )
        assert config.admin_password == "custom_admin"
        assert config.secret_key == "custom_secret"

    def test_config_default_ports(self):
        """Test that config defaults to auto-allocation (0)."""
        config = REFInstanceConfig()
        assert config.http_port == 0
        assert config.ssh_port == 0

    def test_config_custom_ports(self):
        """Test that config accepts custom ports."""
        config = REFInstanceConfig(http_port=8080, ssh_port=2222)
        assert config.http_port == 8080
        assert config.ssh_port == 2222

    def test_config_project_name_defaults_to_prefix(self):
        """Test that project_name defaults to prefix."""
        config = REFInstanceConfig(prefix="test_prefix")
        assert config.project_name == "test_prefix"

    def test_config_custom_project_name(self):
        """Test that config accepts custom project name."""
        config = REFInstanceConfig(prefix="test_prefix", project_name="custom_project")
        assert config.project_name == "custom_project"

    def test_config_testing_mode_default(self):
        """Test that testing mode is True by default."""
        config = REFInstanceConfig()
        assert config.testing is True

    def test_config_debug_mode_default(self):
        """Test that debug mode is True by default."""
        config = REFInstanceConfig()
        assert config.debug is True


@pytest.mark.offline
class TestREFInstanceInitialization:
    """Test REFInstance initialization."""

    def test_instance_creates_with_default_config(self):
        """Test that instance can be created with default config."""
        instance = REFInstance()
        assert instance.prefix.startswith("ref_test_")
        assert not instance.is_running

    def test_instance_creates_with_custom_config(self):
        """Test that instance can be created with custom config."""
        config = REFInstanceConfig(prefix="custom_test_instance")
        instance = REFInstance(config)
        assert instance.prefix == "custom_test_instance"

    def test_instance_allocates_ports(self):
        """Test that instance allocates ports automatically."""
        instance = REFInstance()
        assert instance.http_port > 0
        assert instance.ssh_port > 0
        assert instance.http_port != instance.ssh_port

    def test_instance_with_custom_ports(self):
        """Test that instance uses custom ports when specified."""
        config = REFInstanceConfig(http_port=18888, ssh_port=12345)
        instance = REFInstance(config)
        assert instance.http_port == 18888
        assert instance.ssh_port == 12345

    def test_instance_web_url_property(self):
        """Test that web_url property is formatted correctly."""
        config = REFInstanceConfig(http_port=18000)
        instance = REFInstance(config)
        assert instance.web_url == "http://localhost:18000"

    def test_instance_ssh_host_property(self):
        """Test that ssh_host property returns localhost."""
        instance = REFInstance()
        assert instance.ssh_host == "localhost"

    def test_instance_creates_data_dir(self):
        """Test that instance creates data directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = REFInstanceConfig(work_dir=Path(temp_dir))
            instance = REFInstance(config)
            assert instance.data_dir.exists()

    def test_instance_creates_exercises_dir(self):
        """Test that instance creates exercises directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = REFInstanceConfig(work_dir=Path(temp_dir))
            instance = REFInstance(config)
            assert instance.exercises_dir.exists()

    def test_instance_admin_password_property(self):
        """Test that admin_password property returns the configured password."""
        config = REFInstanceConfig(admin_password="test_admin_pw")
        instance = REFInstance(config)
        assert instance.admin_password == "test_admin_pw"


@pytest.mark.offline
class TestREFInstanceClassMethods:
    """Test REFInstance class methods."""

    def test_create_with_defaults(self):
        """Test REFInstance.create() with defaults."""
        instance = REFInstance.create()
        assert instance is not None
        assert instance.prefix.startswith("ref_test_")

    def test_create_with_prefix(self):
        """Test REFInstance.create() with custom prefix."""
        instance = REFInstance.create(prefix="my_test")
        assert instance.prefix == "my_test"

    def test_create_with_kwargs(self):
        """Test REFInstance.create() with additional kwargs."""
        instance = REFInstance.create(
            prefix="my_test",
            http_port=19000,
            debug=False,
        )
        assert instance.prefix == "my_test"
        assert instance.http_port == 19000


@pytest.mark.offline
class TestREFInstanceManager:
    """Test REFInstanceManager functionality."""

    def test_manager_creates_with_base_prefix(self):
        """Test that manager accepts base prefix."""
        manager = REFInstanceManager(base_prefix="custom_base")
        assert manager.base_prefix == "custom_base"

    def test_manager_create_instance(self):
        """Test that manager can create instances."""
        manager = REFInstanceManager()
        instance = manager.create_instance(name="test_1")
        assert instance is not None
        assert "test_1" in instance.prefix

    def test_manager_create_multiple_instances(self):
        """Test that manager can create multiple instances."""
        manager = REFInstanceManager()
        instance1 = manager.create_instance(name="test_1")
        instance2 = manager.create_instance(name="test_2")
        assert instance1.prefix != instance2.prefix
        assert instance1.http_port != instance2.http_port
        assert instance1.ssh_port != instance2.ssh_port

    def test_manager_get_instance(self):
        """Test that manager can retrieve instances by name."""
        manager = REFInstanceManager()
        created = manager.create_instance(name="test_get")
        retrieved = manager.get_instance("test_get")
        assert retrieved is created

    def test_manager_get_nonexistent_instance(self):
        """Test that manager returns None for nonexistent instance."""
        manager = REFInstanceManager()
        result = manager.get_instance("nonexistent")
        assert result is None

    def test_manager_prevents_duplicate_names(self):
        """Test that manager prevents duplicate instance names."""
        manager = REFInstanceManager()
        manager.create_instance(name="duplicate")
        with pytest.raises(ValueError, match="already exists"):
            manager.create_instance(name="duplicate")


@pytest.mark.offline
class TestREFInstanceConfigGeneration:
    """Test configuration file generation."""

    def test_generate_settings_env(self):
        """Test that settings.env content is generated correctly."""
        config = REFInstanceConfig(
            prefix="test_env",
            admin_password="test_admin",
            ssh_to_web_key="test_key",
        )
        instance = REFInstance(config)
        env_content = instance._generate_settings_env()

        assert "ADMIN_PASSWORD=test_admin" in env_content
        assert "SSH_TO_WEB_KEY=test_key" in env_content
        assert "DEBUG=1" in env_content  # debug=True by default

    def test_generate_docker_compose_requires_template(self):
        """Test that docker compose generation requires the template file."""
        # This will fail if the template doesn't exist
        # which is expected behavior
        config = REFInstanceConfig(
            ref_root=Path("/nonexistent/path"),
        )
        instance = REFInstance.__new__(REFInstance)
        instance.config = config
        instance._ref_root = Path("/nonexistent/path")

        with pytest.raises(FileNotFoundError):
            instance._generate_docker_compose()


@pytest.mark.offline
class TestCleanupFunctions:
    """Test cleanup utility functions."""

    def test_cleanup_by_prefix_does_not_crash(self):
        """Test that cleanup function doesn't crash with nonexistent prefix."""
        # This should not raise any exception
        cleanup_docker_resources_by_prefix("nonexistent_prefix_xyz123")
