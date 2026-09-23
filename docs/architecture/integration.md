# Integration

`agentic_inquiry/integration/` is the lifecycle contract the AFP pack calls.

The package is stdlib and SQLite on the hook path. `contract.py` parses the request and bounds the response. `state.py` owns the ledger under `INQUIRY_HOME`. `capabilities.py`, `hooks.py`, `verbs.py`, and `reconcile.py` each expose one public function per verb. `agentic_inquiry/cli/` parses arguments and prints. It does not decide.

A hook queues capture and refresh. It does not open the embedding model and it does not create the ledger. `ai integration enable` creates the ledger. `ai integration reconcile` and the MCP maintenance tick commit queued rows. The tick calls `reconcile` with `lock_timeout=0` and logs `environment_busy` when the project lock is held.

The marker `<project>/.agentic-inquiry/integration.json` tells the adapter which clients are enabled. The SQLite binding is the authority. The ledger module uses synchronous `sqlite3`. A caller that already has an event loop reaches it through `asyncio.to_thread`.

See [the lifecycle CLI reference](../guides/reference/lifecycle-cli.md) for the verbs, codes, and deadlines.
