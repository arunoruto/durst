import asyncio
import datetime as dt

import pytest

from durst.db import DurstDB, can_undo
from durst.tui import ConfirmScreen, DurstApp, FormScreen, PickScreen, VimTable, parse_day

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
        assert app.tabs[app.tab][0] == "stats"
        await pilot.press("j", "right")  # the stats page scrolls, arrows still switch tabs
        assert app.tabs[app.tab][0] == "approvals"  # local runs are admin
        await pilot.press("left", "left")
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


def test_count_prefix_takes_several(db_path):
    async def steps(app, pilot):
        await pilot.press("b", "2", "enter")
        assert "2× Cola" in app.screen.question
        await pilot.press("y")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob"), steps)
    assert DurstDB(db_file=db_path).get_user_by_name("Bob").balance == -3.0


def test_catch_up_tallies_drinks_for_an_earlier_day(db_path):
    db = DurstDB(db_file=db_path)
    db.restock("Mate", 10, 10.0, "Alice")

    async def steps(app, pilot):
        await pilot.press("c")
        assert isinstance(app.screen, FormScreen)
        await pilot.press("enter")  # "yesterday" is filled in
        await pilot.press("3", "enter")  # 3× Cola, back to the list
        assert "3× Cola" in app.screen.title_text
        await pilot.press("j", "enter", "escape")  # 1× Mate, done
        assert "3× Cola, 1× Mate" in app.screen.question
        await pilot.press("y")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob"), steps)
    mine = [p for p in db.get_recent_purchases() if p["user_name"] == "Bob"]
    yesterday = str(dt.date.today() - dt.timedelta(days=1))
    assert sorted(p["drink_name"] for p in mine) == ["Cola", "Cola", "Cola", "Mate"]
    assert {p["purchase_date"] for p in mine} == {f"{yesterday} 12:00:00"}
    assert all(can_undo(p, "Bob", False) for p in mine)  # typed in just now
    assert db.get_user_by_name("Bob").balance == -5.5


def test_parse_day():
    today = dt.date(2026, 1, 10)
    assert parse_day("gestern", today) == dt.date(2026, 1, 9)
    assert parse_day("3.1.", today) == dt.date(2026, 1, 3)
    assert parse_day("28.12.", today) == dt.date(2025, 12, 28)  # last year, not the future
    assert parse_day("3.1.26", today) == parse_day("2026-01-03", today) == dt.date(2026, 1, 3)
    assert parse_day("11.1.", today) is None and parse_day("31.2.", today) is None
    assert parse_day("tomorrow", today) is None


def test_add_purchases_is_all_or_nothing(db_path):
    db = DurstDB(db_file=db_path)
    with pytest.raises(ValueError, match="No stock"):
        db.add_purchases("Bob", ["Cola"] * 25)
    with pytest.raises(ValueError, match="hasn't happened"):
        db.add_purchases("Bob", ["Cola"], dt.date.today() + dt.timedelta(days=1))
    assert db.get_recent_purchases() == []


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


def test_guest_without_key_learns_to_make_one(db_path):
    async def steps(app, pilot):
        await pilot.press("r")
        await pilot.pause()
        assert not isinstance(app.screen, FormScreen)
        assert any("ssh-keygen" in str(n.message) for n in app._notifications)

    run(DurstApp(db_path, guest=True), steps)
    assert DurstDB(db_file=db_path).get_pending_keys() == []


def test_guest_registers_and_admin_approves(db_path):
    async def register(app, pilot):
        assert not app.check_action("buy", ())
        await pilot.press("r")
        assert isinstance(app.screen, FormScreen)
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
        await pilot.press("6")  # Drinks, Balances, History, Stats, Me, Approvals
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
        assert [t for t, _ in app.tabs] == ["drinks", "balances", "history", "stats", "me"]

    run(DurstApp(db_path, user="Bob"), reject)
    db.reject_key(db.get_pending_keys()[0]["key"])
    assert db.get_pending_keys() == [] and db.get_user_by_name("Bob")  # Bob survives


def test_me_tab_manages_own_keys_and_email(db_path):
    import asyncssh

    db = DurstDB(db_file=db_path)
    bob = db.get_user_id_by_name("Bob")
    session = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().strip()
    other = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().strip()
    db.add_ssh_key(bob, session + " desktop")

    async def steps(app, pilot):
        await pilot.press("5")
        assert app.tabs[app.tab][0] == "me"
        assert app.check_action("add_key", ()) and not app.check_action("approve", ())
        await pilot.press("n")
        app.screen.query_one("#f0").value = other + " laptop"
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one("#me-keys", VimTable).row_count == 2
        await pilot.press("g", "d")  # first row: the session key ("desktop" < "laptop")
        assert not isinstance(app.screen, ConfirmScreen)  # refused
        await pilot.press("j", "d", "y")
        await pilot.pause()
        assert app.query_one("#me-keys", VimTable).row_count == 1
        await pilot.press("e")
        app.screen.query_one("#f0").value = "bobby@example.com"
        await pilot.press("enter")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob", key=session), steps)
    assert db.get_user_by_name("Bob").email == "bobby@example.com"
    assert [k["label"] for k in db.get_ssh_keys(bob)] == ["desktop"]


def test_keys_cannot_be_taken_from_others(db_path):
    db = DurstDB(db_file=db_path)
    db.add_ssh_key(db.get_user_id_by_name("Alice"), KEY)
    with pytest.raises(ValueError, match="another account"):
        db.add_ssh_key(db.get_user_id_by_name("Bob"), KEY)
    with pytest.raises(ValueError, match="another account"):
        db.register("Mallory", None, KEY)
    with pytest.raises(ValueError, match="OpenSSH public key"):
        db.add_ssh_key(db.get_user_id_by_name("Bob"), "ssh-ed25519 notbase64!!")
    assert db.get_user_by_ssh_key(KEY).name == "Alice"


def test_buy_list_puts_last_taken_first(db_path):
    db = DurstDB(db_file=db_path)
    alice = db.get_user_id_by_name("Alice")
    mate = db.add_drink_type("Mate", verbose=False)
    db.stock_new_drinks(alice, 9.0, [{"drink_type_id": mate, "cost_per_item": 0.9, "quantity": 10}], verbose=False)
    db.add_purchase("Bob", "Mate")
    db.add_purchase("Bob", "Cola")  # Cola last

    async def steps(app, pilot):
        await pilot.press("b")
        assert [i[0] for i in app.screen.items] == ["Cola", "Mate"]

    run(DurstApp(db_path, user="Bob"), steps)
    db.add_purchase("Bob", "Mate")
    run(DurstApp(db_path, user="Bob"), lambda app, pilot: _first_item_is(app, pilot, "Mate"))


async def _first_item_is(app, pilot, drink):
    await pilot.press("b")
    assert app.screen.items[0][0] == drink


def test_admin_restocks_a_new_drink_and_books_a_deposit(db_path):
    async def steps(app, pilot):
        assert app.check_action("restock", ()) and not app.check_action("deposit", ())
        await pilot.press("o")
        assert isinstance(app.screen, FormScreen)
        for i, value in enumerate(["Fritz Kola", "24", "30,00"]):
            app.screen.query_one(f"#f{i}").value = value
        app.screen.query_one("#f3").focus()
        await pilot.press("enter")  # paid by: Kasse (prefilled)
        assert isinstance(app.screen, ConfirmScreen)
        assert "new drink Fritz Kola" in app.screen.question and "1,25 €" in app.screen.question
        await pilot.press("y")
        await pilot.pause()
        await pilot.press("2", "j", "p")  # Balances, Bob
        app.screen.query_one("#f0").value = "10"
        await pilot.press("enter")
        await pilot.pause()

    run(DurstApp(db_path, user="Alice"), steps)
    db = DurstDB(db_file=db_path)
    stock = {s["drink_name"]: s for s in db.get_stock_status()}
    assert stock["Fritz Kola"]["total_remaining"] == 24 and stock["Fritz Kola"]["price"] == 1.25
    assert db.get_user_by_name("Bob").balance == 10


def test_undo_own_recent_drink_only(db_path):
    db = DurstDB(db_file=db_path)
    db.add_purchase("Alice", "Cola")
    db.add_purchase("Bob", "Cola")  # newest: first row in History

    async def steps(app, pilot):
        await pilot.press("3")
        assert app.check_action("undo", ())
        await pilot.press("j", "u")  # Alice's drink: not Bob's to undo
        assert not isinstance(app.screen, ConfirmScreen)
        await pilot.press("g", "u", "y")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob"), steps)
    assert db.get_user_by_name("Bob").balance == 0
    assert db.get_user_by_name("Alice").balance == 0  # -1.50 for her Cola, +1.50 as orderer
    assert {s["drink_name"]: s["total_remaining"] for s in db.get_stock_status()} == {"Cola": 23}


def test_user_asks_for_money_and_admin_confirms(db_path):
    async def ask(app, pilot):
        await pilot.press("5")  # Me
        assert app.check_action("deposit", ())
        await pilot.press("p")
        app.screen.query_one("#f0").value = "10"
        await pilot.press("enter")
        await pilot.pause()

    run(DurstApp(db_path, user="Bob"), ask)
    db = DurstDB(db_file=db_path)
    assert db.get_user_by_name("Bob").balance == 0  # waits for an admin

    async def confirm(app, pilot):
        assert "Approvals (1)" in [label for _, label in app.tabs]
        await pilot.press("6", "a")
        assert "Did you get 10,00 € from Bob?" in app.screen.question
        await pilot.press("y")
        await pilot.pause()

    run(DurstApp(db_path, user="Alice"), confirm)
    assert db.get_user_by_name("Bob").balance == 10
    assert db.get_deposit_requests() == []
