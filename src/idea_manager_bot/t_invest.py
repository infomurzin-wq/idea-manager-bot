from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


API_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"


@dataclass(frozen=True)
class TInvestSnapshot:
    fetched_at: str
    account_id: str
    positions: list[dict[str, Any]]


@dataclass(frozen=True)
class TInvestCashflowSnapshot:
    fetched_at: str
    account_id: str
    events: list[dict[str, Any]]


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

    def fetch_cashflow_snapshot(self, account_id: str | None = None, *, days: int = 92) -> TInvestCashflowSnapshot:
        if not self.token:
            raise RuntimeError("T_INVEST_TOKEN is not configured")

        selected_account_id = (account_id or "").strip() or self._default_account_id()
        portfolio = self._post("tinkoff.public.invest.api.contract.v1.OperationsService/GetPortfolio", {"accountId": selected_account_id})
        from_dt = datetime.now(UTC)
        to_dt = from_dt + timedelta(days=days)
        events: list[dict[str, Any]] = []
        for item in portfolio.get("positions", []):
            if not self._is_bond_position(item):
                continue
            instrument_uid = str(item.get("instrumentUid") or item.get("instrument_uid") or "").strip()
            bond = self._fetch_bond(instrument_uid) if instrument_uid else {}
            quantity = quotation_to_float(item.get("quantity")) or 0
            if quantity <= 0:
                continue
            figi = item.get("figi") or bond.get("figi")
            if not figi:
                continue
            name = bond.get("name") or item.get("name") or item.get("ticker") or item.get("figi") or "Облигация"
            currency = bond.get("currency") or money_currency(item.get("currentPrice") or item.get("current_price")) or "rub"
            events.extend(self._cashflow_coupon_events(figi, name, quantity, currency, from_dt, to_dt))
            principal_events = self._cashflow_principal_events(instrument_uid or figi, name, quantity, currency, from_dt, to_dt)
            if principal_events:
                events.extend(principal_events)
            else:
                maturity_event = self._cashflow_maturity_fallback(bond, name, quantity, currency, from_dt, to_dt)
                if maturity_event:
                    events.append(maturity_event)
        return TInvestCashflowSnapshot(
            fetched_at=from_dt.isoformat(timespec="seconds"),
            account_id=selected_account_id,
            events=sorted(events, key=lambda event: (event["date"], event["type"], event["name"])),
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
            "coupon_rate": self._fetch_coupon_rate(item, bond),
            "rating": None,
        }

    def _fetch_bond(self, instrument_uid: str) -> dict[str, Any]:
        response = self._post(
            "tinkoff.public.invest.api.contract.v1.InstrumentsService/BondBy",
            {"idType": "INSTRUMENT_ID_TYPE_UID", "id": instrument_uid},
        )
        return response.get("instrument", {}) or {}

    def _fetch_coupon_rate(self, item: dict[str, Any], bond: dict[str, Any]) -> float | None:
        nominal = money_to_float(bond.get("nominal"))
        if not nominal:
            return None
        try:
            coupons = self._fetch_bond_coupons(
                item.get("figi") or bond.get("figi"),
                datetime.now(UTC),
                datetime.now(UTC) + timedelta(days=370),
            )
        except httpx.HTTPError:
            return None

        if not coupons:
            return None
        coupon = coupons[0]
        coupon_payment = money_to_float(coupon.get("payOneBond") or coupon.get("pay_one_bond"))
        if coupon_payment is None:
            return None
        days = coupon_period_days(coupon)
        if days:
            return coupon_payment / nominal * (365 / days) * 100
        frequency = quotation_to_float(bond.get("couponQuantityPerYear") or bond.get("coupon_quantity_per_year"))
        if frequency:
            return coupon_payment / nominal * frequency * 100
        return None

    def _cashflow_coupon_events(
        self,
        figi: str,
        name: str,
        quantity: float,
        currency: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[dict[str, Any]]:
        try:
            coupons = self._fetch_bond_coupons(figi, from_dt, to_dt)
        except httpx.HTTPError:
            return []
        events: list[dict[str, Any]] = []
        for coupon in coupons:
            event_date = normalize_date(coupon.get("couponDate") or coupon.get("coupon_date") or coupon.get("date"))
            amount_per_bond = money_to_float(coupon.get("payOneBond") or coupon.get("pay_one_bond"))
            if not event_date or amount_per_bond is None:
                continue
            events.append(
                {
                    "date": event_date,
                    "type": "coupon",
                    "name": name,
                    "amount": amount_per_bond * quantity,
                    "currency": currency,
                }
            )
        return events

    def _cashflow_principal_events(
        self,
        instrument_id: str,
        name: str,
        quantity: float,
        currency: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> list[dict[str, Any]]:
        try:
            response = self._post(
                "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetBondEvents",
                {"instrumentId": instrument_id, "from": from_dt.isoformat(timespec="seconds"), "to": to_dt.isoformat(timespec="seconds")},
            )
        except httpx.HTTPError:
            return []
        raw_events = response.get("events", []) or response.get("bondEvents", []) or response.get("bond_events", [])
        events: list[dict[str, Any]] = []
        for item in raw_events:
            event_type = normalize_bond_event_type(item.get("eventType") or item.get("event_type") or item.get("type"))
            if event_type not in {"amortization", "maturity"}:
                continue
            event_date = normalize_date(item.get("eventDate") or item.get("event_date") or item.get("date"))
            amount_per_bond = money_to_float(
                item.get("payOneBond")
                or item.get("pay_one_bond")
                or item.get("amount")
                or item.get("value")
            )
            if not event_date or amount_per_bond is None:
                continue
            events.append(
                {
                    "date": event_date,
                    "type": event_type,
                    "name": name,
                    "amount": amount_per_bond * quantity,
                    "currency": currency,
                }
            )
        return events

    def _cashflow_maturity_fallback(
        self,
        bond: dict[str, Any],
        name: str,
        quantity: float,
        currency: str,
        from_dt: datetime,
        to_dt: datetime,
    ) -> dict[str, Any] | None:
        maturity_date = normalize_date(bond.get("maturityDate") or bond.get("maturity_date"))
        nominal = money_to_float(bond.get("nominal"))
        if not maturity_date or nominal is None:
            return None
        parsed = parse_datetime(f"{maturity_date}T00:00:00+00:00")
        if not parsed or not (from_dt.date() <= parsed.date() <= to_dt.date()):
            return None
        return {
            "date": maturity_date,
            "type": "maturity",
            "name": name,
            "amount": nominal * quantity,
            "currency": currency,
        }

    def _fetch_bond_coupons(self, figi: str | None, from_dt: datetime, to_dt: datetime) -> list[dict[str, Any]]:
        if not figi:
            return []
        response = self._post(
            "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetBondCoupons",
            {"figi": figi, "from": from_dt.isoformat(timespec="seconds"), "to": to_dt.isoformat(timespec="seconds")},
        )
        return response.get("events", []) or response.get("coupons", [])

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


def coupon_period_days(coupon: dict[str, Any]) -> int | None:
    start = parse_datetime(coupon.get("couponStartDate") or coupon.get("coupon_start_date"))
    end = parse_datetime(coupon.get("couponEndDate") or coupon.get("coupon_end_date"))
    if start and end:
        days = (end.date() - start.date()).days
        return days if days > 0 else None
    return None


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_bond_event_type(value: Any) -> str | None:
    text = str(value or "").upper()
    if "AMORT" in text or "AMORTIZATION" in text:
        return "amortization"
    if "MTY" in text or "MATURITY" in text or "REDEMPTION" in text:
        return "maturity"
    if "CPN" in text or "COUPON" in text:
        return "coupon"
    return None
