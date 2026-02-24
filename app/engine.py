from decimal import Decimal
from datetime import date

from app.models import (
    Currency,
    TransactionStatus,
    TransactionLineItem,
    RefundDetail,
    FraudFlag,
    PayoutSummary,
)
from app.store import DataStore
from app.currency import convert

_ZERO = Decimal("0.00")


def _detect_fraud(captured: list, refund_map: dict, seller) -> list[FraudFlag]:
    flags = []
    amounts = [float(t.amount) for t in captured]
    if not amounts:
        return flags
    avg = sum(amounts) / len(amounts)

    for txn in captured:
        # Flag transactions > 3x the seller's average in this period
        if float(txn.amount) > avg * 3:
            flags.append(FraudFlag(
                transaction_id=txn.id,
                reason=f"Amount {txn.amount} {txn.currency} is {txn.amount / Decimal(str(avg)):.1f}x the period average",
                severity="high" if float(txn.amount) > avg * 5 else "medium",
            ))

    # Flag if refund rate > 30%
    refunded_count = sum(1 for v in refund_map.values() if v)
    if len(captured) > 0 and refunded_count / len(captured) > 0.30:
        flags.append(FraudFlag(
            transaction_id="SELLER",
            reason=f"High refund rate: {refunded_count}/{len(captured)} transactions refunded ({refunded_count/len(captured)*100:.0f}%)",
            severity="medium",
        ))

    return flags


def calculate_payout(
    seller_id: str,
    start_date: date,
    end_date: date,
    store: DataStore,
) -> PayoutSummary:
    seller = store.get_seller(seller_id)
    if seller is None:
        raise ValueError(f"Seller '{seller_id}' not found")

    all_txns = store.get_transactions_for_seller(seller_id)

    # ── 1. Captured transactions inside the requested window ─────────────────
    captured = [
        t for t in all_txns
        if t.status == TransactionStatus.CAPTURED
        and t.captured_at is not None
        and start_date <= t.captured_at.date() <= end_date
    ]

    # ── 2. All refunds / chargebacks that reference those transactions ────────
    #       (regardless of when the refund happened)
    captured_ids = {t.id for t in captured}
    refund_map: dict[str, list] = {tid: [] for tid in captured_ids}

    for t in all_txns:
        if (
            t.status in (TransactionStatus.REFUNDED, TransactionStatus.CHARGEBACK)
            and t.parent_transaction_id in captured_ids
        ):
            refund_map[t.parent_transaction_id].append(t)

    # ── 3. Build line items ──────────────────────────────────────────────────
    line_items: list[TransactionLineItem] = []
    sc = seller.settlement_currency  # shorthand

    for txn in sorted(captured, key=lambda t: t.captured_at):
        linked = refund_map.get(txn.id, [])

        # amounts in original currency
        total_refunded_orig = sum((r.amount for r in linked), Decimal("0"))
        net_after_refunds_orig = max(Decimal("0"), txn.amount - total_refunded_orig)

        # commission applied on the net-after-refunds amount
        commission_orig = (net_after_refunds_orig * seller.commission_rate).quantize(Decimal("0.01"))
        net_orig = net_after_refunds_orig - commission_orig

        # convert each component to settlement currency
        converted_gross, ex_rate = convert(txn.amount, txn.currency, sc)
        converted_refunds, _ = convert(total_refunded_orig, txn.currency, sc)
        converted_commission, _ = convert(commission_orig, txn.currency, sc)
        converted_net, _ = convert(net_orig, txn.currency, sc)
        gross_after_refunds = max(Decimal("0"), converted_gross - converted_refunds)

        refund_details = [
            RefundDetail(
                refund_id=r.id,
                amount=r.amount,
                currency=r.currency,
                status=r.status.value,
                date=r.created_at,
            )
            for r in linked
        ]

        line_items.append(
            TransactionLineItem(
                transaction_id=txn.id,
                captured_at=txn.captured_at,
                original_amount=txn.amount,
                original_currency=txn.currency,
                converted_gross=converted_gross,
                exchange_rate=ex_rate,
                refunds=refund_details,
                total_refunded_converted=converted_refunds,
                gross_after_refunds=gross_after_refunds,
                commission_rate=seller.commission_rate,
                commission_amount=converted_commission,
                net_payout=converted_net,
            )
        )

    # ── 4. Aggregate ─────────────────────────────────────────────────────────
    two_dp = Decimal("0.01")

    total_gross      = sum((i.converted_gross          for i in line_items), _ZERO).quantize(two_dp)
    total_commission = sum((i.commission_amount         for i in line_items), _ZERO).quantize(two_dp)
    total_refunds    = sum((i.total_refunded_converted  for i in line_items), _ZERO).quantize(two_dp)
    total_net        = sum((i.net_payout                for i in line_items), _ZERO).quantize(two_dp)
    refund_count     = sum(len(i.refunds)               for i in line_items)

    return PayoutSummary(
        seller_id=seller_id,
        seller_name=seller.name,
        commission_rate=seller.commission_rate,
        period_start=str(start_date),
        period_end=str(end_date),
        settlement_currency=sc,
        gross_volume=total_gross,
        commission_deducted=total_commission,
        refunds_deducted=total_refunds,
        net_payout=total_net,
        transaction_count=len(captured),
        refund_count=refund_count,
        fraud_flags=_detect_fraud(captured, refund_map, seller),
        breakdown=line_items,
    )
