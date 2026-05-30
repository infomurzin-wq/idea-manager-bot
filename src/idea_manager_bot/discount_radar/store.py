from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class Product:
    id: str
    user_id: int
    url: str
    reference_price: int
    title: str | None
    last_price: int | None
    last_checked_at: str | None
    last_error: str | None
    is_active: bool
    created_at: str
    updated_at: str


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class DiscountRadarStore:
    def __init__(self, store_path: Path) -> None:
        self.store_path = store_path

    def list_products(self, user_id: int) -> list[Product]:
        return [
            product
            for product in self._load()
            if product.user_id == user_id and product.is_active
        ]

    def get_product(self, *, user_id: int, product_id: str) -> Product | None:
        for product in self._load():
            if product.user_id == user_id and product.id == product_id and product.is_active:
                return product
        return None

    def add_product(
        self,
        *,
        user_id: int,
        url: str,
        reference_price: int,
        title: str | None = None,
        last_price: int | None = None,
    ) -> Product:
        products = self._load()
        now = utc_now_iso()
        for index, product in enumerate(products):
            if product.user_id == user_id and product.url == url:
                updated = Product(
                    id=product.id,
                    user_id=product.user_id,
                    url=product.url,
                    reference_price=reference_price,
                    title=title or product.title,
                    last_price=last_price if last_price is not None else product.last_price,
                    last_checked_at=product.last_checked_at,
                    last_error=None,
                    is_active=True,
                    created_at=product.created_at,
                    updated_at=now,
                )
                products[index] = updated
                self._save(products)
                return updated

        product = Product(
            id=uuid4().hex[:10],
            user_id=user_id,
            url=url,
            reference_price=reference_price,
            title=title,
            last_price=last_price,
            last_checked_at=None,
            last_error=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        products.append(product)
        self._save(products)
        return product

    def delete_product(self, *, user_id: int, product_id: str) -> bool:
        products = self._load()
        changed = False
        now = utc_now_iso()
        updated_products: list[Product] = []
        for product in products:
            if product.user_id == user_id and product.id == product_id and product.is_active:
                updated_products.append(
                    Product(
                        id=product.id,
                        user_id=product.user_id,
                        url=product.url,
                        reference_price=product.reference_price,
                        title=product.title,
                        last_price=product.last_price,
                        last_checked_at=product.last_checked_at,
                        last_error=product.last_error,
                        is_active=False,
                        created_at=product.created_at,
                        updated_at=now,
                    )
                )
                changed = True
            else:
                updated_products.append(product)

        if changed:
            self._save(updated_products)
        return changed

    def update_reference_price(
        self,
        *,
        user_id: int,
        product_id: str,
        reference_price: int,
    ) -> Product | None:
        products = self._load()
        now = utc_now_iso()
        for index, product in enumerate(products):
            if product.user_id == user_id and product.id == product_id and product.is_active:
                updated = Product(
                    id=product.id,
                    user_id=product.user_id,
                    url=product.url,
                    reference_price=reference_price,
                    title=product.title,
                    last_price=product.last_price,
                    last_checked_at=product.last_checked_at,
                    last_error=product.last_error,
                    is_active=product.is_active,
                    created_at=product.created_at,
                    updated_at=now,
                )
                products[index] = updated
                self._save(products)
                return updated
        return None

    def update_check_result(
        self,
        *,
        user_id: int,
        product_id: str,
        price: int | None,
        error: str | None,
        title: str | None = None,
    ) -> Product | None:
        products = self._load()
        now = utc_now_iso()
        for index, product in enumerate(products):
            if product.user_id == user_id and product.id == product_id and product.is_active:
                updated = Product(
                    id=product.id,
                    user_id=product.user_id,
                    url=product.url,
                    reference_price=product.reference_price,
                    title=title or product.title,
                    last_price=price if price is not None else product.last_price,
                    last_checked_at=now,
                    last_error=error,
                    is_active=product.is_active,
                    created_at=product.created_at,
                    updated_at=now,
                )
                products[index] = updated
                self._save(products)
                return updated
        return None

    def _load(self) -> list[Product]:
        if not self.store_path.exists():
            return []
        payload = json.loads(self.store_path.read_text(encoding="utf-8"))
        return [self._product_from_payload(item) for item in payload.get("products", [])]

    def _save(self, products: list[Product]) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"products": [asdict(product) for product in products]}
        self.store_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _product_from_payload(item: dict) -> Product:
        # Compatibility with the first deployed MVP, where the baseline price
        # was named target_price before the product rule was clarified.
        if "reference_price" not in item and "target_price" in item:
            item = {**item, "reference_price": item["target_price"]}
        item = {key: value for key, value in item.items() if key != "target_price"}
        return Product(**item)
