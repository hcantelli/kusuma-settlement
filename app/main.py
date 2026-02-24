from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query

from app.engine import calculate_payout
from app.store import store
from app.models import Seller, Transaction


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-seed on startup so the service is immediately usable
    from scripts.seed_data import seed
    seed(store)
    yield


app = FastAPI(
    title="Kusuma Settlement Service",
    version="1.0.0",
    description="Seller payout calculation engine for Kusuma Marketplace",
    lifespan=lifespan,
)


# ── Sellers ──────────────────────────────────────────────────────────────────

@app.get("/api/v1/sellers", summary="List all sellers")
def list_sellers():
    return {"sellers": [s.model_dump() for s in store.list_sellers()]}


@app.get("/api/v1/sellers/{seller_id}", summary="Get seller details")
def get_seller(seller_id: str):
    seller = store.get_seller(seller_id)
    if not seller:
        raise HTTPException(404, f"Seller '{seller_id}' not found")
    return seller.model_dump()


# ── Payouts ──────────────────────────────────────────────────────────────────

@app.get(
    "/api/v1/sellers/{seller_id}/payout",
    summary="Calculate payout for a seller and date range",
)
def get_payout(
    seller_id: str,
    start_date: date = Query(..., example="2026-01-01"),
    end_date:   date = Query(..., example="2026-01-07"),
):
    if start_date > end_date:
        raise HTTPException(400, "start_date must not be after end_date")
    try:
        result = calculate_payout(seller_id, start_date, end_date, store)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return result.model_dump()


@app.get(
    "/api/v1/payouts/pending",
    summary="List sellers with a positive pending payout",
)
def get_pending_payouts(
    as_of: date = Query(default=None, description="Calculate as of this date (defaults to today)"),
):
    cutoff = as_of or date.today()
    results = []
    for seller in store.list_sellers():
        try:
            payout = calculate_payout(seller.id, date(2025, 1, 1), cutoff, store)
            if payout.net_payout > 0:
                results.append({
                    "seller_id": seller.id,
                    "seller_name": seller.name,
                    "pending_amount": str(payout.net_payout),
                    "currency": payout.settlement_currency,
                    "transaction_count": payout.transaction_count,
                })
        except Exception:
            pass
    return {"pending_payouts": results}


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.post("/api/v1/admin/seed", summary="Re-seed test data")
def reseed():
    from scripts.seed_data import seed
    store.clear()
    seed(store)
    return {
        "status": "seeded",
        "sellers": len(store.sellers),
        "transactions": len(store.transactions),
    }
