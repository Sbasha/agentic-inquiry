.PHONY: bench bench-pin bench-clean session-bench eval-dev eval-test help

PYTHON ?= uv run --env-file .env python

help:
	@echo "Targets:"
	@echo "  bench         Run the golden bench and diff against tests/golden/baseline.json (exit 1 on regression)"
	@echo "  bench-pin     Regenerate tests/golden/baseline.json from the current corpus"
	@echo "  bench-clean   Remove the cached bench artifacts under $${TMPDIR:-/tmp}/ai-golden-bench"
	@echo "  session-bench Replay tests/golden/sessions.json and report evidence recall@10"
	@echo "  eval-dev      Level A retrieval evaluation, dev split, every suite (evals/README.md)"
	@echo "  eval-test     Level A test split, every suite; clean tree only, appends to the test ledger"

bench:
	@$(PYTHON) tests/golden/bench.py

bench-pin:
	@rm -rf "$${TMPDIR:-/tmp}/ai-golden-bench"
	@$(PYTHON) tests/golden/bench.py --pin --reindex

bench-clean:
	@rm -rf "$${TMPDIR:-/tmp}/ai-golden-bench"
	@echo "Removed $${TMPDIR:-/tmp}/ai-golden-bench"

session-bench:
	@$(PYTHON) tests/golden/session_bench.py

EVAL_SUITES ?= scifact swebench locomo longmemeval
EVAL_PYTHON ?= uv run --group eval python

eval-dev:
	@for s in $(EVAL_SUITES); do $(EVAL_PYTHON) -m evals run --suite $$s --split dev || exit 1; done

eval-test:
	@for s in $(EVAL_SUITES) erpnext; do $(EVAL_PYTHON) -m evals run --suite $$s --split test || exit 1; done
