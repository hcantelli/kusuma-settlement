from decimal import Decimal
from app.models import Currency

# Approximate real-world rates as of early 2026
# 1 unit of FROM → X units of TO
_RATES: dict[tuple[str, str], Decimal] = {
    ("IDR", "IDR"): Decimal("1"),
    ("IDR", "THB"): Decimal("0.002268"),
    ("IDR", "VND"): Decimal("1.5500"),
    ("THB", "IDR"): Decimal("440.99"),
    ("THB", "THB"): Decimal("1"),
    ("THB", "VND"): Decimal("683.50"),
    ("VND", "IDR"): Decimal("0.6452"),
    ("VND", "THB"): Decimal("0.001463"),
    ("VND", "VND"): Decimal("1"),
}


def get_rate(from_currency: Currency, to_currency: Currency) -> Decimal:
    key = (from_currency.value, to_currency.value)
    rate = _RATES.get(key)
    if rate is None:
        raise ValueError(f"No exchange rate for {from_currency} → {to_currency}")
    return rate


def convert(amount: Decimal, from_currency: Currency, to_currency: Currency) -> tuple[Decimal, Decimal]:
    """Return (converted_amount, rate). Amount is rounded to 2 dp."""
    rate = get_rate(from_currency, to_currency)
    return (amount * rate).quantize(Decimal("0.01")), rate
