---
name: typescript-development
description: Apply repository-compatible TypeScript and JavaScript practices when implementing, reviewing, or testing frontend, backend, library, or tooling code. Use when strictness, runtime targets, package-manager conventions, module format, schema validation, tests, generated types, and UI styling must remain aligned with the project's existing configuration and supported environments.
---

# TypeScript

- Read package metadata, lockfiles, `tsconfig`, lint configuration, and runtime targets before selecting syntax or tools. Preserve JavaScript when it is an intentional project boundary.
- Prefer strict typing for maintained TypeScript, `unknown` at untrusted boundaries, discriminated unions for state, and readonly data when immutability is part of the contract.
- Const by default, async/await over promise chains, optional chaining and nullish coalescing
- Follow the existing design-system and styling conventions; avoid introducing a parallel theme mechanism.
- Run the repository's typecheck, lint, tests, build, and user-facing validation.
