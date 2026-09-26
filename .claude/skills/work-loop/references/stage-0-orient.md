## Step 0. ORIENT

First distinguish the invocation shape. An explicit current request is eligible to
enter direct-light only through the decision record and eligibility routing
in [`references/light-mode.md`](light-mode.md).
An argless queued start and a fresh-session `resume` remain workspace dispatch;
they never infer a direct-light authority from workspace comments, old chat,
branch names, or surrounding prose. A supplied spec path remains subject to
canonical preflight.

If `workspace.toml` is present, read it and Surface an orientation block:
   - **Initiative:** `name` from `["ini-NNN"]` (all `status = "active"` sections).
   - **Milestone:** `milestone` from `["ini-NNN"]`.
   - **Canonical preflight:** use `workspace-status` canonical reconciliation output for
     dispatch decisions and active-resume selection. `canonical.ready` is the only
     queue-ready set; it already means an existing Approved `spec.md` has an
     existing sibling `plan.md`, valid provenance, satisfied hard dependencies,
     and no fail-closed finding. `canonical.active` is the only resumable set.
     Any matching `canonical.blocked` or `canonical.findings` entry blocks
     autonomous start with its stable `code`, `path`, and `next_action`;
     `missing_plan`, `unapproved_spec`, and comment-only changes are refusals.
     Retained `legacy_memberships` are visible context only and never dispatch.
     - Supplied spec path: continue only when the path has a matching
       `canonical.ready` evaluation for a new start or matching `canonical.active`
       evaluation for a resume. Otherwise stop and surface the matching canonical
       finding, or `unregistered_work` if no canonical evaluation exists.
     - Argless queued start: select only the first `canonical.ready` item. Raw
       workspace `[work].queue` membership never authorizes PLAN.
     - Active resume: accept only a matching `canonical.active` item. Raw
       `[work].active` membership never authorizes PLAN when canonical findings,
       legacy membership, missing artifact, missing plan, unapproved spec, or any
       other canonical refusal is present.
   - **Active spec** (argless queued starts and fresh-session resumes only; skip
     when an explicit current request or spec path was given):
     collect all items from `canonical.active`, not raw `workspace.toml`. If exactly
     one, include "Resuming `docs/specs/<slug>/spec.md`" in this orientation block.
     - Zero → use `canonical.ready` for a queued start; if no item exists, surface "No canonical ready or active spec found - run `workspace-status` to see blocked findings." Stop.
     - More than one → list all canonical active items and ask the user to pick. Stop.
   - **Stale-queue check.** Use the `workspace-status` reconciliation/canonical
     findings for drift warnings. Do not re-read raw `[work].queue` or
     `[work].active` membership to authorize start or resume; raw membership is
     advisory only after canonical preflight has accepted the item. Never reconstruct
     requirements from comments, summaries, list order, or surrounding prose.

Then apply the **Shaping-item guard** when a workspace-resolved or supplied slug
exists. Derive slug (strip `docs/specs/` prefix + trailing `/`). Check all active
initiatives' `[shaping_queue].active`, `.backlog`, and `[backlog].open` typed
entries for a slug match. On match, stop: "This is a `[shape]` item (`type =
<subtype>`); use `<skill>` - `work-loop` is for build items only."
(shape→`frame-intent`; research→`desk-research-project-start`; strategy→`frame-situation`/`frame-intent`; design→`experience-status`.) Signal type → "Monitoring signal - `work-loop` is for build items only."

After orientation, route by invocation shape. **Order matters: an explicit
current request is decided before the workspace-dispatch branches, which exist
only for an argless start or a fresh-session `resume`.** A canonical active item
must never capture an explicit request for different work.

- If a spec path was supplied and matched `canonical.ready` or `canonical.active`, use
  that canonical evaluation and proceed to PLAN.
- Otherwise, for an **explicit current request**: with no matching
  `canonical.ready`, `canonical.active`, or `canonical.blocked` item, proceed to
  the direct-light decision record. A matching or conflicting canonical item
  surfaces the conflict rather than starting untracked parallel implementation,
  and an explicit request that names existing durable work uses that spec.
- Otherwise, for an **argless start or fresh-session `resume`** only: exactly one
  canonical active item → read its `spec.md` and `plan.md`, then proceed to PLAN.
- Otherwise, for an **argless start** only: exactly one selected canonical ready
  item → read its `spec.md` and `plan.md`, then proceed to PLAN.
- Otherwise, stop. A direct-light run is not resumable through
  `workspace-status`; a bare `resume` in a fresh context requires a matching
  `canonical.active` item.

If `workspace.toml` is absent, an explicit current request may still proceed to
the direct-light decision record. An argless queued start, a fresh-session
`resume`, or a supplied spec path has no canonical preflight result and must
Surface rather than infer authority.

