from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any
from urllib.parse import urljoin

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class PmaOpsError(RuntimeError):
    pass


class PmaOpsBridge:
    """Thin signed client for the independent funded-tennis recovery API."""

    def __init__(
        self,
        api_base: str | None,
        hmac_secret: str | None,
        *,
        timeout_seconds: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_base = (api_base or "").rstrip("/") + "/" if api_base else ""
        self.hmac_secret = hmac_secret or ""
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.api_base and len(self.hmac_secret) >= 32)

    def handle_action(self, action: str, *, actor_id: int) -> dict[str, Any]:
        if not self.configured:
            return self._error_screen(
                "PMA recovery API пока не настроен.",
                include_retry=False,
            )
        try:
            if action in {"pma:home", "pma:status", "pma:test"}:
                return self._status_screen(
                    self._request("GET", "/v1/recovery/status")
                )
            if action == "pma:restart":
                payload = self._request(
                    "POST",
                    "/v1/recovery/restart/request",
                    {"actor_id": str(actor_id)},
                )
                result = payload.get("result")
                result = result if isinstance(result, dict) else {}
                return self._confirmation_screen(str(result.get("expires_at") or ""))
            if action == "pma:confirm_restart":
                self._request(
                    "POST",
                    "/v1/recovery/restart/confirm",
                    {"actor_id": str(actor_id)},
                )
                return {
                    "text": (
                        "✅ Railway принял команду перезапуска funded-tennis.\n"
                        "Recovery-сервис остаётся доступным. Через 30 секунд нажмите «🩺 Тест системы»."
                    ),
                    "buttons": [
                        [{"text": "🩺 Тест системы", "callback_data": "pma:test"}],
                        [{"text": "Главное меню", "callback_data": "main:home"}],
                    ],
                }
            if action == "pma:cancel_restart":
                self._request(
                    "POST",
                    "/v1/recovery/restart/cancel",
                    {"actor_id": str(actor_id)},
                )
                return {
                    "text": "Перезапуск отменён. Бот ничего не изменил.",
                    "buttons": [
                        [{"text": "🩺 Тест системы", "callback_data": "pma:test"}],
                        [{"text": "Главное меню", "callback_data": "main:home"}],
                    ],
                }
            return self.handle_action("pma:home", actor_id=actor_id)
        except PmaOpsError as exc:
            return self._error_screen(str(exc))

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if payload is not None
            else b""
        )
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(18)
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(
            [timestamp, nonce, method.upper(), path, body_hash]
        ).encode("utf-8")
        signature = hmac.new(
            self.hmac_secret.encode("utf-8"),
            canonical,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-PMA-Timestamp": timestamp,
            "X-PMA-Nonce": nonce,
            "X-PMA-Signature": signature,
            "Content-Type": "application/json",
            "User-Agent": "idea-manager-pma-recovery/1.0",
        }
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.request(
                    method,
                    urljoin(self.api_base, path.lstrip("/")),
                    content=body,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise PmaOpsError(f"PMA recovery API недоступен: {type(exc).__name__}") from exc
        try:
            response_payload = response.json()
        except ValueError as exc:
            raise PmaOpsError("PMA recovery API вернул некорректный ответ.") from exc
        if not isinstance(response_payload, dict):
            raise PmaOpsError("PMA recovery API вернул некорректный ответ.")
        if response.status_code >= 400 or response_payload.get("ok") is not True:
            message = str(
                response_payload.get("message")
                or "Операция заблокирована защитным контуром."
            )
            raise PmaOpsError(message)
        return response_payload

    @staticmethod
    def _status_screen(payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or "Статус PMA недоступен.")
        return {
            "text": text,
            "buttons": [
                [
                    {"text": "🩺 Тест системы", "callback_data": "pma:test"},
                    {"text": "🔄 Перезапустить", "callback_data": "pma:restart"},
                ],
                [{"text": "Главное меню", "callback_data": "main:home"}],
            ],
        }

    @staticmethod
    def _confirmation_screen(expires_at: str) -> dict[str, Any]:
        return {
            "text": (
                "⚠️ Подтвердить перезапуск funded-tennis?\n\n"
                "Непосредственно перед командой recovery-сервис заново проверит emergency, "
                "активную отправку ордера, журнал, settlement и Railway.\n"
                f"Подтверждение действует до: {expires_at or 'неизвестно'}"
            ),
            "buttons": [
                [
                    {"text": "✅ Подтвердить рестарт", "callback_data": "pma:confirm_restart"},
                    {"text": "❌ Отмена", "callback_data": "pma:cancel_restart"},
                ],
                [{"text": "Назад", "callback_data": "pma:status"}],
            ],
        }

    @staticmethod
    def _error_screen(message: str, *, include_retry: bool = True) -> dict[str, Any]:
        buttons = []
        if include_retry:
            buttons.append([{"text": "🩺 Повторить тест", "callback_data": "pma:test"}])
        buttons.append([{"text": "Главное меню", "callback_data": "main:home"}])
        return {"text": message, "buttons": buttons}

    @staticmethod
    def inline_keyboard(buttons: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        item["text"],
                        callback_data=item.get("callback_data"),
                    )
                    for item in row
                ]
                for row in buttons
            ]
        )
