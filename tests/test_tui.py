import asyncio
import os
import tempfile

import pytest

from textual.widgets import DataTable, Input, Select

from durst.db import DurstDB
from durst.tui import AddUserScreen, BuyScreen, DurstApp


@pytest.fixture
def db_path():
    """Create a temporary database file path for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def populated_db_path(db_path: str):
    """A database file with users, drinks, stock, and one purchase."""
    db = DurstDB(db_file=db_path)
    alice = db.add_user("Alice", "alice@example.com", verbose=False)
    db.add_user("Bob", "bob@example.com", verbose=False)
    cola = db.add_drink_type("Cola", "CocaCola", verbose=False)
    assert alice is not None and cola is not None
    db.stock_new_drinks(
        alice,
        36.0,
        [{"drink_type_id": cola, "cost_per_item": 1.50, "quantity": 24}],
        verbose=False,
    )
    db.add_purchase("Bob", "Cola")
    return db_path


class TestEmptyDatabase:
    def test_tables_render_with_headers(self, db_path: str):
        """All tabs should show column headers even with no data."""

        async def run() -> None:
            app = DurstApp(db_file=db_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                for table_id, n_columns in [
                    ("#purchases-table", 6),
                    ("#stock-table", 3),
                    ("#balances-table", 3),
                    ("#debts-table", 3),
                ]:
                    table = app.query_one(table_id, DataTable)
                    assert len(table.columns) == n_columns
                    assert table.row_count == 0

        asyncio.run(run())

    def test_buy_without_users_warns(self, db_path: str):
        """Pressing 'b' with no users should not open the buy dialog."""

        async def run() -> None:
            app = DurstApp(db_file=db_path)
            async with app.run_test() as pilot:
                await pilot.press("b")
                await pilot.pause()
                assert not isinstance(app.screen, BuyScreen)

        asyncio.run(run())


class TestPopulatedDatabase:
    def test_tables_show_data(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.query_one("#purchases-table", DataTable).row_count == 1
                assert app.query_one("#stock-table", DataTable).row_count == 1
                assert app.query_one("#balances-table", DataTable).row_count == 2
                assert app.query_one("#debts-table", DataTable).row_count == 1

        asyncio.run(run())

    def test_buy_dialog_opens_and_cancels(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.press("b")
                await pilot.pause()
                assert isinstance(app.screen, BuyScreen)
                await pilot.click("#buy-cancel")
                await pilot.pause()
                assert not isinstance(app.screen, BuyScreen)

        asyncio.run(run())

    def test_buy_flow_records_purchase(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.press("b")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, BuyScreen)
                screen.query_one("#buy-user", Select).value = "Bob"
                screen.query_one("#buy-drink", Select).value = "Cola"
                await pilot.click("#buy-confirm")
                await pilot.pause()
                assert app.query_one("#purchases-table", DataTable).row_count == 2

            db = DurstDB(db_file=populated_db_path)
            bob = db.get_user_by_name("Bob")
            assert bob is not None
            assert abs(bob.balance - (-3.00)) < 0.01

        asyncio.run(run())

    def test_add_user_flow(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.press("u")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, AddUserScreen)
                screen.query_one("#user-name", Input).value = "Charlie"
                screen.query_one("#user-email", Input).value = "charlie@example.com"
                await pilot.click("#user-confirm")
                await pilot.pause()
                assert app.query_one("#balances-table", DataTable).row_count == 3

            db = DurstDB(db_file=populated_db_path)
            assert db.get_user_by_name("Charlie") is not None

        asyncio.run(run())

    def test_add_duplicate_email_rejected(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.press("u")
                await pilot.pause()
                screen = app.screen
                assert isinstance(screen, AddUserScreen)
                screen.query_one("#user-name", Input).value = "Impostor"
                screen.query_one("#user-email", Input).value = "alice@example.com"
                await pilot.click("#user-confirm")
                await pilot.pause()
                # Still only Alice and Bob.
                assert app.query_one("#balances-table", DataTable).row_count == 2

        asyncio.run(run())

    def test_refresh_binding(self, populated_db_path: str):
        async def run() -> None:
            app = DurstApp(db_file=populated_db_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                # Add data behind the app's back, then refresh.
                db = DurstDB(db_file=populated_db_path)
                db.add_purchase("Bob", "Cola")
                await pilot.press("r")
                await pilot.pause()
                assert app.query_one("#purchases-table", DataTable).row_count == 2

        asyncio.run(run())
