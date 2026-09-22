"""Tests for diff truncation utility (T44).

Tests truncate_diff() which caps the size of LocalDiff payloads.

Covers:
- No truncation when content is under limits
- Per-file cap: changed_lines truncated to max_per_file (100 default)
- Total cap: files dropped once total changed_lines exceeds max_total (500 default)
- Alphabetical ordering: files sorted by path before processing
- Truncation flag set to True when files/lines are omitted
- omitted_count reflects number of dropped files
- Empty diff passthrough: no-op for empty modified_files
- Original LocalDiff object is not mutated
"""

from __future__ import annotations


from agent_vault.server.routes.search import LocalDiff, LocalDiffFile
from agent_vault.server.overlay.truncation import truncate_diff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(path: str, n_lines: int, status: str = "modified") -> LocalDiffFile:
    """Create a LocalDiffFile with n_lines synthetic changed_lines."""
    return LocalDiffFile(path=path, changed_lines=list(range(1, n_lines + 1)), status=status)


def _make_diff(files: list[LocalDiffFile], branch: str | None = None) -> LocalDiff:
    return LocalDiff(branch=branch, modified_files=files)


# ---------------------------------------------------------------------------
# T44-1: No truncation under limits
# ---------------------------------------------------------------------------

class TestNoTruncation:
    """When content is within limits, output must equal input."""

    def test_small_diff_unchanged(self):
        """A diff well under limits must be returned as-is (logically equivalent)."""
        files = [_make_file("a.py", 10), _make_file("b.py", 20)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        assert result.truncated is False
        assert result.omitted_count == 0
        assert len(result.modified_files) == 2

    def test_exact_per_file_limit_not_truncated(self):
        """Exactly max_per_file lines must not trigger truncation."""
        files = [_make_file("a.py", 100)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        assert len(result.modified_files[0].changed_lines) == 100
        assert result.truncated is False

    def test_single_file_one_line_passthrough(self):
        """Single-line diff must pass through unchanged."""
        files = [_make_file("only.py", 1)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        assert len(result.modified_files) == 1
        assert len(result.modified_files[0].changed_lines) == 1
        assert result.truncated is False

    def test_branch_preserved_in_output(self):
        """The branch field on LocalDiff must be preserved."""
        diff = _make_diff([_make_file("f.py", 5)], branch="feature/x")

        result = truncate_diff(diff)

        assert result.branch == "feature/x"


# ---------------------------------------------------------------------------
# T44-2: Per-file cap (100 lines default)
# ---------------------------------------------------------------------------

class TestPerFileCap:
    """changed_lines is capped at max_per_file per file."""

    def test_per_file_cap_applied(self):
        """A file with 200 lines must be capped to max_per_file=100."""
        files = [_make_file("big.py", 200)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=5000)

        assert len(result.modified_files[0].changed_lines) == 100

    def test_custom_per_file_cap(self):
        """A custom max_per_file value must be respected."""
        files = [_make_file("big.py", 50)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=10, max_total=5000)

        assert len(result.modified_files[0].changed_lines) == 10

    def test_per_file_cap_does_not_drop_file(self):
        """Capping lines within a file must not remove the file from modified_files."""
        files = [_make_file("big.py", 200)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=5000)

        assert len(result.modified_files) == 1

    def test_per_file_cap_preserves_small_files_unchanged(self):
        """Files smaller than max_per_file must keep all their lines."""
        files = [_make_file("small.py", 5), _make_file("big.py", 200)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=5000)

        # After alphabetical sort: big.py first, small.py second
        # Regardless of order, each file's line count must be checked
        result_by_path = {f.path: f for f in result.modified_files}
        assert len(result_by_path["small.py"].changed_lines) == 5
        assert len(result_by_path["big.py"].changed_lines) == 100


# ---------------------------------------------------------------------------
# T44-3: Total cap (500 lines default)
# ---------------------------------------------------------------------------

class TestTotalCap:
    """Files are dropped once max_total changed_lines accumulates."""

    def test_total_cap_drops_extra_files(self):
        """After 500 total lines, remaining files must be dropped."""
        # 6 files of 100 lines each = 600 total; first 5 fit, 6th is dropped
        files = [_make_file(f"file{i:02d}.py", 100) for i in range(6)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        # Should have exactly 5 files (alphabetical order: file00..file04)
        assert len(result.modified_files) == 5
        assert result.truncated is True
        assert result.omitted_count == 1

    def test_total_lines_do_not_exceed_max_total(self):
        """Total changed_lines across all kept files must not exceed max_total."""
        files = [_make_file(f"f{i:02d}.py", 100) for i in range(10)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        total = sum(len(f.changed_lines) for f in result.modified_files)
        assert total <= 500

    def test_last_file_partially_trimmed_by_total_budget(self):
        """When the total budget is partially consumed, the next file is trimmed."""
        # 4 files of 100 lines + 1 file of 200 lines; budget=450
        # After 4 files (400 lines), 50 remain for last file
        files = [_make_file(f"f{i:02d}.py", 100) for i in range(4)]
        files.append(_make_file("z_big.py", 200))  # alphabetically last
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=200, max_total=450)

        # After alphabetical sort: f00..f03 (100 each = 400), z_big.py gets 50
        result_by_path = {f.path: f for f in result.modified_files}
        assert "z_big.py" in result_by_path
        assert len(result_by_path["z_big.py"].changed_lines) == 50

    def test_omitted_count_matches_dropped_files(self):
        """omitted_count must equal the number of files that were not included."""
        files = [_make_file(f"file{i:02d}.py", 100) for i in range(8)]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        included = len(result.modified_files)
        assert result.omitted_count == 8 - included


# ---------------------------------------------------------------------------
# T44-4: Alphabetical ordering
# ---------------------------------------------------------------------------

class TestAlphabeticalOrdering:
    """Files are sorted alphabetically before processing."""

    def test_files_in_output_are_alphabetically_ordered(self):
        """Output modified_files must be sorted by path."""
        files = [
            _make_file("z_last.py", 5),
            _make_file("a_first.py", 5),
            _make_file("m_middle.py", 5),
        ]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=500)

        paths = [f.path for f in result.modified_files]
        assert paths == sorted(paths)

    def test_alphabetically_first_files_preserved_on_total_overflow(self):
        """When total cap is hit, files that come first alphabetically must be kept."""
        files = [
            _make_file("z_big.py", 100),   # alphabetically last
            _make_file("a_big.py", 100),   # alphabetically first
            _make_file("m_big.py", 100),   # alphabetically middle
        ]
        diff = _make_diff(files)

        result = truncate_diff(diff, max_per_file=100, max_total=200)

        paths = [f.path for f in result.modified_files]
        assert "a_big.py" in paths
        assert "m_big.py" in paths
        assert "z_big.py" not in paths  # dropped: comes last alphabetically


# ---------------------------------------------------------------------------
# T44-5: Truncation flag
# ---------------------------------------------------------------------------

class TestTruncationFlag:
    """truncated is set correctly based on whether any omissions happened."""

    def test_truncated_false_when_no_omission(self):
        files = [_make_file("a.py", 5)]
        diff = _make_diff(files)
        result = truncate_diff(diff, max_per_file=100, max_total=500)
        assert result.truncated is False

    def test_truncated_true_when_file_dropped(self):
        files = [_make_file(f"f{i}.py", 100) for i in range(6)]
        diff = _make_diff(files)
        result = truncate_diff(diff, max_per_file=100, max_total=500)
        assert result.truncated is True

    def test_truncated_propagates_from_input(self):
        """If input diff was already truncated, output must also be truncated."""
        already_truncated = LocalDiff(
            modified_files=[_make_file("a.py", 5)],
            truncated=True,
            omitted_count=2,
        )
        result = truncate_diff(already_truncated, max_per_file=100, max_total=500)
        assert result.truncated is True

    def test_omitted_count_accumulates_from_input(self):
        """omitted_count from input diff is added to any new omissions."""
        already_truncated = LocalDiff(
            modified_files=[_make_file("a.py", 5)],
            truncated=True,
            omitted_count=3,
        )
        result = truncate_diff(already_truncated, max_per_file=100, max_total=500)
        # No new omissions, but existing omitted_count must be preserved
        assert result.omitted_count == 3


# ---------------------------------------------------------------------------
# T44-6: Empty diff passthrough
# ---------------------------------------------------------------------------

class TestEmptyDiffPassthrough:
    """An empty LocalDiff (no modified files) must pass through unchanged."""

    def test_empty_diff_returns_same_object(self):
        """Empty diff must be returned without modification."""
        diff = LocalDiff(modified_files=[])
        result = truncate_diff(diff)
        # Same object (no-op early return)
        assert result is diff

    def test_empty_diff_has_no_truncation_flag(self):
        diff = LocalDiff(modified_files=[])
        result = truncate_diff(diff)
        assert result.truncated is False

    def test_empty_diff_has_zero_omitted_count(self):
        diff = LocalDiff(modified_files=[])
        result = truncate_diff(diff)
        assert result.omitted_count == 0


# ---------------------------------------------------------------------------
# T44-7: Original object not mutated
# ---------------------------------------------------------------------------

class TestNoMutation:
    """The original LocalDiff must not be mutated by truncate_diff."""

    def test_original_files_unchanged_after_per_file_cap(self):
        original_lines = list(range(1, 201))  # 200 lines
        file_entry = LocalDiffFile(path="big.py", changed_lines=original_lines[:])
        diff = LocalDiff(modified_files=[file_entry])

        truncate_diff(diff, max_per_file=100, max_total=5000)

        # Original must still have 200 lines
        assert len(diff.modified_files[0].changed_lines) == 200

    def test_original_list_unchanged_after_total_cap(self):
        files = [_make_file(f"f{i}.py", 100) for i in range(6)]
        diff = LocalDiff(modified_files=files)
        original_count = len(diff.modified_files)

        truncate_diff(diff, max_per_file=100, max_total=500)

        assert len(diff.modified_files) == original_count


# ---------------------------------------------------------------------------
# T44-8: File status preserved
# ---------------------------------------------------------------------------

class TestFileStatusPreserved:
    """The status field on LocalDiffFile must be preserved through truncation."""

    def test_added_status_preserved(self):
        files = [LocalDiffFile(path="new.py", changed_lines=[1, 2, 3], status="added")]
        diff = _make_diff(files)
        result = truncate_diff(diff)
        assert result.modified_files[0].status == "added"

    def test_deleted_status_preserved(self):
        files = [LocalDiffFile(path="gone.py", changed_lines=[1], status="deleted")]
        diff = _make_diff(files)
        result = truncate_diff(diff)
        assert result.modified_files[0].status == "deleted"
