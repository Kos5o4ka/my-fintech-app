"""
InvestTrack — full test suite.

To avoid starting APScheduler during tests, set FLASK_TESTING=1 before importing app.
"""

import io
import os
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

os.environ["FLASK_TESTING"] = "1"  # must be set before 'from app import app'
os.environ["FLASK_ENV"] = "testing"  # force TestingConfig (sqlite:///:memory:)
os.environ.pop("DATABASE_URL", None)  # prevent accidental PostgreSQL connection

from sqlalchemy.pool import StaticPool  # noqa: E402

from app import app  # noqa: E402
from app.extensions import db  # noqa: E402
from werkzeug.exceptions import RequestEntityTooLarge  # noqa: E402


# ── Shared MOEX stub ──────────────────────────────────────────────────────────
MOCK_MOEX = {
    "secid": "SU26238RMFS4",
    "name": "ОФЗ 26238",
    "price": 900.0,
    "facevalue": 1000,
    "nkd": 5.5,
    "ytm": 8.5,
}

MOCK_REQUESTS_SPEC_EMPTY = MagicMock()
MOCK_REQUESTS_SPEC_EMPTY.json.return_value = {"description": {"data": []}}


# ── Base fixture ──────────────────────────────────────────────────────────────
class BaseTest(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["RATELIMIT_ENABLED"] = False  # disable rate limiting in tests
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        # StaticPool: all SQLite connections share the same in-memory database,
        # which ensures that _make_user() and request handlers see the same data.
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
        self.client = app.test_client()
        with app.app_context():
            db.drop_all()  # clean any leftover tables
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    # ── Helpers ────────────────────────────────────────────────────────────
    def _make_user(self, username="testuser", password="testpass1", is_admin=False):
        from app.models import User
        from werkzeug.security import generate_password_hash

        with app.app_context():
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                is_admin=is_admin,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def _login(self, username="testuser", password="testpass1"):
        """Call the login API endpoint (use only for auth-specific tests)."""
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
            content_type="application/json",
        )

    def _set_logged_in(self, user_id: int):
        """Set Flask-Login session directly — bypasses the rate-limited endpoint.
        Use this in tests that need auth but are NOT testing the login flow."""
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(user_id)
            sess["_fresh"] = True

    def _make_bond(
        self,
        user_id,
        isin="SU26238RMFS4",
        is_sold=False,
        sell_price=None,
        sell_date=None,
        buy_price=900.0,
        amount=10,
    ):
        from app.models import BondPortfolio

        with app.app_context():
            bond = BondPortfolio(
                user_id=user_id,
                isin=isin,
                secid=isin,
                name="ОФЗ 26238",
                amount=amount,
                buy_price=buy_price,
                last_price=910.0,
                purchase_date=date.today(),
                is_sold=is_sold,
                sell_price=sell_price,
                sell_date=sell_date or (date.today() if is_sold else None),
            )
            db.session.add(bond)
            db.session.commit()
            return bond.id


# ── Smoke tests ────────────────────────────────────────────────────────────────
class SmokTests(BaseTest):
    def test_index_page_loads(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"InvestTrack", r.data)
        self.assertIn("XSRF-TOKEN", r.headers.get("Set-Cookie", ""))

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("frame-ancestors", r.headers.get("Content-Security-Policy", ""))

    def test_api_init_response(self):
        r = self.client.get("/api/init")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("visits", data)
        self.assertIn("is_authenticated", data)

    def test_config_security_settings(self):
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 50 * 1024 * 1024)
        self.assertIn("png", app.config["ALLOWED_EXTENSIONS"])
        self.assertTrue(app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(app.config["SESSION_COOKIE_SAMESITE"], "Lax")

    def test_upload_folder_config(self):
        self.assertTrue(
            app.config["UPLOAD_FOLDER"].endswith(("static\\avatars", "static/avatars"))
        )

    def test_large_file_error_handler(self):
        with app.test_request_context("/api/init"):
            error = RequestEntityTooLarge()
            resp = app.handle_user_exception(error)
        self.assertEqual(resp.status_code, 413)
        payload = resp.get_json()
        self.assertEqual(
            payload["message"],
            "Загруженный файл слишком велик. Максимальный размер — 5 МБ.",
        )

    def test_portfolio_requires_auth(self):
        r = self.client.get("/portfolio")
        self.assertIn(r.status_code, [302, 401])


# ── Auth tests ─────────────────────────────────────────────────────────────────
class AuthTests(BaseTest):
    def test_login_wrong_password(self):
        self._make_user()
        r = self.client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "wrong"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)

    def test_login_success(self):
        self._make_user()
        r = self._login()
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["user"]["username"], "testuser")

    def test_logout(self):
        self._make_user()
        self._login()
        r = self.client.post("/api/auth/logout")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

    def test_change_password_success(self):
        self._make_user()
        self._login()
        r = self.client.post(
            "/api/auth/change_password",
            json={
                "old_password": "testpass1",
                "new_password": "newpass99",
                "confirm_password": "newpass99",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

    def test_change_password_wrong_old(self):
        self._make_user()
        self._login()
        r = self.client.post(
            "/api/auth/change_password",
            json={
                "old_password": "wrongold",
                "new_password": "newpass99",
                "confirm_password": "newpass99",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 401)

    def test_change_password_mismatch(self):
        self._make_user()
        self._login()
        r = self.client.post(
            "/api/auth/change_password",
            json={
                "old_password": "testpass1",
                "new_password": "newpass99",
                "confirm_password": "different9",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_change_password_too_short(self):
        self._make_user()
        self._login()
        r = self.client.post(
            "/api/auth/change_password",
            json={
                "old_password": "testpass1",
                "new_password": "short",
                "confirm_password": "short",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_change_password_requires_auth(self):
        r = self.client.post(
            "/api/auth/change_password",
            json={"old_password": "a", "new_password": "b", "confirm_password": "b"},
            content_type="application/json",
        )
        self.assertIn(r.status_code, [302, 401])


# ── Admin tests ────────────────────────────────────────────────────────────────
class AdminTests(BaseTest):
    def test_get_users_requires_admin(self):
        uid = self._make_user()  # non-admin
        self._set_logged_in(uid)
        r = self.client.get("/api/admin/users")
        self.assertEqual(r.status_code, 403)

    def test_admin_get_users(self):
        uid = self._make_user(is_admin=True)
        self._set_logged_in(uid)
        r = self.client.get("/api/admin/users")
        self.assertEqual(r.status_code, 200)
        users = r.get_json()
        self.assertIsInstance(users, list)
        self.assertEqual(len(users), 1)

    def test_admin_add_user_success(self):
        uid = self._make_user(is_admin=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/admin/add_user",
            json={"username": "newuser", "password": "pass123", "is_admin": False},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("user_id", data)

    def test_admin_add_user_duplicate(self):
        uid = self._make_user(username="dupuser", is_admin=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/admin/add_user",
            json={"username": "dupuser", "password": "pass123"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_admin_add_user_invalid_username(self):
        uid = self._make_user(is_admin=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/admin/add_user",
            json={"username": "bad user!", "password": "pass123"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_admin_delete_user(self):
        uid = self._make_user(is_admin=True)
        target_id = self._make_user(username="victim", password="pass123")
        self._set_logged_in(uid)
        r = self.client.delete(f"/api/admin/delete_user/{target_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

    def test_admin_cannot_delete_self(self):
        uid = self._make_user(is_admin=True)
        self._set_logged_in(uid)
        r = self.client.delete(f"/api/admin/delete_user/{uid}")
        self.assertEqual(r.status_code, 400)


# ── Portfolio tests ────────────────────────────────────────────────────────────
class PortfolioTests(BaseTest):
    def test_get_portfolio_empty(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        with patch("app.services.moex_service.get_bond_cached", return_value=None):
            r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["bonds"], [])
        self.assertEqual(data["total_value"], 0.0)

    def test_get_portfolio_with_bond(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_bond(uid)
        # Patch via the local reference in portfolio_service (from-import)
        mock_moex_910 = {**MOCK_MOEX, "price": 910.0}
        with patch(
            "app.services.portfolio_service.get_bond_cached", return_value=mock_moex_910
        ):
            r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["bonds"]), 1)
        bond = data["bonds"][0]
        self.assertIn("pnl", bond)
        self.assertIn("pnl_pct", bond)
        # moex price=910, buy_price=900, amount=10 → pnl = (910-900)*10 = 100
        self.assertAlmostEqual(bond["pnl"], 100.0, places=1)

    def test_add_bond_missing_fields(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/add_bond",
            json={"isin": "SU26238RMFS4"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    @patch("app.moex.requests.get")
    @patch("app.blueprints.portfolio.get_moex_bond")
    def test_add_bond_success(self, mock_moex, mock_req):
        mock_moex.return_value = MOCK_MOEX
        mock_req.return_value = MOCK_REQUESTS_SPEC_EMPTY
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/add_bond",
            json={
                "isin": "SU26238RMFS4",
                "amount": 10,
                "buy_price": 900.0,
                "purchase_date": "2024-01-15",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["status"], "success")

    @patch("app.moex.requests.get")
    @patch("app.blueprints.portfolio.get_moex_bond")
    def test_add_bond_not_found(self, mock_moex, mock_req):
        mock_moex.return_value = None
        mock_req.return_value = MOCK_REQUESTS_SPEC_EMPTY
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/add_bond",
            json={"isin": "BADCODE00000", "amount": 1, "buy_price": 100.0},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_sell_bond_success(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        bond_id = self._make_bond(uid)
        r = self.client.post(
            f"/api/sell_bond/{bond_id}",
            json={"sell_price": 920.0},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

    def test_sell_bond_wrong_owner(self):
        uid1 = self._make_user(username="owner", password="pass123")
        uid2 = self._make_user(username="hacker", password="pass456")
        self._set_logged_in(uid2)
        bond_id = self._make_bond(uid1)  # owned by user1
        r = self.client.post(
            f"/api/sell_bond/{bond_id}",
            json={"sell_price": 900.0},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_sell_bond_partial_success(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        bond_id = self._make_bond(uid, amount=10, buy_price=900.0)

        r = self.client.post(
            f"/api/sell_bond/{bond_id}",
            json={"sell_price": 950.0, "amount": 4, "broker_commission": 2.5},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

        with app.app_context():
            from app.models import BondPortfolio, Transaction

            orig_bond = db.session.get(BondPortfolio, bond_id)
            self.assertEqual(orig_bond.amount, 6)
            self.assertFalse(orig_bond.is_sold)

            sold_bonds = BondPortfolio.query.filter_by(user_id=uid, is_sold=True).all()
            self.assertEqual(len(sold_bonds), 1)
            self.assertEqual(sold_bonds[0].amount, 4)
            self.assertEqual(float(sold_bonds[0].sell_price), 950.0)
            self.assertEqual(float(sold_bonds[0].broker_commission), 2.5)

            txs = Transaction.query.filter_by(user_id=uid, tx_type="sell").all()
            self.assertEqual(len(txs), 1)
            self.assertEqual(txs[0].amount, 4)
            self.assertEqual(float(txs[0].price), 950.0)

    def test_sell_bond_partial_excessive_amount(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        bond_id = self._make_bond(uid, amount=10)

        r = self.client.post(
            f"/api/sell_bond/{bond_id}",
            json={"sell_price": 950.0, "amount": 15},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["status"], "error")
        self.assertIn("Нельзя продать больше", r.get_json()["message"])

    def test_update_bond_notes_success(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        bond_id = self._make_bond(uid)

        r = self.client.patch(
            f"/api/portfolio/{bond_id}/notes",
            json={"notes": "Great long term investment"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")
        self.assertEqual(r.get_json()["notes"], "Great long term investment")

        with app.app_context():
            from app.models import BondPortfolio

            bond = db.session.get(BondPortfolio, bond_id)
            self.assertEqual(bond.notes, "Great long term investment")

    def test_update_bond_notes_wrong_owner(self):
        uid1 = self._make_user(username="owner", password="pass123")
        uid2 = self._make_user(username="hacker", password="pass456")
        self._set_logged_in(uid2)
        bond_id = self._make_bond(uid1)

        r = self.client.patch(
            f"/api/portfolio/{bond_id}/notes",
            json={"notes": "Hacked"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 404)

    def test_portfolio_history_empty(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/portfolio/history")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["trades"], [])

    def test_portfolio_history_with_trade(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_bond(uid, is_sold=True, buy_price=900.0, sell_price=950.0)
        r = self.client.get("/api/portfolio/history")
        self.assertEqual(r.status_code, 200)
        trades = r.get_json()["trades"]
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertAlmostEqual(t["pnl"], 500.0, places=1)  # (950-900)*10
        self.assertAlmostEqual(t["pnl_pct"], 5.556, places=1)

    def test_portfolio_stats_empty(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/portfolio_stats")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["labels"], [])
        self.assertIsInstance(data["datasets"], list)

    def test_csv_export(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_bond(uid)
        r = self.client.get("/api/portfolio/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.content_type)
        # UTF-8 BOM present for Excel compatibility
        self.assertTrue(
            r.data.startswith(b"\xef\xbb\xbf") or r.data.startswith("ï»¿".encode())
        )

    def test_search_bond_too_short(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/search_bond?q=O")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])

    @patch("app.blueprints.portfolio.search_bonds")
    def test_search_bond_results(self, mock_search):
        mock_search.return_value = [
            {"secid": "SU26238RMFS4", "isin": "SU26238RMFS4", "name": "ОФЗ 26238"}
        ]
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/search_bond?q=ОФЗ")
        self.assertEqual(r.status_code, 200)
        results = r.get_json()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["isin"], "SU26238RMFS4")

    def test_avatar_upload_invalid_extension(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/profile",
            data={"avatar": (io.BytesIO(b"fake content"), "file.exe")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.get_json()["status"])


# ── MOEX Currency Rates tests ─────────────────────────────────────────────────
class MoexCurrencyRatesTests(BaseTest):
    """Tests for get_currency_rates() and get_gold_price() in moex.py."""

    def test_currency_rates_fallback_on_error(self):
        """When MOEX is unreachable, fallback static rates are returned and valid."""
        from app.moex import get_currency_rates

        with patch("app.moex._fetch_json", side_effect=Exception("Network error")):
            rates = get_currency_rates()
        self.assertIsInstance(rates, dict)
        self.assertIn("USD", rates)
        self.assertIn("CNY", rates)
        self.assertIn("EUR", rates)
        self.assertIn("RUB", rates)
        self.assertEqual(rates["RUB"], 1.0)
        # Fallback values must be positive and reasonable
        self.assertGreater(rates["USD"], 0)
        self.assertGreater(rates["CNY"], 0)
        self.assertGreater(rates["EUR"], 0)

    def test_currency_rates_parses_moex_response(self):
        """When MOEX returns a price, it overrides the fallback."""
        from app.moex import get_currency_rates

        fake_response = {
            "marketdata": {
                "columns": ["LAST", "CURRENTVALUE"],
                "data": [[91.5, None]],
            },
            "securities": {"columns": [], "data": []},
        }
        # Cache miss → _fetch_json called for each currency
        with patch("app.moex._fetch_json", return_value=fake_response), patch(
            "app.moex.get_currency_rates.__wrapped__", create=True
        ):
            # Clear cache before test
            try:
                from app.extensions import cache

                cache.delete("moex_currency_rates")
            except Exception:
                pass
            rates = get_currency_rates()
        self.assertIn("USD", rates)
        # 91.5 should have been parsed from LAST column
        self.assertAlmostEqual(rates["USD"], 91.5, places=2)

    def test_gold_price_fallback_on_error(self):
        """When MOEX gold endpoint fails, the static fallback 7000.0 is returned."""
        from app.moex import get_gold_price

        # Clear cache so the cached value from a previous test doesn't leak in
        try:
            from app.extensions import cache

            cache.delete("moex_gold_price")
        except Exception:
            pass
        with patch("app.moex._fetch_json", side_effect=Exception("Timeout")):
            price = get_gold_price()
        self.assertIsInstance(price, float)
        self.assertEqual(price, 7000.0)

    def test_gold_price_parses_moex_response(self):
        """When MOEX returns a valid gold spot price, it is returned correctly."""
        from app.moex import get_gold_price

        fake_response = {
            "marketdata": {
                "columns": ["LAST", "WAPRICE"],
                "data": [[8500.0, None]],
            },
            "securities": {"columns": [], "data": []},
        }
        try:
            from app.extensions import cache

            cache.delete("moex_gold_price")
        except Exception:
            pass
        with patch("app.moex._fetch_json", return_value=fake_response):
            price = get_gold_price()
        self.assertIsInstance(price, float)
        self.assertAlmostEqual(price, 8500.0, places=1)


# ── Gold Bond Valuation tests ─────────────────────────────────────────────────
class GoldBondValuationTests(BaseTest):
    """Tests for correct valuation of GLD (gold-denominated) bonds."""

    def _make_gld_bond(self, user_id, buy_price=100.0, amount=5):
        """Helper: inserts a BondPortfolio entry with currency='GLD'."""
        from app.models import BondPortfolio

        with app.app_context():
            bond = BondPortfolio(
                user_id=user_id,
                isin="RU000GOLD001",
                secid="GOLD001",
                name="Золотая облигация",
                amount=amount,
                buy_price=buy_price,
                last_price=None,
                currency="GLD",
                purchase_date=date.today(),
                is_sold=False,
            )
            db.session.add(bond)
            db.session.commit()
            return bond.id

    def test_gold_bond_stored_currency_is_gld(self):
        """A bond with currency='GLD' is persisted correctly in DB."""
        uid = self._make_user()
        bond_id = self._make_gld_bond(uid)
        with app.app_context():
            from app.models import BondPortfolio

            bond = db.session.get(BondPortfolio, bond_id)
            self.assertEqual(bond.currency, "GLD")
            self.assertFalse(bond.is_sold)

    def test_portfolio_api_handles_gld_bond(self):
        """GET /api/portfolio succeeds even when a GLD bond is present."""
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_gld_bond(uid)

        mock_gld_moex = {
            "secid": "GOLD001",
            "name": "Золотая облигация",
            "price": 8400.0,  # gold_price * last_pct / 100
            "facevalue": 8000.0,
            "nkd": 0.0,
            "ytm": 0.0,
            "currency": "GLD",
        }
        with patch(
            "app.services.moex_service.get_bond_cached", return_value=mock_gld_moex
        ):
            r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("bonds", data)
        # total_value should be a positive float (GLD bond contributes in RUB)
        self.assertIsInstance(data["total_value"], float)
        self.assertGreaterEqual(data["total_value"], 0.0)

    @patch("app.blueprints.portfolio.get_bond_preview")
    def test_bond_preview_returns_gld_currency(self, mock_preview):
        """GET /api/bond_preview/<isin> returns currency='GLD' for gold bonds."""
        mock_preview.return_value = {
            "status": "ok",
            "name": "Золотая облигация",
            "price": 8200.0,
            "facevalue": 7800.0,
            "nkd": 0.0,
            "ytm": 0.0,
            "currency": "GLD",
        }
        uid = self._make_user()
        self._set_logged_in(uid)

        r = self.client.get("/api/bond_preview/RU000GOLD001")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["currency"], "GLD")


# ── Broker Import tests ───────────────────────────────────────────────────────
class BrokerImportTests(BaseTest):
    """Tests for POST /api/portfolio/import (CSV and JSON payloads)."""

    def _csv_bytes(self, rows: list[dict]) -> bytes:
        """Helper: serialise list-of-dicts into UTF-8 CSV bytes."""
        import io as _io
        import csv as _csv

        buf = _io.StringIO()
        fieldnames = list(rows[0].keys())
        writer = _csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")

    @patch("app.blueprints.portfolio.get_moex_bond")
    def test_import_csv_single_deal_success(self, mock_moex):
        """Uploading a valid one-row CSV creates one BondPortfolio + Transaction."""
        mock_moex.return_value = {
            "secid": "SU26238RMFS4",
            "name": "ОФЗ 26238",
            "price": 905.0,
            "facevalue": 1000,
            "nkd": 5.0,
            "ytm": 8.2,
            "currency": "RUB",
        }
        uid = self._make_user()
        self._set_logged_in(uid)

        csv_data = self._csv_bytes(
            [
                {
                    "ISIN": "SU26238RMFS4",
                    "Amount": "10",
                    "Price": "900.00",
                    "Date": "2025-01-15",
                }
            ]
        )
        r = self.client.post(
            "/api/portfolio/import",
            data={"file": (io.BytesIO(csv_data), "deals.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["imported_count"], 1)
        self.assertEqual(data["errors"], [])

        with app.app_context():
            from app.models import BondPortfolio, Transaction

            bonds = BondPortfolio.query.filter_by(user_id=uid, is_sold=False).all()
            self.assertEqual(len(bonds), 1)
            self.assertEqual(bonds[0].isin, "SU26238RMFS4")
            self.assertEqual(bonds[0].amount, 10)
            self.assertAlmostEqual(float(bonds[0].buy_price), 900.0)

            txs = Transaction.query.filter_by(user_id=uid, tx_type="buy").all()
            self.assertEqual(len(txs), 1)
            self.assertEqual(txs[0].isin, "SU26238RMFS4")

    @patch("app.blueprints.portfolio.get_moex_bond")
    def test_import_json_deals_success(self, mock_moex):
        """Sending JSON deals array via POST body imports correctly."""
        mock_moex.return_value = {
            "secid": "SU26238RMFS4",
            "name": "ОФЗ 26238",
            "price": 905.0,
            "facevalue": 1000,
            "nkd": 5.0,
            "ytm": 8.2,
            "currency": "RUB",
        }
        uid = self._make_user()
        self._set_logged_in(uid)

        r = self.client.post(
            "/api/portfolio/import",
            json={
                "deals": [
                    {
                        "isin": "SU26238RMFS4",
                        "amount": "5",
                        "price": "910.00",
                        "date": "2025-03-10",
                    },
                ]
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["imported_count"], 1)

    def test_import_no_file_no_json_returns_error(self):
        """POST /api/portfolio/import without any payload returns 400."""
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/portfolio/import",
            json={"deals": []},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertEqual(data["status"], "error")

    def test_import_unsupported_file_extension_returns_error(self):
        """Uploading a .txt file returns 400 with a clear error message."""
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/portfolio/import",
            data={"file": (io.BytesIO(b"some data"), "report.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("error", r.get_json()["status"])

    def test_import_csv_unknown_isin_imported_optimistically(self):
        """Unknown ISINs are imported as-is; secid is resolved later on portfolio load."""
        uid = self._make_user()
        self._set_logged_in(uid)

        csv_data = self._csv_bytes(
            [{"ISIN": "UNKNOWN00001", "Amount": "3", "Price": "500.00"}]
        )
        r = self.client.post(
            "/api/portfolio/import",
            data={"file": (io.BytesIO(csv_data), "deals.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["imported_count"], 1)
        self.assertEqual(len(data["errors"]), 0)

    def test_import_requires_auth(self):
        """POST /api/portfolio/import redirects unauthenticated users."""
        r = self.client.post("/api/portfolio/import", json={"deals": []})
        self.assertIn(r.status_code, [302, 401])

    def test_import_deduplication(self):
        """Test that importing identical deal_no or identical fields does not duplicate transactions/lots."""
        uid = self._make_user()
        self._set_logged_in(uid)

        deal_payload = {
            "deals": [
                {
                    "isin": "SU26238RMFS4",
                    "amount": 10,
                    "price": 900.0,
                    "date": "2025-01-15",
                    "deal_no": "DEAL12345",
                }
            ]
        }

        # First import
        r = self.client.post(
            "/api/portfolio/import", json=deal_payload, content_type="application/json"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["imported_count"], 1)

        # Second import (same deal_no)
        r = self.client.post(
            "/api/portfolio/import", json=deal_payload, content_type="application/json"
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["imported_count"], 0)  # Skipped duplicate!

        with app.app_context():
            from app.models import BondPortfolio, Transaction

            bonds = BondPortfolio.query.filter_by(user_id=uid).all()
            txs = Transaction.query.filter_by(user_id=uid).all()
            self.assertEqual(len(bonds), 1)
            self.assertEqual(len(txs), 1)

    def test_bond_price_healing_via_portfolio(self):
        """Test that percentage prices <= 150 are healed to absolute currency based on MOEX face value."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Make a bond entry in database with a buy price in percent (e.g. 98.50)
        bond_id = self._make_bond(uid, isin="SU26238RMFS4", buy_price=98.50, amount=10)

        # Add corresponding transaction in database
        with app.app_context():
            from app.models import Transaction

            db.session.add(
                Transaction(
                    user_id=uid,
                    isin="SU26238RMFS4",
                    name="ОФЗ 26238",
                    tx_type="buy",
                    amount=10,
                    price=98.50,
                    tx_date=date.today(),
                )
            )
            db.session.commit()

        mock_moex = {
            "secid": "SU26238RMFS4",
            "name": "ОФЗ 26238",
            "price": 990.0,
            "facevalue": 1000.0,  # Nominal is 1000
            "nkd": 5.5,
            "ytm": 8.5,
            "currency": "RUB",
        }

        with patch(
            "app.services.portfolio_service.get_bond_cached", return_value=mock_moex
        ):
            # Fetch portfolio, which triggers build_portfolio_entry -> normalize_bond_price
            r = self.client.get("/api/portfolio")
            self.assertEqual(r.status_code, 200)

        with app.app_context():
            from app.models import BondPortfolio, Transaction

            bond = db.session.get(BondPortfolio, bond_id)
            # The buy price should be healed: (98.50 / 100) * 1000 = 985.00
            self.assertAlmostEqual(float(bond.buy_price), 985.00, places=2)

            txs = Transaction.query.filter_by(user_id=uid, tx_type="buy").all()
            for tx in txs:
                self.assertAlmostEqual(float(tx.price), 985.00, places=2)

    def test_delete_position_physical(self):
        """Test that physical deletion endpoint deletes active lot and its corresponding buy transaction."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Create a bond and a corresponding transaction in database
        bond_id = self._make_bond(uid, isin="SU26238RMFS4", buy_price=900.0, amount=10)
        with app.app_context():
            from app.models import Transaction, BondPortfolio

            bond = db.session.get(BondPortfolio, bond_id)
            db.session.add(
                Transaction(
                    user_id=uid,
                    isin="SU26238RMFS4",
                    name="ОФЗ 26238",
                    tx_type="buy",
                    amount=bond.amount,
                    price=bond.buy_price,
                    tx_date=bond.purchase_date,
                )
            )
            db.session.commit()

        # Call physical delete API
        r = self.client.delete(f"/api/portfolio/{bond_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

        # Verify that both are deleted
        with app.app_context():
            from app.models import BondPortfolio, Transaction

            bond_after = db.session.get(BondPortfolio, bond_id)
            self.assertIsNone(bond_after)

            tx_after = Transaction.query.filter_by(
                user_id=uid, isin="SU26238RMFS4", tx_type="buy"
            ).first()
            self.assertIsNone(tx_after)


if __name__ == "__main__":
    unittest.main()
