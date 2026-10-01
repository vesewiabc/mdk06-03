"""Авторизация, rate-limit, смена пароля, роли, аудит."""
import pytest

from tests.conftest import DEMO_PASSWORDS, login


class TestLogin:
    def test_wrong_password(self, client):
        r = client.post("/auth/login",
                        data={"username": "admin", "password": "nope"})
        assert r.status_code == 200
        assert "Неверный логин" in r.get_data(as_text=True)

    def test_unknown_user(self, client):
        r = client.post("/auth/login",
                        data={"username": "ghost", "password": "ghostpass12"})
        assert "Неверный логин" in r.get_data(as_text=True)

    def test_success_admin_redirects_to_index(self, client):
        r = login(client, "admin")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/")

    def test_success_waiter(self, client):
        r = login(client, "waiter1")
        assert r.status_code == 302

    def test_open_redirect_blocked(self, client):
        r = client.post(
            "/auth/login",
            data={"username": "admin", "password": DEMO_PASSWORDS["admin"],
                  "next": "//evil.com"},
        )
        assert r.status_code == 302
        assert "evil.com" not in r.headers["Location"]

    @pytest.mark.slow
    def test_rate_limit_blocks_after_failures(self, client):
        for _ in range(6):
            client.post("/auth/login",
                        data={"username": "admin", "password": "wrong"})
        r = client.post("/auth/login",
                        data={"username": "admin", "password": "wrong"})
        assert r.status_code == 429
        assert "Слишком много попыток" in r.get_data(as_text=True)


class TestLogout:
    def test_logout_clears_session(self, client):
        login(client, "admin")
        r = client.post("/auth/logout")
        assert r.status_code == 302
        r2 = client.get("/")
        assert r2.status_code == 302
        assert "/auth/login" in r2.headers["Location"]

    def test_logout_requires_post(self, client):
        login(client, "admin")
        r = client.get("/auth/logout")
        assert r.status_code == 405


class TestChangePassword:
    def test_success_and_forced_logout(self, client):
        login(client, "admin")
        r = client.post(
            "/auth/change-password",
            data={
                "old_password": DEMO_PASSWORDS["admin"],
                "new_password": "Fresh-Veggies-2025",
                "new_password_confirm": "Fresh-Veggies-2025",
            },
        )
        assert r.status_code == 302
        assert "/auth/login" in r.headers["Location"]
        r2 = login(client, "admin", password="Fresh-Veggies-2025")
        assert r2.status_code == 302

    def test_wrong_old_password(self, client):
        login(client, "admin")
        r = client.post(
            "/auth/change-password",
            data={"old_password": "wrong",
                  "new_password": "AnotherGood12345",
                  "new_password_confirm": "AnotherGood12345"},
        )
        assert r.status_code == 400

    def test_new_equals_old_rejected(self, client):
        login(client, "admin")
        r = client.post(
            "/auth/change-password",
            data={"old_password": DEMO_PASSWORDS["admin"],
                  "new_password": DEMO_PASSWORDS["admin"],
                  "new_password_confirm": DEMO_PASSWORDS["admin"]},
        )
        assert r.status_code == 400


class TestRoles:
    def test_waiter_cannot_open_admin_pages(self, client):
        login(client, "waiter1")
        r = client.get("/auth/users")
        assert r.status_code == 302

    def test_anonymous_redirected_to_login(self, client):
        for url in ["/", "/orders/", "/warehouse/", "/admin/db", "/auth/users"]:
            r = client.get(url)
            assert r.status_code == 302, url
            assert "/auth/login" in r.headers["Location"], url


class TestAuditLog:
    def test_admin_can_view_audit(self, client):
        login(client, "admin")
        r = client.get("/auth/audit")
        assert r.status_code == 200
        assert "Журнал аудита" in r.get_data(as_text=True)

    def test_login_is_audited(self, client, app, db):
        login(client, "admin")
        with app.app_context():
            row = db.execute(
                "SELECT action FROM audit_log WHERE action LIKE '%Вход%' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert row is not None
            assert "admin" in row["action"]