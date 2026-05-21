import unittest
from app import app
from extensions import db
from werkzeug.exceptions import RequestEntityTooLarge


class AppSmokeTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.client = app.test_client()
        self.client.testing = True
        with app.app_context():
            db.create_all()

    def tearDown(self):
        with app.app_context():
            db.session.remove()
            db.drop_all()

    def test_index_page_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'InvestTrack', response.data)
        self.assertIn('XSRF-TOKEN', response.headers.get('Set-Cookie', ''))

    def test_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(response.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertIn('frame-ancestors', response.headers.get('Content-Security-Policy', ''))

    def test_login_wrong_password(self):
        with app.app_context():
            from models import User
            from werkzeug.security import generate_password_hash
            user = User(username='testuser', password_hash=generate_password_hash('correct'))
            db.session.add(user)
            db.session.commit()
        response = self.client.post('/api/auth/login',
            json={'username': 'testuser', 'password': 'wrong'},
            content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_portfolio_requires_auth(self):
        response = self.client.get('/portfolio')
        self.assertIn(response.status_code, [302, 401])

    def test_upload_folder_config(self):
        self.assertTrue(app.config['UPLOAD_FOLDER'].endswith(('static\\avatars', 'static/avatars')))

    def test_api_init_response(self):
        response = self.client.get('/api/init')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn('visits', data)
        self.assertIn('is_authenticated', data)

    def test_config_security_settings(self):
        self.assertEqual(app.config['MAX_CONTENT_LENGTH'], 5 * 1024 * 1024)
        self.assertIn('png', app.config['ALLOWED_EXTENSIONS'])
        self.assertIn('jpg', app.config['ALLOWED_EXTENSIONS'])
        self.assertTrue(app.config['SESSION_COOKIE_HTTPONLY'])
        self.assertEqual(app.config['SESSION_COOKIE_SAMESITE'], 'Lax')

    def test_large_file_error_handler(self):
        with app.test_request_context('/api/init'):
            error = RequestEntityTooLarge()
            response = app.handle_user_exception(error)
            self.assertEqual(response.status_code, 413)
            payload = response.get_json()
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload.get('message'), 'Загруженный файл слишком велик. Максимальный размер — 5 МБ.')


if __name__ == '__main__':
    unittest.main()
