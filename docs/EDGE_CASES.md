# Edge cases

Every structured error this system returns (`{ok: false, code, message_en, message_ar,
recovery_hint, data}` -- see D5 in [ARCHITECTURE.md](ARCHITECTURE.md)), what triggers it, and where.
Codes are stable and machine-branchable; `recovery_hint` is written for the agent to act on.

## Leave management (`app/api/tools/leave.py`)

| Code | Triggered when | Tool |
|---|---|---|
| `EMPLOYEE_NOT_FOUND` | `employee_id` doesn't resolve via `HRISPort.get_employee` | `get_leave_balance`, `preview_leave_request` |
| `COUNTRY_NOT_SUPPORTED` | The employee's country has no entry in `COUNTRY_POLICIES` (no verified entitlement law encoded) | `get_leave_balance`, `preview_leave_request` |
| `LEAVE_TYPE_NOT_SUPPORTED` | `leave_type` isn't `"annual"` -- sick leave has no balance/preview logic, only a pay-tier table | `get_leave_balance`, `preview_leave_request` |
| `INVALID_DATE_RANGE` | `end_date < start_date` | `preview_leave_request` |
| `APPROVER_NOT_FOUND` | The direct manager and the one-level skip escalation are both unavailable (inactive, on leave, or the requester themself) | `preview_leave_request` |
| `PREVIEW_EXPIRED` | The signed `issued_at` in the preview token plus the 15-minute TTL has passed | `submit_leave_request` |
| `PREVIEW_ALREADY_USED` | The token's nonce was already consumed (single-use enforcement) | `submit_leave_request` |
| `PREVIEW_INVALID` | Signature verification failed (tampered, malformed, or wrong-secret token). The specific reason is logged server-side only, never in the response -- an attacker probing signatures shouldn't learn which field broke | `submit_leave_request` |
| `BALANCE_CHANGED` | Re-derived working days, entitlement, balance, or approver at submit time don't match what was signed at preview time | `submit_leave_request` |
| `NOT_AUTHORIZED` | The caller isn't the server-side-resolved approver for this request -- re-derived fresh via `resolve_approver`, never trusted from what the request claims | `decide_leave_request` |
| `UPSTREAM_UNAVAILABLE` | The HRIS write raised inside the idempotency-guarded closure. Logged via `logger.exception` before returning (added after a real incident -- see ROADMAP.md) | `submit_leave_request`, `decide_leave_request` |

## Check-ins (`app/api/tools/checkins.py`)

| Code | Triggered when | Tool |
|---|---|---|
| `EMPLOYEE_NOT_FOUND` | `employee_id` (or `manager_id`) doesn't resolve | `submit_daily_checkin`, `list_missing_checkins`, `get_team_summary` |
| `INVALID_RATING` | `rating` outside 1-5 inclusive | `submit_daily_checkin` |
| `UPSTREAM_UNAVAILABLE` | The dashboard write raised inside the idempotency-guarded closure | `submit_daily_checkin` |

A manager with zero direct reports is **not** an error for `list_missing_checkins`/
`get_team_summary` -- both return `ok: true` with an empty/zero-count result, since having no
reports is a normal state, not a failure.

## Knowledge base (`app/api/tools/knowledge.py`)

| Code | Triggered when | Tool |
|---|---|---|
| `EMPLOYEE_NOT_FOUND` | `employee_id` doesn't resolve -- required, not optional, precisely so a country-specific answer can never be given without a resolved country behind it | `answer_hr_question` |
| `NO_SOP_FOUND` | The top BM25 match scores below the calibrated threshold (2.0). Logs the question to `sop_gaps` so HR can see what the corpus is missing | `answer_hr_question` |
| `COUNTRY_NOT_SUPPORTED` | The matched topic is country-specific (currently only `annual_leave_policy`) and the employee's country has no encoded policy. Also logs a gap | `answer_hr_question` |

## Gratuity (`app/api/tools/gratuity.py`)

| Code | Triggered when | Tool |
|---|---|---|
| `EMPLOYEE_NOT_FOUND` | `employee_id` doesn't resolve | `calculate_gratuity` |
| `GRATUITY_NOT_MODELED` | Country/reason combination has no confident, citable formula: any reason for Jordan; any reason but `retirement` for Egypt; any country outside {KSA, UAE, Egypt} | `calculate_gratuity` |

## Idempotency (`app/core/idempotency.py`, shared by every mutating tool)

| Code | Triggered when |
|---|---|
| `REQUEST_IN_PROGRESS` | The same `idempotency_key` is already being processed by a concurrent call -- returned immediately, not waited on |
| `IDEMPOTENCY_KEY_REUSED` | The same `idempotency_key` was used before with a *different* request fingerprint -- a client bug, not a legitimate retry |

A replay (same key, same fingerprint, already completed) is not an error -- it returns the original
cached response verbatim, and the underlying write never runs twice.

## Agent runtime (`app/agent/runtime.py`)

| Code | Triggered when |
|---|---|
| `UNKNOWN_TOOL` | The model (or the mock) named a tool that isn't in the registry |
| `TOOL_ERROR` | A tool handler raised an exception the runtime didn't expect (logged via `logger.exception`, never propagated to the HTTP response as a 500) |

## Known gaps: not surfaced as a structured error, because the code path doesn't exist yet

- **`AmbiguousEmployeeError`** (`app/integrations/ports.py`) is raised by
  `HRISPort.find_employee_by_phone` when a phone number matches more than one employee, but no current tool
  calls that method -- this demo authenticates by direct `employee_id` (a web-portal field), not a
  WhatsApp-style phone lookup. If a future tool calls it without a `try`/`except`, it will surface as
  a raw, unhandled exception (a 500), not a `ToolError` -- there is no global FastAPI exception
  handler that would catch and reshape it.
- **Sick leave, Hajj/bereavement/marriage leave, disability-based leave** have no balance/preview
  logic at all (`LEAVE_TYPE_NOT_SUPPORTED` covers asking for them, but there's no tier table backing
  a real answer even if that error didn't exist) -- see ROADMAP.md's "Not modelled" section for
  exactly which figures have a citation and which don't.
- **A manager checking `list_pending_approvals`** only sees requests from their *direct* reports,
  not ones escalated to them as a skip-level approver -- they're still authorized to decide an
  escalated request (via `decide_leave_request`), they just don't see it in this listing. Documented,
  not fixed, in ROADMAP.md.
