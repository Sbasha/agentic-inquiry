"""Tests for AccuracyValidator."""
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agent_vault.validation.accuracy_validator import AccuracyValidator
from agent_vault.validation.models import ValidationResult, ValidationReport


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_creation(self) -> None:
        """Test creating a validation result."""
        result = ValidationResult(
            check_name="test_check",
            category="existence",
            total_checked=100,
            valid_count=95,
        )
        assert result.check_name == "test_check"
        assert result.category == "existence"
        assert result.total_checked == 100
        assert result.valid_count == 95

    def test_validation_result_with_details(self) -> None:
        """Test validation result with details."""
        result = ValidationResult(
            check_name="test_check",
            category="reference",
            total_checked=100,
            valid_count=80,
            details=["Error 1", "Error 2"],
        )
        result.compute()
        assert result.passed is False
        assert len(result.details) == 2

    def test_validation_result_compute_accuracy(self) -> None:
        """Test accuracy calculation."""
        result = ValidationResult(
            check_name="test_check",
            category="existence",
            total_checked=100,
            valid_count=95,
        )
        result.compute()
        assert result.accuracy == 0.95
        assert result.passed is True

    def test_validation_result_zero_items(self) -> None:
        """Test accuracy with zero items."""
        result = ValidationResult(
            check_name="test_check",
            category="existence",
            total_checked=0,
            valid_count=0,
        )
        result.compute()
        assert result.accuracy == 1.0
        assert result.passed is True

    def test_validation_result_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = ValidationResult(
            check_name="test_check",
            category="existence",
            total_checked=100,
            valid_count=95,
        )
        result.compute()
        data = result.to_dict()
        assert data["check_name"] == "test_check"
        assert data["accuracy"] == 0.95
        assert data["passed"] is True


class TestValidationReport:
    """Tests for ValidationReport dataclass."""

    def test_report_creation(self) -> None:
        """Test creating a validation report."""
        result1 = ValidationResult("check1", "existence", 100, 95)
        result1.compute()
        result2 = ValidationResult("check2", "reference", 50, 48)
        result2.compute()

        report = ValidationReport(
            project_id="test_project",
            results=[result1, result2],
        )
        assert report.project_id == "test_project"
        assert len(report.results) == 2

    def test_report_compute_overall_accuracy(self) -> None:
        """Test overall accuracy calculation."""
        result1 = ValidationResult("check1", "existence", 100, 95)
        result1.compute()
        result2 = ValidationResult("check2", "reference", 100, 90)
        result2.compute()

        report = ValidationReport(
            project_id="test_project",
            results=[result1, result2],
        )
        report.compute_overall()
        # (95 + 90) / 200 = 0.925
        assert report.overall_accuracy == 0.925

    def test_report_meets_threshold(self) -> None:
        """Test threshold check."""
        result = ValidationResult("check1", "existence", 100, 96)
        result.compute()

        report = ValidationReport(
            project_id="test_project",
            results=[result],
            threshold=0.95,
        )
        report.compute_overall()
        assert report.meets_threshold is True

    def test_report_below_threshold(self) -> None:
        """Test failed threshold check."""
        result = ValidationResult("check1", "existence", 100, 90)
        result.compute()

        report = ValidationReport(
            project_id="test_project",
            results=[result],
            threshold=0.95,
        )
        report.compute_overall()
        assert report.meets_threshold is False

    def test_report_empty_results(self) -> None:
        """Test report with no results."""
        report = ValidationReport(project_id="test_project")
        report.compute_overall()
        assert report.overall_accuracy == 1.0
        assert report.meets_threshold is True

    def test_report_to_dict(self) -> None:
        """Test conversion to dictionary."""
        result = ValidationResult("check1", "existence", 100, 95)
        result.compute()
        report = ValidationReport(
            project_id="test_project",
            results=[result],
        )
        report.compute_overall()
        data = report.to_dict()
        assert data["project_id"] == "test_project"
        assert "overall_accuracy" in data
        assert "results" in data


class TestAccuracyValidator:
    """Tests for AccuracyValidator."""

    @pytest.fixture
    def mock_storage(self) -> MagicMock:
        """Create mock storage."""
        storage = MagicMock()
        storage.project_id = "test_project"
        storage.query_raw = AsyncMock(return_value=[])
        storage.query_entities = AsyncMock(return_value=[])
        storage.query_relationships = AsyncMock(return_value=[])
        return storage

    @pytest.fixture
    def validator(self, mock_storage: MagicMock, tmp_path: Path) -> AccuracyValidator:
        """Create validator with mock storage."""
        return AccuracyValidator(
            storage=mock_storage,
            project_root=tmp_path,
        )

    @pytest.mark.asyncio
    async def test_validate_all_empty_index(
        self, validator: AccuracyValidator
    ) -> None:
        """Test validation with empty index."""
        report = await validator.validate_all()
        assert isinstance(report, ValidationReport)
        # With empty index, checks should still run
        assert len(report.results) >= 3  # At least symbol, ref, lineage checks

    @pytest.mark.asyncio
    async def test_validate_all_with_sample_size(
        self, validator: AccuracyValidator
    ) -> None:
        """Test validation with custom sample size."""
        report = await validator.validate_all(sample_size=50)
        assert isinstance(report, ValidationReport)

    @pytest.mark.asyncio
    async def test_validate_all_deep(
        self, validator: AccuracyValidator
    ) -> None:
        """Test validation with deep completeness check."""
        report = await validator.validate_all(deep=True)
        assert isinstance(report, ValidationReport)
        # Deep mode adds completeness check
        check_names = [r.check_name for r in report.results]
        assert "completeness" in check_names

    @pytest.mark.asyncio
    async def test_validate_all_detects_stack(
        self, validator: AccuracyValidator, tmp_path: Path
    ) -> None:
        """Test that validation detects project stack."""
        # Create a Python file to detect
        (tmp_path / "test.py").write_text("# Python file")
        report = await validator.validate_all()
        assert "detected_stack" in report.to_dict()

    @pytest.mark.asyncio
    async def test_validate_all_threshold(
        self, validator: AccuracyValidator
    ) -> None:
        """Test that validation uses threshold."""
        validator._threshold = 0.99
        report = await validator.validate_all()
        assert report.threshold == 0.99


class TestAccuracyValidatorIntegration:
    """Integration tests for AccuracyValidator."""

    @pytest.fixture
    def mock_storage_with_data(self) -> MagicMock:
        """Create mock storage with sample data."""
        storage = MagicMock()
        storage.project_id = "test_project"
        storage.query_raw = AsyncMock(return_value=[
            {
                "id": "entity1",
                "name": "test_func",
                "type": "function",
                "file_path": "test.py",
                "line_start": 10,
                "line_end": 20,
            },
            {
                "id": "entity2",
                "name": "TestClass",
                "type": "class",
                "file_path": "test.py",
                "line_start": 1,
                "line_end": 30,
            },
        ])
        storage.query_entities = AsyncMock(return_value=[])
        storage.query_relationships = AsyncMock(return_value=[
            {
                "source_id": "entity1",
                "target_id": "entity2",
                "type": "belongs_to",
            }
        ])
        return storage

    @pytest.mark.asyncio
    async def test_validate_with_sample_data(
        self, mock_storage_with_data: MagicMock, tmp_path: Path
    ) -> None:
        """Test validation with sample entity data."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("""
class TestClass:
    def test_func(self):
        pass
""")

        validator = AccuracyValidator(
            storage=mock_storage_with_data,
            project_root=tmp_path,
        )
        report = await validator.validate_all(sample_size=10)
        assert isinstance(report, ValidationReport)
        assert len(report.results) > 0
