# Spec: Import `agentic_inquiry.watching` without touching the filesystem

- **Status:** Shipped (2026-09-26)
- **Owner:** sbasha
- **Plan:** [`plan.md`](plan.md)
- **Constrained by:** none

Mode: full (escalated from light)

## Objective

Importing `agentic_inquiry.watching`, or any of its submodules, must not
create files or directories. Building a `FileTracker` loads configuration and
creates the tracker database's parent directory, so at import it would create
`.agentic-inquiry/` in the working directory of every process that imports
the package, pytest collection included. The built-in `"default"` watcher, a
`FileWatcher` over a `FileTracker`, is built on the first lookup that needs
it: a lookup of `"default"` by name, a lookup with no name while no caller
default is set, or a listing of the registered watchers.

## Boundaries

### Always do

- Keep `register_watcher`, `unregister_watcher`, `get_watcher` and
  `available_watchers` signatures unchanged.
- Let a watcher the caller registered keep precedence over the built-in one.
- Let errors from building the built-in watcher reach the caller.

### Ask first

- Changing `WatcherRegistry.register` / `unregister` default-selection rules.
- Moving the directory creation out of `FileTracker.__init__`.

### Never do

- Build the default watcher, load configuration or touch the filesystem at
  import of `agentic_inquiry.watching`.
- Add a dependency or a new module.

## Testing Strategy

TDD for every behavior: each acceptance criterion is asserted in a fresh
interpreter spawned by `tests/unit/test_import_hygiene.py` with a scratch
working directory and `HOME`, because the defect is an import-time effect
that an in-process test cannot observe once another test has imported the
package. The existing in-process registry tests in `tests/watching/` and the
watcher tests in `tests/indexing/` are the regression gate for callers.

## Acceptance Criteria

- [x] A fresh interpreter with an empty working directory and an empty
      `HOME` that imports `agentic_inquiry.watching.file_tracker` or
      `agentic_inquiry.watching` exits 0 and leaves both directories empty.
- [x] With no caller default set, whichever of `get_watcher()`,
      `get_watcher("default")` or `available_watchers()` runs first registers
      the built-in `FileWatcher` as `"default"`; later calls return the same
      instance.
- [x] The built-in watcher becomes the registry default only when no default
      is set. A caller's watcher that is the default (first registered, or
      registered with `set_default=True`) keeps precedence, and `get_watcher()`
      returns it without building the built-in one.
- [x] A watcher the caller registers as `"default"` before the first lookup
      wins; the built-in one is not built.
- [x] `get_watcher("<other name>")`, `register_watcher` and
      `unregister_watcher` never build the built-in watcher.
- [x] With no default set, `get_watcher()` returns the watcher registered as
      `"default"`, building a new built-in one if none is registered (for
      example after `unregister_watcher("default")`).
- [x] An error while building the built-in watcher propagates to the caller
      of `get_watcher()` or `available_watchers()`.
- [x] Concurrent first lookups build and register the built-in watcher once.
