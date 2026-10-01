"""Жизненный цикл заказа: открытие, позиции, отправка, оплата, отмена."""
import pytest

from tests.conftest import login


def _open_order_for_table(client, table_id):
    return client.post(f"/orders/table/{table_id}/open",
                       data={"guests": "2"}, follow_redirects=False)


def _extract_order_id(location: str) -> int:
    # .../orders/<id>
    return int(location.rstrip("/").rsplit("/", 1)[-1])


class TestOrderLifecycle:
    def test_waiter_opens_and_sees_tables(self, client):
        login(client, "waiter1")
        r = client.get("/orders/")
        assert r.status_code == 200
        r = _open_order_for_table(client, 1)
        assert r.status_code == 302
        oid = _extract_order_id(r.headers["Location"])

        detail = client.get(f"/orders/{oid}")
        assert detail.status_code == 200
        assert "Заказ" in detail.get_data(as_text=True)

    def test_add_item(self, client, app, db):
        login(client, "waiter1")
        r = _open_order_for_table(client, 2)
        oid = _extract_order_id(r.headers["Location"])

        client.post(f"/orders/{oid}/add_item",
                    data={"dish_id": "1", "qty": "2"},
                    follow_redirects=True)

        with app.app_context():
            n = db.execute(
                "SELECT COUNT(*) AS c FROM order_items WHERE order_id = ?",
                (oid,),
            ).fetchone()["c"]
            assert n == 1

    def test_send_to_kitchen_writes_off_stock(self, client, app, db):
        login(client, "waiter1")
        r = _open_order_for_table(client, 3)
        oid = _extract_order_id(r.headers["Location"])

        # Блюдо 1 «Цезарь» — есть техкарта (ингредиенты 6, 5, 2).
        client.post(f"/orders/{oid}/add_item",
                    data={"dish_id": "1", "qty": "1"})
        with app.app_context():
            before = dict(db.execute(
                "SELECT id, stock_qty FROM ingredients WHERE id IN (6,5,2)"
            ).fetchall() and {
                row["id"]: row["stock_qty"] for row in
                db.execute("SELECT id, stock_qty FROM ingredients WHERE id IN (6,5,2)").fetchall()
            })

        r = client.post(f"/orders/{oid}/send", follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            after = {
                row["id"]: row["stock_qty"] for row in
                db.execute("SELECT id, stock_qty FROM ingredients WHERE id IN (6,5,2)").fetchall()
            }
            # Списание произошло.
            assert after[6] < before[6]
            # Статус заказа — sent.
            st = db.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()["status"]
            assert st == "sent"
            # Есть движения склада с reason='order'.
            n = db.execute(
                "SELECT COUNT(*) AS c FROM stock_movements "
                "WHERE reason='order' AND comment LIKE ?", (f"%Заказ #{oid}%",),
            ).fetchone()["c"]
            assert n >= 1

    def test_pay_requires_served_items(self, client, app, db):
        login(client, "waiter1")
        r = _open_order_for_table(client, 4)
        oid = _extract_order_id(r.headers["Location"])
        client.post(f"/orders/{oid}/add_item",
                    data={"dish_id": "1", "qty": "1"})
        client.post(f"/orders/{oid}/send")

        # Позиции ещё cooking → оплата должна быть отклонена.
        r = client.post(f"/orders/{oid}/pay", follow_redirects=True)
        assert "не поданы" in r.get_data(as_text=True)

    def test_full_happy_path(self, client, app, db):
        login(client, "waiter1")
        r = _open_order_for_table(client, 5)
        oid = _extract_order_id(r.headers["Location"])
        client.post(f"/orders/{oid}/add_item",
                    data={"dish_id": "10", "qty": "1"})  # Капучино
        client.post(f"/orders/{oid}/send")

        with app.app_context():
            item_id = db.execute(
                "SELECT id FROM order_items WHERE order_id = ?", (oid,)
            ).fetchone()["id"]
            # Повар/бармен: bar-позиция — нужен бармен.
        client.post("/auth/logout")
        login(client, "bartender1")
        client.post(f"/orders/item/{item_id}/status", data={"status": "ready"})

        client.post("/auth/logout")
        login(client, "waiter1")
        client.post(f"/orders/item/{item_id}/status", data={"status": "served"})
        r = client.post(f"/orders/{oid}/pay", follow_redirects=True)
        assert r.status_code == 200

        with app.app_context():
            o = db.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
            assert o["status"] == "paid"
            t = db.execute("SELECT status FROM restaurant_tables WHERE id = 5").fetchone()
            assert t["status"] == "free"


class TestOrderOwnership:
    def test_waiter_cannot_touch_foreign_order(self, client, app, db):
        # admin открывает заказ №6, waiter1 пытается читать.
        login(client, "admin")
        r = _open_order_for_table(client, 6)
        oid = _extract_order_id(r.headers["Location"])
        client.post("/auth/logout")

        login(client, "waiter1")
        r = client.get(f"/orders/{oid}", follow_redirects=False)
        assert r.status_code == 302  # редирект «это чужой заказ»


class TestCancelRestoresStock:
    def test_cancel_after_send_restores_stock(self, client, app, db):
        login(client, "waiter1")
        r = _open_order_for_table(client, 7)
        oid = _extract_order_id(r.headers["Location"])
        client.post(f"/orders/{oid}/add_item", data={"dish_id": "1", "qty": "2"})
        client.post(f"/orders/{oid}/send")

        with app.app_context():
            before = {row["id"]: row["stock_qty"] for row in
                      db.execute("SELECT id, stock_qty FROM ingredients WHERE id IN (6,5,2)").fetchall()}

        client.post(f"/orders/{oid}/cancel", follow_redirects=True)

        with app.app_context():
            after = {row["id"]: row["stock_qty"] for row in
                     db.execute("SELECT id, stock_qty FROM ingredients WHERE id IN (6,5,2)").fetchall()}
            # Склад восстановлен.
            for k in before:
                assert after[k] == pytest.approx(before[k], abs=1e-6)
            st = db.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()["status"]
            assert st == "cancelled"