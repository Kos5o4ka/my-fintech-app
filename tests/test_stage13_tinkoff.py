"""Stage 13 — T-Invest integration tests."""
import os
from decimal import Decimal
from unittest.mock import patch

os.environ["FLASK_TESTING"] = "1"

from tests.test_app import BaseTest, app, db  # noqa: E402
from app.services.tinkoff_service import (  # noqa: E402
    TInvestAuthError,
    TInvestClient,
    TInvestError,
    decrypt_token,
    encrypt_token,
    money_to_decimal,
    quotation_to_decimal,
    timestamp_to_datetime,
)


# ── Конвертеры ────────────────────────────────────────────────────────────────


class ConvertersTests(BaseTest):
    def test_money_value_positive(self):
        self.assertEqual(
            money_to_decimal({"units": "114", "nano": 250000000}),
            Decimal("114.25"),
        )

    def test_money_value_negative(self):
        self.assertEqual(
            money_to_decimal({"units": "-200", "nano": -200000000}),
            Decimal("-200.2"),
        )

    def test_money_value_none(self):
        self.assertEqual(money_to_decimal(None), Decimal("0"))

    def test_quotation_alias(self):
        self.assertEqual(
            quotation_to_decimal({"units": "5", "nano": 500000000}),
            Decimal("5.5"),
        )

    def test_timestamp_to_datetime(self):
        dt = timestamp_to_datetime({"seconds": "1700000000", "nanos": 0})
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2023)


# ── Шифрование ────────────────────────────────────────────────────────────────


class EncryptionTests(BaseTest):
    def test_roundtrip(self):
        with app.app_context():
            token = "t.SomeLongTinkoffTokenValue_AAAA1234"
            enc = encrypt_token(token)
            self.assertNotEqual(enc, token)
            self.assertEqual(decrypt_token(enc), token)

    def test_decrypt_garbage_raises(self):
        with app.app_context():
            with self.assertRaises(TInvestError):
                decrypt_token("not-a-real-fernet-token")


# ── HTTP-клиент с моком requests ──────────────────────────────────────────────


class _FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}
        self.text = text or ""

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class ClientTests(BaseTest):
    def test_get_accounts_ok(self):
        client = TInvestClient(token="t.x")
        fake = _FakeResp(200, {"accounts": [{"id": "1", "status": "ACCOUNT_STATUS_OPEN"}]})
        with patch.object(client.session, "post", return_value=fake) as p:
            accounts = client.get_accounts()
        self.assertEqual(len(accounts), 1)
        args, kwargs = p.call_args
        self.assertIn("UsersService/GetAccounts", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer t.x")

    def test_auth_error_on_401(self):
        client = TInvestClient(token="t.bad")
        with patch.object(client.session, "post", return_value=_FakeResp(401)):
            with self.assertRaises(TInvestAuthError):
                client.get_accounts()

    def test_business_error_40003_mapped_to_auth(self):
        client = TInvestClient(token="t.bad")
        with patch.object(
            client.session, "post",
            return_value=_FakeResp(400, {"code": "40003", "message": "expired"}),
        ):
            with self.assertRaises(TInvestAuthError):
                client.get_accounts()


# ── End-to-end sync с моком HTTP ──────────────────────────────────────────────


def _portfolio_response():
    return _FakeResp(200, {
        "positions": [
            {
                "figi": "BBG00BOND0001",
                "instrumentType": "bond",
                "quantity": {"units": "5", "nano": 0},
                "averagePositionPrice": {"currency": "RUB", "units": "950", "nano": 0},
                "currentPrice": {"currency": "RUB", "units": "970", "nano": 0},
            },
            {
                "figi": "BBG00SHARE001",
                "instrumentType": "share",
                "quantity": {"units": "10", "nano": 0},
                "averagePositionPrice": {"currency": "RUB", "units": "100", "nano": 0},
                "currentPrice": {"currency": "RUB", "units": "110", "nano": 0},
            },
        ],
    })


def _route(url):
    if "GetAccounts" in url:
        return _FakeResp(200, {"accounts": [
            {"id": "ACC1", "status": "ACCOUNT_STATUS_OPEN", "name": "Брокерский", "type": "ACCOUNT_TYPE_TINKOFF"},
        ]})
    if "GetPortfolio" in url:
        return _portfolio_response()
    if "GetInstrumentBy" in url:
        return _FakeResp(200, {"instrument": {
            "figi": "BBG00BOND0001",
            "ticker": "SU26238",
            "isin": "RU000A1038V6",
            "name": "ОФЗ 26238",
            "currency": "rub",
            "nominal": {"units": "1000", "nano": 0},
        }})
    return _FakeResp(404, {}, text="unknown")


class SyncTests(BaseTest):
    def test_full_sync_imports_bond(self):
        from app.models import User, BondPortfolio
        from app.services.tinkoff_service import sync_tinkoff_portfolio

        with app.app_context():
            uid = self._make_user()
            u = db.session.get(User, uid)
            u.tinkoff_token = encrypt_token("t.validtoken12345")
            db.session.commit()

            with patch("requests.Session.post", side_effect=lambda url, **kw: _route(url)):
                result = sync_tinkoff_portfolio(u)

            self.assertEqual(result["status"], "success", result)
            s = result["summary"]
            self.assertEqual(s["accounts"], 1)
            self.assertEqual(s["bonds_imported"], 1)
            self.assertEqual(s["positions_total"], 2)  # bond + share, share отфильтрована

            bonds = BondPortfolio.query.filter_by(user_id=uid).all()
            self.assertEqual(len(bonds), 1)
            b = bonds[0]
            self.assertEqual(b.isin, "RU000A1038V6")
            self.assertEqual(b.amount, 5)
            # 950 / 1000 * 100 = 95.00
            self.assertEqual(b.buy_price, Decimal("95.00"))
            self.assertEqual(b.last_price, Decimal("97.00"))

    def test_sync_without_token(self):
        from app.models import User
        from app.services.tinkoff_service import sync_tinkoff_portfolio

        with app.app_context():
            uid = self._make_user()
            u = db.session.get(User, uid)
            result = sync_tinkoff_portfolio(u)
            self.assertEqual(result["status"], "error")
            self.assertIn("не настроен", result["message"].lower())


# ── HTTP-эндпоинты ────────────────────────────────────────────────────────────


class EndpointTests(BaseTest):
    def test_status_when_not_linked(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/profile/tinkoff_token")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertFalse(body["linked"])

    def test_save_token_validates_prefix(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/tinkoff_token",
            json={"token": "not-prefixed-token-12345"},
        )
        self.assertEqual(r.status_code, 400)

    def test_save_token_calls_verify(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        with patch(
            "app.services.tinkoff_service.verify_token",
            return_value=[{"id": "A", "status": "ACCOUNT_STATUS_OPEN"}],
        ):
            r = self.client.post(
                "/api/profile/tinkoff_token",
                json={"token": "t.GoodToken1234567"},
            )
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.get_json()["accounts_count"], 1)

        # Токен должен быть зашифрован в БД, не plain
        from app.models import User
        with app.app_context():
            u = db.session.get(User, uid)
            self.assertIsNotNone(u.tinkoff_token)
            self.assertNotIn("t.GoodToken1234567", u.tinkoff_token)

    def test_save_token_remove(self):
        from app.models import User
        uid = self._make_user()
        with app.app_context():
            u = db.session.get(User, uid)
            u.tinkoff_token = encrypt_token("t.something1234567")
            db.session.commit()
        self._set_logged_in(uid)
        r = self.client.post("/api/profile/tinkoff_token", json={"token": ""})
        self.assertEqual(r.status_code, 200)
        with app.app_context():
            u = db.session.get(User, uid)
            self.assertIsNone(u.tinkoff_token)
