"""
Tests for Stage 12 features: Settings, Activity categories, 2FA toggle,
Site notifications, Admin broadcast.
"""

from unittest.mock import patch, MagicMock

from tests.test_app import BaseTest
from app import app
from app.extensions import db


class SettingsTests(BaseTest):
    """Tests for GET/POST /api/profile/settings."""

    def test_get_settings_defaults(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/profile/settings")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["theme"], "system")
        self.assertEqual(data["notif_time"], "09:00")
        self.assertEqual(data["notif_timezone"], "Europe/Moscow")
        self.assertEqual(data["oferta_advance_days"], 14)

    def test_save_settings_success(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/settings",
            json={
                "theme": "dark",
                "notif_time": "18:30",
                "notif_timezone": "Asia/Tokyo",
                "oferta_advance_days": 7,
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")

        r = self.client.get("/api/profile/settings")
        data = r.get_json()
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["notif_time"], "18:30")
        self.assertEqual(data["notif_timezone"], "Asia/Tokyo")
        self.assertEqual(data["oferta_advance_days"], 7)

    def test_save_settings_invalid_theme_falls_back(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/settings",
            json={"theme": "rainbow"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/profile/settings")
        self.assertEqual(r.get_json()["theme"], "system")

    def test_save_settings_invalid_oferta_falls_back(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/settings",
            json={"oferta_advance_days": 999},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/profile/settings")
        self.assertEqual(r.get_json()["oferta_advance_days"], 14)

    def test_save_settings_invalid_time_falls_back(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/settings",
            json={"notif_time": "not-a-time"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/profile/settings")
        self.assertEqual(r.get_json()["notif_time"], "09:00")

    def test_save_settings_long_timezone_falls_back(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/settings",
            json={"notif_timezone": "A" * 100},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/profile/settings")
        self.assertEqual(r.get_json()["notif_timezone"], "Europe/Moscow")

    def test_settings_requires_auth(self):
        r = self.client.get("/api/profile/settings")
        self.assertIn(r.status_code, [302, 401])

    def test_settings_creates_audit_entry(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self.client.post(
            "/api/profile/settings",
            json={"theme": "light"},
            content_type="application/json",
        )
        with app.app_context():
            from app.models import AuditLog

            entry = AuditLog.query.filter_by(
                user_id=uid, action="settings_update"
            ).first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.category, "account")


class ActivityCategoryTests(BaseTest):
    """Tests for activity log category filtering."""

    def _make_audit_entries(self, uid):
        from app.models import AuditLog

        with app.app_context():
            db.session.add(
                AuditLog(user_id=uid, action="login_ok", category="account")
            )
            db.session.add(
                AuditLog(user_id=uid, action="bond_add", category="portfolio")
            )
            db.session.add(
                AuditLog(user_id=uid, action="logout", category="account")
            )
            db.session.commit()

    def test_activity_all(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_audit_entries(uid)
        r = self.client.get("/api/profile/activity")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["total"], 3)

    def test_activity_filter_account(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_audit_entries(uid)
        r = self.client.get("/api/profile/activity?category=account")
        data = r.get_json()
        self.assertEqual(data["total"], 2)
        for e in data["entries"]:
            self.assertIn(e["action"], ("login_ok", "logout"))

    def test_activity_filter_portfolio(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_audit_entries(uid)
        r = self.client.get("/api/profile/activity?category=portfolio")
        data = r.get_json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["entries"][0]["action"], "bond_add")

    def test_activity_filter_invalid_category_ignored(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._make_audit_entries(uid)
        r = self.client.get("/api/profile/activity?category=hacker")
        data = r.get_json()
        self.assertEqual(data["total"], 3)

    def test_activity_pagination(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        from app.models import AuditLog

        with app.app_context():
            for i in range(25):
                db.session.add(
                    AuditLog(user_id=uid, action="login_ok", category="account")
                )
            db.session.commit()
        r = self.client.get("/api/profile/activity?page=1")
        data = r.get_json()
        self.assertEqual(len(data["entries"]), 20)
        self.assertEqual(data["pages"], 2)

        r = self.client.get("/api/profile/activity?page=2")
        data = r.get_json()
        self.assertEqual(len(data["entries"]), 5)


class TwoFAToggleTests(BaseTest):
    """Tests for 2FA enable/disable endpoints."""

    def _make_user_with_tg(self, two_fa=True):
        from app.models import User
        from werkzeug.security import generate_password_hash

        with app.app_context():
            user = User(
                username="tguser",
                password_hash=generate_password_hash("testpass1"),
                telegram_chat_id="123456",
                telegram_notifications=True,
                two_fa_enabled=two_fa,
            )
            db.session.add(user)
            db.session.commit()
            return user.id

    def test_enable_2fa_success(self):
        uid = self._make_user_with_tg(two_fa=False)
        self._set_logged_in(uid)
        r = self.client.post("/api/profile/2fa/enable")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")
        with app.app_context():
            from app.models import User

            user = db.session.get(User, uid)
            self.assertTrue(user.two_fa_enabled)

    def test_enable_2fa_without_telegram(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post("/api/profile/2fa/enable")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Telegram", r.get_json()["message"])

    def test_disable_2fa_with_password(self):
        uid = self._make_user_with_tg(two_fa=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/2fa/disable",
            json={"method": "password", "password": "testpass1"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "success")
        with app.app_context():
            from app.models import User

            user = db.session.get(User, uid)
            self.assertFalse(user.two_fa_enabled)

    def test_disable_2fa_wrong_password(self):
        uid = self._make_user_with_tg(two_fa=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/2fa/disable",
            json={"method": "password", "password": "wrongpass"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_disable_2fa_with_otp(self):
        uid = self._make_user_with_tg(two_fa=True)
        self._set_logged_in(uid)
        with patch("app.blueprints.profile.verify_otp", return_value=True):
            r = self.client.post(
                "/api/profile/2fa/disable",
                json={"method": "otp", "code": "123456"},
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)

    def test_disable_2fa_invalid_otp(self):
        uid = self._make_user_with_tg(two_fa=True)
        self._set_logged_in(uid)
        with patch("app.blueprints.profile.verify_otp", return_value=False):
            r = self.client.post(
                "/api/profile/2fa/disable",
                json={"method": "otp", "code": "000000"},
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)

    def test_disable_2fa_invalid_method(self):
        uid = self._make_user_with_tg(two_fa=True)
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/profile/2fa/disable",
            json={"method": "magic"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_send_otp_success(self):
        uid = self._make_user_with_tg()
        self._set_logged_in(uid)
        with patch("app.blueprints.profile.generate_otp") as mock_gen:
            r = self.client.post("/api/profile/2fa/send-otp")
        self.assertEqual(r.status_code, 200)
        mock_gen.assert_called_once_with("123456")

    def test_send_otp_no_telegram(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post("/api/profile/2fa/send-otp")
        self.assertEqual(r.status_code, 400)


class SiteNotificationTests(BaseTest):
    """Tests for site notification CRUD endpoints."""

    def _create_notifications(self, uid, count=3):
        from app.models import SiteNotification

        with app.app_context():
            for i in range(count):
                db.session.add(
                    SiteNotification(
                        user_id=uid,
                        title=f"Notif {i}",
                        body=f"Body {i}",
                    )
                )
            db.session.commit()

    def test_unread_count_zero(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["count"], 0)

    def test_unread_count_with_notifications(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._create_notifications(uid, 5)
        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.get_json()["count"], 5)

    def test_list_notifications(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._create_notifications(uid, 3)
        r = self.client.get("/api/notifications")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["notifications"]), 3)
        self.assertFalse(data["notifications"][0]["is_read"])

    def test_mark_read_specific_ids(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._create_notifications(uid, 3)

        r = self.client.get("/api/notifications")
        notifs = r.get_json()["notifications"]
        target_id = notifs[0]["id"]

        r = self.client.post(
            "/api/notifications/read",
            json={"ids": [target_id]},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["marked"], 1)

        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.get_json()["count"], 2)

    def test_mark_read_all(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        self._create_notifications(uid, 5)
        r = self.client.post(
            "/api/notifications/read",
            json={"all": True},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["marked"], 5)

        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.get_json()["count"], 0)

    def test_notifications_isolation_between_users(self):
        uid1 = self._make_user(username="user1", password="testpass1")
        uid2 = self._make_user(username="user2", password="testpass2")
        self._create_notifications(uid1, 3)
        self._set_logged_in(uid2)
        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.get_json()["count"], 0)

    def test_notifications_requires_auth(self):
        r = self.client.get("/api/notifications/unread_count")
        self.assertIn(r.status_code, [302, 401])


class AdminBroadcastTests(BaseTest):
    """Tests for POST /api/admin/broadcast."""

    def test_broadcast_site_all(self):
        admin_id = self._make_user(username="admin", password="pass123", is_admin=True)
        self._make_user(username="user1", password="pass123")
        self._make_user(username="user2", password="pass123")
        self._set_logged_in(admin_id)
        r = self.client.post(
            "/api/admin/broadcast",
            json={
                "title": "Тест",
                "body": "Тестовое уведомление",
                "recipients": "all",
                "channels": ["site"],
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("3", data["message"])

    def test_broadcast_specific_users(self):
        admin_id = self._make_user(username="admin", password="pass123", is_admin=True)
        uid1 = self._make_user(username="user1", password="pass123")
        self._make_user(username="user2", password="pass123")
        self._set_logged_in(admin_id)
        r = self.client.post(
            "/api/admin/broadcast",
            json={
                "title": "Личное",
                "body": "Только для вас",
                "recipients": [uid1],
                "channels": ["site"],
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("1", r.get_json()["message"])

        self._set_logged_in(uid1)
        r = self.client.get("/api/notifications/unread_count")
        self.assertEqual(r.get_json()["count"], 1)

    def test_broadcast_telegram_channel(self):
        admin_id = self._make_user(username="admin", password="pass123", is_admin=True)
        from app.models import User

        with app.app_context():
            user = User(
                username="tguser",
                password_hash="hash",
                telegram_chat_id="111",
                telegram_notifications=True,
            )
            db.session.add(user)
            db.session.commit()

        self._set_logged_in(admin_id)
        with patch("app.services.telegram_service.send_message", return_value=True) as mock_send:
            r = self.client.post(
                "/api/admin/broadcast",
                json={
                    "title": "TG Test",
                    "body": "Hello TG",
                    "recipients": "all",
                    "channels": ["telegram"],
                },
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 200)
        mock_send.assert_called_once()

    def test_broadcast_no_title(self):
        admin_id = self._make_user(is_admin=True)
        self._set_logged_in(admin_id)
        r = self.client.post(
            "/api/admin/broadcast",
            json={"title": "", "channels": ["site"], "recipients": "all"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_broadcast_no_channels(self):
        admin_id = self._make_user(is_admin=True)
        self._set_logged_in(admin_id)
        r = self.client.post(
            "/api/admin/broadcast",
            json={"title": "Test", "channels": [], "recipients": "all"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_broadcast_invalid_channel(self):
        admin_id = self._make_user(is_admin=True)
        self._set_logged_in(admin_id)
        r = self.client.post(
            "/api/admin/broadcast",
            json={"title": "Test", "channels": ["sms"], "recipients": "all"},
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 400)

    def test_broadcast_requires_admin(self):
        uid = self._make_user()
        self._set_logged_in(uid)
        r = self.client.post(
            "/api/admin/broadcast",
            json={
                "title": "Hack",
                "body": "No",
                "channels": ["site"],
                "recipients": "all",
            },
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 403)

    def test_broadcast_creates_audit_entry(self):
        admin_id = self._make_user(is_admin=True)
        self._set_logged_in(admin_id)
        self.client.post(
            "/api/admin/broadcast",
            json={
                "title": "Audit test",
                "channels": ["site"],
                "recipients": "all",
            },
            content_type="application/json",
        )
        with app.app_context():
            from app.models import AuditLog

            entry = AuditLog.query.filter_by(
                user_id=admin_id, action="admin_broadcast"
            ).first()
            self.assertIsNotNone(entry)


class AuditServiceTests(BaseTest):
    """Tests for audit_service.log_action."""

    def test_log_action_creates_entry(self):
        uid = self._make_user()
        with app.app_context():
            from app.services.audit_service import log_action

            log_action("test_action", user_id=uid, category="account", details={"key": "val"})
            db.session.commit()
            from app.models import AuditLog

            entry = AuditLog.query.filter_by(user_id=uid, action="test_action").first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.category, "account")
            self.assertEqual(entry.details, {"key": "val"})

    def test_log_action_default_category(self):
        uid = self._make_user()
        with app.app_context():
            from app.services.audit_service import log_action

            log_action("some_action", user_id=uid)
            db.session.commit()
            from app.models import AuditLog

            entry = AuditLog.query.filter_by(user_id=uid, action="some_action").first()
            self.assertEqual(entry.category, "account")


class NotificationServiceTests(BaseTest):
    """Tests for notification_service functions directly."""

    def test_broadcast_returns_counts(self):
        uid = self._make_user()
        with app.app_context():
            from app.services.notification_service import broadcast

            result = broadcast(uid, "all", ["site"], "Title", "Body")
            self.assertIn("sent_site", result)
            self.assertIn("sent_tg", result)
            self.assertIn("total_users", result)
            self.assertEqual(result["sent_site"], 1)
            self.assertEqual(result["sent_tg"], 0)

    def test_mark_read_empty_ids(self):
        uid = self._make_user()
        with app.app_context():
            from app.services.notification_service import mark_read

            count = mark_read(uid, ids=[])
            self.assertEqual(count, 0)

    def test_get_notifications_pagination(self):
        uid = self._make_user()
        from app.models import SiteNotification

        with app.app_context():
            for i in range(25):
                db.session.add(
                    SiteNotification(user_id=uid, title=f"N{i}", body="b")
                )
            db.session.commit()
            from app.services.notification_service import get_notifications

            items, total = get_notifications(uid, page=1, per_page=10)
            self.assertEqual(len(items), 10)
            self.assertEqual(total, 25)

            items2, _ = get_notifications(uid, page=3, per_page=10)
            self.assertEqual(len(items2), 5)


class SchemaValidationTests(BaseTest):
    """Tests for Pydantic schemas in app/schemas/profile.py."""

    def test_settings_update_defaults(self):
        from app.schemas.profile import SettingsUpdate

        s = SettingsUpdate()
        self.assertEqual(s.theme, "system")
        self.assertEqual(s.notif_time, "09:00")
        self.assertEqual(s.oferta_advance_days, 14)

    def test_settings_update_sanitizes_bad_values(self):
        from app.schemas.profile import SettingsUpdate

        s = SettingsUpdate(
            theme="neon",
            notif_time="abc",
            notif_timezone="X" * 100,
            oferta_advance_days=42,
        )
        self.assertEqual(s.theme, "system")
        self.assertEqual(s.notif_time, "09:00")
        self.assertEqual(s.notif_timezone, "Europe/Moscow")
        self.assertEqual(s.oferta_advance_days, 14)

    def test_settings_update_valid_values(self):
        from app.schemas.profile import SettingsUpdate

        s = SettingsUpdate(
            theme="dark",
            notif_time="22:00",
            notif_timezone="US/Eastern",
            oferta_advance_days=30,
        )
        self.assertEqual(s.theme, "dark")
        self.assertEqual(s.notif_time, "22:00")
        self.assertEqual(s.notif_timezone, "US/Eastern")
        self.assertEqual(s.oferta_advance_days, 30)
