# Sync — the OT / synchronous-integration plan

**Status:** direction doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**The plan for serving OT (operational-technology / industrial) workloads on the
async kernel.** Everything here is DIRECTION except the decision record in §1.
The async execution model it builds on is [`async.md`](async.md).

---

## 1. Decision record — one async kernel, no IT/OT fork

Decided 2026-07-08: the kernel stays **async-only**; there is no separate sync or
OT kernel variant — *for now deliberately unhurried*: the OT track takes the time
to consider the architecture thoroughly (§2) instead of rushing a sync fork.

Why no fork:

- **Sync is not what OT needs.** OT needs *bounded latency, determinism and
  guaranteed behaviour*. A blocking API gives *less* latency control than async
  with deadlines — you can't time-box or cancel a call you're blocked inside.
- **LLM turns are inherently variable-latency** (seconds to minutes). No kernel
  design makes a model call hard-real-time. The agent belongs at the
  *supervisory* level — planning, diagnosing, reconfiguring — with deterministic
  controllers below it executing in real time.
- **A fork is a rewrite.** Storage (`aiosqlite`, `to_thread`), providers,
  middleware and tools are async-native ([`async.md`](async.md) §1–4); a sync
  variant means parallel code paths everywhere, permanently — maximal technical
  debt for a property (real-time) it still couldn't deliver.

What sync call-sites get instead: a **facade** (§4). What OT workloads get
instead: **determinism facilities on the async core** (§3).

## 2. Open architecture considerations — take the time

The questions to settle before committing an OT profile, worked here first:

- **Low-latency local inference with SLMs.** The biggest OT lever: a local
  small-language-model adapter fits the existing `Provider` protocol
  ([`drivers.md`](drivers.md) §2) *unchanged* — one `async complete()`, on-premise, no
  WAN round-trip, no cloud dependency in the loop. To settle:
  - which runtime class (llama.cpp / Ollama / vLLM-grade server) and the
    latency envelope per turn it can guarantee;
  - the cost model — local ≈ 0 USD per token but *bounded capacity*, so the
    money budget ([`budgets.md`](budgets.md)) matters less and the capacity
    gate ([`async.md`](async.md) §6) matters more;
  - routing when local SLM and cloud LLM are both active — routine turns local,
    escalation to a big model as a *policy* decision
    ([`routing.md`](routing.md) §4–5 is exactly this seam);
  - determinism knobs — pinned model version, temperature 0, replayable
    trajectories — as an "OT profile" of config, not new code.
- **Failure semantics on the shop floor** — what a `paused` session means when
  an operator is a shift worker, not a cloud dashboard; escalation/handoff
  vocabulary already exists ([`session.md`](session.md)).
- **Where the agent sits** — supervisory level only; interfaces to PLC/SCADA
  layers are app tools behind the safety gate ([`tools.md`](tools.md) §5),
  never kernel concerns.

## 3. OT needs → facilities on the async core

| OT need | Facility | Status |
|---|---|---|
| Bounded latency per turn | turn deadline: `run_turn(..., deadline_seconds=…)` → clean abort → `paused` | #71 |
| No runaway work | cooperative cancellation checked between tool iterations | #72 |
| Crash detection / takeover | lease heartbeat + reaper ([`session.md`](session.md) §6) | landed |
| Admission control | `configure_llm_capacity` gate ([`async.md`](async.md) §6) | landed |
| Audit / replay | TrajectoryCapture — every turn mirrored to the store ([`engine.md`](engine.md) §3) | landed |
| Spend certainty | money budget, warn→compress→abort ([`budgets.md`](budgets.md) §4) | landed |
| Low-latency inference | local SLM provider adapter + routing policy (§2) | consider |

## 4. The sync facade (`agentix.sync`) — #70, coming soon

**Status: planned, not scheduled for implementation yet** — documented here so
integrators know it is coming. For integrators whose codebase is synchronous
(typical in OT toolchains):

- One module owning a **single dedicated background event-loop thread** — not
  per-call `asyncio.run` — so per-loop limiter state and `ContextVar` binding
  ([`async.md`](async.md) §4) stay consistent across calls.
- Blocking wrappers (`run_turn`, `create_session`, `resume_or_create`) submit
  via `asyncio.run_coroutine_threadsafe` and block on the future, optionally
  with the same deadline semantics as #71.
- **Single-flight** semantics documented: the facade serves one session at a
  time; fan-out is the async API's job.
- Side benefit outside OT: retires the reference app's ~10 hand-rolled
  `asyncio.run` CLI bridges over time.

## 5. Non-goals

- **Hard real-time** — the agent is never in a control loop with millisecond
  deadlines; deterministic controllers own that layer.
- **A sync-native kernel** — no parallel sync implementations of storage,
  providers or middleware, ever.
- **A second kernel repo** — OT is a *profile* (config + facilities + a facade)
  of the one kernel, not a fork.

## 6. Tracked issues

- #70 — `agentix.sync` blocking facade (dedicated loop thread)
- #71 — turn deadline (`asyncio.timeout`, abort → `paused`)
- #72 — cooperative-cancellation seam in the dispatcher
- #67 — SessionRuntime: lift the session-run loop into the kernel
- #39 — per-task SQLite connection (I2) — prerequisite for in-process fan-out
