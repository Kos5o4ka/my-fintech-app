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

from sqlalchemy.pool import StaticPool

from app import app
from extensions import db
from werkzeug.exceptions import RequestEntityTooLarge


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
            db.drop_all()   # clean any leftover tables
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    # ── Helpers ────────────────────────────────────────────────────────────
    def _make_user(self, username="testuser", password="testpass1", is_admin=False):
        from models import User
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

    def _make_bond(self, user_id, isin="SU26238RMFS4", is_sold=False,
                   sell_price=None, sell_date=None, buy_price=900.0, amount=10):
        from models import BondPortfolio

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
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 5 * 1024 * 1024)
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
            payload["message"], "Загруженный файл слишком велик. Максимальный размер — 5 МБ."
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
        with patch("blueprints.portfolio._get_moex_cached", return_value=None):
            r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["bonds"], [])
        self.assertEqual(data["total_value"], 0.0)

    def test_get_portfolio_with_bond(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_bond(uid)
        with patch("blueprints.portfolio._get_moex_cached", return_value=MOCK_MOEX):
            r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(len(data["bonds"]), 1)
        bond = data["bonds"][0]
        self.assertIn("pnl", bond)
        self.assertIn("pnl_pct", bond)
        # last_price=910, buy_price=900, amount=10 → pnl = (910-900)*10 = 100
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

    @patch("blueprints.portfolio.requests.get")
    @patch("blueprints.portfolio.get_moex_bond")
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

    @patch("blueprints.portfolio.requests.get")
    @patch("blueprints.portfolio.get_moex_bond")
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
        self.assertAlmostEqual(t["pnl"], 500.0, places=1)    # (950-900)*10
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
        self.assertTrue(r.data.startswith(b"\xef\xbb\xbf") or r.data.startswith("ï»¿".encode()))

    def test_search_bond_too_short(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/search_bond?q=O")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [])

    @patch("blueprints.portfolio.search_bonds")
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


if __name__ == "__main__":
    unittest.main()
