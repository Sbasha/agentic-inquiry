# Spec: User config files overlay the packaged defaults

Mode: light (borderline - changes the effective meaning of an existing user
config file, which touches the public-interface trigger, but the documented
contract in README and the `Config` docstrings already promised layering and
the change is one loader path. Escalate if anything structural surfaces.)

- **Status:** Shipped (2026-09-26)

## Objective

`Config.load()` reads one user config file (explicit path, `INQUIRY_CONFIG`,
`./agentic-inquiry.yaml`, or `~/.agentic-inquiry/config.yaml`) and merges it
over the packaged `default.yaml` before schema validation. A partial file such
as the README example loads; keys it omits take the packaged default, not the
dataclass default.

**Migration.** A complete user file that omitted a key used to get the
dataclass default; it now gets the `default.yaml` value. Where the two differ:

| Key | Was (dataclass) | Now (`default.yaml`) |
| --- | --- | --- |
| `search.hybrid_search.reranker_type` | `linear_combination` | `rrf` |
| `storage.default_project_id` | unset, so `ai index` asked for a project | `default` |
| `connectors.filesystem.watch_enabled` | `false` | `true` |
| `storage.backend` (deprecated) | `""` | `lancedb` |

`connectors.filesystem.watch_enabled`, `binary_extensions` and
`ignore_patterns` have no runtime reader today (connectors use
`DEFAULT_BINARY_EXTENSIONS` / `DEFAULT_IGNORE_PATTERNS` from
`connectors/base.py`), so those rows change only the loaded `Config`.
`default.yaml`'s two lists were subsets of the dataclass lists and now match
them, keeping the two sources consistent for when a reader is wired.

## Acceptance Criteria

- [x] The YAML block under README "### Configuration", written to
      `./agentic-inquiry.yaml` in an empty cwd with an empty `HOME` and no
      `INQUIRY_CONFIG`, loads through `Config.load()`; its keys win and an
      omitted key equals the `default.yaml` value.
- [x] A partial `~/.agentic-inquiry/config.yaml` and a partial file passed as
      `config_path` load the same way.
- [x] `Config.load_with_overlay(env_file)` stacks: env overlay > selected user
      file > `default.yaml`, with a partial user file.
- [x] A user file whose top level is not a mapping raises `ConfigurationError`.
- [x] `search.hybrid_search.reranker_params` in a user file arrive at the
      reranker exactly as written: `default.yaml` defines no params, and the
      default RRF reranker still uses `k=60`.
- [x] `default.yaml` `connectors.filesystem.binary_extensions` and
      `ignore_patterns` contain every entry of the dataclass defaults.
- [x] README states the precedence (env vars > environment overlay > config
      file > packaged defaults), the merge rule (mappings merge key by key,
      lists and scalars replace, keys cannot be removed), which file is
      selected, and its example contains only keys that change a default.
