# Kusuma Settlement Service

A prototype payout-calculation engine for Kusuma Marketplace, built with Python and FastAPI.

## Quick start

```bash
cd kusuma-settlement
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The service seeds test data automatically on startup.
Interactive API docs: http://localhost:8000/docs

## Usage examples

### List all sellers
```
GET /api/v1/sellers
```

### Calculate a payout
```
GET /api/v1/sellers/S-001/payout?start_date=2026-01-01&end_date=2026-01-07
```

### Pending payouts across all sellers
```
GET /api/v1/payouts/pending
```

### Re-seed test data
```
POST /api/v1/admin/seed
```

## Running tests

```bash
pytest tests/ -v
```

## Test data

Generated deterministically by `scripts/seed_data.py` (seed = 42).

| Seller | Commission | Settlement | Cross-currency |
|---|---|---|---|
| S-001 Batik Nusantara | 8 % | IDR | IDR + THB |
| S-002 Thai Silk House | 12 % | THB | THB + IDR |
| S-003 Hanoi Crafts | 15 % | VND | VND + THB |

220 transactions over January 2026:
- ~70 % captured
- ~10 % authorized (excluded from payouts)
- ~15 % refunded (~60 % full, ~40 % partial at 20–80 % of original)
- ~5 % chargeback (linked to parent)

## How the calculation works

1. **Select** all `captured` transactions for the seller whose `captured_at` falls within the requested date range.
2. **Find all linked refunds / chargebacks** for those transactions — regardless of when they occurred.
3. **Net amount per transaction** = `original_amount − total_refunded`
4. **Commission** is applied to the net amount: `commission = net × commission_rate`
5. **Payout per transaction** = `net − commission`
6. **Currency conversion**: if the transaction currency differs from the seller's settlement currency, the payout is converted using the static exchange-rate table in `app/currency.py`.
7. **Aggregate**: sum gross volume, total commission, total refunds, and net payout across all line items.

## Key design decisions

| Decision | Rationale |
|---|---|
| Refunds applied regardless of date | A refund for a Jan 3 transaction that arrives Jan 10 must still zero out the Jan 3 payout; the system always looks at the full refund history. |
| Commission on net-after-refunds | The marketplace should not earn commission on money that was returned. |
| Static exchange rates | Sufficient for a prototype; production would pull rates from a provider at the time of capture. |
| In-memory store | Keeps the prototype self-contained; replace `DataStore` with a DB-backed repository without changing the engine. |
| `Decimal` arithmetic | Avoids floating-point rounding errors in financial calculations. |

## Stretch Goals

### Preview mode
Add `&preview=true` to any payout request to simulate without side effects:
```
GET /api/v1/sellers/S-001/payout?start_date=2026-01-01&end_date=2026-01-07&preview=true
```

### Batch payouts
Calculate all sellers in one request:
```
GET /api/v1/payouts/batch?start_date=2026-01-01&end_date=2026-01-07
```

### Execute & audit trail
```
POST /api/v1/sellers/S-001/payout/execute?start_date=2026-01-01&end_date=2026-01-07
GET  /api/v1/executions
```

### Fraud flagging
Every payout response includes a `fraud_flags` array. Flags are raised when:
- A transaction amount exceeds 3× the seller's period average (severity: medium/high)
- The seller's refund rate in the period exceeds 30% (severity: medium)

### Partial refunds
The test dataset includes partial refunds (20–80% of original amount) in addition to full refunds.

## Example output
See [`examples/s001_jan1-7.json`](examples/s001_jan1-7.json) for a full payout calculation response for seller S-001, January 1–7 2026.

## Assumptions

- Exchange rates are fixed; rate-at-capture would be used in production.
- The service has no authentication layer (prototype scope).
