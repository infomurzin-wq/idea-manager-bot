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
        "На первом этапе проверка Ozon ещё не подключена: "
        "сейчас собираем удобный список и сценарий добавления."
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


def format_check_screen(products: list[Product]) -> str:
    if not products:
        return "🛒 Дисконт Радар\n\nСписок пуст. Сначала добавь товар."

    lines = ["🛒 Дисконт Радар\n", "🔎 Проверка цен:"]
    for product in products:
        title = product.title or "Без названия"
        if product.last_price is None:
            status = "новая цена пока неизвестна"
        elif product.last_price < product.reference_price:
            status = "подешевел"
        else:
            status = "не дешевле последней цены"
        lines.append(f"- {title}: {status}")

    lines.append("\nРеальную проверку Ozon подключим отдельным этапом.")
    return "\n".join(lines)


def product_button_label(product: Product) -> str:
    title = product.title or product.url.replace("https://", "").replace("http://", "")
    return title[:48]
