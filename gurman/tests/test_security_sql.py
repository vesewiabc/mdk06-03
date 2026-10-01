"""Защита SQL-консоли, security headers, CSRF."""
import pytest

from tests.conftest import login


class TestSQLConsole:
    @pytest.mark.parametrize("sql,ok", [
        ("SELECT 1", True),
        ("select * from users limit 1", True),
        ("WITH x AS (SELECT 1) SELECT * FROM x", True),
        ("SELECT * FROM users; DROP TABLE users;", False),
        ("INSERT INTO users (username) VALUES ('x')", False),
        ("UPDATE users SET role='admin'", False),
        ("DELETE FROM users", False),
        ("DROP TABLE users", False),
        ("ATTACH DATABASE '/etc/passwd' AS p", False),
        ("PRAGMA writable_schema = 1", False),
        ("  -- comment\nSELECT 1", True),
        ("/* x */ SELECT 1", True),
    ])
    def test_select_only_gatekeeper(self, sql, ok):
        from blueprints.admin import _is_select_only
        passed, _ = _is_select_only(sql)
        assert passed is ok, sql

    def test_non_admin_redirected(self, client):
        login(client, "waiter1")
        r = client.get("/admin/db")
        assert r.status_code == 302

    def test_admin_can_list_tables(self, client):
        login(client, "admin")
        r = client.get("/admin/db")
        assert r.status_code == 200
        assert b"users" in r.data

    def test_admin_select_executes(self, client):
        login(client, "admin")
        r = client.post("/admin/db/query", data={"sql": "SELECT 1 AS x"})
        assert r.status_code == 200
        assert b"x" in r.data

    def test_admin_write_rejected(self, client, app, db):
        login(client, "admin")
        r = client.post("/admin/db/query",
                        data={"sql": "DELETE FROM users"},
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            n = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            assert n > 0  # ничего не удалено


class TestSecurityHeaders:
    def test_headers_present_on_login(self, client):
        r = client.get("/auth/login")
        h = r.headers
        assert h.get("X-Content-Type-Options") == "nosniff"
        assert h.get("X-Frame-Options") == "DENY"
        assert h.get("Referrer-Policy") == "no-referrer"
        assert "default-src 'self'" in h.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in h.get("Content-Security-Policy", "")

    def test_no_store_on_authenticated_pages(self, client):
        login(client, "admin")
        r = client.get("/")
        assert "no-store" in r.headers.get("Cache-Control", "")


class TestCSRFProtection:
    """Отдельная проверка, что CSRF действительно включён (в prod)."""

    def test_csrf_enabled_blocks_post_without_token(self, tmp_path, monkeypatch):
        # Собираем приложение с включённым CSRF и своим SECRET_KEY.
        import config as config_module
        from app import create_app
        from config import Config

        monkeypatch.setattr(Config, "DATABASE", str(tmp_path / "csrf.db"))
        monkeypatch.setattr(config_module.Config, "DATABASE", str(tmp_path / "csrf.db"))
        app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SECRET_KEY": "x" * 32,
            "SHOW_DEMO_ACCOUNTS": True,
        })
        c = app.test_client()
        # POST без CSRF-токена → 400.
        r = c.post("/auth/login",
                   data={"username": "admin", "password": "admin123456"})
        assert r.status_code == 400


class TestErrorPages:
    def test_404(self, client):
        r = client.get("/definitely-not-here")
        assert r.status_code == 404

    def test_405(self, client):
        r = client.get("/auth/logout")
        assert r.status_code == 405