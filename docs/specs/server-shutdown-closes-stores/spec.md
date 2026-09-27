# Spec: The server closes its stores when it stops

Mode: light (no risk trigger fired)

- **Status:** Shipped
- **Owner:** sbasha

## Objective

`create_app` initializes `MCPServer`, which opens the event and session
stores. Each open aiosqlite connection runs a non-daemon thread, and
interpreter shutdown joins those threads. The app's lifespan was FastMCP's
alone, so nothing closed the stores: `python -m agentic_inquiry.server.run`
logged "Finished server process" after Ctrl-C and kept running until
`stop_server` fell back to SIGKILL, and the test suite's thread watchdog
exited pytest with status 1 although every test passed.

The app's lifespan now ends by calling `MCPServer.shutdown()`, and tests
that build the app run its lifespan. The runner checks the bind address
before `create_app` opens any store, removes its PID file however `serve()`
ends, and exits quietly on Ctrl-C.

## Acceptance Criteria

- [x] After SIGTERM or SIGINT, `python -m agentic_inquiry.server.run` exits
      within 5 s (the `stop_server` SIGKILL deadline), logs "MCP server
      shutdown complete" and leaves no PID file.
- [x] A refused bind address (non-loopback host without an API key) makes
      the runner exit with an error before it opens any store.
- [x] When the app's lifespan ends, no aiosqlite thread the app opened is
      still alive.
- [x] The full suite leaves no non-daemon thread at exit, so pytest's exit
      status reflects the test results.

## Tasks

1. Regression test for the lifespan closing the stores (TDD).
2. Wrap FastMCP's lifespan in `create_app` so it ends with
   `MCPServer.shutdown()`.
3. Run the app lifespan in the eight tests that build the app.
4. In the runner, check the bind address before `create_app`, remove the
   PID file in a `finally`, and catch `KeyboardInterrupt` in `main()`
   (manual QA through the documented `python -m agentic_inquiry.server.run`).
