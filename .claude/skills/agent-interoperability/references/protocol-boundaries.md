# Protocol boundaries

Use the specification matching the project's chosen release. The links below locate official sources; they are not a requirement to upgrade.

## MCP

Inspect the server initialization and declared capabilities before using tools, resources or prompts. Build against the installed SDK's schema and transport implementation. Validate arguments before dispatch and distinguish protocol errors from a tool-reported failure. Descriptive annotations should not be the enforcement mechanism for a tool's access or effects.

For HTTP authorization, validate that incoming tokens are intended for this server. Credentials for an upstream API are separately acquired for that destination; do not forward the incoming client token to it. Use the chosen release's discovery and resource binding rules. Local stdio credential handling and remote HTTP authorization are different paths. See the official [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) and select its matching version in the documentation.

For stdio, preserve the protocol stream: diagnostic logging belongs off the response channel. For HTTP, verify origin/session/transport behavior in the chosen SDK and deployment. Apply tool-specific authorization even after transport authentication. Inspect arguments that select files or URLs before accessing those resources.

## A2A

Read the Agent Card's advertised interfaces, versions and capabilities, then select a compatible binding. Verify server identity and authenticate the caller. A card's existence does not authorize task or artifact access.

Keep task identity distinct from conversational context. Track the returned task and its observed state; a stream disconnect does not terminate it. Implement cancellation and reconnection using the chosen binding. A completed task still needs the expected artifact and business outcome.

Authorize access when retrieving tasks or artifacts. Treat push notification URLs as destinations requiring validation, and authenticate received notifications. Follow the chosen release's delivery and retry semantics. See the official [A2A specification](https://a2a-protocol.org/latest/specification/) for the selected protocol version and SDK binding.

## Project-level acceptance

Name the actual client/server versions and target environment. Exercise the changed operation through the public client with a real configured peer when authorized, preserving raw status/error evidence and redacting credentials. Report unavailable credentials, absent peer capability or unsupported versions precisely. Do not replace a failed interoperability check with a fabricated peer or label source inspection as a successful integration.
