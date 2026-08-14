# Regulatory notes

**Verified as of: 2026-08-07.**

> ## This is not tax advice.
>
> Costa Rican tax rules change, and they have changed twice in the recent past in
> ways that invalidated working software. This document records **what rules this
> engine implements and why**, so that its behaviour can be checked against the
> law by somebody qualified to do that. It is not a statement of what the law
> requires of you.
>
> Before relying on anything here for a real filing, verify it against the
> current text published by the Dirección General de Tributación and, for
> anything with money attached, against a Costa Rican tax professional. If this
> document and the law disagree, the law is right and this document is out of
> date.

---

## Contents

1. [What changed, and when](#1-what-changed-and-when)
2. [The rule this engine implements](#2-the-rule-this-engine-implements)
3. [Which days are días hábiles](#3-which-days-are-días-hábiles)
4. [What the engine deliberately does not decide](#4-what-the-engine-deliberately-does-not-decide)
5. [Validation rules and what backs them](#5-validation-rules-and-what-backs-them)
6. [Reference data, and how stale it can get](#6-reference-data-and-how-stale-it-can-get)
7. [What a real implementation would need](#7-what-a-real-implementation-would-need)
8. [Sources](#8-sources)

---

## 1. What changed, and when

Two changes in 2025 reset the ground for anything integrating with Costa Rican
electronic invoicing.

| Date | Change |
|---|---|
| **1 September 2025** | Electronic receipt format **version 4.4** became mandatory. |
| **6 October 2025** | **TRIBU-CR** replaced **ATV** as the tax administration platform. |

v4.4 is not a revision of the previous format — required fields, the tax
breakdown structure and several catalogues all changed. TRIBU-CR is a different
platform, not a new interface onto the old one.

The practical consequence for software: an integration written against ATV and
the previous format does not need updating. It needs rebuilding, because the
thing it connected to no longer exists.

---

## 2. The rule this engine implements

### The statement

> An electronic document that a taxpayer **receives** must be answered with a
> confirmation message — *aceptación*, *aceptación parcial* or *rechazo* —
> **within the first eight business days of the month following the transaction
> date**. The count begins on the first business day of that following month.

### The consequence of missing it

If the window closes without a confirmation message, the document **loses its
standing as support for the IVA credit**, and may also lose its standing as a
deductible expense for income tax. The loss is definitive. There is no
retroactive upload that restores it.

This is the entire reason the project exists. Most deadlines have a penalty and a
remedy. This one has no remedy.

### How the engine computes it

```
deadline(issue_date) = 8th business day of (month of issue_date + 1)
```

Implemented in `src/fractal_desk/deadline.py`, over the business-day primitives
in `src/fractal_desk/business_calendar.py`.

Three properties worth stating explicitly, because each is a place a naive
implementation goes wrong:

**It is not "eight business days after the invoice."** The window is anchored to
the *following month*, not to the document. A document issued on 2 March and one
issued on 31 March have the same deadline. `tests/test_deadline_engine.py`
asserts this directly, including a test that specifically guards against the
naive reading.

**Every document issued in a month shares one deadline.** That makes the issue
month the natural reporting period, which is why `fct_deadline_status` is grouped
that way and why the run report prints `distinct_deadlines` per month — it is 1
for every month, which demonstrates the property on real output.

**December rolls into January of the following year.** Handled in one place
(`_following_month`), because `month + 1` producing month 13 is the likeliest bug
in the file and should exist exactly once.

### Worked example — the hardest month in the window

Documents issued in **March 2026**. Deadline is the 8th business day of April
2026:

| Date | | Business day |
|---|---|---|
| Wed 1 Apr | | **1** |
| Thu 2 Apr | Jueves Santo | — |
| Fri 3 Apr | Viernes Santo | — |
| Sat–Sun 4–5 Apr | weekend | — |
| Mon 6 Apr | | **2** |
| Tue 7 Apr | | **3** |
| Wed 8 Apr | | **4** |
| Thu 9 Apr | | **5** |
| Fri 10 Apr | | **6** |
| Sat–Sun 11–12 Apr | weekend | — |
| Mon 13 Apr | | **7** |
| **Tue 14 Apr** | | **8 — deadline** |

Semana Santa moves the deadline from 9 April to **14 April**. An engine that
ignored holidays would be five days optimistic, in the direction that costs
money.

The instructive contrast: in **2025**, Easter fell on 20 April, so Jueves and
Viernes Santo (17–18 April) landed *after* the 8th business day and shifted
nothing — the deadline for March 2025 documents was 10 April 2025. Same holiday,
opposite effect, purely because of where Easter sat that year. This is why the
calendar is maintained data rather than a fixed list.

### Status model

The engine classifies **outcome**, not activity.

| Status | Meaning |
|---|---|
| `ACCEPTED` | Confirmed on or before the deadline. Credit secured. |
| `PENDING_SAFE` | Not confirmed; more than 3 business days remain. |
| `PENDING_AT_RISK` | Not confirmed; 3 or fewer business days remain, inclusive of the deadline day. |
| `EXPIRED_CREDIT_LOST` | Window closed unanswered, **or** confirmed after it closed. |

The last row is a judgement call and worth defending. A document confirmed two
days late is recorded as "accepted" in the source system, but the credit is gone.
Reporting it as `ACCEPTED` would make the dashboard's headline figure false. The
engine calls it `EXPIRED_CREDIT_LOST` and carries `accepted_late = TRUE` so the
distinction — a process failure, versus a document nobody ever touched — stays
queryable.

**The three-business-day at-risk threshold is not statutory.** It is an
operational choice about when to escalate, configurable via
`at_risk_threshold_days`. Three business days is roughly "you have this week",
which is the smallest window in which someone can chase a supplier for a
corrected document and still confirm in time.

**Counting is inclusive at both ends.** On the deadline day itself,
`business_days_remaining` is 1, not 0 — there is still a working day in which to
act. Getting that off by one is how a deadline tool tells someone they are fine
on the morning of the day the credit dies.

---

## 3. Which days are días hábiles

A date is a business day when it is Monday–Friday and not a national holiday the
calendar observes. The holiday file is `data/cr_holidays.csv`, covering
2025–2027.

### The judgement call: pago no obligatorio holidays

Costa Rica has twelve national holidays. Nine are *feriado de pago obligatorio*;
three — **2 August**, **31 August** and **1 December** — are *pago no
obligatorio*.

That distinction is a **labour-law rule about whether an employer must pay for
the day**. It is not a statement about whether the day is a día hábil.

**The engine observes all twelve as non-business days by default.** They are
national holidays, and *día hábil* in tax procedure excludes feriados.

`BusinessCalendar(observe_non_mandatory_pay_holidays=False)` treats the three as
working days, which moves affected deadlines **earlier**. That is the safer
direction to be wrong in — you act sooner than required — but it is not the
reading of the law, so it is not the default. If you want a safety margin, widen
`at_risk_threshold_days` rather than distorting the calendar: a distorted
calendar produces a deadline you cannot defend to an auditor, and the difference
only bites in three months of the year.

Both configurations are tested (`tests/test_business_calendar.py`). The
difference is visible: December 2026's deadline is 11 December under the default
and 10 December with the switch off.

### No Monday transfers in 2025–2027

Between roughly 2020 and 2024, several Costa Rican holidays were shifted to the
nearest Monday to create long weekends for tourism. **That measure is not in
force for 2025, 2026 or 2027** — every holiday is observed on its natural date.

If it is reinstated, `data/cr_holidays.csv` becomes wrong and must be reissued.
The file says so in its own header.

### Moveable holidays

Jueves Santo and Viernes Santo track Easter and change every year. They are
listed explicitly per year rather than computed, so that the calendar the engine
actually used is auditable after the fact.

- Easter 2025: 20 April → 17–18 April
- Easter 2026: 5 April → 2–3 April
- Easter 2027: 28 March → 25–26 March

### Coverage is enforced

Asking about a date outside 2025–2027 raises `CalendarCoverageError`. It does not
fall back to a holiday-free year. That fallback would produce deadlines wrong by
up to a week that look entirely normal in a dashboard — the worst possible
failure mode for a tool whose whole job is a date.

### Explicitly not modelled

- **Half-day observances.** 24 and 31 December are worked as half days by many
  institutions. A half day is still a día hábil, so it does not change the count.
- **Institution-specific or regional closures.** Not national feriados, so they
  do not change the statutory count.
- **Extraordinary administrative closures.** If the tax administration ever
  announces one that extends a filing window, that is a change to the holiday
  file, not to the code.

---

## 4. What the engine deliberately does not decide

This section exists so the scope is not overstated by omission.

- **It does not file anything.** There is no submission path. See
  [section 7](#7-what-a-real-implementation-would-need).
- **It does not decide whether to accept, partially accept or reject.** That is a
  commercial judgement about whether the document reflects a real transaction on
  agreed terms. The engine tracks whether a decision was made in time.
- **It does not decide what IVA rate a product is entitled to.** That follows
  from the CABYS code and the law. The engine checks that the stated rate matches
  the stated rate code and that the arithmetic closes.
- **It does not verify a taxpayer is registered for the activity claimed.** That
  needs Hacienda's registry.
- **It does not compute a tax return.** No D-104, no declaration, no filing
  position.
- **It does not know your transactions.** Every document in this repository is
  fabricated.

---

## 5. Validation rules and what backs them

Twenty structural rules, in `src/fractal_desk/validation.py`. Each is a check on
**structure and internal consistency**, not on legal correctness.

### Clave numérica

The 50-digit clave is positional and carries a copy of the issue date and the
document type. That is what makes it worth validating rather than treating as an
opaque string: a document whose clave disagrees with its own header is detectably
malformed.

| Positions | Digits | Content |
|---|---|---|
| 1–3 | 3 | Country code (506) |
| 4–9 | 6 | Issue date, DDMMYY |
| 10–21 | 12 | Issuer identification, zero-padded |
| 22–41 | 20 | Consecutivo numérico |
| 42 | 1 | Situación (1 normal, 2 contingencia, 3 sin internet) |
| 43–50 | 8 | Security code |

The 20-digit consecutivo is itself positional: branch (3), terminal (5), document
type (2), sequence (10).

Rules V001–V006 check length, numeric content, country code, date agreement with
the header, type-code agreement with the header, and uniqueness across the
dataset.

### Severity, and why one rule is a WARNING

`ERROR` means structurally wrong. `WARNING` means suspicious, **or** checked
against a catalogue this repository only ships a placeholder for.

**V009 (activity code in catalogue) is a WARNING, not an ERROR**, because
`data/catalog_economic_activities.csv` contains invented placeholder codes. Making
it an ERROR would produce a validator that is loudly confident on the strength of
data it made up. When the real Hacienda catalogue replaces that file, V009 should
be promoted to ERROR.

### Arithmetic

All monetary comparison is `Decimal` with an explicit one-céntimo tolerance.
v4.4 permits five decimal places and different issuing systems quantise at
different points, so a reconciliation rule in floating point fails on rounding
noise and passes on real errors — exactly backwards.

The rule with money attached is **V017**: the document-level `TotalImpuesto` must
equal the sum of its own lines' IVA. That header figure is the number a
bookkeeper keys into the return. If it disagrees with the lines it was computed
from, the return is wrong regardless of which of the two is right.

---

## 6. Reference data, and how stale it can get

Every catalogue in `data/` carries a version, a status and a maintenance warning
in its own header. Summary:

| File | Status | Risk if stale |
|---|---|---|
| `cr_holidays.csv` | **Real dates**, verified 2026-08-07, covers 2025–2027 | Deadlines wrong by days. Coverage is enforced, so an unknown year fails loudly rather than silently. |
| `catalog_document_types.csv` | Structurally accurate; verify against current annex | A type could be wrongly included in or excluded from the acceptance workflow. |
| `catalog_tax_rates.csv` | **Illustrative subset** | A valid rate code absent from the subset would be flagged as unknown. |
| `catalog_units_of_measure.csv` | **Illustrative subset** | A document using a legitimate unit absent from the subset would be flagged invalid. |
| `catalog_economic_activities.csv` | **Synthetic placeholders — not real codes** | Meaningless against real data. All codes are in the `9xxxxx` range so they are recognisable at a glance. Replace before any real use. |

The holiday file is the only one that is real data. The rest are labelled as what
they are, in the files themselves.

---

## 7. What a real implementation would need

Documented so the gap is explicit. **None of this is implemented here**, and the
absences are load-bearing — see the README's safety section and
`src/fractal_desk/submission/interface.py`.

1. **A Hacienda-issued cryptographic key** (*llave criptográfica*) and its PIN.
   Issued to the registered taxpayer or their authorised representative. Not
   something a project acquires — something a business is issued.
2. **XML construction to the v4.4 schema**, including the acceptance-message
   schema (`MensajeReceptor`), which is a different document from an invoice.
3. **XAdES-EPES signing** with the policy identifier the resolution specifies.
   Signature placement and canonicalisation are strict; a valid document with a
   signature in the wrong place is rejected.
4. **API connection details** — authentication and reception endpoints, per the
   technical annex covering API connection, with separate sandbox and production
   credentials.
5. **An asynchronous result model.** Submission is accepted for processing and
   answered later. A real implementation needs durable storage of in-flight
   submissions and a retry policy that cannot double-submit.
6. **A rejection-handling path.** `rechazado` is a normal outcome, not an error,
   and it feeds back into the deadline engine: a rejected document does not stop
   the clock.

---

## 8. Sources

Consulted 2026-08-06 and 2026-08-07 while building this engine.

**Instruments referenced in the sources below.** Cited as they were reported;
each should be checked against the official text before being relied on.

- **Resolución DGT-R-063-2018** — confirmation messages (aceptación, aceptación
  parcial, rechazo) for received electronic documents, and the eight-business-day
  window. Reported as remaining operative under TRIBU-CR.
- **Resolución MH-DGT-RES-0027-2024** — technical provisions for electronic
  receipts version 4.4, and the annexes carrying the catalogues.
- **Código de Normas y Procedimientos Tributarios, Ley N.º 4755.**

**Web sources.**

- [Comprobantes electrónicos recibidos en TRIBU-CR: aceptación — Siempre al Día](https://siemprealdia.co/costa-rica/impuestos/comprobantes-electronicos-recibidos-en-tribu-cr/) — the eight-business-day rule, the counting basis, the permanence of the loss, the three message types, and the instruments above.
- [Feriados Costa Rica 2026 y 2027 — Lenox HR](https://www.lenoxhr.com/feriados-costa-rica) — holiday dates and pago obligatorio / no obligatorio classification for 2026 and 2027, and confirmation of no Monday transfers.
- [Feriados 2026 en Costa Rica — El Financiero](https://www.elfinancierocr.com/estilo-de-vida/feriados-2026-en-costa-rica-esta-es-la-lista/GTFG3FLWVRGDLDHBPE744J7LR4/story/) — 2026 list and the nine/three pay split.
- [Estos son todos los feriados que habrá en 2025 — Monumental](https://www.monumental.co.cr/2025/01/31/estos-son-todos-los-feriados-que-habra-en-2025/) — 2025 list and confirmation that no holidays were transferred to Mondays.
- [aplicación de feriados del año 2025 — MTSS](https://www.mtss.go.cr/temas-laborales/feriados/feriados_calendario_2025.pdf) — Ministry of Labour 2025 holiday calendar.
- [Guía práctica para evitar rechazos de facturas electrónicas en TRIBU-CR — Officium Legal](https://blog.officiumlegal.com/es/derecho-tributario/tribu-cr-gua-practica-para-evitar-rechazos-de-facturas-electrnicas) — rejection handling under TRIBU-CR.
- [TRIBU-CR: qué es, cómo ingresar y trámites — Siempre al Día](https://siemprealdia.co/costa-rica/impuestos/plataforma-tribu-cr/) — the 6 October 2025 replacement of ATV.

Easter dates (and therefore Jueves and Viernes Santo) were computed with the
standard Gregorian computus and cross-checked against the published holiday
calendars above.

---

**Last verified: 2026-08-07.** If you are reading this materially later than
that, assume something below has changed and check.
