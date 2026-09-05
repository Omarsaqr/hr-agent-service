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

## BM25 retrieval on a small corpus: a real, demonstrated precision limit

`app/knowledge/store.py` retrieves by BM25 over per-section chunks (~56 chunks total across 10
topics x 2 languages). On a corpus this small, BM25's length normalization can make a short,
tangentially-relevant section outscore a longer, genuinely on-topic one, because term frequency is
judged relative to document length: a 16-word section that happens to use two query words scores
higher than a 40-word section that uses them once. This isn't a hypothetical -- it's how
`transfer_request.en.md`'s "Effect on Leave and Tenure" section was originally worded (it mentioned
"annual leave" incidentally, in a section about transfers), and it briefly outscored the actual
`annual_leave_policy` document for the query "What is the annual leave policy?" during this
corpus's own test-writing. That specific collision was fixed by rewording the offending sentence
(`transfer_request.{en,ar}.md`), which is a legitimate fix for hand-authored mock content but not a
general solution -- the next accidental collision in a larger, less curated corpus would not be
caught by rereading every section.

Stopword filtering (`_STOPWORDS` in `store.py`) and an empirically-set match threshold
(`_MATCH_THRESHOLD = 2.0` in `app/api/tools/knowledge.py`) narrow the gap but don't close it. A real
implementation at HR's actual document scale should re-evaluate retrieval quality with a larger,
representative corpus before trusting BM25 alone -- likely candidates are a cross-encoder reranker
over BM25's top-N, or a hybrid BM25 + embedding score, neither of which is justified for ~56 mock
chunks.

## Cross-language section pairing is positional, not semantic

`KnowledgeStore.get_chunk` pairs an English chunk with its Arabic counterpart by `(topic,
section_index, language)` -- the Nth section of `topic.en.md` is assumed to be the translation of
the Nth section of `topic.ar.md`. Section titles can't be the join key: they're written in each
file's own language ("What It Is" vs. "ما هي"), so a title string never matches across languages.
Positional pairing holds for this corpus because every topic's `.en.md` and `.ar.md` were authored
as parallel translations with the same section count and order (verified for all 10 topics as part
of this fix). It would silently mispair if a future edit added or reordered a section in one
language's file without mirroring the change in the other -- there's no check that enforces
parallel structure across the two files. A per-section stable key (e.g., a slug in the section
heading, `## what-it-is: What It Is`) would remove that fragility; not done here since the corpus is
small enough to keep the two files in sync by hand.

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

## Google Sheets dashboard adapter: built real, verified against no live spreadsheet

`GoogleSheetsAdapter` and `GoogleSheetsClient` (`app/integrations/sheets/`) are a real Sheets API v4
integration -- OAuth2 service-account auth (JWT Bearer flow, RFC 7523), `values.get`/`values.append`
over httpx, retried through the same `request_with_retry` every other vendor uses. Unlike the
BambooHR adapter, this one was built with no Google Cloud project available, so `DASHBOARD_DRIVER`
defaults to `memory` and nothing here has been exercised against a real spreadsheet. What's actually
covered: `tests/contract/test_google_sheets_adapter.py` runs the full request/response flow through
`respx`, including real JWT construction and RSA-SHA256 signing (`google.auth.jwt.encode` +
`google.auth.crypt.RSASigner`) against a throwaway locally-generated key -- so the auth code path is
exercised end-to-end, just not against Google's actual token endpoint. `.env.example` documents
exactly what running this for real requires: a GCP project with the Sheets API enabled, a service
account with a downloaded JSON key, and a spreadsheet shared with that service account's email as an
Editor.

**New dependency: `google-auth`.** Needed for RSA-SHA256 JWT signing, which is not something to
hand-roll (it's security-sensitive, credential-adjacent code). Deliberately not
`google-api-python-client` or `gspread` -- both are full client SDKs built on top of `requests`, and
both would mean a second HTTP library alongside httpx for what is, underneath, two REST calls
(`values.get`, `values.append`). `google-auth` alone provides the signing primitives
(`google.auth.crypt`, `google.auth.jwt`) without pulling in a transport of its own; this adapter does
its own token-endpoint POST and API calls via httpx + the shared retry module, the same as BambooHR.

**Retry and cache generalized out of the BambooHR package.** `app/integrations/bamboohr/retry.py`
and `cache.py` moved to `app/integrations/retry.py` and `cache.py`, becoming vendor-neutral
(`request_with_retry` now takes a `service_name` for its error messages/logs instead of hardcoding
"BambooHR"). Both BambooHR and Sheets clients import the shared versions -- one retry policy and one
TTL-cache implementation for the whole codebase, not one per vendor. `TTLCache` was not reused for
the Sheets OAuth token cache, though: `TTLCache` assumes one fixed TTL configured at construction,
but an OAuth token's real lifetime comes from the token response itself (`expires_in`), which varies
per call. Forcing that through a fixed-TTL cache would mean ignoring the server's stated expiry in
favor of a guess; a plain `(token, expires_at)` pair on the client is more correct for this one case,
not a DRY violation.

**Not verified, and worth re-checking against a real spreadsheet before relying on this in
production:** whether Google's actual `values.get` response shape for a sparse/gapped range matches
the trimmed-trailing-cell behavior this adapter defends against (documented, not directly observed);
whether a 401 from an expired-early token (clock skew) should trigger one forced-refresh-and-retry
rather than surfacing as a bare `httpx.HTTPStatusError` -- no live credentials existed to provoke
that case, so no code exists to handle it either.

## Check-in tools: a ninth port method, and two decisions worth naming

`submit_daily_checkin`, `list_missing_checkins`, and `get_team_summary`
(`app/api/tools/checkins.py`) needed one relationship no existing port method provided: "who reports
to this manager." `get_manager` (commit 8) resolves the relationship in the other direction; this is
its mirror. Added as `HRISPort.list_direct_reports(manager_id) -> list[str]` -- ids only, not full
`Employee` records, because every actual caller (this, and `list_pending_approvals`, refactored to
call it instead of duplicating its own directory-scan-by-supervisor-name logic) only needs the id set
to filter something else by. A caller that wants a name already has `get_employee`; bundling full
records into the relationship lookup itself would cost every id-only caller N extra fetches it never
asked for. `BambooHRAdapter.list_pending_approvals` picked up a small behavior change from this
refactor: it now returns early (skipping the pending-requests fetch entirely) when the manager has
zero direct reports, instead of fetching and then filtering to nothing -- confirmed against the
existing contract tests, which check the returned list, not call counts.

**Company-local "today," not server-local or UTC.** `submit_daily_checkin` converts the caller's UTC
`now` to `Asia/Riyadh` before taking `.date()` -- a check-in submitted at 22:30 UTC is already
tomorrow in Riyadh (UTC+3), and which calendar day a check-in counts as is a business-calendar
question, not a function of whichever timezone the request happened to arrive in. Pinned as a
regression test. On Windows, `zoneinfo` has no system IANA database to read from, so this also added
`tzdata` as a dependency -- not a new capability, a portability fix for a stdlib module already in
use; Python's own `zoneinfo` docs recommend it for exactly this case.

**Sunday-start week, verified against `date.strftime`, not derived by hand.** `domain/checkins.
week_bounds` computes the Sunday-to-Saturday week (the Gulf work week, not the ISO Monday-start one)
containing a given date. The formula was checked empirically against a confirmed Sunday
(2026-06-07) and every day through the following Saturday before being trusted, the same discipline
applied to the Hijri epoch constant -- an off-by-one here would misfile which week a Thursday
check-in belongs to without ever raising an error.

**`get_team_summary` aggregates; it doesn't re-filter.** `DashboardPort.get_checkins` already scopes
results to the requested employee ids and date range and collapses same-day resubmissions to the
latest one. `domain.checkins.summarize_team_week` trusts that and only computes missing-employee ids
and the average rating over what it's given, rather than re-implementing filtering that already
happened at the adapter boundary.

## Gratuity: modelled where the law is confident, refused where it isn't

`app/domain/gratuity.py` and `app/api/tools/gratuity.py`. Every figure below was checked against
current sources (not encoded from training-data recall) precisely because this area has already
burned this project once -- Egypt's annual leave law changed in 2025, and gratuity/end-of-service
law across these four countries turns out to be even less uniform than leave entitlement.

- **KSA** -- full model. Half a month's wage per year of service for the first 5 years, a full
  month's wage per year after that (Art. 84). Resignation scales the award by tenure: <2 years
  nothing, 2-5 years a third, 5-10 years two-thirds, 10+ years the full award (Art. 85).
  Cause-termination under the nine grounds in Art. 80 forfeits it entirely. Everything else --
  ordinary termination, retirement, death, disability -- pays the full award regardless of tenure.
- **UAE** -- full model, and simpler than expected. Under the *current* law (Federal Decree-Law No.
  33 of 2021, effective Feb 2022), gratuity is reason-independent: resignation, ordinary
  termination, and even Art. 44 summary dismissal for gross misconduct all pay the same award once
  the 1-year minimum is met. This is a genuine change from the pre-2022 law, which several
  still-current-looking summary articles conflate with today's rule (misconduct no longer
  auto-forfeits -- forfeiture now needs a court ruling or MOHRE-approved settlement, which this
  system has no way to know about, so it's never assumed). 21 days' wage/year for the first 5
  years, 30 days/year after, capped at two years' total wage.
- **Egypt -- retirement only.** Egypt has no Gulf-style gratuity payable on any separation;
  end-of-service normally runs through the social-insurance/pension system (Law 148/2019), outside
  this system's scope entirely. The one figure with a confident, consistent citation across sources
  is the retirement gratuity (half a month/year for 5 years, a full month/year after, under Law
  14/2025). Resignation and employer-initiated termination are governed by separate compensation
  formulas that depend on *why* the employer ended the contract (arbitrary dismissal: 2 months/year;
  economic dismissal: a different graduated formula; fixed-term expiry: 1 month/year) --
  secondary sources describe these consistently with each other but not always precisely enough to
  cite an article number with confidence, and a wrong severance figure stated confidently is worse
  than an honest refusal. `calculate_gratuity` returns `GRATUITY_NOT_MODELED` for every Egypt reason
  except `retirement`.
- **Jordan -- not modelled at all.** Most Jordanian employees' end-of-service benefit is
  administered by the Social Security Corporation (a government lump-sum/pension), not paid
  directly by the employer -- the employer-gratuity formula found (1 month/year) only applies to
  employees outside SSC coverage, and there's a further wrinkle where gratuity may still be owed on
  salary above the SSC ceiling (JOD 3,349) even for covered employees. This system has no
  SSC-coverage-status field and no way to apply that ceiling correctly, so rather than encode a
  formula that's only sometimes the right one, Jordan is refused entirely -- the same "no confident
  source, no entry" rule already applied to sick leave for UAE/Egypt/Jordan.

**Salary is caller-supplied, not fetched from HRIS.** `calculate_gratuity` takes `basic_salary` as an
explicit parameter rather than reading it from BambooHR. No compensation endpoint has been verified
against the live trial account (previous BambooHR work only verified employee, time-off, and
directory endpoints) -- inventing a shape for an unverified endpoint would repeat exactly the
mistake this project's verification discipline exists to avoid. The tool's job is the computation,
not sourcing the wage figure.

## Iqama expiry alerts: a real scan, a logged alert, no outbound message

`app/domain/iqama.py`, `app/jobs/iqama_expiry.py`, `app/core/iqama_alerts.py`,
`app/core/scheduler.py`. A daily APScheduler cron job (6am `Asia/Riyadh`, explicit timezone --
APScheduler defaults to the server's local time, which would silently alert at the wrong hour if
this is ever deployed outside Riyadh) scans every KSA employee for an Iqama expiring within 90 days
(a pragmatic ops default, not a legal citation) or already expired, and records each hit in
`iqama_alerts`, an append-only table with the same shape as `GapLog`/`AuditLog`.

"Alert" means exactly that recorded row -- there is no WhatsApp/HeyLua outbound-messaging
integration in this system, so nothing is actually sent to anyone. Building that would mean
inventing an unverified messaging integration under the same time pressure this project has
otherwise refused to cut corners under; logging the alert for HR to review is the honest scope.
The scheduler itself is off by default (`IQAMA_SCHEDULER_ENABLED=false`) so tests and CI never spin
up a background thread; `run_iqama_expiry_check` is a plain, directly-callable, fully-tested
function underneath it, the same "tools are plain functions" shape used everywhere else here.

**`iqama_expiry_date` is always `None` on `BambooHRAdapter`.** BambooHR has no native Iqama field --
a real integration needs a per-tenant custom field (id + name), configured the same way
`leave_type_mapping.toml` handles custom time-off type names. Not built here, for the same reason
the compensation endpoint above isn't: no live tenant configuration exists to verify a shape
against, and a real production tenant would need its own custom field regardless of what (if
anything) the trial account happens to have configured.

**`list_employees_by_country` on `BambooHRAdapter` is N+1 and won't scale to 50,000 employees.** The
directory endpoint (verified in commit 6) carries no `country` field -- only `get_employee`'s fuller
field set does -- so listing "every KSA employee" means one directory call plus one `get_employee`
call per employee in the entire directory, filtered client-side. Fine for a demo tenant; a real
50,000-employee scan needs BambooHR's Reports API (bulk field export) instead, which hasn't been
verified against a live account and so isn't built here.
