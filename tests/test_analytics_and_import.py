"""
Tests for Analytics and Imports pages and APIs.
"""

import unittest
from datetime import date
from unittest.mock import patch, MagicMock

from tests.test_app import BaseTest, MOCK_MOEX
from app import app
from app.extensions import db
from app.models import BondPortfolio, Transaction


class AnalyticsAndImportTests(BaseTest):
    # ── Page Render Tests ──────────────────────────────────────────────────
    def test_analytics_page_requires_auth(self):
        """GET /analytics redirects unauthenticated user."""
        r = self.client.get("/analytics")
        self.assertIn(r.status_code, [302, 401])

    def test_analytics_page_loads(self):
        """GET /analytics loads successfully for logged-in user."""
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/analytics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Аналитика", r.data.decode("utf-8"))

    def test_import_page_requires_auth(self):
        """GET /import redirects unauthenticated user."""
        r = self.client.get("/import")
        self.assertIn(r.status_code, [302, 401])

    def test_import_page_loads(self):
        """GET /import loads successfully for logged-in user."""
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/import")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Импорт", r.data.decode("utf-8"))

    # ── Analytics API Tests ────────────────────────────────────────────────
    def test_portfolio_tax_requires_auth(self):
        """GET /api/portfolio/tax redirects unauthenticated user."""
        r = self.client.get("/api/portfolio/tax")
        self.assertIn(r.status_code, [302, 401])

    def test_portfolio_tax_empty(self):
        """GET /api/portfolio/tax returns correct zero tax summary when no sales exist."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        r = self.client.get("/api/portfolio/tax?year=2026")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["gross_profit"], 0.0)
        self.assertEqual(data["total_commission"], 0.0)
        self.assertEqual(data["taxable_base"], 0.0)
        self.assertEqual(data["tax_amount"], 0.0)
        self.assertEqual(data["trades"], [])

    def test_portfolio_tax_with_trades(self):
        """GET /api/portfolio/tax calculates taxable base correctly for sold positions."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Make one sold bond lot (profitable)
        self._make_bond(uid, isin="SU26238RMFS4", is_sold=True, buy_price=900.0, sell_price=950.0, amount=10)

        r = self.client.get(f"/api/portfolio/tax?year={date.today().year}")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        # Profit: (950 - 900) * 10 = 500
        self.assertAlmostEqual(data["gross_profit"], 500.0)
        self.assertAlmostEqual(data["taxable_base"], 500.0)
        self.assertAlmostEqual(data["tax_amount"], 65.0)  # 13% of 500 is 65
        self.assertEqual(len(data["trades"]), 1)
        self.assertEqual(data["trades"][0]["isin"], "SU26238RMFS4")

    @patch("app.blueprints.analytics.get_rgbi_history")
    def test_portfolio_benchmark_success(self, mock_rgbi):
        """GET /api/portfolio/benchmark returns mocked RGBI data."""
        mock_rgbi.return_value = [
            {"date": "2026-05-01", "close": 120.5},
            {"date": "2026-05-02", "close": 121.2},
        ]
        uid = self._make_user()
        self._set_logged_in(uid)

        r = self.client.get("/api/portfolio/benchmark?range=month")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["range"], "month")
        self.assertEqual(len(data["rgbi"]), 2)
        self.assertEqual(data["rgbi"][0]["close"], 120.5)

    def test_portfolio_sharpe_insufficient_data(self):
        """GET /api/portfolio/sharpe returns reason when closed trades count is < 3."""
        uid = self._make_user()
        self._set_logged_in(uid)

        r = self.client.get("/api/portfolio/sharpe")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsNone(data["sharpe"])
        self.assertIn("Недостаточно данных", data["reason"])

    def test_portfolio_sharpe_ratio_success(self):
        """GET /api/portfolio/sharpe calculates ratio with 3+ closed trades."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Insert 3 different profitable trades
        self._make_bond(uid, isin="ISIN1", is_sold=True, buy_price=100.0, sell_price=110.0, amount=1)
        self._make_bond(uid, isin="ISIN2", is_sold=True, buy_price=100.0, sell_price=120.0, amount=1)
        self._make_bond(uid, isin="ISIN3", is_sold=True, buy_price=100.0, sell_price=115.0, amount=1)

        r = self.client.get("/api/portfolio/sharpe")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIsNotNone(data["sharpe"])
        self.assertGreater(data["sample_size"], 2)

    def test_compare_bonds_invalid_params(self):
        """GET /api/portfolio/compare returns 400 for identical or missing ISIN parameters."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Missing params
        r = self.client.get("/api/portfolio/compare?isin1=SU26238RMFS4")
        self.assertEqual(r.status_code, 400)

        # Identical params
        r = self.client.get("/api/portfolio/compare?isin1=SU26238RMFS4&isin2=SU26238RMFS4")
        self.assertEqual(r.status_code, 400)

    @patch("app.blueprints.analytics.get_bond_history_all")
    @patch("app.blueprints.analytics.get_moex_bond")
    def test_compare_bonds_success(self, mock_get_bond, mock_history):
        """GET /api/portfolio/compare returns normalized historical comparison."""
        mock_get_bond.side_effect = lambda isin: {
            "secid": isin,
            "name": f"Bond {isin}",
            "facevalue": 1000
        }
        mock_history.side_effect = lambda secid, fv: {
            "labels": ["2026-05-01", "2026-05-02"],
            "data": [900.0, 990.0] if secid == "SU1" else [1000.0, 1050.0]
        }

        uid = self._make_user()
        self._set_logged_in(uid)

        r = self.client.get("/api/portfolio/compare?isin1=SU1&isin2=SU2&range=month")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        
        # Norm to 100 on start of period
        # Bond 1: [900.0, 990.0] -> [100.0, 110.0]
        # Bond 2: [1000.0, 1050.0] -> [100.0, 105.0]
        self.assertEqual(data["bond1"]["data"], [100.0, 110.0])
        self.assertEqual(data["bond2"]["data"], [100.0, 105.0])

    def test_dashboard_pnl_chart(self):
        """GET /api/dashboard/pnl_chart returns data for dashboard area chart."""
        uid = self._make_user()
        self._set_logged_in(uid)

        # Make one sold lot
        self._make_bond(uid, isin="SU26238RMFS4", is_sold=True, buy_price=900.0, sell_price=950.0, amount=10)

        # Make one active lot
        self._make_bond(uid, isin="SU26238RMFS4", is_sold=False, buy_price=900.0, amount=5)

        r = self.client.get("/api/dashboard/pnl_chart?period=30d")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["period"], "30d")
        self.assertIn("labels", data)
        self.assertIn("data", data)
        self.assertIn("unrealized", data)

    # ── New Features & Refactoring Tests (Stage 4+) ───────────────────────
    def test_prometheus_metrics(self):
        """GET /metrics returns Prometheus formatted gauge metrics."""
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["Content-Type"])
        body = r.data.decode("utf-8")
        self.assertIn("investtrack_users_total", body)
        self.assertIn("investtrack_active_positions_total", body)
        self.assertIn("investtrack_system_status", body)

    def test_portfolio_diversification(self):
        """GET /api/portfolio/diversification returns assets, currencies, and issuers HHI."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        # Add a couple of active bonds
        self._make_bond(uid, isin="SU26238RMFS4", buy_price=900.0, amount=10)
        self._make_bond(uid, isin="RU000A105C94", buy_price=100.0, amount=5)
        
        r = self.client.get("/api/portfolio/diversification")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("assets", data)
        self.assertIn("currencies", data)
        self.assertIn("issuers", data)
        self.assertIn("hhi", data["assets"])
        self.assertIn("weights", data["assets"])

    @patch("app.services.portfolio_service.get_coupon_calendar_cached")
    def test_modified_duration_calculation(self, mock_calendar):
        """GET /api/portfolio includes modified_duration and weighted average portfolio_duration."""
        mock_calendar.return_value = [
            {"date": "2026-12-31", "value": 50.0},
        ]
        uid = self._make_user()
        self._set_logged_in(uid)
        
        self._make_bond(uid, isin="SU26238RMFS4", buy_price=900.0, amount=10)
        
        r = self.client.get("/api/portfolio")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("portfolio_duration", data)
        self.assertGreater(len(data["bonds"]), 0)
        self.assertIn("modified_duration", data["bonds"][0])
        self.assertIn("macaulay_duration", data["bonds"][0])

    def test_svg_sparkline_endpoint(self):
        """GET /api/portfolio/sparkline/<isin> returns SVG image."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        r = self.client.get("/api/portfolio/sparkline/SU26238RMFS4")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["Content-Type"], "image/svg+xml")
        body = r.data.decode("utf-8")
        self.assertIn("<svg", body)
        self.assertIn("</svg>", body)

    def test_price_alerts_crud(self):
        """POST, GET, and DELETE price alerts works successfully."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        # 1. Create alert
        alert_payload = {
            "isin": "SU26238RMFS4",
            "target_price": 950.0,
            "condition": "<="
        }
        r = self.client.post("/api/alerts", json=alert_payload)
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["alert"]["target_price"], 950.0)
        alert_id = data["alert"]["id"]
        
        # 2. Get alerts
        r = self.client.get("/api/alerts")
        self.assertEqual(r.status_code, 200)
        alerts_list = r.get_json()
        self.assertEqual(len(alerts_list), 1)
        self.assertEqual(alerts_list[0]["id"], alert_id)
        
        # 3. Delete alert
        r = self.client.delete(f"/api/alerts/{alert_id}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")
        
        # Verify empty list
        r = self.client.get("/api/alerts")
        self.assertEqual(len(r.get_json()), 0)

    def test_circuit_breaker_failsafe(self):
        """MOEX circuit breaker locks requests after consecutive failures."""
        from app.moex import _fetch_json
        from app import moex
        
        # Reset local count
        moex._cb_fail_count = 0
        moex._cb_open_until = 0.0
        
        # Простая имитация кэша через словарь
        test_cache = {}
        
        def mock_get(key):
            return test_cache.get(key)
            
        def mock_set(key, val, timeout=None):
            test_cache[key] = val
            return True
            
        def mock_delete(key):
            test_cache.pop(key, None)
            return True
            
        import requests
        with patch("app.extensions.cache.get", side_effect=mock_get), \
             patch("app.extensions.cache.set", side_effect=mock_set), \
             patch("app.extensions.cache.delete", side_effect=mock_delete), \
             patch("app.moex.requests.get", side_effect=requests.RequestException("Network failure")):
             
            # Делаем 5 неудачных попыток чтобы взвести предохранитель
            for _ in range(5):
                try:
                    _fetch_json("https://example.com")
                except Exception:
                    pass
            
            # 6-й вызов должен бросить RuntimeError из-за открытого автомата
            with self.assertRaises(RuntimeError) as ctx:
                _fetch_json("https://example.com")
            self.assertIn("MOEX недоступен", str(ctx.exception))

    def test_profile_api_stats(self):
        """GET /api/profile/stats returns profile statistics (positions count, sold count, value)."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        self._make_bond(uid, isin="SU26238RMFS4", is_sold=False, buy_price=900.0, amount=10)
        self._make_bond(uid, isin="RU000A105C94", is_sold=True, buy_price=100.0, sell_price=120.0, amount=5)
        
        r = self.client.get("/api/profile/stats")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("bond_count", data)
        self.assertIn("sold_count", data)
        self.assertIn("total_value", data)
        self.assertEqual(data["sold_count"], 1)

    def test_profile_delete_avatar_api(self):
        """DELETE /api/profile/avatar successfully removes avatar from user profile."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        with app.app_context():
            from app.models import User
            user = db.session.get(User, uid)
            user.avatar = "some_cat_avatar.png"
            db.session.commit()
            
        r = self.client.delete("/api/profile/avatar")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        
        with app.app_context():
            from app.models import User
            user = db.session.get(User, uid)
            self.assertIsNone(user.avatar)

    def test_telegram_link_endpoints(self):
        """GET /api/profile/telegram/status and POST /api/profile/telegram/link return correct status."""
        uid = self._make_user()
        self._set_logged_in(uid)
        
        app.config["TELEGRAM_BOT_TOKEN"] = "dummy_token"
        
        r = self.client.get("/api/profile/telegram/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertFalse(data["linked"])
        
        r = self.client.post("/api/profile/telegram/link")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("deep_link", data)
