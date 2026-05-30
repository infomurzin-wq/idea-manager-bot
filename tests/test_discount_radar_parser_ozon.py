from __future__ import annotations

import unittest

from idea_manager_bot.discount_radar.parser_ozon import (
    OzonParser,
    normalize_price,
    parse_ozon_html,
)


class OzonParserTest(unittest.TestCase):
    def test_parses_json_ld_product_snapshot(self) -> None:
        html = """
        <html>
          <head>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Кофе в зернах тестовый",
                "offers": {
                  "@type": "Offer",
                  "price": "1490.00",
                  "priceCurrency": "RUB"
                }
              }
            </script>
          </head>
        </html>
        """

        snapshot = parse_ozon_html(html, url="https://www.ozon.ru/product/test")

        self.assertTrue(snapshot.ok)
        self.assertEqual("Кофе в зернах тестовый", snapshot.title)
        self.assertEqual(1490, snapshot.price)
        self.assertIsNone(snapshot.error)

    def test_parses_meta_price_and_title(self) -> None:
        html = """
        <html>
          <head>
            <meta property="og:title" content="Фильтр для воды | OZON">
            <meta property="product:price:amount" content="2 390">
          </head>
        </html>
        """

        snapshot = parse_ozon_html(html, url="https://www.ozon.ru/product/test")

        self.assertTrue(snapshot.ok)
        self.assertEqual("Фильтр для воды", snapshot.title)
        self.assertEqual(2390, snapshot.price)

    def test_returns_clear_error_when_price_is_missing(self) -> None:
        html = """
        <html>
          <head><meta property="og:title" content="Товар без цены"></head>
          <body>Описание товара</body>
        </html>
        """

        snapshot = parse_ozon_html(html, url="https://www.ozon.ru/product/test")

        self.assertFalse(snapshot.ok)
        self.assertEqual("price_not_found", snapshot.status)
        self.assertEqual("Товар без цены", snapshot.title)
        self.assertIn("Не удалось найти цену", snapshot.error or "")

    def test_detects_blocked_page(self) -> None:
        html = "<html><body>Подтвердите, что вы не робот. CAPTCHA</body></html>"

        snapshot = parse_ozon_html(html, url="https://www.ozon.ru/product/test")

        self.assertFalse(snapshot.ok)
        self.assertEqual("blocked", snapshot.status)
        self.assertIn("капчу", snapshot.error or "")

    def test_normalizes_price_formats(self) -> None:
        self.assertEqual(1490, normalize_price("1 490 ₽"))
        self.assertEqual(1490, normalize_price("1490.00"))
        self.assertEqual(1490, normalize_price("1490,00"))
        self.assertEqual(2390, normalize_price(2390))
        self.assertIsNone(normalize_price("нет цены"))
        self.assertIsNone(normalize_price(0))

    def test_rejects_non_ozon_url_before_fetch(self) -> None:
        snapshot = OzonParser().fetch("https://example.com/product/test")

        self.assertFalse(snapshot.ok)
        self.assertEqual("invalid_url", snapshot.status)
        self.assertIn("не похоже", snapshot.error or "")


if __name__ == "__main__":
    unittest.main()
