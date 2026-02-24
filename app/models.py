from pydantic import BaseModel
from enum import Enum
from datetime import datetime
from decimal import Decimal
from typing import Optional


class Currency(str, Enum):
    IDR = "IDR"
    THB = "THB"
    VND = "VND"


class TransactionStatus(str, Enum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    CHARGEBACK = "chargeback"


class Seller(BaseModel):
    id: str
    name: str
    commission_rate: Decimal  # e.g. Decimal("0.08") for 8%
    settlement_currency: Currency
    country: str
    email: str


class Transaction(BaseModel):
    id: str
    seller_id: str
    buyer_id: str
    amount: Decimal
    currency: Currency
    status: TransactionStatus
    created_at: datetime
    captured_at: Optional[datetime] = None
    parent_transaction_id: Optional[str] = None  # for refunds / chargebacks
    description: Optional[str] = None


# ── Response models ──────────────────────────────────────────────────────────

class RefundDetail(BaseModel):
    refund_id: str
    amount: Decimal
    currency: Currency
    status: str
    date: datetime


class TransactionLineItem(BaseModel):
    transaction_id: str
    captured_at: datetime
    original_amount: Decimal
    original_currency: Currency
    # gross in settlement currency (before refunds / commission)
    converted_gross: Decimal
    exchange_rate: Decimal
    # refund info
    refunds: list[RefundDetail]
    total_refunded_converted: Decimal
    # after deducting refunds
    gross_after_refunds: Decimal
    # commission
    commission_rate: Decimal
    commission_amount: Decimal
    # final
    net_payout: Decimal


class PayoutSummary(BaseModel):
    seller_id: str
    seller_name: str
    commission_rate: Decimal
    period_start: str
    period_end: str
    settlement_currency: Currency
    gross_volume: Decimal
    commission_deducted: Decimal
    refunds_deducted: Decimal
    net_payout: Decimal
    transaction_count: int
    refund_count: int
    breakdown: list[TransactionLineItem]
