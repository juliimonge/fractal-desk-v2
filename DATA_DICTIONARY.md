# Data dictionary

Every table in `build/fractal_desk.duckdb`, its grain, and what each column
means. Column names and types below were read from a built warehouse, not
written from memory.

> **All data is synthetic.** Every taxpayer identifier begins `999` (a range
> Costa Rica does not issue), every company name begins `SYN`, and every row in
> every mart carries `is_synthetic = TRUE`. See the README.

**Model layout**

```
raw_*        loaded by warehouse.py from the generator, engine and validator
ref_*        reference catalogues, copied into the warehouse so it is self-describing
stg_*        staging  — rename, cast, trim. No logic.
int_*        intermediate — rollups and summaries
dim_/fct_    marts — the tables you query
```

Layers run in order: `staging` → `intermediate` → `marts`. Numeric filename
prefixes (`01_`, `02_`, …) declare the dependency order within each layer.

**Conventions**

- Money is `DECIMAL`, never `DOUBLE`. Reconciliation rules in floating point fail
  on rounding noise and pass on real errors.
- Amounts suffixed `_crc` are restated in Costa Rican colones at the document's
  own exchange rate — the rate that applied on the issue date, not a current
  rate. Unsuffixed amounts are in the document's own currency.
- `document_record_id` is the surrogate key throughout. **`clave` is not a key**:
  the dataset contains duplicate claves by design.

---

## Marts

### `fct_deadline_status`

**Grain:** one row per document record subject to an acceptance obligation.
**The table the dashboard is built on.**

> **Fewer rows than `fct_document`.** Only document types with
> `enters_acceptance_workflow = TRUE` appear — a tiquete electrónico is issued to
> a final consumer and carries no receiver confirmation obligation, so it never
> generates a deadline. **Join from `fct_document` with a LEFT JOIN**, and read a
> NULL status as "no obligation", not "not yet assessed".

| Column | Type | Meaning |
|---|---|---|
| `document_record_id` | BIGINT | Surrogate key. Unique. |
| `clave` | VARCHAR | 50-digit clave numérica. May be malformed; may repeat. |
| `clave_is_duplicated` | BOOLEAN | This clave appears on more than one record. |
| `document_type_code` | VARCHAR | TipoDocumento, two digits. |
| `document_type_name_es` | VARCHAR | Spanish name. |
| `issuer_id` | VARCHAR | Issuer identifier. Always `999…`. |
| `issuer_name` | VARCHAR | Issuer name. Always `SYN …`. |
| `issue_date` | DATE | FechaEmisión. **Drives the deadline** — not the received date. |
| `issue_month` | DATE | First day of the issue month. The natural reporting period: every document in a month shares one deadline. |
| `received_date` | DATE | When the document reached the business. |
| `arrival_lag_days` | BIGINT | Calendar days between issue and arrival. High values are the upstream cause of most lost credit and cannot be fixed internally. |
| `window_opens_on` | DATE | First business day of the month after `issue_month`. When the statutory window opens. |
| `deadline_date` | DATE | **8th business day of the month after `issue_month`.** The last día hábil to confirm. |
| `as_of` | DATE | The date this assessment was computed against. |
| `status` | VARCHAR | `ACCEPTED` / `PENDING_SAFE` / `PENDING_AT_RISK` / `EXPIRED_CREDIT_LOST`. |
| `business_days_remaining` | INTEGER | Business days in the closed interval `[as_of, deadline_date]`. **Inclusive**: 1 on the deadline day itself. 0 for both terminal statuses. |
| `accepted_on` | DATE | Date the confirmation was sent. NULL if none. |
| `accepted_late` | BOOLEAN | A confirmation exists but was sent after the deadline. Credit lost anyway. |
| `due_today_or_next` | BOOLEAN | At risk with 1 or fewer business days left. |
| `due_within_five_business_days` | BOOLEAN | Pending with 5 or fewer business days left. |
| `currency` | VARCHAR | CRC, USD or EUR. |
| `exchange_rate` | DECIMAL(18,5) | TipoCambio carried on the document. 1 for CRC. |
| `total_tax` | DECIMAL(18,5) | IVA in the document's own currency. |
| `total_tax_crc` | DECIMAL(18,10) | IVA in colones. |
| `iva_at_risk_crc` | DECIMAL(18,2) | **Recoverable** IVA. Non-zero only for `PENDING_*`. Signed by `credit_sign`. |
| `iva_lost_crc` | DECIMAL(18,2) | **Unrecoverable** IVA. Non-zero only for `EXPIRED_CREDIT_LOST`. |
| `iva_secured_crc` | DECIMAL(18,2) | IVA confirmed in time. Non-zero only for `ACCEPTED`. |
| `error_count` | BIGINT | Validation ERRORs on this document. |
| `has_blocking_error` | BOOLEAN | `error_count > 0`. |
| `is_synthetic` | BOOLEAN | Always TRUE. |

**Contract (asserted in `tests/test_sql_models.py`):**

- `document_record_id` unique.
- `status` is always one of the four values.
- `business_days_remaining >= 0`, and exactly 0 for `ACCEPTED` and `EXPIRED_CREDIT_LOST`.
- `deadline_date > issue_date` always; `window_opens_on <= deadline_date` always.
- Exactly one deadline per `issue_month`.
- `PENDING_AT_RISK` never has more than 3 business days remaining.
- `accepted_late = TRUE` never coexists with `status = 'ACCEPTED'`.
- **A row contributes to at most one of `iva_at_risk_crc`, `iva_lost_crc`,
  `iva_secured_crc`.** They never double-count the same IVA.

**The three money columns are separate on purpose.** Recoverable and
unrecoverable money answer different questions — one is a to-do list, the other
is a loss report. Adding them together produces a number that is true of nothing.

---

### `fct_document`

**Grain:** one row per document **record**.

> **Duplicate claves are kept, not deduplicated.** A duplicate clave is a defect
> with a money consequence, not noise to be cleaned: two records claiming the
> same IVA credit either double-count it or cost the time to work out which copy
> is real. Filter `clave_occurrence = 1` for a deduplicated view, or
> `clave_is_duplicated` for the remediation queue. Neither is the silent default.

| Column | Type | Meaning |
|---|---|---|
| `document_record_id` | BIGINT | Surrogate key. Unique. |
| `clave` | VARCHAR | 50-digit clave numérica. |
| `clave_occurrence` | BIGINT | 1 for the first record carrying this clave, 2 for the next, and so on. |
| `clave_record_count` | BIGINT | How many records carry this clave. |
| `clave_is_duplicated` | BOOLEAN | `clave_record_count > 1`. |
| `consecutivo` | VARCHAR | 20-digit consecutivo numérico. |
| `document_type_code` | VARCHAR | TipoDocumento. |
| `document_type_name_es` | VARCHAR | Spanish name. |
| `enters_acceptance_workflow` | BOOLEAN | Whether receiving this type starts an acceptance clock. |
| `credit_sign` | INTEGER | `+1` adds to IVA credit, `-1` reduces it (nota de crédito), `0` neutral. |
| `issuer_id` / `issuer_name` | VARCHAR | Issuer. Always `999…` / `SYN …`. |
| `receiver_id` / `receiver_name` | VARCHAR | Receiver. NULL on tiquetes, and on documents with the MISSING_RECEIVER defect. |
| `issue_date` | DATE | FechaEmisión. |
| `issue_month` | DATE | First day of the issue month. |
| `received_date` | DATE | Arrival. |
| `accepted_date` | DATE | Confirmation date, or NULL. |
| `arrival_lag_days` | BIGINT | `received_date - issue_date`, calendar days. |
| `economic_activity_code` | VARCHAR | CodigoActividad. NULL when absent. **Placeholder codes** — see `data/catalog_economic_activities.csv`. |
| `currency` | VARCHAR | CRC / USD / EUR. |
| `exchange_rate` | DECIMAL(18,5) | TipoCambio. 0 marks the MISSING_EXCHANGE_RATE defect. |
| `total_net` | DECIMAL(18,5) | Net total before IVA, document currency. |
| `total_tax` | DECIMAL(18,5) | **Stated** IVA from the document header. |
| `total_document` | DECIMAL(18,5) | Stated grand total. |
| `total_tax_crc` | DECIMAL(18,10) | Stated IVA in colones. |
| `line_count` | BIGINT | Lines on the document. Always >= 1. |
| `recomputed_net` | DECIMAL(38,5) | Net total **recomputed from the lines**. |
| `recomputed_tax` | DECIMAL(38,5) | IVA **recomputed from the lines**. |
| `iva_discrepancy_crc` | DECIMAL(38,2) | Signed gap `total_tax - recomputed_tax`, in colones. |
| `finding_count` / `error_count` / `warning_count` | BIGINT | Validation findings by severity. |
| `has_blocking_error` | BOOLEAN | `error_count > 0`. |
| `triggered_rule_ids` | VARCHAR | Comma-separated, sorted rule ids. Stable across runs. |
| `injected_defects` | VARCHAR | Comma-separated defect labels the **generator** planted. Ground truth for tests. Would not exist on real data. |
| `is_synthetic` | BOOLEAN | Always TRUE. |

**On `iva_discrepancy_crc`.** Stated versus recomputed sit side by side so the
gap is summable. "142 documents fail IVA reconciliation" is a bug report;
"₡2.1M of stated IVA does not match the lines it came from" is a business case.

---

### `fct_validation_finding`

**Grain:** one row per finding. A document may produce many; a clean one
produces none.

| Column | Type | Meaning |
|---|---|---|
| `document_record_id` | BIGINT | The record this finding belongs to. |
| `clave` | VARCHAR | Clave of that record. |
| `rule_id` | VARCHAR | `V001`–`V020`. See `src/fractal_desk/validation.py`. |
| `rule_name` | VARCHAR | Short rule name. |
| `severity` | VARCHAR | `ERROR` / `WARNING` / `INFO`. |
| `message` | VARCHAR | Human-readable finding. |
| `line_number` | INTEGER | NULL for document-level findings; populated for line-level. |
| `expected_value` | VARCHAR | What the rule expected. |
| `actual_value` | VARCHAR | What it found. |
| `document_type_code`, `document_type_name_es`, `issuer_id`, `issuer_name`, `issue_date`, `issue_month`, `currency` | | Denormalised document context, so findings can be grouped by issuer or month without a join. |
| `iva_exposed_crc` | DECIMAL(18,10) | The document's whole IVA, in colones. |
| `is_synthetic` | BOOLEAN | Always TRUE. |

> **Do not sum `iva_exposed_crc` across a document's findings.** It is the
> document's entire IVA attached to each of its findings, so a document with
> three findings would count its IVA three times. Sum it only **within a single
> `rule_id`**, which is how the dashboard uses it.

**Contract:** `(document_record_id, rule_id, line_number)` is unique — a finding
is never recorded twice for the same document.

---

### `dim_contributor`

**Grain:** one row per synthetic taxpayer (48 issuers + 1 receiving business).

A dimension with pre-aggregated behavioural attributes attached. That is a
deliberate departure from a pure dimension: "which of my suppliers keeps costing
me credit" is asked constantly, and answering it from the fact table every time
is slower and easier to get wrong.

| Column | Type | Meaning |
|---|---|---|
| `contributor_id` | VARCHAR | Identifier. Always begins `999`. |
| `contributor_name` | VARCHAR | Name. Always begins `SYN`. |
| `id_type` | VARCHAR | `01` física, `02` jurídica. |
| `id_type_name` | VARCHAR | Decoded label. |
| `sector` | VARCHAR | `real_estate`, `construction`, `hospitality`, `professional_services`, `other`. |
| `activity_code` | VARCHAR | Placeholder activity code. |
| `role` | VARCHAR | `issuer` or `receiver`. |
| `document_count` | BIGINT | Documents issued. |
| `total_iva_crc` | DECIMAL(38,10) | Total IVA issued, colones. |
| `first_document_date` / `last_document_date` | DATE | Activity span. |
| `avg_arrival_lag_days` | DOUBLE | **Mean calendar days between issue and arrival.** The best single predictor of whether a supplier will cost you credit. |
| `accepted_document_count` | BIGINT | Confirmed in time. |
| `pending_document_count` | BIGINT | Still open. |
| `expired_document_count` | BIGINT | Credit lost. |
| `credit_lost_crc` | DECIMAL(38,10) | IVA lost on this supplier's documents. |
| `is_synthetic` | BOOLEAN | Always TRUE. |

`expired_document_count` and `credit_lost_crc` are what make this worth opening:
they support a conversation with a supplier, which is the only durable fix for a
document that arrives too late to accept.

---

### `dim_document_type`

**Grain:** one row per TipoDocumento code. Source:
`data/catalog_document_types.csv`.

| Column | Type | Meaning |
|---|---|---|
| `document_type_code` | VARCHAR | Two-digit code. |
| `document_type_name_es` / `_en` | VARCHAR | Names. |
| `requires_receiver` | BOOLEAN | A receptor block is mandatory. |
| `enters_acceptance_workflow` | BOOLEAN | **Receiving one starts an acceptance clock.** The flag the whole deadline model hinges on. |
| `credit_sign` | INTEGER | `+1` / `-1` / `0`. |

Encoding `enters_acceptance_workflow` as a dimension attribute rather than a
hardcoded `WHERE document_type_code <> '04'` in five places means the rule changes
in one row of a CSV if Hacienda changes it.

`credit_sign` lets IVA be summed directionally: a nota de crédito reduces the
credit position rather than adding to it, so summing raw IVA across mixed types
overstates exposure.

| Code | Type | Receiver required | Acceptance clock | Credit sign |
|---|---|---|---|---|
| `01` | Factura electrónica | yes | **yes** | +1 |
| `02` | Nota de débito electrónica | yes | **yes** | +1 |
| `03` | Nota de crédito electrónica | yes | **yes** | −1 |
| `04` | Tiquete electrónico | no | no | 0 |
| `08` | Factura electrónica de compra | yes | no | +1 |
| `09` | Factura electrónica de exportación | yes | no | 0 |
| `10` | Recibo electrónico de pago | yes | no | 0 |

---

## Intermediate

### `int_document_line_rollup`
**Grain:** one row per document record.
`line_count`, `recomputed_gross`, `recomputed_discount`, `recomputed_net`,
`recomputed_tax`, `recomputed_total`, `recomputed_taxable`, `recomputed_exempt`,
`distinct_rate_codes`. Rolls lines to the document and produces the figure the
header is supposed to agree with.

### `int_document_validation_summary`
**Grain:** one row per document record **that produced at least one finding**.
`finding_count`, `error_count`, `warning_count`, `info_count`,
`triggered_rule_ids`. Documents with no findings are absent — a clean document
should not need a row to prove it is clean. Downstream joins are LEFT and treat
NULL as zero.

---

## Staging

Rename, cast, trim. No joins, no logic, no filtering.

| Model | Grain |
|---|---|
| `stg_contributors` | one row per synthetic taxpayer |
| `stg_documents` | one row per document **record** (duplicate claves preserved) |
| `stg_document_lines` | one row per line per document record |
| `stg_deadline_status` | one row per document record with an acceptance obligation |
| `stg_validation_findings` | one row per finding |

`stg_document_lines` joins to documents on `document_record_id`, **never on
clave** — a clave join would fan lines across both copies of a duplicate and
silently double every rolled-up total.

---

## Reference tables

Copied into the warehouse so the build artefact is interpretable without the CSV
files beside it.

| Table | Rows | Source | Status |
|---|---|---|---|
| `ref_holidays` | 36 | `data/cr_holidays.csv` | **Real dates**, 2025–2027, verified 2026-08-07 |
| `ref_document_types` | 7 | `data/catalog_document_types.csv` | Structurally accurate; verify against current annex |
| `ref_tax_rates` | 11 | `data/catalog_tax_rates.csv` | Illustrative subset |
| `ref_units_of_measure` | 25 | `data/catalog_units_of_measure.csv` | Illustrative subset |
| `ref_economic_activities` | 15 | `data/catalog_economic_activities.csv` | **Synthetic placeholders — not real codes** |

Each source file carries its own version, status and maintenance warning in its
header. See [REGULATORY_NOTES.md § 6](./REGULATORY_NOTES.md#6-reference-data-and-how-stale-it-can-get).

---

## Raw tables

Loaded by `src/fractal_desk/warehouse.py` before any SQL runs:
`raw_documents`, `raw_document_lines`, `raw_deadline_status`,
`raw_validation_findings`, `raw_contributors`.

`raw_deadline_status` is written by the Python deadline engine. **The SQL layer
consumes it; it does not re-derive it.** Business-day arithmetic against a
holiday file is awkward in SQL and easy to get wrong at month boundaries —
exactly where this rule lives — it needs exhaustive unit testing, and two
implementations of a money-losing rule is one more than is defensible.
