"""Склад: движения, заявки, инвентаризация."""
from tests.conftest import login


class TestStock:
    def test_storekeeper_sees_stock(self, client):
        login(client, "storekeeper1")
        r = client.get("/warehouse/")
        assert r.status_code == 200

    def test_receipt_increases_stock(self, client, app, db):
        login(client, "storekeeper1")
        with app.app_context():
            before = db.execute(
                "SELECT stock_qty FROM ingredients WHERE id = 1"
            ).fetchone()["stock_qty"]
        r = client.post("/warehouse/1/movement",
                        data={"reason": "receipt", "qty": "10"},
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            after = db.execute(
                "SELECT stock_qty FROM ingredients WHERE id = 1"
            ).fetchone()["stock_qty"]
            assert after == before + 10

    def test_writeoff_more_than_stock_rejected(self, client, app, db):
        login(client, "storekeeper1")
        with app.app_context():
            before = db.execute(
                "SELECT stock_qty FROM ingredients WHERE id = 1"
            ).fetchone()["stock_qty"]
        client.post("/warehouse/1/movement",
                    data={"reason": "writeoff", "qty": str(before + 1000)},
                    follow_redirects=True)
        with app.app_context():
            after = db.execute(
                "SELECT stock_qty FROM ingredients WHERE id = 1"
            ).fetchone()["stock_qty"]
            assert after == before  # ничего не изменилось

    def test_inventory_requires_comment(self, client):
        login(client, "storekeeper1")
        r = client.post("/warehouse/1/movement",
                        data={"reason": "inventory", "qty": "5"},
                        follow_redirects=True)
        assert "комментар" in r.get_data(as_text=True).lower()

    def test_inventory_sets_absolute_value(self, client, app, db):
        login(client, "storekeeper1")
        client.post("/warehouse/1/movement",
                    data={"reason": "inventory", "qty": "7", "comment": "пересчёт"},
                    follow_redirects=True)
        with app.app_context():
            v = db.execute("SELECT stock_qty FROM ingredients WHERE id = 1").fetchone()["stock_qty"]
            assert v == 7


class TestRequests:
    def test_storekeeper_creates_request(self, client, app, db):
        login(client, "storekeeper1")
        client.post("/warehouse/requests/new",
                    data={"ingredient_id": "1", "qty": "5"},
                    follow_redirects=True)
        with app.app_context():
            n = db.execute("SELECT COUNT(*) AS c FROM restock_requests").fetchone()["c"]
            assert n == 1

    def test_done_request_increases_stock(self, client, app, db):
        login(client, "storekeeper1")
        client.post("/warehouse/requests/new",
                    data={"ingredient_id": "1", "qty": "5"})
        with app.app_context():
            rid = db.execute(
                "SELECT id FROM restock_requests ORDER BY id DESC LIMIT 1"
            ).fetchone()["id"]
            before = db.execute("SELECT stock_qty FROM ingredients WHERE id = 1").fetchone()["stock_qty"]

        client.post(f"/warehouse/requests/{rid}/status",
                    data={"status": "done"}, follow_redirects=True)
        with app.app_context():
            after = db.execute("SELECT stock_qty FROM ingredients WHERE id = 1").fetchone()["stock_qty"]
            assert after == before + 5