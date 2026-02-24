from typing import Optional
from app.models import Seller, Transaction


class DataStore:
    def __init__(self) -> None:
        self.sellers: dict[str, Seller] = {}
        self.transactions: dict[str, Transaction] = {}

    # ── writes ────────────────────────────────────────────────────────────────

    def add_seller(self, seller: Seller) -> None:
        self.sellers[seller.id] = seller

    def add_transaction(self, txn: Transaction) -> None:
        self.transactions[txn.id] = txn

    def clear(self) -> None:
        self.sellers.clear()
        self.transactions.clear()

    # ── reads ─────────────────────────────────────────────────────────────────

    def get_seller(self, seller_id: str) -> Optional[Seller]:
        return self.sellers.get(seller_id)

    def get_transaction(self, txn_id: str) -> Optional[Transaction]:
        return self.transactions.get(txn_id)

    def list_sellers(self) -> list[Seller]:
        return list(self.sellers.values())

    def get_transactions_for_seller(self, seller_id: str) -> list[Transaction]:
        return [t for t in self.transactions.values() if t.seller_id == seller_id]


# module-level singleton used by the app
store = DataStore()
