# A2A — agent-to-agent

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for A2A in `docs/`.** Sections 1–3 document the landed
kernel surface (code: `src/agentix/a2a/`); sections 4–5 are **DIRECTION** — the
deferred substrate, tracked as epic euroblaze/ludo #492 (W1–W4). The cluster-wide
*application* of A2A (trust-zone agent map, guardrails, the four locked principles)
is canonical in `ludo-agent/docs/proposals/agentic-cluster-a2a.md` — referenced,
never restated (CRIE rule, same as [`isolation.md`](isolation.md) §2).

---

## 1. What A2A is in the kernel

A2A is how one agent hands work to another: the **delegate** verb
([`tools.md`](tools.md) §9) — a call whose execution leaves the process. The kernel
models the crossing with pieces that already exist:

- **The unit that crosses is a Session.** A delegated task runs as a **child
  Session** with its own context window — in-process as a child session-task, over
  A2A as a remote session in another NATS Account
  ([`isolation.md`](isolation.md) §5).
- **The link is persisted** — `Session.parent_session_id`
  ([`session.md`](session.md) §1) carries the delegation hierarchy.
- **Only distilled context crosses** — a brief in, a summary out, never raw shared
  state (P-ISO-2, [`isolation.md`](isolation.md) §1). The crossing law is the same
  whether the peer is a thread away or an Account away.

## 2. `AgentCard` — the A2A v1.0 discovery data model

`a2a/card.py` — **pure data + validation, no transport, no credentials, no
trust-zone wiring.** Shaped to [A2A v1.0](https://a2a-protocol.org) so driver and
app authors can publish spec-compliant cards today; the wire substrate lands in
W1–W3 (§4).

Three types:

- **`AgentSkill`** — one thing an agent can do. `id` is the stable machine handle;
  `name` is the human label. A2A fields: `tags`, `examples`, `input_modes` /
  `output_modes` (camelCase in JSON: `inputModes` / `outputModes`). Kernel
  extension: `subject` — the future NATS routing address, `None` until W2.
- **`AgentCapabilities`** — protocol feature flags: `streaming`,
  `push_notifications`, `state_transition_history` (camelCase aliases in JSON).
- **`AgentCard`** — an agent's declarative self-description. A2A required fields:
  `name`, `description`, `url`, `version`, `protocol_version` (`"1.0"`). A2A
  optional: `provider`, `capabilities` (`AgentCapabilities`),
  `default_input_modes` / `default_output_modes`, `skills: list[AgentSkill]`,
  `security_schemes`, `security`. Kernel extensions: `tools: list[str]`,
  `activatable` (key-gated agent, §5). `to_a2a_json()` emits camelCase JSON
  via `model_dump(by_alias=True, exclude_none=True)`.

Helpers: `skill_ids()`, `has_skill(id)`, `skill(id)`.

Tests: `tests/unit/a2a/test_card.py`.

## 3. Where the other landed pieces live

| Concern | Canonical home |
|---|---|
| the *delegate* verb among the four calling verbs (#502) | [`tools.md`](tools.md) §9 |
| child-Session runtime relationship + crossing rules | [`isolation.md`](isolation.md) §5 |
| persisted `parent_session_id` | [`session.md`](session.md) §1 |
| skills reached *via* A2A (client agents carry no server skills) | [`skills.md`](skills.md) §7 |
| `SkillBundle.to_agent_skill()` — project a bundle into `AgentSkill` | [`skills.md`](skills.md) §3 |
| A2A wire (JSON-RPC 2.0, Task lifecycle, SSE/push, JWS) | epic #492 (W1–W3) |

---

*Everything below is DIRECTION — converged design, not the code today. Epic
euroblaze/ludo #492 (workstreams W1–W4, #493–496).*

## 4. The deferred substrate (W1–W3)

What the card model deliberately excludes, landing in reviewed slices:

- **Capability subjects as the registry** — the NATS subject-space
  (`int.<domain>.<account>.<name>`) doubles as service discovery; `Capability.subject`
  gets filled when routing wires up (W2).
- **The INFO reply** — the `AgentCard` served as a NATS micro discovery response,
  so a peer can enumerate capabilities before delegating.
- **Trust-zone NATS Accounts** — one NATS deployment partitioned into
  deny-by-default Accounts (edge / control / internal) with per-tenant subject
  permissions; the Account + credential is the boundary, not a second broker.
  Detail: the cluster proposal.
- **Credential minting + ActionGate** — per-agent credentials and the guardrail
  middleware on act-tools (rate-limit · quiet-hours · idempotency · audit) gate
  every mutating delegated action (W3).
- **Delegate dispatch** — the verb wired end-to-end: resolve a capability from a
  peer's card, publish the job, await the distilled summary — a tool call whose
  round-trip is a broker job, not a function call.

## 5. Activatable agents

The kernel principle behind `AgentCard.activatable`: an agent's LLM-nature is a
**key-gated layer**. With a valid key the component reasons; with no key it runs as
deterministic software — the whole-cluster generalisation of "deterministic body,
Cortex on escalation". Consequence (canonical in the cluster proposal): **whoever
holds the key owns the guardrails** — server-side keyed agents do the guardrailed,
mutating, outward work; client agents (BYO-key, source-available) are read/local/
advisory and reach real capability only by delegating to a server-side agent.
