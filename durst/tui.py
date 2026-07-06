from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    TabbedContent,
    TabPane,
)

from durst.db import DurstDB


def money(amount: float) -> Text:
    """Format an amount as colored currency text."""
    if amount > 0:
        style = "green"
    elif amount < 0:
        style = "red"
    else:
        style = ""
    return Text(f"{amount:+.2f} €", style=style, justify="right")


class BuyScreen(ModalScreen[tuple[str, str] | None]):
    """Modal dialog to record a drink purchase."""

    def __init__(self, users: list[str], drinks: list[str]) -> None:
        super().__init__()
        self.users = users
        self.drinks = drinks

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Buy a drink 🍻", classes="dialog-title")
            yield Select(
                [(name, name) for name in self.users],
                prompt="Who is drinking?",
                id="buy-user",
            )
            yield Select(
                [(name, name) for name in self.drinks],
                prompt="Which drink?",
                id="buy-drink",
            )
            with Horizontal(classes="dialog-buttons"):
                yield Button("Buy", variant="success", id="buy-confirm")
                yield Button("Cancel", id="buy-cancel")

    @on(Button.Pressed, "#buy-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#buy-confirm")
    def confirm(self) -> None:
        user = self.query_one("#buy-user", Select).value
        drink = self.query_one("#buy-drink", Select).value
        if user is Select.BLANK or drink is Select.BLANK:
            self.notify("Please select a user and a drink.", severity="warning")
            return
        self.dismiss((str(user), str(drink)))


class AddUserScreen(ModalScreen[tuple[str, str] | None]):
    """Modal dialog to register a new user."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Add a user", classes="dialog-title")
            yield Input(placeholder="Name", id="user-name")
            yield Input(placeholder="Email", id="user-email")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Add", variant="success", id="user-confirm")
                yield Button("Cancel", id="user-cancel")

    @on(Button.Pressed, "#user-cancel")
    def cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#user-confirm")
    def confirm(self) -> None:
        name = self.query_one("#user-name", Input).value.strip()
        email = self.query_one("#user-email", Input).value.strip()
        if not name or "@" not in email:
            self.notify("Please enter a name and a valid email.", severity="warning")
            return
        self.dismiss((name, email))


class DurstApp(App):
    """A TUI for managing soft drinks."""

    TITLE = "Durst"
    SUB_TITLE = "Prost! 🍻"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("b", "buy", "Buy drink"),
        Binding("u", "add_user", "Add user"),
    ]

    CSS = """
    BuyScreen, AddUserScreen {
        align: center middle;
    }

    .dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    .dialog-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .dialog Select, .dialog Input {
        margin-bottom: 1;
    }

    .dialog-buttons {
        height: auto;
        align-horizontal: right;
    }

    .dialog-buttons Button {
        margin-left: 2;
    }
    """

    def __init__(self, db_file: str = "sqlite.db"):
        super().__init__()
        self.db_file = db_file

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with TabbedContent(initial="purchases"):
            with TabPane("Purchases", id="purchases"):
                yield DataTable(id="purchases-table")
            with TabPane("Stock", id="stock"):
                yield DataTable(id="stock-table")
            with TabPane("Balances", id="balances"):
                yield DataTable(id="balances-table")
            with TabPane("Debts", id="debts"):
                yield DataTable(id="debts-table")
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted to the screen."""
        # Ensure the database file and tables are created.
        self.db = DurstDB(db_file=self.db_file)
        for table in self.query(DataTable):
            table.cursor_type = "row"
        self.action_refresh()

    ##########################################
    #             Table Refresh              #
    ##########################################
    def action_refresh(self) -> None:
        """Reload all tables from the database."""
        self._refresh_purchases()
        self._refresh_stock()
        self._refresh_balances()
        self._refresh_debts()

    @staticmethod
    def _fill_table(table: DataTable, headers: list[str], rows: list[tuple]) -> None:
        """Replace the contents of a DataTable with fresh headers and rows."""
        table.clear(columns=True)
        table.add_columns(*headers)
        table.add_rows(rows)

    def _refresh_purchases(self) -> None:
        purchases = self.db.get_recent_purchases(limit=50)
        self._fill_table(
            self.query_one("#purchases-table", DataTable),
            ["#", "User", "Drink", "Cost", "Date", "Ordered by"],
            [
                (
                    p["purchase_id"],
                    p["user_name"],
                    p["drink_name"],
                    f"{p['cost']:.2f} €",
                    p["purchase_date"],
                    p["orderer_name"],
                )
                for p in purchases
            ],
        )

    def _refresh_stock(self) -> None:
        stock = self.db.get_stock_status()
        self._fill_table(
            self.query_one("#stock-table", DataTable),
            ["Drink", "Brand", "Remaining"],
            [(s["drink_name"], s["brand"] or "", s["total_remaining"]) for s in stock],
        )

    def _refresh_balances(self) -> None:
        users = self.db.get_all_users()
        self._fill_table(
            self.query_one("#balances-table", DataTable),
            ["Name", "Email", "Balance"],
            [(u.name, u.email, money(u.balance)) for u in users],
        )

    def _refresh_debts(self) -> None:
        debts = self.db.get_user_debts()
        self._fill_table(
            self.query_one("#debts-table", DataTable),
            ["Debtor", "Creditor", "Owed"],
            [
                (d["debtor_name"], d["creditor_name"], f"{d['amount_owed']:.2f} €")
                for d in debts
            ],
        )

    ##########################################
    #               Actions                  #
    ##########################################
    def action_buy(self) -> None:
        """Open the buy dialog."""
        users = [u.name for u in self.db.get_all_users()]
        drinks = [
            s["drink_name"]
            for s in self.db.get_stock_status()
            if s["total_remaining"] > 0
        ]
        if not users:
            self.notify("No users yet — press 'u' to add one.", severity="warning")
            return
        if not drinks:
            self.notify(
                "Nothing in stock — record an order with 'durst stock add'.",
                severity="warning",
            )
            return

        def on_result(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            user, drink = result
            try:
                self.db.add_purchase(user, drink)
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            self.notify(f"{user} bought a {drink}. Prost! 🍻")
            self.action_refresh()

        self.push_screen(BuyScreen(users, drinks), on_result)

    def action_add_user(self) -> None:
        """Open the add-user dialog."""

        def on_result(result: tuple[str, str] | None) -> None:
            if result is None:
                return
            name, email = result
            existing = self.db.get_user_by_email(email)
            if existing:
                self.notify(
                    f"A user with email {email} already exists: {existing.name}",
                    severity="error",
                )
                return
            self.db.add_user(name, email, verbose=False)
            self.notify(f"Added user {name}.")
            self.action_refresh()

        self.push_screen(AddUserScreen(), on_result)


if __name__ == "__main__":
    DurstApp().run()
