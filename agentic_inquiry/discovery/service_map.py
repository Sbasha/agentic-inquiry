"""Service map detection using multiple discovery strategies.

Detects microservice architecture from:
1. Infrastructure files (Docker Compose, Kubernetes, Terraform)
2. Code structure via ast-grep (decorators, annotations)
3. String patterns via ripgrep (URLs, connection references)
4. Folder conventions
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, cast

logger = logging.getLogger(__name__)

# Type aliases for service map types
ServiceType = Literal["application", "database", "queue", "cache", "gateway", "external", "unknown"]
ProtocolType = Literal["HTTP", "HTTPS", "gRPC", "JDBC", "AMQP", "Redis", "MongoDB", "TCP", "unknown"]
ConfidenceType = Literal["high", "medium", "low"]


@dataclass
class ServiceNode:
    """A service in the architecture."""

    id: str
    name: str
    service_type: ServiceType
    source: str  # Detection source: docker, k8s, terraform, ast-grep, ripgrep, convention
    confidence: ConfidenceType
    file_path: Optional[str] = None
    ports: List[int] = field(default_factory=list)
    technology: Optional[str] = None  # e.g., "postgresql", "redis", "spring-boot"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceConnection:
    """Connection between services."""

    source_id: str
    target_id: str
    protocol: ProtocolType
    port: Optional[int] = None
    confidence: ConfidenceType = "medium"
    source_detection: str = ""  # How this connection was detected


@dataclass
class ServiceMap:
    """Complete service architecture."""

    services: List[ServiceNode] = field(default_factory=list)
    connections: List[ServiceConnection] = field(default_factory=list)
    detection_sources: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)
    workspace_path: str = ""

    def add_service(self, service: ServiceNode) -> None:
        """Add service, deduplicating by name."""
        existing = next((s for s in self.services if s.name == service.name), None)
        if existing:
            # Merge: prefer higher confidence
            if _confidence_rank(service.confidence) > _confidence_rank(existing.confidence):
                self.services.remove(existing)
                self.services.append(service)
        else:
            self.services.append(service)

    def add_connection(self, conn: ServiceConnection) -> None:
        """Add connection, deduplicating."""
        existing = next(
            (c for c in self.connections if c.source_id == conn.source_id and c.target_id == conn.target_id),
            None,
        )
        if not existing:
            self.connections.append(conn)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "workspace": self.workspace_path,
            "services": [
                {
                    "id": s.id,
                    "name": s.name,
                    "type": s.service_type,
                    "technology": s.technology,
                    "confidence": s.confidence,
                    "source": s.source,
                    "file": s.file_path,
                    "ports": s.ports,
                }
                for s in self.services
            ],
            "connections": [
                {
                    "from": c.source_id,
                    "to": c.target_id,
                    "protocol": c.protocol,
                    "port": c.port,
                    "confidence": c.confidence,
                }
                for c in self.connections
            ],
            "detection_sources": self.detection_sources,
            "gaps": self.gaps,
        }


def _confidence_rank(conf: str) -> int:
    """Rank confidence for comparison."""
    return {"high": 3, "medium": 2, "low": 1}.get(conf, 0)


class ServiceMapDetector:
    """Detects microservice architecture using multiple strategies.

    Uses all available tools:
    - YAML parsing for Docker Compose, Kubernetes
    - HCL parsing for Terraform (if available)
    - ast-grep for structural code patterns
    - ripgrep for string patterns
    - Folder structure analysis
    """

    # Service type inference from image names / technology
    # Note: Order matters - cache is checked before database since redis can be either
    SERVICE_TYPE_PATTERNS = {
        "cache": [
            "redis", "memcached", "hazelcast", "varnish",
        ],
        "queue": [
            "rabbitmq", "kafka", "activemq", "sqs", "pubsub", "nats", "zeromq",
        ],
        "gateway": [
            "nginx", "traefik", "kong", "envoy", "haproxy", "istio", "ambassador",
        ],
        "database": [
            "postgres", "mysql", "mariadb", "mongodb", "mongo",
            "elasticsearch", "cassandra", "cockroach", "sqlite", "oracle",
            "sqlserver", "mssql", "dynamodb", "firestore", "neo4j",
        ],
    }

    # Protocol inference
    PROTOCOL_PATTERNS = {
        "JDBC": ["jdbc:", "postgresql://", "mysql://", "oracle:"],
        "MongoDB": ["mongodb://", "mongodb+srv://"],
        "Redis": ["redis://", "rediss://"],
        "AMQP": ["amqp://", "amqps://"],
        "gRPC": ["grpc://", ":grpc", "grpc."],
        "HTTP": ["http://", "https://", "fetch(", "axios.", "requests."],
    }

    # Directories to exclude from detection
    EXCLUDE_PATTERNS = [
        ".venv", "venv", "node_modules", "__pycache__", ".git",
        ".mypy_cache", ".pytest_cache", ".tox", ".cache", "dist",
        "build", "egg-info", ".eggs", "site-packages",
    ]

    def __init__(self, workspace_path: Path):
        """Initialize detector.

        Args:
            workspace_path: Root path to analyze
        """
        self.workspace = workspace_path
        self._ast_grep_available: Optional[bool] = None
        self._ripgrep_available: Optional[bool] = None

    def _should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded from detection."""
        path_str = str(path)
        return any(excl in path_str for excl in self.EXCLUDE_PATTERNS)

    async def detect(self) -> ServiceMap:
        """Run all detection strategies and merge results.

        Returns:
            ServiceMap with discovered services and connections
        """
        service_map = ServiceMap(workspace_path=str(self.workspace))

        # Run all detectors
        detectors = [
            ("docker-compose", self._detect_docker_compose),
            ("kubernetes", self._detect_kubernetes),
            ("terraform", self._detect_terraform),
            ("ast-grep", self._detect_ast_grep),
            ("ripgrep", self._detect_ripgrep),
            ("conventions", self._detect_conventions),
        ]

        for source_name, detector in detectors:
            try:
                services, connections = await detector()
                if services or connections:
                    service_map.detection_sources.append(source_name)
                    for svc in services:
                        service_map.add_service(svc)
                    for conn in connections:
                        service_map.add_connection(conn)
                    logger.info("Detected %d services from %s", len(services), source_name)
            except Exception as e:
                logger.warning("Detector %s failed: %s", source_name, e)

        # Find gaps
        service_map.gaps = self._find_gaps(service_map)

        return service_map

    async def _detect_docker_compose(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Parse docker-compose files."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        compose_files = list(self.workspace.glob("**/docker-compose*.yml")) + \
                       list(self.workspace.glob("**/docker-compose*.yaml"))

        for compose_file in compose_files:
            if self._should_exclude(compose_file):
                continue
            try:
                import yaml
                content = yaml.safe_load(compose_file.read_text())
                if not content or "services" not in content:
                    continue

                for name, config in content.get("services", {}).items():
                    image = config.get("image", "")
                    service_type = self._infer_service_type(image, name)
                    technology = self._infer_technology(image, name)

                    svc = ServiceNode(
                        id=f"docker:{name}",
                        name=name,
                        service_type=service_type,
                        source="docker-compose",
                        confidence="high",
                        file_path=str(compose_file),
                        ports=self._extract_ports(config.get("ports", [])),
                        technology=technology,
                        metadata={"image": image},
                    )
                    services.append(svc)

                    # Extract connections from depends_on
                    depends = config.get("depends_on", [])
                    if isinstance(depends, dict):
                        depends = list(depends.keys())
                    for dep in depends:
                        conn = ServiceConnection(
                            source_id=f"docker:{name}",
                            target_id=f"docker:{dep}",
                            protocol=self._infer_protocol_for_service(dep),
                            confidence="high",
                            source_detection="depends_on",
                        )
                        connections.append(conn)

                    # Extract connections from environment variables
                    env = config.get("environment", {})
                    if isinstance(env, list):
                        env = dict(e.split("=", 1) for e in env if "=" in e)
                    for key, val in env.items():
                        if any(p in str(val) for p in ["://", "_HOST", "_URL"]):
                            # Try to find target service
                            target = self._extract_service_from_env(str(val), services)
                            if target:
                                conn = ServiceConnection(
                                    source_id=f"docker:{name}",
                                    target_id=target,
                                    protocol=self._infer_protocol(str(val)),
                                    confidence="medium",
                                    source_detection=f"env:{key}",
                                )
                                connections.append(conn)

            except Exception as e:
                logger.warning("Failed to parse %s: %s", compose_file, e)

        return services, connections

    async def _detect_kubernetes(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Parse Kubernetes manifests."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        k8s_files = list(self.workspace.glob("**/k8s/**/*.yaml")) + \
                   list(self.workspace.glob("**/k8s/**/*.yml")) + \
                   list(self.workspace.glob("**/kubernetes/**/*.yaml")) + \
                   list(self.workspace.glob("**/manifests/**/*.yaml"))

        for k8s_file in k8s_files:
            if self._should_exclude(k8s_file):
                continue
            try:
                import yaml
                # Handle multi-document YAML
                docs = list(yaml.safe_load_all(k8s_file.read_text()))

                for doc in docs:
                    if not doc or not isinstance(doc, dict):
                        continue

                    kind = doc.get("kind", "")
                    metadata = doc.get("metadata", {})
                    name = metadata.get("name", "")

                    if kind in ("Deployment", "StatefulSet", "DaemonSet"):
                        # Extract container info
                        spec = doc.get("spec", {}).get("template", {}).get("spec", {})
                        containers = spec.get("containers", [])

                        for container in containers:
                            image = container.get("image", "")
                            service_type = self._infer_service_type(image, name)

                            svc = ServiceNode(
                                id=f"k8s:{name}",
                                name=name,
                                service_type=service_type,
                                source="kubernetes",
                                confidence="high",
                                file_path=str(k8s_file),
                                technology=self._infer_technology(image, name),
                                metadata={"kind": kind, "image": image},
                            )
                            services.append(svc)

                    elif kind == "Service":
                        # K8s Service - might indicate connections
                        spec = doc.get("spec", {})
                        ports = spec.get("ports", [])
                        for port in ports:
                            port_num = port.get("port") or port.get("targetPort")
                            if port_num:
                                # Find matching deployment
                                for svc in services:
                                    if svc.name == name or name in svc.name:
                                        svc.ports.append(int(port_num))

            except Exception as e:
                logger.warning("Failed to parse %s: %s", k8s_file, e)

        return services, connections

    async def _detect_terraform(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Parse Terraform files for cloud resources."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        tf_files = list(self.workspace.glob("**/*.tf"))
        if not tf_files:
            return services, connections

        # Simple regex-based parsing (HCL parsing would be better but requires dependency)
        resource_pattern = re.compile(r'resource\s+"(\w+)"\s+"(\w+)"')

        cloud_service_types = {
            "aws_rds": ("database", "RDS"),
            "aws_elasticache": ("cache", "ElastiCache"),
            "aws_sqs": ("queue", "SQS"),
            "aws_sns": ("queue", "SNS"),
            "aws_lambda": ("application", "Lambda"),
            "aws_ecs": ("application", "ECS"),
            "aws_eks": ("application", "EKS"),
            "google_sql_database": ("database", "CloudSQL"),
            "google_redis_instance": ("cache", "Memorystore"),
            "google_pubsub": ("queue", "PubSub"),
            "google_cloud_run": ("application", "CloudRun"),
            "azurerm_postgresql": ("database", "PostgreSQL"),
            "azurerm_redis_cache": ("cache", "Redis"),
        }

        for tf_file in tf_files:
            if self._should_exclude(tf_file):
                continue
            try:
                content = tf_file.read_text()
                for match in resource_pattern.finditer(content):
                    resource_type, resource_name = match.groups()

                    for pattern, (svc_type, tech) in cloud_service_types.items():
                        if pattern in resource_type:
                            svc = ServiceNode(
                                id=f"tf:{resource_name}",
                                name=resource_name,
                                service_type=cast(ServiceType, svc_type),
                                source="terraform",
                                confidence="high",
                                file_path=str(tf_file),
                                technology=tech,
                                metadata={"resource_type": resource_type},
                            )
                            services.append(svc)
                            break

            except Exception as e:
                logger.warning("Failed to parse %s: %s", tf_file, e)

        return services, connections

    async def _detect_ast_grep(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Use ast-grep for structural code pattern detection."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        if not await self._check_ast_grep():
            logger.debug("ast-grep not available, skipping")
            return services, connections

        # Patterns for service detection
        patterns = [
            # Spring Boot
            {
                "pattern": "@RestController",
                "lang": "java",
                "type": "application",
                "tech": "spring-boot",
            },
            {
                "pattern": "@Service",
                "lang": "java",
                "type": "application",
                "tech": "spring",
            },
            # FastAPI
            {
                "pattern": "app = FastAPI($$$)",
                "lang": "python",
                "type": "application",
                "tech": "fastapi",
            },
            # Express
            {
                "pattern": "express()",
                "lang": "javascript",
                "type": "application",
                "tech": "express",
            },
            # Flask
            {
                "pattern": "Flask(__name__)",
                "lang": "python",
                "type": "application",
                "tech": "flask",
            },
            # Django
            {
                "pattern": "urlpatterns = [$$$]",
                "lang": "python",
                "type": "application",
                "tech": "django",
            },
            # gRPC
            {
                "pattern": "grpc.server($$$)",
                "lang": "python",
                "type": "application",
                "tech": "grpc",
            },
        ]

        for pat_info in patterns:
            try:
                result = await self._run_ast_grep(pat_info["pattern"], pat_info["lang"])
                for match in result:
                    file_path = match.get("file", "")
                    # Derive service name from file path
                    name = Path(file_path).stem
                    if name in ("app", "main", "server", "index"):
                        name = Path(file_path).parent.name or name

                    svc = ServiceNode(
                        id=f"code:{name}",
                        name=name,
                        service_type=cast(ServiceType, pat_info["type"]),
                        source="ast-grep",
                        confidence="medium",
                        file_path=file_path,
                        technology=pat_info["tech"],
                    )
                    services.append(svc)

            except Exception as e:
                logger.debug("ast-grep pattern failed: %s", e)

        return services, connections

    async def _detect_ripgrep(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Use ripgrep for string pattern detection."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        if not await self._check_ripgrep():
            logger.debug("ripgrep not available, skipping")
            return services, connections

        # Patterns for connection detection
        connection_patterns = [
            # Database connections (variable names, not values!)
            (r'(DATABASE_URL|DB_HOST|POSTGRES_HOST|MYSQL_HOST)', "database"),
            (r'(REDIS_URL|REDIS_HOST|CACHE_URL)', "cache"),
            (r'(RABBITMQ_URL|AMQP_URL|KAFKA_BROKERS)', "queue"),
            # HTTP service references
            (r'(API_URL|SERVICE_URL|BACKEND_URL)', "application"),
        ]

        for pattern, target_type in connection_patterns:
            try:
                matches = await self._run_ripgrep(pattern)
                for match in matches:
                    # Extract the env var name being used
                    env_var = re.search(pattern, match.get("text", ""))
                    if env_var:
                        var_name = env_var.group(1)
                        # This indicates a connection to a service of this type
                        # We'll add as a potential service if not already found
                        svc_name = var_name.replace("_URL", "").replace("_HOST", "").lower()

                        svc = ServiceNode(
                            id=f"env:{svc_name}",
                            name=svc_name,
                            service_type=cast(ServiceType, target_type),
                            source="ripgrep",
                            confidence="low",
                            file_path=match.get("file"),
                            metadata={"env_var": var_name},
                        )
                        services.append(svc)

            except Exception as e:
                logger.debug("ripgrep pattern failed: %s", e)

        return services, connections

    async def _detect_conventions(self) -> tuple[List[ServiceNode], List[ServiceConnection]]:
        """Detect services from folder naming conventions."""
        services: List[ServiceNode] = []
        connections: List[ServiceConnection] = []

        convention_dirs = {
            "services": "application",
            "microservices": "application",
            "apps": "application",
            "api": "application",
            "gateway": "gateway",
            "workers": "application",
            "jobs": "application",
        }

        for dir_name, service_type in convention_dirs.items():
            for dir_path in self.workspace.glob(f"**/{dir_name}"):
                if not dir_path.is_dir() or self._should_exclude(dir_path):
                    continue

                # Each subdirectory might be a service
                for subdir in dir_path.iterdir():
                    if subdir.is_dir() and not subdir.name.startswith(".") and not self._should_exclude(subdir):
                        svc = ServiceNode(
                            id=f"conv:{subdir.name}",
                            name=subdir.name,
                            service_type=cast(ServiceType, service_type),
                            source="conventions",
                            confidence="low",
                            file_path=str(subdir),
                        )
                        services.append(svc)

        return services, connections

    def _infer_service_type(self, image: str, name: str) -> ServiceType:
        """Infer service type from image name or service name."""
        search_text = f"{image} {name}".lower()

        for svc_type, patterns in self.SERVICE_TYPE_PATTERNS.items():
            if any(p in search_text for p in patterns):
                return cast(ServiceType, svc_type)

        return "application"

    def _infer_technology(self, image: str, name: str) -> Optional[str]:
        """Infer technology from image or name."""
        search_text = f"{image} {name}".lower()

        tech_patterns = [
            ("postgresql", ["postgres", "pg"]),
            ("mysql", ["mysql", "mariadb"]),
            ("mongodb", ["mongo"]),
            ("redis", ["redis"]),
            ("elasticsearch", ["elastic", "opensearch"]),
            ("rabbitmq", ["rabbitmq", "rabbit"]),
            ("kafka", ["kafka"]),
            ("nginx", ["nginx"]),
            ("spring-boot", ["spring"]),
            ("node.js", ["node"]),
            ("python", ["python", "django", "flask", "fastapi"]),
        ]

        for tech, patterns in tech_patterns:
            if any(p in search_text for p in patterns):
                return tech

        return None

    def _extract_ports(self, ports_config: List) -> List[int]:
        """Extract port numbers from docker-compose ports config."""
        result = []
        for port in ports_config:
            if isinstance(port, int):
                result.append(port)
            elif isinstance(port, str):
                # Handle "8080:80" or "8080"
                match = re.search(r':?(\d+)$', port)
                if match:
                    result.append(int(match.group(1)))
        return result

    def _infer_protocol(self, connection_str: str) -> ProtocolType:
        """Infer protocol from connection string."""
        for protocol, patterns in self.PROTOCOL_PATTERNS.items():
            if any(p in connection_str.lower() for p in patterns):
                return cast(ProtocolType, protocol)
        return "unknown"

    def _infer_protocol_for_service(self, service_name: str) -> ProtocolType:
        """Infer protocol based on service name."""
        name_lower = service_name.lower()
        if any(p in name_lower for p in ["postgres", "mysql", "db", "database"]):
            return "JDBC"
        if "redis" in name_lower:
            return "Redis"
        if "mongo" in name_lower:
            return "MongoDB"
        if any(p in name_lower for p in ["rabbit", "kafka", "queue"]):
            return "AMQP"
        return "HTTP"

    def _extract_service_from_env(self, value: str, known_services: List[ServiceNode]) -> Optional[str]:
        """Try to match env value to a known service."""
        value_lower = value.lower()
        for svc in known_services:
            if svc.name.lower() in value_lower:
                return svc.id
        return None

    def _find_gaps(self, service_map: ServiceMap) -> List[str]:
        """Identify gaps in the service map."""
        gaps = []

        # Services without connections
        connected_ids: Set[str] = set()
        for conn in service_map.connections:
            connected_ids.add(conn.source_id)
            connected_ids.add(conn.target_id)

        for svc in service_map.services:
            if svc.id not in connected_ids and svc.service_type == "application":
                gaps.append(f"Service '{svc.name}' has no detected connections")

        # Connections to unknown services
        known_ids = {s.id for s in service_map.services}
        for conn in service_map.connections:
            if conn.target_id not in known_ids:
                gaps.append(f"Connection to unknown service: {conn.target_id}")

        return gaps

    async def _check_ast_grep(self) -> bool:
        """Check if ast-grep is available."""
        if self._ast_grep_available is not None:
            return self._ast_grep_available

        try:
            proc = await asyncio.create_subprocess_exec(
                "sg", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            self._ast_grep_available = proc.returncode == 0
        except FileNotFoundError:
            self._ast_grep_available = False

        return self._ast_grep_available

    async def _check_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        if self._ripgrep_available is not None:
            return self._ripgrep_available

        try:
            proc = await asyncio.create_subprocess_exec(
                "rg", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            self._ripgrep_available = proc.returncode == 0
        except FileNotFoundError:
            self._ripgrep_available = False

        return self._ripgrep_available

    async def _run_ast_grep(self, pattern: str, lang: str) -> List[Dict[str, Any]]:
        """Run ast-grep with a pattern."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "sg", "--pattern", pattern, "--lang", lang, "--json",
                str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout:
                return json.loads(stdout)
        except Exception as e:
            logger.debug("ast-grep error: %s", e)

        return []

    async def _run_ripgrep(self, pattern: str) -> List[Dict[str, Any]]:
        """Run ripgrep with a pattern."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "rg", "--json", "-e", pattern,
                str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            results = []
            if stdout:
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        try:
                            data = json.loads(line)
                            if data.get("type") == "match":
                                match_data = data.get("data", {})
                                results.append({
                                    "file": match_data.get("path", {}).get("text", ""),
                                    "line": match_data.get("line_number"),
                                    "text": match_data.get("lines", {}).get("text", ""),
                                })
                        except json.JSONDecodeError:
                            pass
            return results

        except Exception as e:
            logger.debug("ripgrep error: %s", e)

        return []
