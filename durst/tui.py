"""The durst TUI, styled after Charm's bubbles/lipgloss.

Runs in three modes: locally (full admin), as a logged-in SSH ``user`` (role
from the DB, admins get the Approvals tab) or as a read-only SSH ``guest``,
who can register their key when they have one.
"""

import base64
import hashlib

from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import ContentSwitcher, DataTable, Input, Static

from durst.db import DurstDB

# Charm palette
PURPLE = "#7D56F4"
PINK = "#F25D94"
FUCHSIA = "#EE6FF8"
SEL_DESC = "#AD58B4"
GREEN = "#04B575"
RED = "#ED567A"
YELLOW = "#ECFD65"
TEXT = "#FAFAFA"
NORMAL = "#DDDDDD"
DIM = "#777777"
HELP_KEY = "#626262"
HELP_DESC = "#4A4A4A"
HELP_SEP = "#3C3C3C"


def euro(amount: float, sign: bool = False) -> str:
    """German money format: ``1,50 €`` (``+1,50 €`` with sign)."""
    return f"{amount:{'+' if sign else ''}.2f} €".replace(".", ",")


def money(amount: float) -> Text:
    """Signed, colored balance."""
    color = GREEN if amount > 0.004 else RED if amount < -0.004 else DIM
    return Text(euro(amount, sign=True), style=color, justify="right")


def pill(label: str, bg: str = PURPLE) -> Text:
    """A lipgloss-style title badge."""
    t = Text()
    t.append(f" {label} ", style=f"bold {TEXT} on {bg}")
    return t


def short_help(entries: list[tuple[str, str]]) -> Text:
    """bubbles/help short view: ``key desc • key desc``."""
    t = Text()
    for i, (key, desc) in enumerate(entries):
        if i:
            t.append(" • ", HELP_SEP)
        t.append(key, HELP_KEY)
        t.append(" " + desc, HELP_DESC)
    return t


def fingerprint(key: str) -> str:
    """OpenSSH-style SHA256 fingerprint of a public key line."""
    blob = base64.b64decode(key.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


class VimTable(DataTable):
    """A DataTable that also speaks vim."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("g,home", "first", show=False),
        Binding("G,end", "last", show=False),
        Binding("ctrl+d", "page_down", show=False),
        Binding("ctrl+u", "page_up", show=False),
        Binding("left", "app.tab(-1)", show=False),  # tabs, not cells
        Binding("right", "app.tab(1)", show=False),
    ]

    def action_first(self) -> None:
        self.move_cursor(row=0)

    def action_last(self) -> None:
        self.move_cursor(row=self.row_count - 1)


class PickScreen(ModalScreen[str | None]):
    """A bubbles/list: title, two-line items, paginator dots."""

    PER_PAGE = 5
    BINDINGS = [
        Binding("j,down", "move(1)", show=False),
        Binding("k,up", "move(-1)", show=False),
        Binding("l,right", "move(5)", show=False),
        Binding("h,left", "move(-5)", show=False),
        Binding("g,home", "move(-1000)", show=False),
        Binding("G,end", "move(1000)", show=False),
        Binding("enter", "pick", show=False),
        Binding("escape,q", "cancel", show=False),
    ]

    def __init__(self, title: str, items: list[tuple[str, str, str]]) -> None:
        """``items`` are ``(value, title, description)``."""
        super().__init__()
        self.title_text = title
        self.items = items
        self.index = 0

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(pill(self.title_text), classes="dialog-title")
            yield Static(id="items")
            yield Static(
                short_help([("↑/k", "up"), ("↓/j", "down"), ("enter", "choose"), ("esc", "back")]),
                classes="dialog-help",
            )

    def on_mount(self) -> None:
        self._render_items()

    def _render_items(self) -> None:
        t = Text()
        page = self.index // self.PER_PAGE
        start = page * self.PER_PAGE
        for i, (_, title, desc) in enumerate(
            self.items[start : start + self.PER_PAGE], start=start
        ):
            if i == self.index:
                t.append("│ ", SEL_DESC)
                t.append(title + "\n", FUCHSIA)
                t.append("│ ", SEL_DESC)
                t.append(desc + "\n\n", SEL_DESC)
            else:
                t.append("  " + title + "\n", NORMAL)
                t.append("  " + desc + "\n\n", DIM)
        pages = -(-len(self.items) // self.PER_PAGE)
        if pages > 1:
            t.append("  ")
            for p in range(pages):
                t.append("• ", TEXT if p == page else HELP_SEP)
        self.query_one("#items", Static).update(t)

    def action_move(self, delta: int) -> None:
        self.index = max(0, min(len(self.items) - 1, self.index + delta))
        self._render_items()

    def action_pick(self) -> None:
        self.dismiss(self.items[self.index][0])

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """The lipgloss dialog: a question and two buttons."""

    BINDINGS = [
        Binding("h,l,left,right,tab", "switch", show=False),
        Binding("y", "answer(True)", show=False),
        Binding("n,escape,q", "answer(False)", show=False),
        Binding("enter", "submit", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question
        self.yes = True

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog confirm"):
            yield Static(Text(self.question, justify="center"), classes="question")
            yield Static(id="buttons")

    def on_mount(self) -> None:
        self._render_buttons()

    def _render_buttons(self) -> None:
        active = f"underline #FFF7DB on {PINK}"
        inactive = "#FFF7DB on #888B7E"
        t = Text(justify="center")
        t.append("   Yes   ", active if self.yes else inactive)
        t.append("  ")
        t.append("   Maybe later   ", inactive if self.yes else active)
        self.query_one("#buttons", Static).update(t)

    def action_switch(self) -> None:
        self.yes = not self.yes
        self._render_buttons()

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)

    def action_submit(self) -> None:
        self.dismiss(self.yes)


class RegisterScreen(ModalScreen[tuple[str, str] | None]):
    """bubbles/textinput-style sign-up form."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, accounts: list[str]) -> None:
        super().__init__()
        self.accounts = accounts

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(pill("Register", PINK), classes="dialog-title")
            yield Static(
                Text(
                    "Already in the sheet? Type your name there to take over that "
                    "account. An admin approves you before you can buy.",
                    style=DIM,
                ),
                classes="dialog-text",
            )
            yield Static("Name", classes="label")
            with Horizontal(classes="field"):
                yield Static("> ", classes="prompt")
                yield Input(
                    placeholder="Mira Muster",
                    suggester=SuggestFromList(self.accounts, case_sensitive=False),
                    id="reg-name",
                )
            yield Static("Email (optional)", classes="label")
            with Horizontal(classes="field"):
                yield Static("> ", classes="prompt")
                yield Input(placeholder="mira@tu-dortmund.de", id="reg-email")
            yield Static(
                short_help([("tab", "next"), ("→", "complete"), ("enter", "submit"), ("esc", "back")]),
                classes="dialog-help",
            )

    @on(Input.Submitted, "#reg-name")
    def next_field(self) -> None:
        self.query_one("#reg-email", Input).focus()

    @on(Input.Submitted, "#reg-email")
    def submit(self) -> None:
        name = self.query_one("#reg-name", Input).value.strip()
        email = self.query_one("#reg-email", Input).value.strip()
        if not 0 < len(name) <= 40:
            self.notify("Please enter your name.", severity="warning")
            self.query_one("#reg-name", Input).focus()
            return
        if email and "@" not in email:
            self.notify("That doesn't look like an email.", severity="warning")
            return
        self.dismiss((name, email))

    def action_cancel(self) -> None:
        self.dismiss(None)


class DurstApp(App):
    """Browse drinks, balances and history; buy drinks; approve sign-ups."""

    TITLE = "durst"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q,ctrl+c", "quit", "quit"),
        Binding("question_mark", "toggle_help", "help"),
        Binding("l,right", "tab(1)", "next tab"),
        Binding("h,left", "tab(-1)", "previous tab"),
        Binding("1", "goto(0)", show=False),
        Binding("2", "goto(1)", show=False),
        Binding("3", "goto(2)", show=False),
        Binding("4", "goto(3)", show=False),
        Binding("b", "buy", "buy"),
        Binding("r", "register", "register"),
        Binding("a", "approve", "approve"),
        Binding("x", "reject", "reject"),
    ]

    CSS = f"""
    Screen {{ background: ansi_default; padding: 1 2; }}
    #top {{ height: 1; margin-bottom: 1; }}
    #body {{ height: 1fr; border: round #383838; padding: 0 1; }}
    #body:focus-within {{ border: round {PURPLE}; }}
    #help {{ height: auto; margin-top: 1; padding: 0 1; }}
    VimTable {{ background: transparent; height: 1fr; scrollbar-size: 1 1; }}
    VimTable > .datatable--header {{ background: transparent; color: {TEXT}; text-style: bold; }}
    VimTable > .datatable--cursor {{ background: #5f00ff; color: #ffffaf; }}
    VimTable > .datatable--hover {{ background: transparent; }}
    VimTable > .datatable--header-hover {{ background: transparent; }}
    PickScreen, ConfirmScreen, RegisterScreen {{ align: center middle; background: #000000 60%; }}
    .dialog {{
        width: 60; height: auto; max-height: 90%;
        padding: 1 2; background: #1a1a1a; border: round #874BFD;
    }}
    .confirm {{ width: 50; }}
    .dialog-title {{ margin-bottom: 1; }}
    .dialog-text {{ margin-bottom: 1; }}
    .dialog-help {{ margin-top: 1; }}
    .question {{ margin-bottom: 1; }}
    .label {{ color: {PURPLE}; }}
    .field {{ height: 1; margin-bottom: 1; }}
    .prompt {{ width: 2; color: {DIM}; }}
    .field:focus-within .prompt {{ color: {PINK}; }}
    Input {{ border: none; background: transparent; padding: 0; height: 1; width: 1fr; }}
    Input:focus {{ border: none; background: transparent; }}
    Input > .input--placeholder, Input > .input--suggestion {{ color: {HELP_KEY}; }}
    Input > .input--cursor {{ background: {PINK}; color: {TEXT}; }}
    Toast {{ background: #1a1a1a; border-left: outer {PINK}; }}
    Toast.-warning {{ border-left: outer {YELLOW}; }}
    Toast.-error {{ border-left: outer {RED}; }}
    """

    def __init__(
        self,
        db_file: str = "sqlite.db",
        user: str | None = None,
        guest: bool = False,
        key: str | None = None,
    ):
        """Run locally (default), as SSH ``user``, or as ``guest`` (``key``: their unregistered key)."""
        super().__init__(ansi_color=True)
        self.db_file = db_file
        self.user = user
        self.guest = guest
        self.key = key
        self.full_help = False
        self.tab = 0

    # ---------------------------------------------------------------- roles
    @property
    def local(self) -> bool:
        return not self.user and not self.guest

    @property
    def is_admin(self) -> bool:
        if self.local:
            return True
        me = self.db.get_user_by_name(self.user) if self.user else None
        return bool(me and me.role == "admin")

    @property
    def pending(self) -> bool:
        return bool(self.guest and self.key and self.db.is_key_pending(self.key))

    @property
    def tabs(self) -> list[tuple[str, str]]:
        tabs = [("drinks", "Drinks"), ("balances", "Balances"), ("history", "History")]
        if self.is_admin:
            n = len(self.db.get_pending_keys())
            tabs.append(("approvals", f"Approvals ({n})" if n else "Approvals"))
        return tabs

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Guests can't buy, only guests with a key can register, only admins approve."""
        if action == "buy":
            return not self.guest
        if action == "register":
            return bool(self.guest and self.key and not self.pending)
        if action in ("approve", "reject"):
            return self.is_admin and self.tabs[self.tab][0] == "approvals"
        return True

    # --------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static(id="top")
        with Vertical(id="body"):
            with ContentSwitcher(initial="drinks"):
                for tab_id in ("drinks", "balances", "history", "approvals"):
                    yield VimTable(id=tab_id, cursor_type="row", zebra_stripes=False)
        yield Static(id="help")

    def on_mount(self) -> None:
        self.db = DurstDB(db_file=self.db_file)
        self.refresh_data()
        self.query_one("#drinks", VimTable).focus()
        self.set_interval(15, self.refresh_data)

    def refresh_data(self) -> None:
        """Reload every table plus the title bar and help."""
        stock = self.db.get_stock_status()
        self._fill(
            "drinks",
            ["Drink", "Price", "In stock"],
            [
                (
                    Text(s["drink_name"], style=NORMAL if s["total_remaining"] else DIM),
                    Text(euro(s["price"]) if s["price"] is not None else "–", justify="right"),
                    Text(str(s["total_remaining"]), justify="right")
                    if s["total_remaining"]
                    else Text("sold out", style=DIM, justify="right"),
                )
                for s in sorted(stock, key=lambda s: (s["total_remaining"] == 0, s["drink_name"]))
            ],
        )
        self._fill(
            "balances",
            ["Name", "Balance"],
            [
                (Text(u.name, style=f"bold {PINK}" if u.name == self.user else NORMAL), money(u.balance))
                for u in self.db.get_all_users()
            ],
        )
        self._fill(
            "history",
            ["When", "Who", "Drink", "Price"],
            [
                (
                    Text(_short_date(p["purchase_date"]), style=DIM),
                    p["user_name"],
                    p["drink_name"],
                    Text(euro(p["cost"]), justify="right"),
                )
                for p in self.db.get_recent_purchases(limit=200)
            ],
        )
        if self.is_admin:
            pending = self.db.get_pending_keys()
            self._fill(
                "approvals",
                ["Name", "Email", "What", "Key"],
                [
                    (
                        p["name"],
                        Text(p["email"], style=DIM),
                        Text("new account", style=GREEN)
                        if p["new_user"]
                        else Text("claims account", style=YELLOW),
                        Text(fingerprint(p["key"])[:23] + "…", style=DIM),
                    )
                    for p in pending
                ],
                keys=[p["key"] for p in pending],
            )
        self._render_top()
        self._render_help()

    def _fill(
        self, tab_id: str, headers: list[str], rows: list[tuple], keys: list | None = None
    ) -> None:
        table = self.query_one(f"#{tab_id}", VimTable)
        cursor = table.cursor_row
        table.clear(columns=True)
        table.add_columns(*headers)
        for i, row in enumerate(rows):
            table.add_row(*row, key=keys[i] if keys else None)
        if rows:
            table.move_cursor(row=min(cursor, len(rows) - 1))

    def _render_top(self) -> None:
        left = pill("durst")
        left.append("  ")
        for i, (_, label) in enumerate(self.tabs):
            if i == self.tab:
                left.append(f" {label} ", f"bold {TEXT} on {PINK}")
            else:
                left.append(f" {label} ", DIM)
            left.append(" ")
        if self.user:
            me = self.db.get_user_by_name(self.user)
            right = Text(self.user + "  ", style=NORMAL)
            if me:
                right.append(euro(me.balance, sign=True), money(me.balance).style)
                if me.role == "admin":
                    right.append("  ")
                    right.append_text(pill("admin", FUCHSIA))
        elif self.pending:
            right = Text("⏳ waiting for an admin to approve you", style=YELLOW)
        elif self.guest:
            right = Text("guest · read-only", style=DIM)
        else:
            right = Text("local admin", style=DIM)
        right.justify = "right"
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1, no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_row(left, right)
        self.query_one("#top", Static).update(grid)

    def _actions_help(self) -> list[tuple[str, str]]:
        return [
            (key, desc)
            for key, desc, action in [
                ("b", "buy a drink", "buy"),
                ("r", "register your key", "register"),
                ("a", "approve", "approve"),
                ("x", "reject", "reject"),
            ]
            if self.check_action(action, ())
        ]

    def _render_help(self) -> None:
        if not self.full_help:
            entries = [("↑/k", "up"), ("↓/j", "down"), ("←/→", "tabs")]
            entries += self._actions_help() + [("?", "more"), ("q", "quit")]
            self.query_one("#help", Static).update(short_help(entries))
            return
        groups = [
            ("Navigation", [
                ("↑/k", "up"), ("↓/j", "down"), ("g/G", "top/bottom"),
                ("ctrl+u/d", "page up/down"),
            ]),
            ("Tabs", [("←/h", "previous"), ("→/l", "next"), ("1-4", "jump to tab")]),
            ("Actions", self._actions_help() or [("-", "read-only")]),
            ("General", [("?", "close help"), ("q", "quit")]),
        ]
        grid = Table.grid(padding=(0, 4))
        columns = []
        for title, entries in groups:
            t = Text(title + "\n", style=f"bold {DIM}")
            width = max(len(k) for k, _ in entries)
            for key, desc in entries:
                t.append(key.ljust(width) + " ", HELP_KEY)
                t.append(desc + "\n", HELP_DESC)
            columns.append(t)
            grid.add_column()
        grid.add_row(*columns)
        self.query_one("#help", Static).update(grid)

    # -------------------------------------------------------------- actions
    def action_toggle_help(self) -> None:
        self.full_help = not self.full_help
        self._render_help()

    def action_tab(self, delta: int) -> None:
        self.action_goto((self.tab + delta) % len(self.tabs))

    def action_goto(self, index: int) -> None:
        if index >= len(self.tabs):
            return
        self.tab = index
        tab_id = self.tabs[index][0]
        self.query_one(ContentSwitcher).current = tab_id
        self.query_one(f"#{tab_id}", VimTable).focus()
        self._render_top()
        self._render_help()

    def action_buy(self) -> None:
        stock = [s for s in self.db.get_stock_status() if s["total_remaining"] > 0]
        if not stock:
            self.notify("Nothing in stock right now.", severity="warning")
            return
        drinks = [
            (s["drink_name"], s["drink_name"], f"{euro(s['price'])} · {s['total_remaining']} left")
            for s in stock
        ]
        prices = {s["drink_name"]: euro(s["price"]) for s in stock}

        def buy_for(user: str | None) -> None:
            if not user:
                return

            def picked(drink: str | None) -> None:
                if not drink:
                    return
                who = "" if user == self.user else f" for {user}"
                self.push_screen(
                    ConfirmScreen(f"Take a {drink}{who} for {prices[drink]}?"),
                    lambda yes: self._buy(user, drink) if yes else None,
                )

            self.push_screen(PickScreen("What are you drinking?", drinks), picked)

        if self.user and not self.is_admin:
            buy_for(self.user)
            return
        users = [(u.name, u.name, euro(u.balance, sign=True)) for u in self.db.get_all_users()]
        if not users:
            self.notify("No users yet — add one with 'durst user add'.", severity="warning")
            return
        users.sort(key=lambda u: u[0] != self.user)  # admins first in their own list
        self.push_screen(PickScreen("Who is drinking?", users), buy_for)

    def _buy(self, user: str, drink: str) -> None:
        try:
            self.db.add_purchase(user, drink)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.notify(f"{drink} for {user}. Prost! 🍻")
        self.refresh_data()

    def action_register(self) -> None:
        taken = {p["name"] for p in self.db.get_pending_keys()}
        accounts = [u.name for u in self.db.get_all_users() if u.name not in taken]

        def done(result: tuple[str, str] | None) -> None:
            if result is None or self.key is None:
                return
            try:
                claim = self.db.register(result[0], result[1] or None, self.key)
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            what = f"take over {result[0]}" if claim else "join"
            self.notify(f"Request to {what} sent — an admin will approve you soon.")
            self.refresh_data()

        self.push_screen(RegisterScreen(accounts), done)

    def _selected_key(self) -> str | None:
        table = self.query_one("#approvals", VimTable)
        if not table.row_count:
            self.notify("Nobody is waiting for approval.")
            return None
        return table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value

    def action_approve(self) -> None:
        key = self._selected_key()
        if key:
            self.db.approve_key(key)
            self.notify("Approved. Welcome aboard! 🎉")
            self.refresh_data()

    def action_reject(self) -> None:
        key = self._selected_key()
        if key:
            self.db.reject_key(key)
            self.notify("Request rejected.")
            self.refresh_data()


def _short_date(value: str | None) -> str:
    """``2026-11-10 14:30:00`` -> ``10.11.26 14:30``."""
    if not value or len(value) < 16:
        return value or ""
    return f"{value[8:10]}.{value[5:7]}.{value[2:4]} {value[11:16]}"


if __name__ == "__main__":
    # Entry point for SSH sessions: no --user means guest.
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("db")
    p.add_argument("--user")
    p.add_argument("--key")
    args = p.parse_args()
    DurstApp(args.db, user=args.user, guest=args.user is None, key=args.key).run()
