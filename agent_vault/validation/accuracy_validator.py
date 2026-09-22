"""Accuracy validator for agv index validation.

Validates index accuracy using consistency-based checks:
1. Symbol existence - Indexed symbols exist at stated file/line locations
2. Reference targets - Reference targets exist in the symbol graph
3. Lineage endpoints - Lineage path endpoints are valid
4. Framework patterns - Framework-specific patterns match source
5. Completeness - Symbols in source are in the index (deep mode)
"""
from __future__ import annotations

import logging
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .models import ValidationReport, ValidationResult

if TYPE_CHECKING:
    from agent_vault.storage.facade import StorageFacade

logger = logging.getLogger(__name__)

# Framework detection indicators
FRAMEWORK_INDICATORS: Dict[str, Dict[str, Any]] = {
    "spring": {
        "files": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "patterns": [r"@Controller", r"@Service", r"@Repository", r"@Entity"],
        "extensions": [".java", ".kt"],
    },
    "django": {
        "files": ["manage.py", "settings.py"],
        "patterns": [r"from django", r"models\.Model", r"class.*\(models\.Model\)"],
        "extensions": [".py"],
    },
    "fastapi": {
        "files": ["requirements.txt", "pyproject.toml"],
        "patterns": [r"from fastapi", r"FastAPI\(\)", r"@app\.(get|post|put|delete)"],
        "extensions": [".py"],
    },
    "flask": {
        "files": ["requirements.txt", "pyproject.toml"],
        "patterns": [r"from flask", r"Flask\(__name__\)", r"@app\.route"],
        "extensions": [".py"],
    },
    "express": {
        "files": ["package.json"],
        "patterns": [r"express\(\)", r"require\(['\"]express['\"]\)", r"app\.(get|post|put|delete)"],
        "extensions": [".js", ".ts"],
    },
    "react": {
        "files": ["package.json"],
        "patterns": [r"from ['\"]react['\"]", r"import React", r"useState", r"useEffect"],
        "extensions": [".jsx", ".tsx", ".js", ".ts"],
    },
    "vue": {
        "files": ["package.json", "vue.config.js"],
        "patterns": [r"<template>", r"Vue\.component", r"defineComponent"],
        "extensions": [".vue", ".js", ".ts"],
    },
}


class AccuracyValidator:
    """Validates agv index accuracy using consistency checks.

    Runs multiple validation checks and computes overall accuracy.
    Target accuracy threshold is 95%.
    """

    def __init__(
        self,
        storage: "StorageFacade",
        project_root: Path,
        threshold: float = 0.95,
    ):
        """Initialize validator.

        Args:
            storage: Storage facade for querying index
            project_root: Root path of the project
            threshold: Accuracy threshold (default 0.95 = 95%)
        """
        self._storage = storage
        self._project_root = project_root
        self._threshold = threshold

    async def validate_all(
        self,
        sample_size: int = 100,
        deep: bool = False,
    ) -> ValidationReport:
        """Run all validation checks.

        Args:
            sample_size: Number of samples per check
            deep: If True, run completeness check (slower)

        Returns:
            ValidationReport with overall accuracy and per-check results
        """
        project_id = getattr(self._storage, "project_id", "unknown")
        report = ValidationReport(project_id=project_id, threshold=self._threshold)

        try:
            # Step 1: Detect stack
            report.detected_stack = await self._detect_stack()
            logger.info("Detected stack: %s", report.detected_stack)

            # Step 2: Core validation checks
            symbol_result = await self._validate_symbol_existence(sample_size)
            report.results.append(symbol_result)

            ref_result = await self._validate_reference_targets(sample_size)
            report.results.append(ref_result)

            lineage_result = await self._validate_lineage_endpoints(sample_size)
            report.results.append(lineage_result)

            # Step 3: Framework-specific validation
            for framework in report.detected_stack.get("frameworks", []):
                result = await self._validate_framework(framework, sample_size)
                if result and result.total_checked > 0:
                    report.results.append(result)

            # Step 4: Deep completeness check (optional)
            if deep:
                completeness_result = await self._validate_completeness(sample_size)
                report.results.append(completeness_result)

        except Exception as e:
            logger.exception("Validation error")
            report.errors.append(str(e))

        report.compute_overall()
        return report

    async def _detect_stack(self) -> Dict[str, Any]:
        """Auto-detect frameworks and technologies in the project."""
        detected: Dict[str, Any] = {
            "frameworks": [],
            "languages": set(),
            "files_scanned": 0,
        }

        # Check for framework indicator files
        for framework, indicators in FRAMEWORK_INDICATORS.items():
            for indicator_file in indicators.get("files", []):
                if list(self._project_root.glob(f"**/{indicator_file}")):
                    if framework not in detected["frameworks"]:
                        detected["frameworks"].append(framework)
                    break

        # Scan for language extensions
        for ext in [".py", ".java", ".js", ".ts", ".go", ".rs", ".kt", ".vue", ".jsx", ".tsx"]:
            if list(self._project_root.glob(f"**/*{ext}"))[:1]:
                detected["languages"].add(ext.lstrip("."))

        detected["languages"] = list(detected["languages"])
        return detected

    async def _validate_symbol_existence(self, sample_size: int) -> ValidationResult:
        """Validate indexed symbols exist at stated locations."""
        result = ValidationResult(
            check_name="symbol_existence",
            category="existence",
            threshold=self._threshold,
        )

        try:
            # Get entities with file locations
            entities = await self._storage.query_raw(
                table_name="graph_entities",
                filters={},
                limit=sample_size * 2,  # Over-fetch for filtering
                project_id=getattr(self._storage, "project_id", None),
            )

            # Filter to entities with file paths and sample
            entities_with_files = [
                e for e in entities
                if e.get("file_path") and e.get("line_number")
            ]
            sample = random.sample(
                entities_with_files,
                min(sample_size, len(entities_with_files))
            ) if entities_with_files else []

            for entity in sample:
                file_path = Path(entity["file_path"])
                if not file_path.is_absolute():
                    file_path = self._project_root / file_path

                result.total_checked += 1

                if not file_path.exists():
                    result.invalid_count += 1
                    result.details.append(f"File not found: {file_path.name}")
                    continue

                # Check if symbol name appears near stated line
                try:
                    content = file_path.read_text(errors="ignore")
                    lines = content.split("\n")
                    line_num = int(entity["line_number"]) - 1  # 0-indexed

                    # Search in a range around the stated line
                    search_start = max(0, line_num - 3)
                    search_end = min(len(lines), line_num + 4)

                    entity_name = entity.get("name", "")
                    found = any(
                        entity_name in lines[i]
                        for i in range(search_start, search_end)
                        if i < len(lines)
                    )

                    if found:
                        result.valid_count += 1
                    else:
                        result.invalid_count += 1
                        result.details.append(
                            f"'{entity_name}' not found near line {line_num + 1} in {file_path.name}"
                        )
                except Exception as e:
                    result.invalid_count += 1
                    result.details.append(f"Error reading {file_path.name}: {e}")

        except Exception as e:
            logger.warning("Symbol existence check failed: %s", e)
            result.details.append(f"Check failed: {e}")

        result.compute()
        return result

    async def _validate_reference_targets(self, sample_size: int) -> ValidationResult:
        """Validate reference targets exist in the graph."""
        result = ValidationResult(
            check_name="reference_targets",
            category="reference",
            threshold=self._threshold,
        )

        try:
            # Get relationships
            relationships = await self._storage.query_raw(
                table_name="graph_relationships",
                filters={},
                limit=sample_size,
                project_id=getattr(self._storage, "project_id", None),
            )

            for rel in relationships:
                result.total_checked += 1
                target_id = rel.get("target_id")

                if not target_id:
                    result.invalid_count += 1
                    result.details.append("Relationship missing target_id")
                    continue

                # Check target exists
                target_entities = await self._storage.query_raw(
                    table_name="graph_entities",
                    filters={"id": target_id},
                    limit=1,
                    project_id=getattr(self._storage, "project_id", None),
                )

                if target_entities:
                    result.valid_count += 1
                else:
                    result.invalid_count += 1
                    source_id = rel.get("source_id", "?")
                    result.details.append(f"Dangling: {source_id} -> {target_id}")

        except Exception as e:
            logger.warning("Reference target check failed: %s", e)
            result.details.append(f"Check failed: {e}")

        result.compute()
        return result

    async def _validate_lineage_endpoints(self, sample_size: int) -> ValidationResult:
        """Validate lineage path endpoints are valid entities."""
        result = ValidationResult(
            check_name="lineage_endpoints",
            category="traceability",
            threshold=self._threshold,
        )

        try:
            # Get relationships that represent lineage (calls, imports, etc.)
            lineage_types = ["calls", "imports", "defines", "inherits", "uses"]
            relationships = await self._storage.query_raw(
                table_name="graph_relationships",
                filters={},
                limit=sample_size * 2,
                project_id=getattr(self._storage, "project_id", None),
            )

            # Filter to lineage-related relationships
            lineage_rels = [
                r for r in relationships
                if r.get("relationship_type") in lineage_types
            ]
            sample = random.sample(
                lineage_rels,
                min(sample_size, len(lineage_rels))
            ) if lineage_rels else []

            for rel in sample:
                result.total_checked += 1
                source_id = rel.get("source_id")
                target_id = rel.get("target_id")

                # Check both endpoints exist
                source_exists = bool(await self._storage.query_raw(
                    table_name="graph_entities",
                    filters={"id": source_id},
                    limit=1,
                    project_id=getattr(self._storage, "project_id", None),
                )) if source_id else False

                target_exists = bool(await self._storage.query_raw(
                    table_name="graph_entities",
                    filters={"id": target_id},
                    limit=1,
                    project_id=getattr(self._storage, "project_id", None),
                )) if target_id else False

                if source_exists and target_exists:
                    result.valid_count += 1
                else:
                    result.invalid_count += 1
                    missing = []
                    if not source_exists:
                        missing.append(f"source={source_id}")
                    if not target_exists:
                        missing.append(f"target={target_id}")
                    result.details.append(f"Missing endpoints: {', '.join(missing)}")

        except Exception as e:
            logger.warning("Lineage endpoint check failed: %s", e)
            result.details.append(f"Check failed: {e}")

        result.compute()
        return result

    async def _validate_framework(
        self,
        framework: str,
        sample_size: int,
    ) -> Optional[ValidationResult]:
        """Validate framework-specific patterns match source."""
        indicators = FRAMEWORK_INDICATORS.get(framework)
        if not indicators:
            return None

        result = ValidationResult(
            check_name=f"framework_{framework}",
            category="framework",
            threshold=self._threshold,
        )

        try:
            patterns = indicators.get("patterns", [])
            extensions = indicators.get("extensions", [])

            # Find files with matching extensions
            source_files: List[Path] = []
            for ext in extensions:
                source_files.extend(
                    list(self._project_root.glob(f"**/*{ext}"))[:sample_size]
                )

            # Exclude common non-source directories
            source_files = [
                f for f in source_files
                if not any(
                    excl in str(f)
                    for excl in [".venv", "node_modules", "__pycache__", ".git", "dist", "build"]
                )
            ][:sample_size]

            for file_path in source_files:
                try:
                    content = file_path.read_text(errors="ignore")

                    # Check if any framework pattern matches
                    has_pattern = any(
                        re.search(pattern, content)
                        for pattern in patterns
                    )

                    if has_pattern:
                        result.total_checked += 1

                        # Verify related symbols are indexed
                        # Simple check: file should have entities in the index
                        rel_path = str(file_path.relative_to(self._project_root))
                        entities = await self._storage.query_raw(
                            table_name="graph_entities",
                            filters={"file_path": rel_path},
                            limit=1,
                            project_id=getattr(self._storage, "project_id", None),
                        )

                        # Also try absolute path
                        if not entities:
                            entities = await self._storage.query_raw(
                                table_name="graph_entities",
                                filters={"file_path": str(file_path)},
                                limit=1,
                                project_id=getattr(self._storage, "project_id", None),
                            )

                        if entities:
                            result.valid_count += 1
                        else:
                            result.invalid_count += 1
                            result.details.append(
                                f"No entities indexed for {framework} file: {file_path.name}"
                            )

                except Exception as e:
                    logger.debug("Error checking %s: %s", file_path, e)

        except Exception as e:
            logger.warning("Framework validation failed for %s: %s", framework, e)
            result.details.append(f"Check failed: {e}")

        result.compute()
        return result

    async def _validate_completeness(self, sample_size: int) -> ValidationResult:
        """Deep check: find symbols in source not in index."""
        result = ValidationResult(
            check_name="completeness",
            category="completeness",
            threshold=self._threshold,
        )

        try:
            # Sample Python files (can extend to other languages)
            py_files = list(self._project_root.glob("**/*.py"))
            py_files = [
                f for f in py_files
                if not any(
                    excl in str(f)
                    for excl in [".venv", "node_modules", "__pycache__", ".git", "test"]
                )
            ]

            sample_files = random.sample(
                py_files,
                min(sample_size // 5, len(py_files))  # ~20 files
            ) if py_files else []

            # Simple pattern-based symbol extraction
            class_pattern = re.compile(r"^class\s+(\w+)", re.MULTILINE)
            func_pattern = re.compile(r"^(?:async\s+)?def\s+(\w+)", re.MULTILINE)

            for file_path in sample_files:
                try:
                    content = file_path.read_text(errors="ignore")
                    rel_path = str(file_path.relative_to(self._project_root))

                    # Find classes and functions
                    classes = class_pattern.findall(content)
                    functions = [f for f in func_pattern.findall(content) if not f.startswith("_")]

                    symbols = classes + functions[:10]  # Limit functions per file

                    for symbol in symbols:
                        result.total_checked += 1

                        # Check if indexed
                        entities = await self._storage.query_raw(
                            table_name="graph_entities",
                            filters={"name": symbol},
                            limit=5,
                            project_id=getattr(self._storage, "project_id", None),
                        )

                        # Check if any match is in this file
                        found = any(
                            rel_path in str(e.get("file_path", "")) or
                            str(file_path) in str(e.get("file_path", ""))
                            for e in entities
                        )

                        if found:
                            result.valid_count += 1
                        else:
                            result.invalid_count += 1
                            result.details.append(
                                f"Missing: {symbol} in {file_path.name}"
                            )

                except Exception as e:
                    logger.debug("Error checking %s: %s", file_path, e)

        except Exception as e:
            logger.warning("Completeness check failed: %s", e)
            result.details.append(f"Check failed: {e}")

        result.compute()
        return result
