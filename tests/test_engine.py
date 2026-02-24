"""
Unit tests for the payout calculation engine.
"""

from decimal import Decimal
from datetime import datetime, date

import pytest

from app.models import Currency, Seller, Transaction, TransactionStatus
from app.store import DataStore
from app.engine import calculate_payout


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_store() -> DataStore:
    s = DataStore()
    s.add_seller(Seller(
        id="S-001",
        name="Test Seller IDR",
        commission_rate=Decimal("0.10"),
        settlement_currency=Currency.IDR,
        country="Indonesia",
        email="test@example.com",
    ))
    return s


def txn(id, seller, amount, currency, status, captured_at=None, parent=None):
    return Transaction(
        id=id,
        seller_id=seller,
        buyer_id="B-001",
        amount=Decimal(str(amount)),
        currency=currency,
        status=status,
        created_at=datetime(2026, 1, 1, 10, 0, 0),
        captured_at=captured_at,
        parent_transaction_id=parent,
    )


JAN1  = datetime(2026, 1, 1, 12, 0)
JAN5  = datetime(2026, 1, 5, 12, 0)
JAN10 = datetime(2026, 1, 10, 12, 0)

RANGE_ALL  = (date(2026, 1, 1), date(2026, 1, 31))
RANGE_WEEK = (date(2026, 1, 1), date(2026, 1, 7))


# ── tests ─────────────────────────────────────────────────────────────────────

class TestBasicPayout:
    def test_single_captured_transaction(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        result = calculate_payout("S-001", *RANGE_ALL, store)

        assert result.transaction_count == 1
        assert result.refund_count == 0
        # 10 % commission → net = 900 000
        assert result.net_payout == Decimal("900000.00")
        assert result.commission_deducted == Decimal("100000.00")
        assert result.gross_volume == Decimal("1000000.00")

    def test_authorized_transaction_excluded(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.AUTHORIZED))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        assert result.transaction_count == 0
        assert result.net_payout == Decimal("0.00")

    def test_multiple_captured_transactions(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 500_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("T-002", "S-001", 500_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN5))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        assert result.transaction_count == 2
        assert result.gross_volume == Decimal("1000000.00")
        assert result.net_payout == Decimal("900000.00")

    def test_date_range_filtering(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("T-002", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN10))  # outside Jan 1-7
        result = calculate_payout("S-001", *RANGE_WEEK, store)
        assert result.transaction_count == 1
        assert result.gross_volume == Decimal("1000000.00")


class TestRefundHandling:
    def test_full_refund_zeroes_out_payout(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        # Refund happens on Jan 10 (outside the payout window, still must be applied)
        store.add_transaction(txn("R-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.REFUNDED, JAN10, parent="T-001"))
        result = calculate_payout("S-001", *RANGE_WEEK, store)
        assert result.net_payout == Decimal("0.00")
        assert result.commission_deducted == Decimal("0.00")
        assert result.refund_count == 1

    def test_chargeback_zeroes_out_payout(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 2_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("CB-001", "S-001", 2_000_000, Currency.IDR,
                                  TransactionStatus.CHARGEBACK, JAN10, parent="T-001"))
        result = calculate_payout("S-001", *RANGE_WEEK, store)
        assert result.net_payout == Decimal("0.00")

    def test_refund_outside_date_range_still_deducted(self):
        """A transaction captured in week 1 but refunded in week 2 must net to 0."""
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("R-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.REFUNDED,
                                  datetime(2026, 1, 20), parent="T-001"))
        # calculate week 1 payout — refund from week 3 must still apply
        result = calculate_payout("S-001", *RANGE_WEEK, store)
        assert result.net_payout == Decimal("0.00")

    def test_refund_does_not_affect_unrelated_transaction(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("T-002", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN5))
        store.add_transaction(txn("R-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.REFUNDED, JAN10, parent="T-001"))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        # only T-001 is zeroed; T-002 contributes 900 000
        assert result.net_payout == Decimal("900000.00")
        assert result.transaction_count == 2
        assert result.refund_count == 1


class TestMultiCurrency:
    def test_thb_to_idr_conversion(self):
        """S-001 settles in IDR; a THB transaction must be converted."""
        store = make_store()
        # 1 000 THB  * 440.99 = 440 990 IDR gross → commission 10 % → net 396 891 IDR
        store.add_transaction(txn("T-001", "S-001", 1_000, Currency.THB,
                                  TransactionStatus.CAPTURED, JAN1))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        assert result.settlement_currency == Currency.IDR
        assert result.gross_volume > Decimal("0")
        # spot-check: gross_volume should equal 1000 * 440.99 = 440990
        assert result.gross_volume == Decimal("440990.00")
        item = result.breakdown[0]
        assert item.exchange_rate == Decimal("440.99")
        assert item.original_currency == Currency.THB


class TestErrorHandling:
    def test_unknown_seller_raises(self):
        store = DataStore()
        with pytest.raises(ValueError, match="not found"):
            calculate_payout("UNKNOWN", *RANGE_ALL, store)

    def test_empty_date_range_returns_zero_payout(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN10))
        # date range before any transactions
        result = calculate_payout("S-001", date(2025, 1, 1), date(2025, 1, 7), store)
        assert result.net_payout == Decimal("0.00")
        assert result.transaction_count == 0


class TestBreakdownLineage:
    def test_breakdown_lists_refund_linked_to_parent(self):
        store = make_store()
        store.add_transaction(txn("T-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        store.add_transaction(txn("R-001", "S-001", 1_000_000, Currency.IDR,
                                  TransactionStatus.REFUNDED, JAN5, parent="T-001"))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        assert len(result.breakdown) == 1
        item = result.breakdown[0]
        assert len(item.refunds) == 1
        assert item.refunds[0].refund_id == "R-001"

    def test_breakdown_transaction_id_matches(self):
        store = make_store()
        store.add_transaction(txn("T-XYZ", "S-001", 500_000, Currency.IDR,
                                  TransactionStatus.CAPTURED, JAN1))
        result = calculate_payout("S-001", *RANGE_ALL, store)
        assert result.breakdown[0].transaction_id == "T-XYZ"
