from __future__ import annotations

from idea_manager_bot.discount_radar.store import Product


def format_price(price: int | None) -> str:
    if price is None:
        return "неизвестно"
    return f"{price:,}".replace(",", " ") + " ₽"


def format_home_screen(products: list[Product]) -> str:
    active_count = len(products)
    return (
        "Дисконт Радар\n\n"
        "Отслеживаем товары и целевые цены.\n"
        f"Активных товаров: {active_count}\n\n"
        "На первом этапе проверка Ozon ещё не подключена: "
        "сейчас собираем удобный список и сценарий добавления."
    )


def format_product_list(products: list[Product]) -> str:
    if not products:
        return "Дисконт Радар\n\nСписок пуст. Добавь первый товар."

    lines = ["Дисконт Радар\n", "Мои товары:"]
    for index, product in enumerate(products, start=1):
        title = product.title or "Без названия"
        lines.append(
            f"{index}. {title}\n"
            f"   цель: {format_price(product.target_price)}\n"
            f"   сейчас: {format_price(product.last_price)}\n"
            f"   ссылка: {product.url}"
        )
    return "\n\n".join(lines)


def format_check_screen(products: list[Product]) -> str:
    if not products:
        return "Дисконт Радар\n\nСписок пуст. Сначала добавь товар."

    lines = ["Дисконт Радар\n", "Проверка цен:"]
    for product in products:
        title = product.title or "Без названия"
        if product.last_price is None:
            status = "цена пока неизвестна"
        elif product.last_price <= product.target_price:
            status = "цена достигла цели"
        else:
            status = "пока выше цели"
        lines.append(f"- {title}: {status}")

    lines.append("\nРеальную проверку Ozon подключим отдельным этапом.")
    return "\n".join(lines)


def product_button_label(product: Product) -> str:
    title = product.title or product.url.replace("https://", "").replace("http://", "")
    return title[:48]

