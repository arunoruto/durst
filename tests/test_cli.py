import os
import tempfile

import pytest
from click.testing import CliRunner

from durst.cli import cli
from durst.db import DurstDB


@pytest.fixture
def db_path():
    """Create a temporary database file path for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def runner():
    return CliRunner()


def invoke(runner: CliRunner, db_path: str, *args: str):
    """Invoke the CLI against the temporary database."""
    return runner.invoke(cli, ["--db", db_path, *args])


@pytest.fixture
def populated_db_path(runner: CliRunner, db_path: str):
    """A database path with users, drinks, and stock set up via the CLI."""
    invoke(runner, db_path, "user", "add", "Alice", "alice@example.com")
    invoke(runner, db_path, "user", "add", "Bob", "bob@example.com")
    invoke(runner, db_path, "drink", "add", "Cola", "--brand", "CocaCola")
    invoke(runner, db_path, "drink", "add", "Sprite", "--brand", "CocaCola")
    invoke(
        runner,
        db_path,
        "stock",
        "add",
        "Alice",
        "-i",
        "Cola:1.50:24",
        "-i",
        "Sprite:1.25:12",
    )
    return db_path


class TestUserCommands:
    def test_user_add(self, runner, db_path):
        result = invoke(runner, db_path, "user", "add", "Alice", "alice@example.com")
        assert result.exit_code == 0
        assert "Added user Alice" in result.output

    def test_user_add_duplicate_email(self, runner, db_path):
        invoke(runner, db_path, "user", "add", "Alice", "alice@example.com")
        result = invoke(runner, db_path, "user", "add", "Alice2", "alice@example.com")
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_user_list(self, runner, db_path):
        invoke(runner, db_path, "user", "add", "Alice", "alice@example.com")
        invoke(runner, db_path, "user", "add", "Bob", "bob@example.com")
        result = invoke(runner, db_path, "user", "list")
        assert result.exit_code == 0
        assert "Alice" in result.output
        assert "Bob" in result.output

    def test_user_list_empty(self, runner, db_path):
        result = invoke(runner, db_path, "user", "list")
        assert result.exit_code == 0
        assert "(no entries)" in result.output

    def test_user_balance(self, runner, db_path):
        invoke(runner, db_path, "user", "add", "Alice", "alice@example.com")
        result = invoke(runner, db_path, "user", "balance", "Alice")
        assert result.exit_code == 0
        assert "0.00" in result.output
        assert "settled" in result.output

    def test_user_balance_unknown_user(self, runner, db_path):
        result = invoke(runner, db_path, "user", "balance", "Nobody")
        assert result.exit_code != 0
        assert "User not found" in result.output


class TestDrinkCommands:
    def test_drink_add(self, runner, db_path):
        result = invoke(runner, db_path, "drink", "add", "Cola", "--brand", "CocaCola")
        assert result.exit_code == 0
        assert "Added drink type 'Cola'" in result.output

    def test_drink_add_duplicate(self, runner, db_path):
        invoke(runner, db_path, "drink", "add", "Cola")
        result = invoke(runner, db_path, "drink", "add", "Cola")
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_drink_list(self, runner, db_path):
        invoke(runner, db_path, "drink", "add", "Cola", "--brand", "CocaCola")
        invoke(runner, db_path, "drink", "add", "Mate")
        result = invoke(runner, db_path, "drink", "list")
        assert result.exit_code == 0
        assert "Cola" in result.output
        assert "Mate" in result.output


class TestStockCommands:
    def test_stock_add(self, runner, populated_db_path):
        result = invoke(
            runner, populated_db_path, "stock", "add", "Alice", "-i", "Cola:1.50:24"
        )
        assert result.exit_code == 0
        assert "Alice stocked 1 item(s)" in result.output
        assert "36.00" in result.output

    def test_stock_add_explicit_total(self, runner, populated_db_path):
        result = invoke(
            runner,
            populated_db_path,
            "stock",
            "add",
            "Alice",
            "-i",
            "Cola:1.50:24",
            "--total-cost",
            "40.0",
        )
        assert result.exit_code == 0
        assert "40.00" in result.output

    def test_stock_add_unknown_orderer(self, runner, populated_db_path):
        result = invoke(
            runner, populated_db_path, "stock", "add", "Nobody", "-i", "Cola:1.50:24"
        )
        assert result.exit_code != 0
        assert "User not found" in result.output

    def test_stock_add_unknown_drink(self, runner, populated_db_path):
        result = invoke(
            runner, populated_db_path, "stock", "add", "Alice", "-i", "Water:1.00:10"
        )
        assert result.exit_code != 0
        assert "Drink type not found" in result.output

    def test_stock_add_bad_item_format(self, runner, populated_db_path):
        result = invoke(
            runner, populated_db_path, "stock", "add", "Alice", "-i", "Cola:24"
        )
        assert result.exit_code != 0
        assert "DRINK:PRICE:QTY" in result.output

    def test_stock_add_bad_item_values(self, runner, populated_db_path):
        result = invoke(
            runner, populated_db_path, "stock", "add", "Alice", "-i", "Cola:cheap:24"
        )
        assert result.exit_code != 0

    def test_stock_status(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "stock", "status")
        assert result.exit_code == 0
        assert "Cola" in result.output
        assert "24" in result.output
        assert "Sprite" in result.output
        assert "12" in result.output


class TestBuyCommand:
    def test_buy(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "buy", "Bob", "Cola")
        assert result.exit_code == 0
        assert "Bob bought 1 x Cola" in result.output
        assert "-1.50" in result.output

    def test_buy_multiple(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "buy", "Bob", "Cola", "--count", "3")
        assert result.exit_code == 0
        assert "Bob bought 3 x Cola" in result.output
        assert "-4.50" in result.output

    def test_buy_updates_stock(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "buy", "Bob", "Sprite")
        result = invoke(runner, populated_db_path, "stock", "status")
        assert "11" in result.output

    def test_buy_unknown_user(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "buy", "Nobody", "Cola")
        assert result.exit_code != 0
        assert "User not found" in result.output

    def test_buy_unknown_drink(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "buy", "Bob", "Water")
        assert result.exit_code != 0
        assert "Drink type not found" in result.output

    def test_buy_no_stock(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "drink", "add", "Water")
        result = invoke(runner, populated_db_path, "buy", "Bob", "Water")
        assert result.exit_code != 0
        assert "No stock available" in result.output

    def test_buy_partially_out_of_stock(self, runner, populated_db_path):
        # Only 12 Sprite in stock; buying 15 should record 12 then fail.
        result = invoke(
            runner, populated_db_path, "buy", "Bob", "Sprite", "--count", "15"
        )
        assert result.exit_code != 0
        assert "Recorded 12 of 15" in result.output


class TestRepayCommand:
    def test_repay(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "buy", "Bob", "Cola")
        result = invoke(runner, populated_db_path, "repay", "Bob", "Alice", "1.50")
        assert result.exit_code == 0
        assert "Bob paid 1.50 € to Alice" in result.output

        balance = invoke(runner, populated_db_path, "user", "balance", "Bob")
        assert "0.00" in balance.output
        assert "settled" in balance.output

    def test_repay_negative_amount(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "repay", "Bob", "Alice", "--", "-5")
        assert result.exit_code != 0
        assert "Amount must be positive" in result.output

    def test_repay_self(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "repay", "Bob", "Bob", "5")
        assert result.exit_code != 0
        assert "must be different" in result.output

    def test_repay_unknown_user(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "repay", "Nobody", "Alice", "5")
        assert result.exit_code != 0
        assert "User not found" in result.output


class TestReportingCommands:
    def test_history(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "buy", "Bob", "Cola")
        invoke(runner, populated_db_path, "buy", "Bob", "Sprite")
        result = invoke(runner, populated_db_path, "history")
        assert result.exit_code == 0
        assert "Cola" in result.output
        assert "Sprite" in result.output
        assert "Bob" in result.output

    def test_history_empty(self, runner, populated_db_path):
        result = invoke(runner, populated_db_path, "history")
        assert result.exit_code == 0
        assert "(no entries)" in result.output

    def test_history_limit(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "buy", "Bob", "Cola", "--count", "5")
        result = invoke(runner, populated_db_path, "history", "--limit", "2")
        assert result.exit_code == 0
        # Header + separator + 2 rows
        assert len(result.output.strip().splitlines()) == 4

    def test_debts(self, runner, populated_db_path):
        invoke(runner, populated_db_path, "buy", "Bob", "Cola")
        result = invoke(runner, populated_db_path, "debts")
        assert result.exit_code == 0
        assert "Bob" in result.output
        assert "Alice" in result.output
        assert "1.50" in result.output


class TestDatabaseCreation:
    def test_db_file_created(self, runner, tmp_path):
        db_file = tmp_path / "fresh.db"
        result = runner.invoke(cli, ["--db", str(db_file), "user", "list"])
        assert result.exit_code == 0
        assert db_file.exists()
        # The schema should be usable right away.
        db = DurstDB(db_file=str(db_file))
        assert db.get_all_users() == []
