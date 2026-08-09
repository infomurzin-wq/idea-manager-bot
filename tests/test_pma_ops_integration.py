from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from types import SimpleNamespace

import httpx

from idea_manager_bot.bot import IdeaManagerApp, MENU_PMA
from idea_manager_bot.pma_ops_bridge import PmaOpsBridge


SECRET = "pma-recovery-test-secret-" * 2


def verify_signature(request: httpx.Request) -> None:
    timestamp = request.headers["X-PMA-Timestamp"]
    nonce = request.headers["X-PMA-Nonce"]
    body = request.content
    canonical = "\n".join(
        [
            timestamp,
            nonce,
            request.method,
            request.url.path,
            hashlib.sha256(body).hexdigest(),
        ]
    ).encode("utf-8")
    expected = hmac.new(SECRET.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers["X-PMA-Signature"]):
        raise AssertionError("invalid PMA request signature")
    if abs(int(time.time()) - int(timestamp)) > 30:
        raise AssertionError("stale timestamp")


class PmaOpsBridgeTests(unittest.TestCase):
    def test_status_screen_has_test_and_restart(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            verify_signature(request)
            self.assertEqual(request.url.path, "/v1/recovery/status")
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "text": "🩺 Проверка funded-tennis\n✅ Система работает.",
                    "snapshot": {"diagnosis": "HEALTHY", "places_orders": False},
                },
            )

        bridge = PmaOpsBridge(
            "https://recovery.example",
            SECRET,
            transport=httpx.MockTransport(handler),
        )
        screen = bridge.handle_action("pma:test", actor_id=42)
        callbacks = {
            item["callback_data"]
            for row in screen["buttons"]
            for item in row
            if item.get("callback_data")
        }

        self.assertIn("Система работает", screen["text"])
        self.assertIn("pma:test", callbacks)
        self.assertIn("pma:restart", callbacks)

    def test_restart_requires_second_button(self) -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            verify_signature(request)
            paths.append(request.url.path)
            payload = json.loads(request.content.decode("utf-8"))
            self.assertEqual(payload["actor_id"], "42")
            if request.url.path.endswith("/request"):
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {"expires_at": "2026-08-09T20:00:00Z"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"status": "REQUESTED"},
                },
            )

        bridge = PmaOpsBridge(
            "https://recovery.example",
            SECRET,
            transport=httpx.MockTransport(handler),
        )
        confirmation = bridge.handle_action("pma:restart", actor_id=42)
        callbacks = {
            item["callback_data"]
            for row in confirmation["buttons"]
            for item in row
        }
        self.assertIn("pma:confirm_restart", callbacks)
        self.assertEqual(paths, ["/v1/recovery/restart/request"])

        result = bridge.handle_action("pma:confirm_restart", actor_id=42)
        self.assertIn("принял команду", result["text"])
        self.assertEqual(
            paths,
            [
                "/v1/recovery/restart/request",
                "/v1/recovery/restart/confirm",
            ],
        )

    def test_protective_error_is_shown_without_raw_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            verify_signature(request)
            return httpx.Response(
                409,
                json={
                    "ok": False,
                    "error": "restart_blocked:restart_not_required",
                    "message": "Система работает штатно; перезапуск не требуется.",
                },
            )

        bridge = PmaOpsBridge(
            "https://recovery.example",
            SECRET,
            transport=httpx.MockTransport(handler),
        )
        screen = bridge.handle_action("pma:restart", actor_id=42)
        self.assertEqual(
            screen["text"],
            "Система работает штатно; перезапуск не требуется.",
        )


class IdeaManagerPmaMenuTests(unittest.TestCase):
    def test_main_menu_contains_pma_section(self) -> None:
        labels = {
            button.text
            for row in IdeaManagerApp._main_menu().keyboard
            for button in row
        }
        self.assertIn(MENU_PMA, labels)

    def test_pma_authorization_requires_exact_private_user_and_chat(self) -> None:
        app = object.__new__(IdeaManagerApp)
        app.settings = SimpleNamespace(
            pma_operator_user_id=42,
            pma_operator_chat_id=42,
        )
        allowed = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42, type="private"),
        )
        wrong_user = SimpleNamespace(
            effective_user=SimpleNamespace(id=43),
            effective_chat=SimpleNamespace(id=42, type="private"),
        )
        group = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=42, type="group"),
        )

        self.assertTrue(app._pma_authorized(allowed))
        self.assertFalse(app._pma_authorized(wrong_user))
        self.assertFalse(app._pma_authorized(group))


if __name__ == "__main__":
    unittest.main()
