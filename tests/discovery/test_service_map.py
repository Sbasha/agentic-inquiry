"""Tests for ServiceMapDetector."""
from __future__ import annotations

import pytest
import tempfile
from pathlib import Path

from agent_vault.discovery import (
    ServiceMapDetector,
    ServiceMap,
    ServiceNode,
    ServiceConnection,
)


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace for testing."""
    return tmp_path


class TestServiceMapDetector:
    """Test ServiceMapDetector functionality."""

    @pytest.mark.asyncio
    async def test_detect_empty_workspace(self, temp_workspace):
        """Test detection on empty workspace."""
        detector = ServiceMapDetector(temp_workspace)
        service_map = await detector.detect()

        assert isinstance(service_map, ServiceMap)
        assert service_map.services == []
        assert service_map.connections == []

    @pytest.mark.asyncio
    async def test_detect_docker_compose(self, temp_workspace):
        """Test detection from docker-compose file."""
        compose_content = """
version: '3'
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
    depends_on:
      - api
  api:
    image: python:3.11
    depends_on:
      - db
  db:
    image: postgres:15
    ports:
      - "5432:5432"
"""
        (temp_workspace / "docker-compose.yml").write_text(compose_content)

        detector = ServiceMapDetector(temp_workspace)
        service_map = await detector.detect()

        assert len(service_map.services) == 3
        assert "docker-compose" in service_map.detection_sources

        # Check service types
        service_names = {s.name for s in service_map.services}
        assert "web" in service_names
        assert "api" in service_names
        assert "db" in service_names

        # Check connections from depends_on
        assert len(service_map.connections) >= 2

    @pytest.mark.asyncio
    async def test_detect_conventions(self, temp_workspace):
        """Test detection from folder conventions."""
        # Create services directory structure
        services_dir = temp_workspace / "services"
        services_dir.mkdir()
        (services_dir / "auth-service").mkdir()
        (services_dir / "user-service").mkdir()
        (services_dir / "order-service").mkdir()

        detector = ServiceMapDetector(temp_workspace)
        service_map = await detector.detect()

        assert "conventions" in service_map.detection_sources
        service_names = {s.name for s in service_map.services}
        assert "auth-service" in service_names
        assert "user-service" in service_names
        assert "order-service" in service_names

    @pytest.mark.asyncio
    async def test_excludes_system_directories(self, temp_workspace):
        """Test that system directories like node_modules and cache are excluded."""
        # Create services in node_modules (should be excluded)
        node_services = temp_workspace / "node_modules" / "lib" / "services"
        node_services.mkdir(parents=True)
        (node_services / "should-ignore").mkdir()

        # Create a proper services directory with subdirectories
        services_dir = temp_workspace / "services"
        services_dir.mkdir()
        (services_dir / "__pycache__").mkdir()
        (services_dir / "real-service").mkdir()

        detector = ServiceMapDetector(temp_workspace)
        service_map = await detector.detect()

        service_names = {s.name for s in service_map.services}
        assert "should-ignore" not in service_names
        assert "__pycache__" not in service_names
        # real-service should be detected from the services convention
        assert "real-service" in service_names

    @pytest.mark.asyncio
    async def test_service_type_inference(self, temp_workspace):
        """Test service type inference from names."""
        compose_content = """
version: '3'
services:
  postgres-db:
    image: postgres:15
  redis-cache:
    image: redis:7
  rabbitmq-queue:
    image: rabbitmq:3
  nginx-gateway:
    image: nginx:latest
  app:
    image: myapp:latest
"""
        (temp_workspace / "docker-compose.yaml").write_text(compose_content)

        detector = ServiceMapDetector(temp_workspace)
        service_map = await detector.detect()

        services_by_name = {s.name: s for s in service_map.services}

        assert services_by_name["postgres-db"].service_type == "database"
        assert services_by_name["redis-cache"].service_type == "cache"
        assert services_by_name["rabbitmq-queue"].service_type == "queue"
        assert services_by_name["nginx-gateway"].service_type == "gateway"
        assert services_by_name["app"].service_type == "application"


class TestServiceMap:
    """Test ServiceMap dataclass."""

    def test_add_service_deduplicates(self):
        """Test that add_service deduplicates by name."""
        service_map = ServiceMap()

        # Add first service
        svc1 = ServiceNode(
            id="svc1",
            name="web",
            service_type="application",
            source="docker",
            confidence="low",
        )
        service_map.add_service(svc1)

        # Add duplicate with higher confidence
        svc2 = ServiceNode(
            id="svc2",
            name="web",
            service_type="application",
            source="k8s",
            confidence="high",
        )
        service_map.add_service(svc2)

        # Should only have one service, with high confidence
        assert len(service_map.services) == 1
        assert service_map.services[0].confidence == "high"
        assert service_map.services[0].source == "k8s"

    def test_add_connection_deduplicates(self):
        """Test that add_connection deduplicates."""
        service_map = ServiceMap()

        conn1 = ServiceConnection(
            source_id="svc1",
            target_id="svc2",
            protocol="HTTP",
        )
        service_map.add_connection(conn1)
        service_map.add_connection(conn1)  # Add duplicate

        assert len(service_map.connections) == 1

    def test_to_dict(self):
        """Test JSON serialization."""
        service_map = ServiceMap(workspace_path="/test")
        svc = ServiceNode(
            id="svc1",
            name="web",
            service_type="application",
            source="docker",
            confidence="high",
            ports=[80, 443],
        )
        service_map.add_service(svc)

        result = service_map.to_dict()

        assert result["workspace"] == "/test"
        assert len(result["services"]) == 1
        assert result["services"][0]["name"] == "web"
        assert result["services"][0]["ports"] == [80, 443]


class TestServiceNode:
    """Test ServiceNode dataclass."""

    def test_service_node_creation(self):
        """Test ServiceNode creation with defaults."""
        node = ServiceNode(
            id="test-1",
            name="test-service",
            service_type="application",
            source="docker",
            confidence="high",
        )
        assert node.ports == []
        assert node.technology is None
        assert node.metadata == {}

    def test_service_node_with_all_fields(self):
        """Test ServiceNode with all fields."""
        node = ServiceNode(
            id="test-1",
            name="test-service",
            service_type="database",
            source="docker",
            confidence="high",
            file_path="/path/to/compose.yml",
            ports=[5432],
            technology="postgresql",
            metadata={"image": "postgres:15"},
        )
        assert node.file_path == "/path/to/compose.yml"
        assert node.ports == [5432]
        assert node.technology == "postgresql"


class TestServiceConnection:
    """Test ServiceConnection dataclass."""

    def test_service_connection_defaults(self):
        """Test ServiceConnection default values."""
        conn = ServiceConnection(
            source_id="svc1",
            target_id="svc2",
            protocol="HTTP",
        )
        assert conn.port is None
        assert conn.confidence == "medium"
        assert conn.source_detection == ""

    def test_service_connection_all_fields(self):
        """Test ServiceConnection with all fields."""
        conn = ServiceConnection(
            source_id="svc1",
            target_id="svc2",
            protocol="JDBC",
            port=5432,
            confidence="high",
            source_detection="depends_on",
        )
        assert conn.port == 5432
        assert conn.confidence == "high"
