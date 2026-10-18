# Labels Agentic Parity Matrix

Updated: 2026-07-16

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
The AI layer orchestrates these domain operations; it does not duplicate label layout,
DOCX export or verification logic.

## Runtime coverage

- read: 0
- write: 2
- total: 2

| Capability | Mode | Agentic contract |
|---|---|---|
| `labels.action_create_labels_from_selected_orders` | write | Exact immutable Orders selection → prepare → approval → DOCX execute → content verify |
| `labels.mark_orders_extracted_from_label_result` | write | Verified label result → explicit approval → local state write → read-back |

## Current acceptance

- Orders→Labels selection and DOCX digital render: `verified_baseline`
- TANEX TW-2610 2×5 Word/PDF/PNG visual acceptance: `verified_baseline`
- Physical TW-2610 sheet alignment: `deferred_supervised`
- Separate Labels task catalog: `not_applicable`; the workflow consumes Orders state and
  must not duplicate selection logic
