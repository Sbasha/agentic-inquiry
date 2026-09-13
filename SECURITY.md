# Security policy

## Reporting a vulnerability

Report suspected vulnerabilities through the repository's private GitHub security advisory form. Include the affected version, a minimal reproduction, the security impact and any known mitigation. Do not include sensitive source content, credentials or private library data in a public issue.

Security fixes target the latest published release. This preview does not provide a long-term support branch or a guaranteed response time.

## Security boundaries

Agentic Inquiry runs locally with the permissions of the invoking user. Its library can contain source excerpts, paths, memory and authored knowledge. Protect the library directory and its backups with the same access controls as the indexed source material.

The application treats source files and archives as untrusted input. It applies path, symlink, size and extraction limits and reports incomplete coverage. Collection filename exclusions reduce accidental credential indexing but are not a content-based secret scanner. Review a source root before indexing it.

The CLI does not call a generative-model API or upload source files. First indexing or explicit model preparation can download public embedding or reranking models. OCR requires a separately installed local Tesseract executable.

The MCP server is scoped to a library, source root and project at startup. Write actions require `--allow-write`, and shared memory is unavailable through that server. Grant access only to clients that should be able to read the configured evidence and any admitted authored state.

Codex and Pi installation previews by default and records ownership when applied. Installation does not enable recall, capture or refresh. Review projected files and enable policy only for the intended owner, project and library.

Forgetting memory, removing evidence and cleaning caches do not erase backups, filesystem history or storage remnants. Use platform-appropriate secure disposal when erasure is required.
