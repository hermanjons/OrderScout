# Logistics Agentic Parity Matrix

Updated: 2026-07-16

Authoritative inventory: `AI.processors.operation_runtime.operation_coverage_report`.
Provider and tariff records remain owned by Logistics.

## Runtime coverage

- read: 3
- write: 8
- total: 11

## Capability inventory

### Read

- `logistics.load_logistics_cargo_providers`
- `logistics.load_logistics_cargo_tariffs`
- `logistics.load_logistics_cargo_tariffs_summary`

### Write

- `logistics.accept_logistics_cargo_provider_record`
- `logistics.accept_logistics_cargo_tariff`
- `logistics.accept_logistics_cargo_tariffs`
- `logistics.delete_logistics_cargo_provider_record`
- `logistics.delete_logistics_cargo_tariff`
- `logistics.delete_logistics_cargo_tariffs`
- `logistics.save_logistics_cargo_provider_record`
- `logistics.save_logistics_cargo_tariff`

## Current acceptance

- Manual parity, local CRUD/bulk verify/audit and task approval/resume: `verified_baseline`
- Long Gemini/OpenRouter/suitable-local and provider-switch matrix: `open`
