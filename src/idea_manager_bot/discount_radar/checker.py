from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from idea_manager_bot.discount_radar.formatter import discounted_products
from idea_manager_bot.discount_radar.parser_ozon import OzonParser
from idea_manager_bot.discount_radar.store import DiscountRadarStore, Product


class ProductSnapshot(Protocol):
    status: str
    title: str | None
    price: int | None
    error: str | None

    @property
    def ok(self) -> bool: ...


class ProductParser(Protocol):
    def fetch(self, url: str) -> ProductSnapshot: ...


@dataclass(frozen=True)
class DiscountCheckNotification:
    user_id: int
    products: list[Product]


@dataclass(frozen=True)
class ScheduledCheckReport:
    users_checked: int
    products_checked: int
    discounted_products: int
    products_with_errors: int
    notifications: list[DiscountCheckNotification]


def run_price_checks(
    store: DiscountRadarStore,
    *,
    user_id: int,
    parser: ProductParser | None = None,
) -> list[Product]:
    parser = parser or OzonParser()
    products = store.list_products(user_id)
    checked_products: list[Product] = []
    for product in products:
        snapshot = parser.fetch(product.url)
        if snapshot.ok:
            updated = store.update_check_result(
                user_id=user_id,
                product_id=product.id,
                price=snapshot.price,
                error=None,
                title=snapshot.title,
            )
        else:
            updated = store.update_check_result(
                user_id=user_id,
                product_id=product.id,
                price=None,
                error=snapshot.error or snapshot.status,
                title=snapshot.title,
            )
        checked_products.append(updated or product)
    return checked_products


def run_scheduled_checks(
    store: DiscountRadarStore,
    *,
    parser: ProductParser | None = None,
) -> list[DiscountCheckNotification]:
    return run_scheduled_check_report(store, parser=parser).notifications


def run_scheduled_check_report(
    store: DiscountRadarStore,
    *,
    parser: ProductParser | None = None,
) -> ScheduledCheckReport:
    notifications: list[DiscountCheckNotification] = []
    users_checked = 0
    products_checked = 0
    discounted_products_count = 0
    products_with_errors = 0
    for user_id in store.list_user_ids():
        users_checked += 1
        checked_products = run_price_checks(store, user_id=user_id, parser=parser)
        products_checked += len(checked_products)
        products_with_errors += sum(1 for product in checked_products if product.last_error)
        discounted = discounted_products(checked_products)
        discounted_products_count += len(discounted)
        if discounted:
            notifications.append(
                DiscountCheckNotification(user_id=user_id, products=discounted)
            )
    return ScheduledCheckReport(
        users_checked=users_checked,
        products_checked=products_checked,
        discounted_products=discounted_products_count,
        products_with_errors=products_with_errors,
        notifications=notifications,
    )
