"""Data models for index validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    check_name: str
    category: str  # existence, reference, traceability, framework, completeness
    total_checked: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    accuracy: float = 0.0
    passed: bool = False  # True if accuracy >= threshold
    details: List[str] = field(default_factory=list)  # Specific failures
    threshold: float = 0.95

    def compute(self) -> None:
        """Compute accuracy and pass/fail status."""
        if self.total_checked > 0:
            self.accuracy = self.valid_count / self.total_checked
            self.passed = self.accuracy >= self.threshold
        else:
            self.accuracy = 1.0
            self.passed = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "check_name": self.check_name,
            "category": self.category,
            "total_checked": self.total_checked,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "accuracy": round(self.accuracy, 4),
            "passed": self.passed,
            "details": self.details[:10],  # Limit details in output
        }


@dataclass
class ValidationReport:
    """Overall validation report."""

    project_id: str
    detected_stack: Dict[str, Any] = field(default_factory=dict)
    total_checks: int = 0
    passed_checks: int = 0
    overall_accuracy: float = 0.0
    meets_threshold: bool = False  # True if overall >= 95%
    results: List[ValidationResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    threshold: float = 0.95

    def compute_overall(self) -> None:
        """Compute overall metrics."""
        if not self.results:
            self.meets_threshold = True
            self.overall_accuracy = 1.0
            return

        total_valid = sum(r.valid_count for r in self.results)
        total_checked = sum(r.total_checked for r in self.results)
        self.overall_accuracy = total_valid / total_checked if total_checked > 0 else 1.0
        self.total_checks = len(self.results)
        self.passed_checks = sum(1 for r in self.results if r.passed)
        self.meets_threshold = self.overall_accuracy >= self.threshold

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "project_id": self.project_id,
            "detected_stack": self.detected_stack,
            "overall_accuracy": round(self.overall_accuracy, 4),
            "meets_threshold": self.meets_threshold,
            "threshold": self.threshold,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
        }
