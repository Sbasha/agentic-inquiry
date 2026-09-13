import { spawn } from "node:child_process";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const MAX_BYTES = 1_048_576;
const HOOK_TIMEOUT_MS = 12_000;
const COMMAND_TIMEOUT_MS = 15 * 60_000;
type Result = {
  schema_version: number;
  library?: string;
  status?: string;
  context?: { text?: string };
  receipts?: unknown[];
  pending?: unknown[];
  errors?: unknown[];
};

async function library(ctx: ExtensionContext): Promise<string> {
  const result = await run(["integration", "library", "--client", "pi", "--root", realpathSync(ctx.cwd)], ctx);
  if (typeof result.library !== "string" || !result.library) {
    throw new Error("Agentic Inquiry did not return a selected project library");
  }
  return result.library;
}

function run(args: string[], ctx: ExtensionContext, input?: object, timeoutMs = HOOK_TIMEOUT_MS): Promise<Result> {
  return new Promise((resolve, reject) => {
    const encoded = input === undefined ? "" : JSON.stringify(input);
    if (Buffer.byteLength(encoded) > MAX_BYTES) {
      reject(new Error("Agentic Inquiry input exceeds 1 MiB"));
      return;
    }
    const child = spawn("ai", args, {
      cwd: ctx.cwd,
      stdio: ["pipe", "pipe", "pipe"],
      signal: ctx.signal,
    });
    let stdout = "", stderr = "", bytes = 0;
    const timer = setTimeout(() => child.kill("SIGKILL"), timeoutMs);
    child.stdout.on("data", (chunk: Buffer) => {
      bytes += chunk.length;
      if (bytes > MAX_BYTES) child.kill("SIGKILL");
      else stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr = (stderr + chunk.toString("utf8")).slice(0, 8192);
    });
    child.on("error", (error) => { clearTimeout(timer); reject(error); });
    child.on("close", (code) => {
      clearTimeout(timer);
      if ((code !== 0 && code !== 1) || bytes > MAX_BYTES) {
        reject(new Error(`Agentic Inquiry failed (${code ?? "interrupted"}): ${stderr}`));
        return;
      }
      try {
        const value = JSON.parse(stdout);
        if (value.schema_version !== 1) throw new Error("Unsupported Agentic Inquiry response");
        resolve(value);
      } catch (error) { reject(error); }
    });
    child.stdin.on("error", () => { /* The process error/close path owns reporting. */ });
    child.stdin.end(encoded);
  });
}

export default function agenticInquiry(pi: ExtensionAPI) {
  let conflicted = false;
  const ownPath = fileURLToPath(import.meta.url);

  function available(ctx: ExtensionContext): boolean {
    const commands = pi.getCommands().filter(command => command.name === "ai");
    if (commands.length > 1 || commands.some(command =>
      command.sourceInfo?.path && command.sourceInfo.path !== ownPath)) conflicted = true;
    if (conflicted) {
      ctx.ui.notify("Another extension owns /ai; disable one owner and reload before using Agentic Inquiry.", "error");
    }
    return !conflicted;
  }

  async function hook(event: string, ctx: ExtensionContext, selected: object = {}): Promise<Result> {
    if (!available(ctx)) throw new Error("Agentic Inquiry client name collision");
    const session = ctx.sessionManager.getSessionId();
    if (!session) throw new Error("Pi did not provide a native session ID; use explicit ai commands.");
    return run(["integration", "hook", "--client", "pi", "--event", event,
      "--input", "-"], ctx, {
      schema_version: 1, project_root: realpathSync(ctx.cwd), session_id: session,
      owner: "standalone", ...selected,
    });
  }

  function present(result: Result, ctx: ExtensionContext, recall: boolean) {
    if (recall && result.context?.text) {
      pi.sendMessage({customType: "agentic-inquiry-context", content: result.context.text,
        display: true}, {triggerTurn: false, deliverAs: "nextTurn"});
    }
    if (result.status === "partial" || result.status === "error" || result.status === "unsupported") {
      ctx.ui.notify(`Agentic Inquiry: ${result.status}; inspect ai capture status and integration inspect.`, "warning");
    }
  }

  async function observe(event: string, ctx: ExtensionContext, selected: object = {}, recall = false) {
    try { present(await hook(event, ctx, selected), ctx, recall); }
    catch (error) { ctx.ui.notify(`Agentic Inquiry: ${String(error)}`, "warning"); }
  }

  pi.registerCommand("ai", {
    description: "Agentic Inquiry: status, search QUERY, context QUERY, or a JSON array of CLI arguments",
    handler: async (args, ctx) => {
      if (!available(ctx)) return;
      try {
        let argv: string[];
        const text = args.trim();
        if (!text || text === "help") {
          ctx.ui.notify('/ai status | /ai search QUERY | /ai context QUERY | /ai ["memory","recall","--project","PROJECT_ID"]', "info");
          return;
        }
        if (text.startsWith("[")) {
          argv = JSON.parse(text);
          if (!Array.isArray(argv) || !argv.length || argv.some(value => typeof value !== "string")) {
            throw new Error("Use a JSON array of CLI argument strings");
          }
          if (!argv.includes("--db") && argv[0] !== "capabilities") argv.push("--db", await library(ctx));
        } else if (text.startsWith("search ") || text.startsWith("context ")) {
          const split = text.indexOf(" ");
          argv = [text.slice(0, split), "--db", await library(ctx), "--", text.slice(split + 1)];
        } else if (text === "status" || text === "doctor") {
          argv = [text, "--db", await library(ctx)];
        } else if (text === "capabilities") {
          argv = ["capabilities", "--json"];
        } else {
          throw new Error("Use /ai help for command syntax; full CLI arguments use a JSON array.");
        }
        const result = await run(argv, ctx, undefined, COMMAND_TIMEOUT_MS);
        pi.sendMessage({customType: "agentic-inquiry-result", content: JSON.stringify(result, null, 2),
          display: true}, {triggerTurn: false, deliverAs: "steer"});
      } catch (error) { ctx.ui.notify(String(error), "error"); }
    },
  });

  pi.registerTool({
    name: "ai_remember",
    label: "Remember selected observation",
    description: "Save one selected structured observation through explicitly enabled project capture. Does not accept transcripts or hidden reasoning.",
    parameters: Type.Object({
      content: Type.String({minLength: 1, maxLength: 65536}),
      kind: Type.Optional(Type.Union([Type.Literal("observation"), Type.Literal("decision"), Type.Literal("preference"), Type.Literal("correction")])),
      origin: Type.Optional(Type.Union([Type.Literal("user"), Type.Literal("agent"), Type.Literal("extracted")])),
      citations: Type.Optional(Type.Array(Type.Object({
        id: Type.String(), collection_id: Type.String(), source_id: Type.String(),
        source_version: Type.String(), source_hash: Type.String(),
        location: Type.Record(Type.String(), Type.Unknown()),
      }), {maxItems: 100})),
    }),
    async execute(toolCallId, params, _signal, _update, ctx) {
      if (!available(ctx)) throw new Error("Agentic Inquiry client name collision");
      if (!toolCallId) throw new Error("No stable native tool ID; use ai capture submit with an explicit event ID.");
      const result = await hook("PostToolUse", ctx, {
        event_id: toolCallId,
        observations: [{origin: "agent", ...params, provenance: {client: "pi", tool: "ai_remember"}}],
      });
      return {content: [{type: "text", text: JSON.stringify(result)}], details: result,
        isError: result.status !== "ok" || !result.receipts?.length};
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    if (!available(ctx)) return;
    await observe("SessionStart", ctx, {}, true);
  });
  pi.on("input", async (event, ctx) => {
    if (event.source === "extension") return {action: "continue"};
    const selected = Buffer.byteLength(event.text) <= 16_384 ? {query: event.text} : {};
    await observe("UserPromptSubmit", ctx, selected, true);
    return {action: "continue"};
  });
  pi.on("tool_result", async (event, ctx) => {
    if (!event.isError && (event.toolName === "write" || event.toolName === "edit")) {
      const path = event.input.path;
      if (typeof path === "string" && event.toolCallId) {
        await observe("PostToolUse", ctx, {event_id: event.toolCallId, artifacts: [path]});
      } else {
        ctx.ui.notify("No stable native tool ID or path; use ai index for explicit refresh.", "warning");
      }
    }
  });
  pi.on("session_before_compact", async (_event, ctx) => {
    await observe("PreCompact", ctx);
  });
  pi.on("session_compact", async (_event, ctx) => {
    await observe("SessionStart", ctx, {}, true);
  });
  pi.on("agent_end", async (_event, ctx) => {
    await observe("Stop", ctx);
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    await observe("SessionEnd", ctx);
  });
}
