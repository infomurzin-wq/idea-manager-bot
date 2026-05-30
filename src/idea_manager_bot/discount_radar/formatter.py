from __future__ import annotations

from idea_manager_bot.discount_radar.store import Product


def format_price(price: int | None) -> str:
    if price is None:
        return "неизвестно"
    return f"{price:,}".replace(",", " ") + " ₽"


def format_home_screen(products: list[Product]) -> str:
    active_count = len(products)
    return (
        "🛒 Дисконт Радар\n\n"
        "Отслеживаем товары и последнюю известную цену.\n"
        f"Активных товаров: {active_count}\n\n"
        "Нажми «Проверить цены», чтобы вручную обновить цены по сохранённым ссылкам."
    )


def format_product_list(products: list[Product]) -> str:
    if not products:
        return "🛒 Дисконт Радар\n\nСписок пуст. Добавь первый товар."

    lines = ["🛒 Дисконт Радар\n", "📦 Мои товары:"]
    for index, product in enumerate(products, start=1):
        title = product.title or "Без названия"
        lines.append(
            f"{index}. {title}\n"
            f"   последняя цена: {format_price(product.reference_price)}\n"
            f"   новая цена: {format_price(product.last_price)}\n"
            f"   ссылка: {product.url}"
        )
    return "\n\n".join(lines)


def format_product_detail(product: Product) -> str:
    title = product.title or "Без названия"
    last_checked = product.last_checked_at or "не проверялся"
    last_error = product.last_error or "нет"
    return (
        "🛒 Дисконт Радар\n\n"
        f"📦 {title}\n\n"
        f"Ссылка: {product.url}\n"
        f"Последняя известная цена: {format_price(product.reference_price)}\n"
        f"Новая найденная цена: {format_price(product.last_price)}\n"
        f"Последняя проверка: {last_checked}\n"
        f"Ошибка проверки: {last_error}"
    )


def format_check_screen(products: list[Product]) -> str:
    if not products:
        return "🛒 Дисконт Радар\n\nСписок пуст. Сначала добавь товар."

    lines = ["🛒 Дисконт Радар\n", "🔎 Проверка цен завершена:"]
    for product in products:
        title = product.title or "Без названия"
        if product.last_error:
            status = f"ошибка: {product.last_error}"
        elif product.last_price is None:
            status = "новая цена пока неизвестна"
        elif product.last_price < product.reference_price:
            discount = product.reference_price - product.last_price
            status = (
                f"подешевел на {format_price(discount)} "
                f"({format_price(product.reference_price)} → {format_price(product.last_price)})"
            )
        else:
            status = (
                f"не дешевле последней цены "
                f"({format_price(product.reference_price)} → {format_price(product.last_price)})"
            )
        lines.append(f"- {title}: {status}")

    return "\n".join(lines)


def product_button_label(product: Product) -> str:
    title = product.title or product.url.replace("https://", "").replace("http://", "")
    return title[:48]
