from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


API_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"


@dataclass(frozen=True)
class TInvestSnapshot:
    fetched_at: str
    account_id: str
    positions: list[dict[str, Any]]


class TInvestClient:
    def __init__(self, token: str | None, *, base_url: str = API_BASE_URL) -> None:
        self.token = token.strip() if token else ""
        self.base_url = base_url.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def fetch_portfolio_snapshot(self, account_id: str | None = None) -> TInvestSnapshot:
        if not self.token:
            raise RuntimeError("T_INVEST_TOKEN is not configured")

        selected_account_id = (account_id or "").strip() or self._default_account_id()
        portfolio = self._post("tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio", {"accountId": selected_account_id})
        positions = [
            self._normalize_position(item)
            for item in portfolio.get("positions", [])
            if self._is_bond_position(item)
        ]
        return TInvestSnapshot(
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            account_id=selected_account_id,
            positions=positions,
        )

    def _default_account_id(self) -> str:
        accounts_response = self._post("tinkoff.public.invest.api.contract.v1.UsersService/GetAccounts", {})
        accounts = accounts_response.get("accounts", [])
        open_accounts = [
            item
            for item in accounts
            if str(item.get("status") or "").upper().endswith("OPEN") or item.get("status") in {"ACCOUNT_STATUS_OPEN", 2}
        ]
        candidates = open_accounts or accounts
        if not candidates:
            raise RuntimeError("T-Invest account not found")
        return str(candidates[0].get("id") or "").strip()

    def _normalize_position(self, item: dict[str, Any]) -> dict[str, Any]:
        instrument_uid = str(item.get("instrumentUid") or item.get("instrument_uid") or "").strip()
        bond = self._fetch_bond(instrument_uid) if instrument_uid else {}
        current_price = money_to_float(item.get("currentPrice") or item.get("current_price"))
        quantity = quotation_to_float(item.get("quantity"))
        position_sum = current_price * quantity if current_price is not None and quantity is not None else None
        return {
            "figi": item.get("figi"),
            "instrument_uid": instrument_uid or None,
            "position_uid": item.get("positionUid") or item.get("position_uid"),
            "isin": bond.get("isin") or item.get("isin"),
            "name": bond.get("name") or item.get("name") or item.get("ticker") or item.get("figi") or "Облигация",
            "ticker": bond.get("ticker") or item.get("ticker"),
            "quantity": quantity,
            "current_price": current_price,
            "average_price": money_to_float(item.get("averagePositionPrice") or item.get("average_position_price")),
            "current_nkd": money_to_float(item.get("currentNkd") or item.get("current_nkd")),
            "expected_yield": money_to_float(item.get("expectedYield") or item.get("expected_yield")),
            "daily_yield": money_to_float(item.get("dailyYield") or item.get("daily_yield")),
            "position_sum": position_sum,
            "currency": money_currency(item.get("currentPrice") or item.get("current_price")) or bond.get("currency"),
            "maturity_date": normalize_date(bond.get("maturityDate") or bond.get("maturity_date")),
            "rating": None,
        }

    def _fetch_bond(self, instrument_uid: str) -> dict[str, Any]:
        response = self._post(
            "tinkoff.public.invest.api.contract.v1.InstrumentsService/BondBy",
            {"idType": "INSTRUMENT_ID_TYPE_UID", "id": instrument_uid},
        )
        return response.get("instrument", {}) or {}

    @staticmethod
    def _is_bond_position(item: dict[str, Any]) -> bool:
        instrument_type = str(item.get("instrumentType") or item.get("instrument_type") or "").lower()
        return instrument_type in {"bond", "instrument_type_bond"}

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        with httpx.Client(timeout=20.0) as client:
            response = client.post(f"{self.base_url}/{method}", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()


def quotation_to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    units = value.get("units", 0)
    nano = value.get("nano", 0)
    try:
        return float(units) + float(nano) / 1_000_000_000
    except (TypeError, ValueError):
        return None


def money_to_float(value: Any) -> float | None:
    return quotation_to_float(value)


def money_currency(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("currency")
    return None


def normalize_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10] if len(text) >= 10 else text
