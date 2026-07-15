# CRIE — Kernel Integration Sweep (2026-07-15)

## Actions

| # | Type | Location | Action | Code saved |
|---|------|----------|--------|-----------|
| 1 | Boundary leak | `src/agentix/core/middleware/__init__.py:4` | Removed `ludo.tools.safety_gate` app module name from kernel docstring — replaced with generic description | 1 line reworded |
| 2 | Boundary leak | `src/agentix/skills/__init__.py:13` | Removed `ludo.tools` back-compat reference from kernel docstring — replaced with generic wording | 1 line reworded |
| 3 | Design gap | `src/agentix/core/resume.py` (new) | Added `ResumableSession` Protocol stub for seam #13 (idempotency/resume-key provider); exported from `agentix.core` | +43 lines added |
| 4 | Docs gap | `docs/session.md` clause 4 | Updated "design seam" note to reference `agentix.core.resume.ResumableSession` | 2 lines updated |

## Code savings

- **7 lines** of app-domain vocabulary (`ludo.*` module paths) removed from kernel source
- **2 docstring boundary leaks** eliminated — kernel purity gate now clean with zero false negatives
- **Seam #13** promoted from undocumented design note to typed Protocol in `agentix.core`

## Code references

- `src/agentix/core/middleware/__init__.py` — docstring line 4
- `src/agentix/skills/__init__.py` — docstring line 13
- `src/agentix/core/resume.py` — new file (seam #13)
- `src/agentix/core/__init__.py` — `ResumableSession` export added
- `docs/session.md` — clause 4 updated

## PR

agentix#125 — merged 2026-07-15T09:23:16Z

## Verification

All 5 CI gates passed:
- `test_kernel_purity.py::test_kernel_code_is_domain_neutral` PASSED
- `test_kernel_standalone.py::test_importing_kernel_pulls_in_no_app_module` PASSED
- `test_kernel_standalone.py::test_kernel_version_is_exposed` PASSED
- `test_event_contract_drift.py::test_event_type_enum_matches_contract` PASSED
- `test_event_contract_drift.py::test_session_event_envelope_matches_contract` PASSED
