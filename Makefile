.PHONY: bench bench-pin bench-clean help

PYTHON ?= uv run --env-file .env python

help:
	@echo "Targets:"
	@echo "  bench         Run the golden bench and diff against tests/golden/baseline.json (exit 1 on regression)"
	@echo "  bench-pin     Regenerate tests/golden/baseline.json from the current corpus"
	@echo "  bench-clean   Remove the cached bench artifacts under $${TMPDIR:-/tmp}/agv-golden-bench"

bench:
	@$(PYTHON) tests/golden/bench.py

bench-pin:
	@rm -rf "$${TMPDIR:-/tmp}/agv-golden-bench"
	@$(PYTHON) tests/golden/bench.py --pin --reindex

bench-clean:
	@rm -rf "$${TMPDIR:-/tmp}/agv-golden-bench"
	@echo "Removed $${TMPDIR:-/tmp}/agv-golden-bench"
