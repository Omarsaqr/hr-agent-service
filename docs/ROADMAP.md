# Roadmap and scope decisions

## Bilingual catalogue is primitives-first, not a full migration yet

`app/core/i18n.py` has the substantive pieces: Hijri conversion (tabular algorithm, verified
against two independently-sourced reference dates rather than trusted from memory -- the commonly
quoted epoch constant was off by a day against both), Arabic-Indic numeral conversion, script
detection, and language resolution (detected script overrides the employee's profile default, per
the brief). It's wired into `get_leave_balance` and `preview_leave_request`'s Arabic messages as
the demonstration of it working end to end. It is not yet a message-template catalogue that every
tool's strings are forced through -- the other tools still build `message_ar` as direct f-strings.
Migrating everything to templates is mechanical, not risky, and deferred rather than done
half-attentively under time pressure.

## Tools are plain functions, not yet HTTP endpoints

`get_leave_balance`, `preview_leave_request`, and `verify_preview_for_submission`
(`app/api/tools/leave.py`) take their dependencies (`HRISPort`, `Settings`, `NonceStore`, `as_of`,
`now`) as explicit parameters rather than being registered as FastAPI routes with
`Depends()`-injected dependencies. This keeps them directly testable without an HTTP
request/response cycle. Route registration, request/response Pydantic schemas, and auth are real
remaining work, not done here -- `app/deps.py` builds the singletons (`get_hris_port`,
`get_nonce_store`, `get_idempotency_store`, `get_audit_log`) that route handlers will inject when
that wiring happens.

## Escalation ladder: listing vs. authorization

`resolve_approver` (`app/api/tools/leave.py`) implements the one-level skip-level ladder: if the
direct manager is inactive, on leave today, or the requester themself, resolution falls through to
the manager's own manager. `decide_leave_request`'s authorization check calls this resolver fresh,
so a skip-level manager genuinely can decide a request that escalated to them.

`list_pending_approvals`, however, calls `HRISPort.list_pending_approvals` directly, which only
returns an employee's *direct* reports. A skip-level manager won't see an escalated request in this
listing even though they're authorized to decide it -- they'd need to learn the request id some
other way (an SLA-breach notification, once that job exists). Making the listing itself
escalation-aware would mean enumerating every employee to find whose *resolved* approver is the
queried manager, which the current ports don't support cheaply. Noted rather than silently
inconsistent; not fixed here.

## SLA breach is a predicate, not a job yet

`domain/approvals.is_sla_breached` is real and tested, and `list_pending_approvals` flags each item
with it. The brief's "auto-escalate and notify both parties" behavior needs a scheduled job to scan
pending approvals and act on breaches -- no scheduler exists yet (APScheduler lands with the Iqama
expiry job). Until then, SLA breach is visible to whoever calls `list_pending_approvals`, not
proactively acted on.

## Deviations from the task brief

The task brief specifies leave-entitlement numbers per country. Every number in
`app/domain/countries.toml` was checked against the underlying law before being encoded; where the
brief and the verified law disagree, the table follows the law. Citations and source URLs live on
each policy entry in the table itself, not just here.

- **KSA sick leave** — the brief states 75% pay for the second tier (days 31-90 of a claim). This
  was checked against Article 117 and several practitioner sources and confirmed correct as
  written; no change made.
- **Egypt annual leave** — the brief states "21 days after one year." The applicable law is now
  Egyptian Labour Law No. 14 of 2025 (in force since 2025-09-01), which superseded the 2003 law the
  brief's figure traces to. The verified rule is 15 days in year one, 21 from year two, 30 after 10
  years or at age 50. Encoded as verified. Because the new law is recent enough that secondary
  sources still disagree on some detail, the conflict and the alternative reading are recorded in
  the `note` field on `Egypt.annual_leave` in `countries.toml` -- so a reviewer of the table itself
  sees it, not just this document.

## Not modelled

- **Sick leave for UAE, Egypt, and Jordan.** Only KSA's sick-leave tiers have a citation the brief
  itself supplies. No verified per-tier structure was sourced for the other three, so `sick_leave`
  is `None` for them rather than an invented table.
- **Hajj leave, bereavement leave, and marriage leave.** The brief names these as leave types to
  encode but gives no day counts or citations for any country. The rule applied everywhere else in
  this table -- no source, no entry -- applies here too.
- **Disability-based leave (Egypt).** Egypt's 2025 law grants 45 days to employees with
  disabilities. Not modelled: there is no disability-status field on the employee record, and
  adding one for a single country-specific tier is deferred until a workflow needs it.
- **Sick-leave preview.** `preview_leave_request` and `get_leave_balance` cover annual leave only.
  Sick leave's "balance" isn't entitlement-minus-taken -- it's which pay tier (100% / 75% / unpaid)
  a given day falls into, based on cumulative days already taken this rolling year (see
  `SickLeavePolicy` in `countries.py`). That's a different response shape, not a variant of this
  one, and deliberately not bolted onto the annual-leave preview to make it fit. Deferred until
  sick-leave preview is specifically built.
- **Moveable public holidays.** `app/domain/calendar.toml` encodes only fixed Gregorian-date
  holidays confirmed by a source (KSA Founding Day and National Day, UAE New Year's Day, Egypt
  Labour Day, Jordan New Year's Day / Labour Day / Christmas Day). Eid al-Fitr, Eid al-Adha,
  Islamic New Year, and the Prophet's Birthday are excluded rather than estimated: they follow
  moon sighting, and secondary sources for a specific year's Gregorian date are not reliable
  enough to encode as fact. A production system would source these from an official Hijri
  calendar feed per country, per year.
- **UAE weekend is a convention, not a universal rule.** The UAE's federal government moved to a
  Saturday-Sunday weekend on 2022-01-01; most large private employers followed, but private
  companies were not required to. `calendar.toml` encodes Sat-Sun as the dominant convention for
  this table, not as a claim that every UAE employer observes it.

## BambooHR adapter: verified against a live trial account

All seven `HRISPort` methods were exercised against a real BambooHR trial account (subdomain
`blackoctant`), reads and writes both, not inferred from documentation or REST convention. Several
things a fixture-only build would not have caught:

- **The directory endpoint defaults to XML.** `/employees/directory` returns `text/xml` unless the
  request sends `Accept: application/json` explicitly. The client never sent it. Every directory
  call would have failed outside a live account -- fixtures encode the JSON shape either way and
  can't fail this way, since respx mocks return whatever the test tells them to.
- **`reportsToId` is not a real field.** The correct field alias, per BambooHR's own
  `/meta/fields`, is `reportsTo` -- and it returns the manager's display name, not an id, no matter
  which employee endpoint asks for it. There is no id-based manager reference available via the
  fields API at all. `Employee.manager_id` is `None` for every BambooHR-backed employee as a
  result; `list_pending_approvals` resolves the target manager's own name via `get_employee` and
  matches it against each directory entry's `supervisor` string, since that name is the only
  manager relationship BambooHR actually exposes.
- **The directory's field set is much thinner than `get_employee`'s** -- no `hireDate`,
  `birthDate`, `status`, or `country`. `find_employee_by_phone` uses the directory only to resolve
  a phone number to an id, then makes a second `get_employee` call for the full record, rather than
  building a partial `Employee` with fields the directory can't supply.
- **Time-off type names are per-tenant, not a BambooHR-wide vocabulary.** This tenant calls its
  types "Annual Leave/Holiday" and "Sick Leave" (not "Sick" -- an initial guess at this name was
  wrong and would have passed silently without the validation below). The mapping from domain leave
  types to tenant-specific names lives in `app/integrations/bamboohr/leave_type_mapping.toml`, and
  `BambooHRAdapter` validates every mapped name against `/meta/time_off/types` on first use, raising
  `LeaveTypeMappingError` if a mapped name doesn't exist on the tenant. Unvalidated, a wrong mapping
  fails silently as "zero days taken" rather than as an error -- the one outcome worse than a
  startup-time exception.
- **`create_time_off_request`'s real payload uses `timeOffTypeId` (an id) and a nested
  `amount: {unit, amount}`,** not the inferred `timeOffTypeName` / flat `amount`. The inferred shape
  returned `400 Bad Request` with an empty body against the live account; the corrected shape was
  confirmed by successfully creating and then cancelling a real (test) request.
- **BambooHR recomputes the day count itself.** A live create request submitted with `amount: 2`
  came back recorded as `1` day, once BambooHR applied its own configured work schedule to the date
  range. `_map_time_off_request` reports whatever the response says, not what was sent -- but this
  means our `domain/calendar.py` working-day count and BambooHR's own can diverge for the same
  request. Worth flagging for whoever builds `preview_leave_request`: the previewed number and the
  number BambooHR ultimately records are not guaranteed to match.
- **`decide_time_off_request`'s status-change endpoint returns `200` with an empty body**, not the
  updated request. There is also no per-request GET. The adapter makes a follow-up company-wide
  `get_all_time_off_requests` call and finds the matching id, rather than returning a request
  object assembled from data it doesn't actually have.
- **BambooHR blocks self-approval.** Attempting to approve the account owner's own pending request
  returned `403 Forbidden`. Not handled specially here (it surfaces as an `httpx.HTTPStatusError`)
  but worth knowing before assuming any employee can decide any request they're authorised for.
