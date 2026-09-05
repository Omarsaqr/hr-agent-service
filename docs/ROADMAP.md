# Roadmap and scope decisions

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
- **Public holiday calendars.** Belongs to the working-day calendar work, not entitlement rules.
