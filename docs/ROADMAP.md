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
- **`get_time_off_taken` had no upper bound.** Re-verifying three real employees' leave balances
  against the live account (not the original demo fixtures) turned up a balance of -15 days for an
  employee entitled to 21. The approved requests behind that number included five days dated in
  **2028** -- a leave year that hasn't started yet -- pulled in because the query only ever had a
  lower bound (`since`) and no upper one: `BambooHRAdapter` queried through `date.max`, and
  `InMemoryHRISAdapter` had no upper filter at all. Scoped correctly to the employee's actual
  2025-11-01–2026-10-31 leave year, the true balance is -6 -- still genuinely over-drawn, just not by
  that much. Fixed by adding a required `until` parameter to `HRISPort.get_time_off_taken`, computed
  from one new function, `domain/entitlements.py`'s `current_leave_year_bounds`, that returns both
  ends of "which leave year is this" rather than leaving the upper bound to be derived separately
  wherever it's needed. This is the third time exercising this adapter against the real account, not
  fixtures, caught a bug fixtures couldn't: the tenant-specific leave-type name guess and the
  inferred `create_time_off_request` payload shape, both above, were the first two. All three share
  the same shape -- a reasonable-looking assumption that fixtures, built from that same assumption,
  could never have contradicted.

## Google Sheets dashboard adapter: built real, now verified against a live spreadsheet

`GoogleSheetsAdapter` and `GoogleSheetsClient` (`app/integrations/sheets/`) are a real Sheets API v4
integration -- OAuth2 service-account auth (JWT Bearer flow, RFC 7523), `values.get`/`values.append`
over httpx, retried through the same `request_with_retry` every other vendor uses. Originally built
with no Google Cloud project available, so `DASHBOARD_DRIVER` defaults to `memory` and this ran
unverified against a real spreadsheet for most of the project. What's covered independent of a live
account: `tests/contract/test_google_sheets_adapter.py` runs the full request/response flow through
`respx`, including real JWT construction and RSA-SHA256 signing (`google.auth.jwt.encode` +
`google.auth.crypt.RSASigner`) against a throwaway locally-generated key -- so the auth code path is
exercised end-to-end, just not against Google's actual token endpoint. `.env.example` documents
exactly what running this for real requires: a GCP project with the Sheets API enabled, a service
account with a downloaded JSON key, and a spreadsheet shared with that service account's email as an
Editor.

**Now verified live, once a real service account and spreadsheet existed.** JWT signing, the
token-endpoint exchange, and both `values.get`/`values.append` all confirmed against Google's actual
servers -- no fixture involved. Full round trip exercised through the real `/chat` endpoint too, not
just the client in isolation: a natural-language check-in (real BambooHR employee, real Gemini
parsing it into a `submit_daily_checkin` call) landed as a real row in the real spreadsheet, read
back afterward to confirm. No bugs found this time -- the contract tests' respx-simulated request/
response shapes matched the live API exactly.

**One thing this surfaced that's a design choice, not a gap: the adapter validates headers, it
doesn't create them.** `GoogleSheetsAdapter._ensure_headers_valid` raises `HeaderMismatchError` on a
missing or wrong header row rather than writing the expected one -- deliberately, the same reasoning
as `BambooHRAdapter` raising `LeaveTypeMappingError` instead of silently treating a wrong mapping as
"zero days taken": a mismatched sheet far more likely means "wrong spreadsheet configured" than
"please set one up for me," and failing loudly beats guessing. A brand-new spreadsheet has none of
this (Google gives it one blank default tab and nothing else), so getting from that to something
`GoogleSheetsAdapter` accepts is a one-time setup step -- create a tab named to match
`GOOGLE_SHEETS_SHEET_NAME` (`checkins` by default) and write `GoogleSheetsAdapter._EXPECTED_HEADERS`
as its first row -- not something this session added as a runtime feature. Done here with a one-off
script using `GoogleSheetsClient`'s existing methods plus one raw `spreadsheets.batchUpdate` call for
the tab itself (the one operation this client has no method for, since the shipped adapter never
needs to create a sheet, only read and append to one that already exists).

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

## The /chat runtime: an LLMPort, a real adapter, and a mock that carries the whole demo

`app/integrations/llm/` (`ports.py`, `gemini.py`, `mock.py`), `app/agent/` (`tools.py`, `runtime.py`,
`sessions.py`), `app/api/chat.py`. Same ports & adapters shape as HRIS/Dashboard: `LLMPort.generate
(system_prompt, history, tools) -> Message` is provider-agnostic (a `Message`/`ToolCall` shape this
system owns, not Gemini's `Content`/`Part`), `LLM_DRIVER` selects the implementation, and `mock` is
the default so nothing about `/chat`, `make demo`, or the end-to-end tests needs a credential.

**Provider: Gemini, because the actual ask was "free yet reliable," not a named vendor.** Anthropic
and OpenAI both require a paid key (their trial credit isn't a standing free tier); Google's Gemini
API has a real, sustained free tier and native tool-calling. Verified rather than assumed, twice
over, because this area is unusually fast-moving:
- **The model name.** Training-data recall would have hardcoded `gemini-1.5-flash` or `2.0-flash` --
  both already shut down. Live docs (fetched during this build) showed the current model line was
  Gemini 3.x, with 2.5 Flash/Pro scheduled to shut down 2026-10-16 -- `gemini-2.5-flash` was kept as
  the default anyway, deliberately as a `GEMINI_MODEL` setting rather than a hardcoded literal,
  specifically because it was known to have an expiry date. That mattered sooner than the documented
  date suggested: the first live key tried against this project (2026-09-07) got `404 NOT_FOUND` from
  `gemini-2.5-flash`, with the response body reading `This model ... is no longer available to new
  users` -- the cutoff for *new* users, evidently, lands before the model's full shutdown for
  everyone else. Fixed with exactly the one-line env change this was built for:
  `GEMINI_MODEL=gemini-3.6-flash`, Google's own error message naming the replacement, no code
  touched. Google's `-latest` alias family was still deliberately not used instead -- it has a
  documented history of silently 404ing when the version behind it is deprecated, which is worse than
  an explicit pin that needs a one-line bump.
- **The API shape.** Google's current docs push a newer "Interactions API" (`client.interactions`)
  for function calling; this adapter is built against the older, still-present `generate_content` +
  manually-managed `Content`/`Part` history instead. Chosen deliberately, not out of inertia: every
  type this adapter constructs (`FunctionDeclaration`, `Tool`, `Content`, `Part`, `FunctionCall`,
  `FunctionResponse`) was verified by direct construction against the installed SDK, while the
  Interactions API's exact request/response contract couldn't be verified without a live key. It
  also keeps conversation history in this process, which the credential-free mock driver needs
  anyway to implement the same `LLMPort` interface.

**Verified live, once a real key existed.** Both paths work end to end against `gemini-3.6-flash`: a
plain-text reply, and a full tool-calling round trip -- model calls `get_leave_balance`, the app
executes it against the live BambooHR account, the result goes back to Gemini, Gemini produces the
final reply -- exercised through the actual `/chat` endpoint, not just the adapter in isolation.
`role="user"` for a function-response turn (the one specific risk flagged here before a key existed)
is indeed what Gemini's server expects; that part needed no fix.

One real bug surfaced that no fixture could have: the second call in that round trip failed with
`400 INVALID_ARGUMENT`, `Function call is missing a thought_signature in functionCall parts`.
Current-generation Gemini models require that exact opaque value (`bytes`, carried on the response
`Part` as a sibling of `function_call`, not inside `FunctionCall` itself) echoed back on any later
turn that replays the call it came from. `GeminiLLMAdapter` now caches it by tool-call id
(`_thought_signatures`, adapter-private state -- deliberately not added to the shared `Message`/
`ToolCall` types the mock adapter also uses, since it's a Gemini-specific concept the mock has no use
for) and reattaches it when reconstructing history for the next call. See
`tests/contract/test_gemini_llm_adapter.py::test_thought_signature_is_replayed_on_a_later_turn`,
written failing against the pre-fix code first, the same discipline as the Egypt age-tier bug.

Verifying this live surfaced a second bug, in the test suite rather than the adapter: switching
`LLM_DRIVER` to `gemini` in `.env` (to test the real key) broke nine tests across `tests/e2e/` and
`tests/unit/test_main.py`, all of them asserting on `MockLLMAdapter`'s specific deterministic replies
-- and burning a real API call per test in the process. `tests/e2e/conftest.py`'s `e2e` fixture
already overrides the HRIS and Dashboard ports via `monkeypatch.setitem` so tests never depend on
whichever real driver `.env` happens to have configured (see above) -- but nobody had done the same
for the LLM port, because until now `.env`'s default (`mock`) and what these tests needed had simply
always agreed. Fixed by giving the LLM port the identical override, plus a small `autouse` fixture in
`test_main.py` for the two module-level tests outside the `e2e` fixture's scope. Same shape as the CI
timezone bug and the `get_time_off_taken` bug elsewhere in this document: a thing that worked was
actually two things that happened to agree, until a change nothing here was fixture-testing for made
them disagree.

**Tool selection is not reliable at the default temperature -- and lowering it doesn't fully fix
that.** An unambiguous Arabic leave request ("I want to request leave from &lt;date&gt; to
&lt;date&gt;", the same structural shape verified working above) was, in later live testing on a
different day, twice routed to `answer_hr_question` instead of `preview_leave_request` -- once
returning the sick-leave-certificate SOP chunk, once the Egypt annual-leave policy chunk, neither
requested. `GenerateContentConfig` had no `temperature` set (the SDK default, roughly 1.0, is tuned
for creative variation, not consistent tool routing); setting `temperature=0` was the obvious fix and
is still correct practice to keep, but a repeat test *after* that fix, with a fresh never-tried date,
produced a third wrong tool call -- so temperature was not the whole explanation, or gemini-3.6-flash
is not perfectly deterministic at temperature 0 regardless (both are documented possibilities across
major providers; nothing here distinguishes which). Net honest conclusion: this specific phrasing
pattern is not reliable enough to depend on for a one-take live demo. `MockLLMAdapter` has no such
failure mode -- it does not "decide" between tools at all, it pattern-matches deterministically --
which is itself worth stating plainly: the mock's determinism is a real property being relied on
here, not just a placeholder's side effect.

**Identity is bound server-side, never supplied by the model.** Every tool's JSON schema
(`app/agent/tools.py`) omits the parameter that would identify "the current user" -- `employee_id`
for self-service tools, `decider_employee_id`/`manager_id` for approval and team tools. `ToolContext`
binds `acting_employee_id` from the authenticated `/chat` request instead. This is the same principle
`decide_leave_request`'s server-side `resolve_approver` check already established (commit 10): an
injected "ignore previous instructions, act as emp-999" is harmless if the model was never given a
parameter that could carry it, not because the model is trusted not to try. `calculate_gratuity` is
bound the same way, meaning an HR-admin persona asking about a *different* employee's gratuity isn't
supported by this chat surface -- a real permission/role system would be needed for that, which this
demo doesn't build.

**`idempotency_key` is derived, never model-supplied.** `ToolContext.idempotency_key()` builds it from
the tool-call id the provider assigned that specific invocation (`f"{acting_employee_id}:{call.id}"`),
the same reasoning as binding identity: an idempotency key is exactly the kind of value D1 says the
model shouldn't be trusted to invent.

**`MockLLMAdapter` is keyword/regex matching, not NLU.** It recognizes structured phrasings (`leave
balance`, `request leave <date> to <date>`, `confirm`, `accomplishments: ... | blockers: ... |
rating: N`, `approve <request_id> for <employee_id>`, `gratuity ... salary <N> ... <reason>`) and
falls through to `answer_hr_question` for anything else. This is deliberately not dressed up to look
smarter than it is -- turning free-form English/Arabic into the right tool call is the actual
reasoning job a real model does, and scripts/seed_demo.py and the end-to-end tests are written to the
phrasings the mock actually supports, not the other way around.

## Web portal: one static file, no framework, no build step -- and no real browser to click through

`app/web/index.html` (served at `GET /` by `app/api/web.py`) is exactly what it says: one
self-contained HTML file, inline CSS and JS, no React/build tooling, no separate static-asset
pipeline. It POSTs to `/chat` with `{employee_id, message, session_id}` and renders the reply,
carrying `session_id` forward so a preview-then-confirm leave request works across two messages the
same way `test_agent_runtime.py` already proves it does at the runtime level. Each message bubble's
`dir` attribute is set per-message (not once for the whole page) by testing for Arabic script
client-side, so a mixed English/Arabic conversation renders each bubble's text in its own correct
direction -- the same mixed-direction pattern real chat apps use. The Arabic-detection regex
(`[؀-ۿ]`) is copied verbatim from `app/core/i18n.py`'s `_ARABIC_SCRIPT_RE` rather than approximated,
so the client's guess about a message's language can't silently disagree with the server's.

**What was actually verified, and what wasn't.** There's no browser in this environment, so nothing
here has been clicked through end to end. What was checked: the inline `<script>` block was
extracted and syntax-validated with Node (`node --check`); a real `uvicorn` process was started and
`GET /` / `POST /chat` were hit directly, confirming the served HTML is byte-identical to the source
file and that the JSON shape the page's `fetch()` call depends on (`{session_id, reply}`) is what the
endpoint actually returns. What wasn't checked: that the DOM actually updates correctly on screen,
that CSS renders as intended, or that a real click-through conversation looks right. Before relying
on this for a live demo, open it in an actual browser first.

## End-to-end conversation tests found real bugs neither unit nor runtime-level tests could

`tests/e2e/` drives both named workflows through the real `POST /chat` endpoint
(`fastapi.testclient.TestClient` against the actual `app`, not `run_chat_turn` called directly) --
leave balance through preview, confirm, and a second manager's approval in `test_leave_workflow.py`;
check-in through team summary and missing-check-in detection in `test_checkin_workflow.py`; knowledge
Q&A and gratuity as a lighter third file. `tests/e2e/conftest.py`'s `e2e` fixture swaps fresh
`InMemoryHRISAdapter`/
`InMemorySheetAdapter` instances into `deps.py`'s process-global caches via `monkeypatch.setitem`
(restored automatically after each test) -- the real app resolves ports by settings value, not by
which fixture asked, so this is what makes seeding realistic data into *the actual running app*
possible without a live vendor.

The first two bugs below were only reachable through this specific combination (the real HTTP
endpoint, the real process-global singletons, actual wall-clock time) -- every earlier test level was
too isolated to trigger either one, which is the actual argument for building this layer at all, not
just a checkbox for "e2e tests exist." The third was a direct side effect of fixing the first.

- **SQLite connections reused across threads.** `NonceStore`/`IdempotencyStore`/`AuditLog`/`GapLog`
  are process-lifetime singletons (`app/deps.py`) holding one `sqlite3.Connection` each, opened on
  whichever thread first calls the relevant `get_*()`. `fastapi.testclient.TestClient` bridges sync
  test code into the async app through an `anyio` background-thread portal, and a second `TestClient`
  instance (or, potentially, a real ASGI server's own thread pool) can dispatch a later request on a
  *different* thread than the one that opened the connection -- sqlite3 refuses this by default:
  `SQLite objects created in a thread can only be used in that same thread`. The actual exception was
  being silently swallowed by `submit_leave_request`'s bare `except Exception: return
  ToolError(UPSTREAM_UNAVAILABLE)`, with no logging at all underneath it -- finding the real cause
  took a temporary `traceback.print_exc()` inserted by hand, which is itself the evidence that this
  catch needed a `logger.exception(...)` call it didn't have. Fixed both: `app/core/db.py` now opens
  every connection with `check_same_thread=False` (safe here because every access is already
  sequential -- this only disables Python's same-thread check, not SQLite's own locking), and the
  outer `except Exception` blocks in `submit_leave_request`, `decide_leave_request`, and
  `submit_daily_checkin` now log the real exception before returning the generic response.
- **A write and a read disagreed about what day "today" is.** `submit_daily_checkin` (commit 15)
  deliberately converts UTC to `Asia/Riyadh` before taking `.date()`, so a check-in submitted late in
  the UTC evening is correctly filed under the *next* Riyadh calendar day. `app/api/chat.py`'s
  `as_of` for every read tool (`list_missing_checkins`, `get_team_summary`, `calculate_gratuity`, the
  leave tools) was computed as naive `datetime.now(UTC).date()` -- a different value from the write's
  Riyadh-based date for roughly three hours of every real day (UTC is behind Riyadh by 3 hours, so
  there's a daily window where it's already tomorrow in Riyadh but still today in UTC). This wasn't a
  hypothetical: it reproduced immediately, live, the first time `test_checkin_workflow.py` ran,
  because the actual wall-clock time during this build happened to fall inside that window -- a
  just-submitted check-in was reported as missing. Fixed by extracting the shared logic both call
  sites need into `app/core/company_time.py` (`COMPANY_TIMEZONE`, `today_in_company_timezone`) and
  using it consistently in `chat.py`, `checkins.py`, and `scheduler.py` (which had the same latent gap
  for the Iqama scan, far less consequential against a 90-day threshold but the same category of bug)
  rather than leaving three private, easily-diverging copies of the same timezone constant.
- **The mock's tool-call ids weren't actually unique.** A side effect of chasing the first bug:
  `MockLLMAdapter._call()` gave every invocation of the same tool the identical id
  (`f"mock-{name}"`), and `ToolContext.idempotency_key()` derives its key from that id. Two genuinely
  different leave requests from the same employee -- in two different conversations, weeks apart --
  would collide on the same idempotency key and the second would be wrongly refused as
  `IDEMPOTENCY_KEY_REUSED`. A real model's tool-call ids are unique per call; the mock needed to match
  that property, not just its interface. Fixed by appending a fresh `uuid.uuid4()` suffix per call.

## CI failed on push: the test suite itself repeated the exact bug it exists to catch

The commit that added `docs/ARCHITECTURE.md`/`DECISIONS.md`/`EDGE_CASES.md` (bbbbf5b) turned green
locally and failed on GitHub Actions (`ubuntu-latest`) 40 seconds later --
`tests/e2e/test_checkin_workflow.py::test_checkin_then_manager_sees_it_in_the_team_summary` and
`test_checkin_replay_with_the_same_wording_does_not_double_count` both failed. Root cause: those two
tests (plus `test_gratuity_question_returns_a_computed_estimate` in
`test_knowledge_and_gratuity.py`) computed "today" via naive `date.today()` to build query windows and
reference dates, while the system under test (`submit_daily_checkin`, and `chat.py`'s `as_of` for
every read tool) computes "today" via `today_in_company_timezone(datetime.now(UTC))` -- the exact
`Asia/Riyadh` conversion this project already fixed once, in production code, for this exact reason
(see the entry above). `date.today()` reflects the *host machine's* local system timezone, which is
incidental: local development happened to run on a machine set to UTC+3 (the same offset as Riyadh),
so the two computations agreed on every local run by coincidence, not by correctness. GitHub Actions
runners default to UTC, where the two disagree for roughly three hours of every real day -- and the
push happened to land inside that window.

This is worth naming plainly: the tests built specifically to catch "a write and a read disagreeing
about what day it is" (see above) *reintroduced the same class of bug in their own assertions*, and
it went undetected through every local run, `git push`, and self-review in this session, surfacing
only on a CI runner in a different timezone. Local-only verification -- no matter how thorough --
cannot catch a bug whose only symptom is "this machine's clock happens to agree with the one true
timezone the code cares about." Fixed by replacing every `date.today()` in the e2e suite with
`today_in_company_timezone(datetime.now(UTC))`, the same call the production code makes, so the test
asks "what day does the system consider it" rather than "what day does this machine consider it."
The gratuity test's `date.today()` usage was, on inspection, arithmetically self-correcting for this
specific off-by-one-day case (verified by hand across several month/leap-year boundaries -- the
`completed_months_of_service` day-comparison logic happens to cancel out a one-day shift when the
reference date shares the same month/day as the reference point), but was changed anyway: correctness
that depends on an unexamined coincidence in unrelated arithmetic is not a property worth keeping
even when it happens to hold, especially in a codebase already burned once by exactly this kind of
assumption.
