import asyncio

import pytest

from durst.db import DurstDB
from durst.tui import ConfirmScreen, DurstApp, PickScreen, RegisterScreen, VimTable

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBzR0cJjLhZ7bG2oJ0n8yDJ1V8wX6kYwqQ6c6w2Zr6kM new"


@pytest.fixture
def db_path(tmp_path):
    """A database with Alice (admin), Bob, and 24 Colas."""
    path = str(tmp_path / "t.db")
    db = DurstDB(db_file=path)
    alice = db.add_user("Alice", "alice@example.com", verbose=False)
    db.add_user("Bob", "bob@example.com", verbose=False)
    db.set_role("Alice", "admin")
    cola = db.add_drink_type("Cola", verbose=False)
    assert alice and cola
    db.stock_new_drinks(
        alice, 36.0, [{"drink_type_id": cola, "cost_per_item": 1.5, "quantity": 24}], verbose=False
    )
    return path


def run(app: DurstApp, steps):
    async def go():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await steps(app, pilot)

    asyncio.run(go())


def test_tables_and_vim_navigation(db_path):
    async def steps(app, pilot):
        assert app.query_one("#drinks", VimTable).row_count == 1
        await pilot.press("l")  # next tab: balances
        table = app.query_one("#balances", VimTable)
        assert app.screen.focused is table and table.row_count == 2
        await pilot.press("j")
        assert table.cursor_row == 1
        await pilot.press("g")
        assert table.cursor_row == 0
        await pilot.press("right", "right")
        assert app.tabs[app.tab][0] == "approvals"  # local runs are admin
        await pilot.press("left")
        assert app.tabs[app.tab][0] == "history"
        await pilot.press("question_mark")
        assert app.full_help

    run(DurstApp(db_path), steps)


def test_member_buys_for_themselves(db_path):
    async def steps(app, pilot):
        await pilot.press("b")
        assert isinstance(app.screen, PickScreen)  # straight to drinks, no user list
        assert app.screen.title_text == "What are you drinking?"
        await pilot.press("enter")
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("y")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob"), steps)
    assert DurstDB(db_file=db_path).get_user_by_name("Bob").balance == -1.5


def test_cancel_buy_records_nothing(db_path):
    async def steps(app, pilot):
        await pilot.press("b", "enter", "n")
        await pilot.pause()
        assert not isinstance(app.screen, (PickScreen, ConfirmScreen))

    run(DurstApp(db_path, user="Bob"), steps)
    assert DurstDB(db_file=db_path).get_recent_purchases() == []


def test_admin_buys_for_others(db_path):
    async def steps(app, pilot):
        await pilot.press("b")
        assert app.screen.title_text == "Who is drinking?"
        await pilot.press("j", "enter", "enter", "enter")  # Bob, Cola, Yes
        await pilot.pause()

    run(DurstApp(db_path, user="Alice"), steps)
    assert DurstDB(db_file=db_path).get_user_by_name("Bob").balance == -1.5


def test_guest_registers_and_admin_approves(db_path):
    async def register(app, pilot):
        assert not app.check_action("buy", ())
        await pilot.press("r")
        assert isinstance(app.screen, RegisterScreen)
        await pilot.press(*"Carla", "enter", "enter")
        await pilot.pause()
        assert app.pending
        assert not app.check_action("register", ())

    run(DurstApp(db_path, guest=True, key=KEY), register)
    db = DurstDB(db_file=db_path)
    assert db.get_user_by_ssh_key(KEY) is None
    assert [u.name for u in db.get_all_users()] == ["Alice", "Bob"]  # not approved yet

    async def approve(app, pilot):
        assert "Approvals (1)" in [label for _, label in app.tabs]
        await pilot.press("4")
        assert app.check_action("approve", ())
        await pilot.press("a")
        await pilot.pause()

    run(DurstApp(db_path, user="Alice"), approve)
    assert db.get_user_by_ssh_key(KEY).name == "Carla"


def test_claiming_an_account_and_rejecting(db_path):
    db = DurstDB(db_file=db_path)
    assert db.register("Bob", None, KEY) is True  # claims the existing Bob
    assert db.get_pending_keys()[0]["new_user"] is False

    async def reject(app, pilot):
        assert not app.check_action("approve", ())  # Bob is not an admin
        assert len(app.tabs) == 3

    run(DurstApp(db_path, user="Bob"), reject)
    db.reject_key(db.get_pending_keys()[0]["key"])
    assert db.get_pending_keys() == [] and db.get_user_by_name("Bob")  # Bob survives
