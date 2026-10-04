# RFC-0004 spikes, 3 October 2026

Companion to [`../0004-unified-project-runtime.md`](../0004-unified-project-runtime.md). The RFC body carries the one-sentence conclusions; this file holds the observations they rest on.

## Working directory of a stdio MCP server, per harness

Probe: [`mcp-cwd-probe.py`](mcp-cwd-probe.py), a stdlib stdio MCP server that appends `os.getcwd()`, `argv`, `PWD`, pid and the parent process name to a log on start and serves one `cwd` tool so the harness treats it as healthy. It was registered under the Bet 1 initiative folder (not a git work tree) and each harness was run headless from that folder. The probe registrations were removed after the run.

| Harness | Registration | cwd observed | Parent process | Notes |
| --- | --- | --- | --- | --- |
| Claude Code | project `.mcp.json`; plugin `.mcp.json` through `--plugin-dir` | the project folder | `claude` | both registrations behave the same |
| Codex 0.154.0 | `-c mcp_servers.*` override; project `.codex/config.toml` | the project folder | `codex` | the project file loads only when the folder's `trust_level = "trusted"` is written in `~/.codex/config.toml`; a `-c projects.*` override does not load it |
| Cursor 3.23.12 | user `~/.cursor/mcp.json` | `$HOME`, `PWD=/` | `Cursor Helper: mcp-process` | a project `.cursor/mcp.json` entry was registered as `project-0-agentic-enterprise-cwdprobe` and stayed `disconnected` until a person enables it in Cursor's MCP settings, so its cwd was not observed and is taken to be the same helper's; Cursor's documentation resolves `${workspaceFolder}` to the folder containing `.cursor/mcp.json` |
| Pi 0.84.1 | none in core (its README: "No MCP") | bash tool cwd is the project folder | | `pi-mcp-adapter` 5.0.0 (read, not run) resolves `.mcp.json` against `process.cwd()` and spawns stdio servers with the config `cwd` or `process.cwd()`; the AFP Pi adapter projects skills and prompt templates and no MCP registration |

Outstanding: the Cursor project-scope run, which needs the approver to enable the project server once in Cursor's MCP settings. Re-run the probe with the label `cursor-project` and record the cwd here.

## `unstructured` base package and extras

Fresh Python 3.12 venv.

| Install | Size | Result |
| --- | --- | --- |
| `unstructured==0.18.31` (the lock) plus `pdftext==0.6.3` | 251 MB | `partition()` raised `ImportError` for `.docx`, `.md`, `.pdf` and `.pptx`, each naming its extra |
| `unstructured==0.27.10` plus `pdftext==0.6.3` | | same behaviour |
| `unstructured[docx,md,pptx]==0.18.31` plus `pdftext==0.6.3` | 268 MB | DOCX fixture 277 elements; Markdown fixtures 4 and 480 elements; PPTX fixture 79 elements; `pdftext.extraction.dictionary_output` read the 36-page PDF fixture in 0.3 s warm |

Dependency pull per extra, from the package metadata: `docx` adds `python-docx`; `md` adds `markdown`; `pptx` adds `python-pptx`; `xlsx` adds `openpyxl`, `pandas`, `xlrd`, `networkx` and `msoffcrypto-tool` (pandas is already a runtime dependency); `pdf` adds `unstructured-inference`, `pdf2image`, `pdfminer.six`, `pikepdf`, `onnxruntime` and `google-cloud-vision`. `document.py` already routes PDF through `pdftext`, so nothing in the runtime needs the `pdf` extra. The `rtf`, `odt`, `epub`, `rst` and `org` partitioners call pandoc through `pypandoc`, so those formats leave `SUPPORTED_EXTENSIONS`.
