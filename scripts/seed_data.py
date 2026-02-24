"""
Deterministic test-data generator.

Produces:
  - 3 sellers  (8 % / 12 % / 15 % commission)
  - 220 transactions spread over Jan 2026
    - ~70 % captured
    - ~10 % authorized
    - ~15 % refunded  (linked to a captured parent)
    - ~5  % chargeback (linked to a captured parent)
  - Currencies: IDR, THB, VND
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal

from app.models import Currency, Seller, Transaction, TransactionStatus
from app.store import DataStore

SEED = 42
START = datetime(2026, 1, 1)
END   = datetime(2026, 1, 31, 23, 59, 59)


def _rand_dt(rng: random.Random, lo: datetime = START, hi: datetime = END) -> datetime:
    delta = hi - lo
    secs = rng.randint(0, int(delta.total_seconds()))
    return lo + timedelta(seconds=secs)


def seed(store: DataStore) -> None:
    rng = random.Random(SEED)

    # ── sellers ──────────────────────────────────────────────────────────────
    sellers = [
        Seller(
            id="S-001",
            name="Batik Nusantara",
            commission_rate=Decimal("0.08"),
            settlement_currency=Currency.IDR,
            country="Indonesia",
            email="finance@batiknusantara.id",
        ),
        Seller(
            id="S-002",
            name="Thai Silk House",
            commission_rate=Decimal("0.12"),
            settlement_currency=Currency.THB,
            country="Thailand",
            email="accounts@thaisilkhouse.th",
        ),
        Seller(
            id="S-003",
            name="Hanoi Crafts",
            commission_rate=Decimal("0.15"),
            settlement_currency=Currency.VND,
            country="Vietnam",
            email="billing@hanoicrafts.vn",
        ),
    ]
    for s in sellers:
        store.add_seller(s)

    # currency pools per seller (cross-currency sellers)
    seller_currencies = {
        "S-001": [Currency.IDR, Currency.IDR, Currency.IDR, Currency.THB],   # mostly IDR
        "S-002": [Currency.THB, Currency.THB, Currency.THB, Currency.IDR],   # mostly THB
        "S-003": [Currency.VND, Currency.VND, Currency.VND, Currency.THB],   # mostly VND
    }

    # amount ranges per currency (realistic ticket sizes)
    amount_ranges = {
        Currency.IDR: (50_000, 5_000_000),
        Currency.THB: (100,    15_000),
        Currency.VND: (50_000, 3_000_000),
    }

    # ── transactions ─────────────────────────────────────────────────────────
    total   = 220
    # index thresholds
    n_cap   = int(total * 0.70)   # 154 captured
    n_auth  = int(total * 0.10)   #  22 authorized
    n_ref   = int(total * 0.15)   #  33 refunded
    n_cb    = total - n_cap - n_auth - n_ref  # 11 chargebacks

    txn_counter = 0

    def next_id(prefix: str) -> str:
        nonlocal txn_counter
        txn_counter += 1
        return f"{prefix}-{txn_counter:04d}"

    # 1. Captured
    captured_ids: list[str] = []
    for _ in range(n_cap):
        seller_id = rng.choice(["S-001", "S-002", "S-003"])
        currency  = rng.choice(seller_currencies[seller_id])
        lo, hi    = amount_ranges[currency]
        amount    = Decimal(str(round(rng.uniform(lo, hi), 2)))
        captured_at = _rand_dt(rng)
        tid = next_id("T")
        captured_ids.append(tid)
        store.add_transaction(Transaction(
            id=tid,
            seller_id=seller_id,
            buyer_id=f"B-{rng.randint(1, 500):04d}",
            amount=amount,
            currency=currency,
            status=TransactionStatus.CAPTURED,
            created_at=captured_at - timedelta(minutes=rng.randint(1, 60)),
            captured_at=captured_at,
        ))

    # 2. Authorized (excluded from payouts — no captured_at)
    for _ in range(n_auth):
        seller_id = rng.choice(["S-001", "S-002", "S-003"])
        currency  = rng.choice(seller_currencies[seller_id])
        lo, hi    = amount_ranges[currency]
        amount    = Decimal(str(round(rng.uniform(lo, hi), 2)))
        store.add_transaction(Transaction(
            id=next_id("T"),
            seller_id=seller_id,
            buyer_id=f"B-{rng.randint(1, 500):04d}",
            amount=amount,
            currency=currency,
            status=TransactionStatus.AUTHORIZED,
            created_at=_rand_dt(rng),
        ))

    # 3. Refunds  (linked to a captured parent)
    parents_for_refund = rng.sample(captured_ids, min(n_ref, len(captured_ids)))
    for parent_id in parents_for_refund:
        parent = store.get_transaction(parent_id)
        assert parent is not None
        # refund can happen up to 14 days after capture (potentially outside Jan)
        refund_dt = parent.captured_at + timedelta(days=rng.randint(0, 14))
        store.add_transaction(Transaction(
            id=next_id("R"),
            seller_id=parent.seller_id,
            buyer_id=parent.buyer_id,
            amount=parent.amount,          # full refund
            currency=parent.currency,
            status=TransactionStatus.REFUNDED,
            created_at=refund_dt,
            parent_transaction_id=parent_id,
            description=f"Refund for {parent_id}",
        ))

    # 4. Chargebacks (linked to a different captured parent set)
    remaining_for_cb = [tid for tid in captured_ids if tid not in parents_for_refund]
    parents_for_cb = rng.sample(remaining_for_cb, min(n_cb, len(remaining_for_cb)))
    for parent_id in parents_for_cb:
        parent = store.get_transaction(parent_id)
        assert parent is not None
        cb_dt = parent.captured_at + timedelta(days=rng.randint(1, 21))
        store.add_transaction(Transaction(
            id=next_id("CB"),
            seller_id=parent.seller_id,
            buyer_id=parent.buyer_id,
            amount=parent.amount,
            currency=parent.currency,
            status=TransactionStatus.CHARGEBACK,
            created_at=cb_dt,
            parent_transaction_id=parent_id,
            description=f"Chargeback for {parent_id}",
        ))
