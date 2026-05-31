"""Тесты для архитектурного рефакторинга stage14:

- watchlist_service, alerts_service, calendar_service
- tax_service, risk_service (smoke + edge cases)
- telegram_bot blueprint (webhook flows)
- domain exceptions
- health_service
"""
import os
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

os.environ["FLASK_TESTING"] = "1"

from tests.test_app import BaseTest, app, db  # noqa: E402


# ── Domain exceptions ─────────────────────────────────────────────────────────


class DomainExceptionsTests(BaseTest):
    def test_to_dict_basic(self):
        from app.exceptions import NotFoundError

        exc = NotFoundError("missing")
        d = exc.to_dict()
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["code"], "not_found")
        self.assertEqual(d["message"], "missing")
        self.assertEqual(exc.http_status, 404)

    def test_with_details(self):
        from app.exceptions import DomainValidationError

        exc = DomainValidationError("bad", details={"field": "isin"})
        self.assertEqual(exc.to_dict()["details"]["field"], "isin")

    def test_auth_is_external(self):
        from app.exceptions import AuthError, ExternalServiceError

        self.assertTrue(issubclass(AuthError, ExternalServiceError))
        self.assertEqual(AuthError("x").http_status, 401)


# ── Watchlist service ─────────────────────────────────────────────────────────


class WatchlistServiceTests(BaseTest):
    def test_add_then_list(self):
        from app.services import watchlist_service

        with app.app_context():
            uid = self._make_user()
            with patch("app.services.watchlist_service.get_bond_cached", return_value={"price": 1000}):
                watchlist_service.add_item(uid, "RU000A100YG1", "SU26238", "ОФЗ 26238")
                items = watchlist_service.list_items(uid)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["isin"], "RU000A100YG1")
            self.assertEqual(items[0]["price"], 1000)

    def test_duplicate_raises_conflict(self):
        from app.exceptions import ConflictError
        from app.services import watchlist_service

        with app.app_context():
            uid = self._make_user()
            watchlist_service.add_item(uid, "RU000A100YG1", "X", "X")
            with self.assertRaises(ConflictError):
                watchlist_service.add_item(uid, "RU000A100YG1", "X", "X")

    def test_remove_not_found_raises(self):
        from app.exceptions import NotFoundError
        from app.services import watchlist_service

        with app.app_context():
            uid = self._make_user()
            with self.assertRaises(NotFoundError):
                watchlist_service.remove_item(uid, "RU000A100YG1")

    def test_legacy_facade_preserved(self):
        # Старые вызовы из portfolio_service должны вернуть прежние типы
        from app.services.portfolio_service import (
            add_to_watchlist, remove_from_watchlist,
        )

        with app.app_context():
            uid = self._make_user()
            self.assertIsNone(add_to_watchlist(uid, "RU000A100YG1", "X", "X"))
            self.assertIsInstance(add_to_watchlist(uid, "RU000A100YG1", "X", "X"), str)
            self.assertTrue(remove_from_watchlist(uid, "RU000A100YG1"))
            self.assertFalse(remove_from_watchlist(uid, "RU000A100YG1"))


# ── Alerts service ────────────────────────────────────────────────────────────


class AlertsServiceTests(BaseTest):
    def test_create_list_delete(self):
        from app.exceptions import NotFoundError
        from app.services import alerts_service

        with app.app_context():
            uid = self._make_user()
            created = alerts_service.create_alert(uid, "RU000A1", "X", 950.5, ">=")
            self.assertIn("id", created)
            items = alerts_service.list_alerts(uid)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["target_price"], 950.5)
            alerts_service.delete_alert(created["id"], uid)
            self.assertEqual(alerts_service.list_alerts(uid), [])
            with self.assertRaises(NotFoundError):
                alerts_service.delete_alert(created["id"], uid)


# ── Calendar service ──────────────────────────────────────────────────────────


class CalendarServiceTests(BaseTest):
    def test_upcoming_coupons(self):
        from app.services import calendar_service

        with app.app_context():
            uid = self._make_user()
            self._make_bond(uid, isin="RU000A1038V6")
            today = date.today()
            in7 = (today + timedelta(days=7)).isoformat()
            far = (today + timedelta(days=400)).isoformat()
            past = (today - timedelta(days=10)).isoformat()
            coupons = [
                {"date": in7, "coupondate": in7, "value": 35.0},
                {"date": far, "value": 35.0},
                {"date": past, "value": 35.0},
            ]
            with patch(
                "app.services.calendar_service.get_coupon_calendar_cached",
                return_value=coupons,
            ):
                events = calendar_service.get_upcoming_coupons(uid, days=30)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["days_left"], 7)

    def test_calendar_events_grouping(self):
        from app.services import calendar_service

        with app.app_context():
            uid = self._make_user()
            self._make_bond(uid, isin="RU000A1038V6", amount=5)
            self._make_bond(uid, isin="RU000A1038V6", amount=3)
            with patch(
                "app.services.calendar_service.get_coupon_calendar_cached",
                return_value=[{"date": "2030-01-15", "value": 10.0}],
            ):
                events = calendar_service.get_calendar_events(uid)
            self.assertEqual(events[0]["total_payout"], 80.0)  # 10 * (5+3)


# ── Tax service ───────────────────────────────────────────────────────────────


class TaxServiceEdgeTests(BaseTest):
    def test_apply_ldv_under_3_years(self):
        from app.services.tax_service import apply_ldv

        self.assertEqual(apply_ldv(100_000.0, days_held=365), 100_000.0)

    def test_apply_ldv_full_deduction(self):
        from app.constants import LDV_ANNUAL_DEDUCTION
        from app.services.tax_service import apply_ldv

        # 5 лет = 5 × LDV_ANNUAL_DEDUCTION; этот вычет покрывает любую базу
        big_deduction_years = 5
        self.assertEqual(
            apply_ldv(LDV_ANNUAL_DEDUCTION * 2, days_held=365 * big_deduction_years),
            0.0,
        )

    def test_tax_report_filters_by_year(self):
        from app.services.tax_service import calc_tax_report

        bond_in_year = SimpleNamespace(
            isin="X", name="X", amount=1, buy_price=900, sell_price=950,
            broker_commission=0, purchase_date=date(2025, 1, 1),
            sell_date=date(2025, 6, 1), currency="RUB",
        )
        bond_other_year = SimpleNamespace(
            isin="Y", name="Y", amount=1, buy_price=900, sell_price=950,
            broker_commission=0, purchase_date=date(2024, 1, 1),
            sell_date=date(2024, 6, 1), currency="RUB",
        )
        with patch("app.services.tax_service.get_currency_rates", return_value={}):
            report = calc_tax_report([bond_in_year, bond_other_year], [], year=2025)
        self.assertEqual(len(report["trades"]), 1)
        self.assertEqual(report["trades"][0]["isin"], "X")
        self.assertEqual(report["year"], 2025)


# ── Risk service ──────────────────────────────────────────────────────────────


class RiskServiceTests(BaseTest):
    def _bond(self, buy, sell, days=200):
        return SimpleNamespace(
            buy_price=buy, sell_price=sell,
            purchase_date=date(2024, 1, 1),
            sell_date=date(2024, 1, 1) + timedelta(days=days),
        )

    def test_sharpe_requires_min_3_samples(self):
        from app.services.risk_service import calc_sharpe_ratio
        self.assertIsNone(calc_sharpe_ratio([self._bond(900, 950)]))

    def test_sharpe_normal_case(self):
        from app.services.risk_service import calc_sharpe_ratio

        bonds = [self._bond(900, 950), self._bond(900, 920), self._bond(900, 980)]
        with patch("app.services.risk_service.get_gcurve_rate", return_value=0.10):
            result = calc_sharpe_ratio(bonds)
        self.assertIsNotNone(result)
        self.assertIn("sharpe", result)
        self.assertEqual(result["sample_size"], 3)

    def test_diversification_empty(self):
        from app.services.risk_service import calc_portfolio_diversification

        result = calc_portfolio_diversification([])
        self.assertEqual(result["assets"]["hhi"], 0.0)

    def test_diversification_ofz_classification(self):
        from app.services.risk_service import calc_portfolio_diversification

        bonds = [
            SimpleNamespace(isin="SU26238RMFS4", name="ОФЗ 26238", amount=10,
                            buy_price=900, last_price=950, currency="RUB"),
            SimpleNamespace(isin="RU000A105104", name="Газпром", amount=5,
                            buy_price=1000, last_price=1010, currency="RUB"),
        ]
        with patch("app.services.risk_service.get_currency_rates", return_value={}):
            result = calc_portfolio_diversification(bonds)
        issuer_names = {w["name"] for w in result["issuers"]["weights"]}
        self.assertIn("Гос. облигации (ОФЗ)", issuer_names)
        self.assertIn("Корпоративные облигации", issuer_names)


# ── Telegram webhook blueprint ────────────────────────────────────────────────


class TelegramWebhookTests(BaseTest):
    def setUp(self):
        super().setUp()
        app.config["TELEGRAM_BOT_TOKEN"] = "fake-bot-token"
        app.config["TELEGRAM_WEBHOOK_SECRET"] = "secret123"

    def tearDown(self):
        app.config.pop("TELEGRAM_BOT_TOKEN", None)
        app.config.pop("TELEGRAM_WEBHOOK_SECRET", None)
        super().tearDown()

    def _post(self, body, secret="secret123"):
        url = f"/api/telegram/webhook/{secret}" if secret else "/api/telegram/webhook"
        return self.client.post(url, json=body)

    def test_no_bot_token_returns_503(self):
        app.config["TELEGRAM_BOT_TOKEN"] = ""
        r = self._post({"message": {"chat": {"id": 1}, "text": "/help"}})
        self.assertEqual(r.status_code, 503)

    def test_wrong_secret_forbidden(self):
        r = self._post({"message": {"chat": {"id": 1}, "text": "/help"}}, secret="wrong")
        self.assertEqual(r.status_code, 403)

    def test_empty_update_ok(self):
        r = self._post({})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"])

    def test_help_command(self):
        with patch("app.blueprints.telegram_bot.send_message") as send:
            self._post({"message": {"chat": {"id": 1}, "text": "/help"}})
        send.assert_called_once()
        self.assertIn("Команды", send.call_args[0][1])

    def test_start_without_token(self):
        with patch("app.blueprints.telegram_bot.send_message") as send:
            self._post({"message": {"chat": {"id": 1}, "text": "/start"}})
        send.assert_called_once()
        self.assertIn("Привет", send.call_args[0][1])

    def test_start_with_invalid_token(self):
        with patch("app.blueprints.telegram_bot.send_message") as send, \
             patch("app.services.telegram_service.verify_link_token", return_value=None):
            self._post({
                "message": {"chat": {"id": 1}, "from": {"username": "alice"},
                            "text": "/start bad-token"},
            })
        send.assert_called_once()
        self.assertIn("устарела", send.call_args[0][1])

    def test_start_links_user(self):
        uid = self._make_user()
        with patch("app.blueprints.telegram_bot.send_message") as send, \
             patch("app.services.telegram_service.verify_link_token", return_value=uid):
            r = self._post({
                "message": {"chat": {"id": 42}, "from": {"username": "alice"},
                            "text": f"/start sometoken"},
            })
        self.assertEqual(r.status_code, 200)
        # Должно отправиться приветствие с именем пользователя
        send.assert_called()
        text = send.call_args[0][1]
        self.assertIn("успешно привязан", text)

        # И пользователь должен реально получить chat_id
        from app.models import User
        with app.app_context():
            u = db.session.get(User, uid)
            self.assertEqual(u.telegram_chat_id, "42")
            self.assertTrue(u.telegram_notifications)

    def test_stop_unlinks(self):
        from app.models import User
        uid = self._make_user()
        with app.app_context():
            u = db.session.get(User, uid)
            u.telegram_chat_id = "99"
            u.telegram_notifications = True
            db.session.commit()

        with patch("app.blueprints.telegram_bot.send_message") as send:
            self._post({"message": {"chat": {"id": 99}, "text": "/stop"}})
        send.assert_called_once()
        self.assertIn("отвязан", send.call_args[0][1])

        with app.app_context():
            u = db.session.get(User, uid)
            self.assertIsNone(u.telegram_chat_id)


# ── Health service ────────────────────────────────────────────────────────────


class HealthServiceTests(BaseTest):
    def test_check_health_service(self):
        from app.services.health_service import check_health

        with app.app_context(), patch("app.services.health_service.requests.get") as get:
            get.return_value = SimpleNamespace(raise_for_status=lambda: None, ok=True)
            payload, code = check_health()
        # db и cache могут быть деградированы локально (Postgres host недоступен);
        # проверяем сам контракт: ключи присутствуют, status согласован с кодом.
        for key in ("db", "cache", "moex", "status"):
            self.assertIn(key, payload)
        self.assertIn(code, (200, 503))
        if code == 200:
            self.assertEqual(payload["status"], "ok")
        else:
            self.assertEqual(payload["status"], "degraded")

    def test_visit_counter_increments(self):
        from app.services.health_service import increment_visit_counter

        with app.app_context():
            v1 = increment_visit_counter()
            v2 = increment_visit_counter()
            self.assertEqual(v2, v1 + 1)
