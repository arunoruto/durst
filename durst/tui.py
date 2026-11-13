"""The durst TUI, styled after Charm's bubbles/lipgloss.

Runs in three modes: locally (full admin), as a logged-in SSH ``user`` (role
from the DB, admins get the Approvals tab) or as a read-only SSH ``guest``,
who can register their key when they have one.
"""

import base64
import datetime as dt
import hashlib
from collections import Counter

from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import ContentSwitcher, DataTable, Input, Static

from durst.db import POT, UNDO_WINDOW, DurstDB, can_undo

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

    def __init__(self, title: str, items: list[tuple[str, str, str]], counting: bool = False) -> None:
        """``items`` are ``(value, title, description)``.

        With ``counting``, digits typed first are a vim-style count (``3⏎``),
        read from ``.times`` once the screen is dismissed.
        """
        super().__init__()
        self.title_text = title
        self.items = items
        self.index = 0
        self.counting = counting
        self.count = ""

    @property
    def times(self) -> int:
        return int(self.count or 1)

    def on_key(self, event) -> None:
        if not self.counting:
            return
        if event.character and event.character.isdigit() and len(self.count) < 2:
            self.count = (self.count + event.character).lstrip("0")
        elif event.key == "backspace":
            self.count = self.count[:-1]
        else:
            return
        event.stop()
        self._render_items()

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(pill(self.title_text), classes="dialog-title")
            yield Static(id="items")
            keys = [("↑/k", "up"), ("↓/j", "down")]
            keys += [("3⏎", "take 3")] if self.counting else []
            yield Static(short_help(keys + [("enter", "choose"), ("esc", "back")]), classes="dialog-help")

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
                if self.times > 1:
                    t.append(f"{self.times}× ", PINK)
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


class FormScreen(ModalScreen[list[str] | None]):
    """bubbles/textinput fields in a dialog; returns the values or None.

    ``fields`` are ``(label, placeholder, value, suggestions)``. Enter moves to
    the next field and submits on the last; ``check(values)`` may return an
    error that keeps the form open.
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, title: str, text: str, fields: list[tuple], check=None) -> None:
        super().__init__()
        self.title_text, self.text, self.fields, self.check = title, text, fields, check

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(pill(self.title_text, PINK), classes="dialog-title")
            if self.text:
                yield Static(Text(self.text, style=DIM), classes="dialog-text")
            for i, (label, placeholder, value, suggestions) in enumerate(self.fields):
                if label:
                    yield Static(label, classes="label")
                with Horizontal(classes="field"):
                    yield Static("> ", classes="prompt")
                    yield Input(
                        value=value,
                        placeholder=placeholder,
                        id=f"f{i}",
                        suggester=SuggestFromList(suggestions, case_sensitive=False)
                        if suggestions
                        else None,
                    )
            keys = [("tab", "next")] if len(self.fields) > 1 else []
            keys += [("→", "complete")] if any(f[3] for f in self.fields) else []
            yield Static(short_help(keys + [("enter", "ok"), ("esc", "back")]), classes="dialog-help")

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        inputs = list(self.query(Input))
        i = inputs.index(event.input)
        if i + 1 < len(inputs):
            inputs[i + 1].focus()
            return
        values = [x.value.strip() for x in inputs]
        if self.check and (error := self.check(values)):
            self.notify(error, severity="warning")
            return
        self.dismiss(values)

    def action_cancel(self) -> None:
        self.dismiss(None)


class VimScroll(VerticalScroll):
    """A scrollable page (the stats) that also speaks vim."""

    BINDINGS = [
        Binding("j", "scroll_down", show=False),
        Binding("k", "scroll_up", show=False),
        Binding("g", "scroll_home", show=False),
        Binding("G", "scroll_end", show=False),
        Binding("left", "app.tab(-1)", show=False),
        Binding("right", "app.tab(1)", show=False),
    ]


def parse_euro(raw: str) -> float | None:
    """``21,60``, ``21.60 €`` or ``-5`` -> float; None if it isn't a number."""
    try:
        return float(raw.replace("€", "").replace(",", ".").strip())
    except ValueError:
        return None


def parse_day(raw: str, today: dt.date | None = None) -> dt.date | None:
    """``today``, ``yesterday``, ``3.11.``, ``3.11.2026`` or ``2026-11-03`` -> date.

    None if it isn't a date or lies in the future; ``28.12.`` in January means last year.
    """
    today = today or dt.date.today()
    raw = raw.strip().lower()
    words = {"today": 0, "heute": 0, "yesterday": 1, "gestern": 1, "vorgestern": 2}
    try:
        if raw in words:
            return today - dt.timedelta(days=words[raw])
        if "-" in raw:
            day = dt.date.fromisoformat(raw)
        else:
            d, m, y = (raw.rstrip(".").split(".") + [""])[:3]
            year = int(y) + (2000 if len(y) == 2 else 0) if y else today.year
            day = dt.date(year, int(m), int(d))
            if not y and (day - today).days > 180:  # 28.12. typed in January
                day = day.replace(year=year - 1)
    except ValueError:
        return None
    return day if day <= today else None


def bars(rows: list, width: int = 18, fmt=lambda v: str(int(v))) -> Text:
    """Horizontal bars in the bubbles/progress gradient, one per ``(label, value)``."""
    top = max((v for _, v in rows), default=0) or 1
    rows = [(label if len(label) <= 18 else label[:17] + "…", v) for label, v in rows]
    pad = max((len(label) for label, _ in rows), default=0)
    t = Text(no_wrap=True)
    for label, value in rows:
        t.append(f"{label:<{pad}} ", NORMAL)
        n = round(value / top * width)
        for i in range(n):
            f = i / max(width - 1, 1)  # 5A56E0 -> EE6FF8
            r, g, b = (round(a + (z - a) * f) for a, z in ((0x5A, 0xEE), (0x56, 0x6F), (0xE0, 0xF8)))
            t.append("█", f"#{r:02x}{g:02x}{b:02x}")
        t.append(f" {fmt(value)}\n" if value else "·\n", DIM)
    return t


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
        Binding("5", "goto(4)", show=False),
        Binding("6", "goto(5)", show=False),
        Binding("b", "buy", "buy"),
        Binding("c", "catch_up", "catch up"),
        Binding("o", "restock", "restock"),
        Binding("p", "deposit", "deposit"),
        Binding("u", "undo", "undo"),
        Binding("r", "register", "register"),
        Binding("a", "approve", "approve"),
        Binding("x", "reject", "reject"),
        Binding("n", "add_key", "add key"),
        Binding("d", "remove_key", "remove key"),
        Binding("e", "edit_email", "edit email"),
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
    PickScreen, ConfirmScreen, FormScreen {{
        align: center middle; background: #000000 60%;
    }}
    VimScroll {{ height: 1fr; scrollbar-size: 1 1; }}
    #stats-body {{ padding: 1 1; }}
    #me {{ height: 1fr; }}
    #profile {{ height: auto; padding: 1 1; }}
    #me-keys {{ height: 1fr; }}
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
        tabs = [("drinks", "Drinks"), ("balances", "Balances"), ("history", "History"), ("stats", "Stats")]
        if self.user:
            tabs.append(("me", "Me"))
        if self.is_admin:
            n = len(self.db.get_pending_keys()) + len(self.db.get_deposit_requests())
            tabs.append(("approvals", f"Approvals ({n})" if n else "Approvals"))
        return tabs

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Guests can't buy, only guests with a key can register, only admins manage."""
        tab = self.tabs[self.tab][0]
        if action in ("buy", "catch_up"):
            return not self.guest
        if action == "restock":
            return self.is_admin and tab == "drinks"
        if action == "deposit":
            return (self.is_admin and tab == "balances") or (bool(self.user) and tab == "me")
        if action == "undo":
            return not self.guest and tab == "history"
        if action == "register":  # keyless guests too: they learn they need a key
            return bool(self.guest and not self.pending)
        if action in ("approve", "reject"):
            return self.is_admin and tab == "approvals"
        if action in ("add_key", "remove_key", "edit_email"):
            return bool(self.user) and tab == "me"
        return True

    # --------------------------------------------------------------- layout
    def compose(self) -> ComposeResult:
        yield Static(id="top")
        with Vertical(id="body"):
            with ContentSwitcher(initial="drinks"):
                for tab_id in ("drinks", "balances", "history", "approvals"):
                    yield VimTable(id=tab_id, cursor_type="row", zebra_stripes=False)
                with VimScroll(id="stats"):
                    yield Static(id="stats-body")
                with Vertical(id="me"):
                    yield Static(id="profile")
                    yield VimTable(id="me-keys", cursor_type="row", zebra_stripes=False)
        yield Static(id="help")

    def on_mount(self) -> None:
        self.db = DurstDB(db_file=self.db_file)
        self.refresh_data()
        self.query_one("#drinks", VimTable).focus()
        self.set_interval(15, self.refresh_data)

    def refresh_data(self) -> None:
        """Reload every table plus the title bar and help."""
        stock = self.db.get_stock_status()
        users = self.db.get_all_users()
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
                for u in users
            ],
            keys=[u.name for u in users],
        )
        recent = self.db.get_recent_purchases(limit=200)
        self.purchases = {str(p["purchase_id"]): p for p in recent}
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
                for p in recent
            ],
            keys=list(self.purchases),
        )
        self._refresh_stats()
        if self.is_admin:
            pending = self.db.get_pending_keys()
            deposits = self.db.get_deposit_requests()
            self._fill(
                "approvals",
                ["Name", "Email", "What", "Details"],
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
                ]
                + [
                    (
                        d["name"],
                        Text(d["email"] or "", style=DIM),
                        Text(f"deposit {euro(d['amount'])}", style=PINK),
                        Text(_short_date(d["created"]), style=DIM),
                    )
                    for d in deposits
                ],
                keys=[p["key"] for p in pending] + [f"deposit:{d['request_id']}" for d in deposits],
            )
        if self.user:
            self._refresh_me()
        self._render_top()
        self._render_help()

    def _refresh_stats(self) -> None:
        now = dt.datetime.now()
        rows = [(dt.datetime.fromisoformat(p["purchase_date"]), p) for p in self.db.all_purchases()]
        recent = [p for d, p in rows if (now - d).days < 90]
        weeks = Counter(d.isocalendar()[:2] for d, _ in rows)
        monday = now - dt.timedelta(days=now.weekday())
        last8 = [(monday - dt.timedelta(weeks=i)).isocalendar()[:2] for i in range(7, -1, -1)]

        def section(title: str, body: Text) -> Text:
            t = Text()
            t.append_text(pill(title))
            t.append("\n\n")
            t.append_text(body)
            return t

        week = section("Drinks per week", bars([(f"KW {w:02}", weeks[(y, w)]) for y, w in last8]))
        drinks = section(
            "Top drinks · 90 days", bars(Counter(p["drink"] for p in recent).most_common(8))
        )
        people = section(
            "Thirstiest · 90 days", bars(Counter(p["user"] for p in recent).most_common(8))
        )
        grid = Table.grid(padding=(1, 6))
        grid.add_column()
        grid.add_column()
        grid.add_row(week, drinks)
        mine = [p for p in recent if p["user"] == self.user]
        you = Text()
        if mine:
            fav, n = Counter(p["drink"] for p in mine).most_common(1)[0]
            you = section("You · 90 days", Text())
            you.append(f"{len(mine)}", f"bold {PINK}")
            you.append(" drinks for ", NORMAL)
            you.append(euro(sum(p["cost"] for p in mine)), f"bold {PINK}")
            you.append("\nmostly ", NORMAL)
            you.append(fav, f"bold {FUCHSIA}")
            you.append(f" ({n}×)", DIM)
        grid.add_row(people, you)
        self.query_one("#stats-body", Static).update(grid)

    def _refresh_me(self) -> None:
        me = self.db.get_user_by_name(self.user) if self.user else None
        if me is None or me.user_id is None:
            return
        t = Text()
        for label, value in [
            ("Name", Text(me.name, style=f"bold {PINK}")),
            ("Email", Text(me.email or "–", style=NORMAL if me.email else DIM)),
            ("Role", Text(me.role, style=FUCHSIA if me.role == "admin" else NORMAL)),
            ("Balance", money(me.balance)),
        ] + [
            ("Pending", Text(f"+{euro(d['amount'])} waiting for an admin", style=YELLOW))
            for d in self.db.get_deposit_requests(me.user_id)
        ]:
            t.append(f"{label:<9}", DIM)
            value.justify = None
            t.append_text(value)
            t.append("\n")
        t.append("\nYour name links you to the sheet; ask an admin to change it.", HELP_KEY)
        self.query_one("#profile", Static).update(t)
        keys = self.db.get_ssh_keys(me.user_id)
        current = self.key.split()[:2] if self.key else None
        self._fill(
            "me-keys",
            ["Key", "Fingerprint", "Status"],
            [
                (
                    Text(k["label"] or "(no label)", style=NORMAL if k["label"] else DIM),
                    Text(fingerprint(k["key"]), style=DIM),
                    Text("this session", style=GREEN)
                    if k["key"].split() == current
                    else Text("active", style=NORMAL)
                    if k["approved"]
                    else Text("waiting for approval", style=YELLOW),
                )
                for k in keys
            ],
            keys=[k["key"] for k in keys],
        )

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
            right = Text("guest · read-only · r to register", style=DIM)
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
                ("b", "buy", "buy"),
                ("c", "catch up", "catch_up"),
                ("o", "restock", "restock"),
                ("p", "deposit", "deposit"),
                ("u", "undo", "undo"),
                ("r", "register your key", "register"),
                ("a", "approve", "approve"),
                ("x", "reject", "reject"),
                ("n", "add key", "add_key"),
                ("d", "remove key", "remove_key"),
                ("e", "edit email", "edit_email"),
            ]
            if self.check_action(action, ())
        ]

    def _render_help(self) -> None:
        if not self.full_help:
            entries = [("jk", "move"), ("hl", "tabs")]
            entries += self._actions_help() + [("?", "more"), ("q", "quit")]
            self.query_one("#help", Static).update(short_help(entries))
            return
        groups = [
            ("Navigation", [
                ("↑/k", "up"), ("↓/j", "down"), ("g/G", "top/bottom"),
                ("ctrl+u/d", "page up/down"),
            ]),
            ("Tabs", [("←/h", "previous"), ("→/l", "next"), (f"1-{len(self.tabs)}", "jump to tab")]),
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
        self.query_one("#me-keys" if tab_id == "me" else f"#{tab_id}").focus()
        self._render_top()
        self._render_help()

    def action_buy(self) -> None:
        self._pick_user(self._pick_drinks)

    def action_catch_up(self) -> None:
        """Book forgotten drinks: pick the day, then tally drinks until esc."""
        def when(values: list[str] | None) -> None:
            day = parse_day(values[0]) if values else None
            if day:
                self._pick_user(lambda user: self._pick_drinks(user, day, Counter()))

        self.push_screen(
            FormScreen(
                "Catch up",
                "Forgot to book some drinks? Pick the day, then the drinks (3⏎ for three). "
                "Press esc when you're done.",
                [("When?", "yesterday, 3.11. or 2026-11-03", "yesterday", ["today", "yesterday"])],
                lambda v: None if parse_day(v[0]) else "Try yesterday, 3.11. or 2026-11-03 (not in the future).",
            ),
            when,
        )

    def _pick_user(self, then) -> None:
        """Users drink for themselves; admins pick who's drinking."""
        if self.user and not self.is_admin:
            then(self.user)
            return
        users = [(u.name, u.name, euro(u.balance, sign=True)) for u in self.db.get_all_users()]
        if not users:
            self.notify("No users yet — add one with 'durst user add'.", severity="warning")
            return
        users.sort(key=lambda u: u[0] != self.user)  # admins first in their own list
        self.push_screen(PickScreen("Who is drinking?", users), lambda u: then(u) if u else None)

    def _pick_drinks(self, user: str, day: dt.date | None = None, basket: Counter | None = None) -> None:
        """The drink picker. ``basket`` (catch-up) keeps it open, collecting drinks until esc."""
        uid = self.db.get_user_id_by_name(user)
        stock = [s for s in self.db.get_stock_status() if s["total_remaining"] > 0]
        if uid is None:
            return
        if not stock:
            self.notify("Nothing in stock right now.", severity="warning")
            return
        prices = {s["drink_name"]: s["price"] for s in stock}
        # Move-to-front: what they took last comes first, the rest A-Z.
        last = self.db.last_taken(uid)
        stock.sort(key=lambda s: last.index(s["drink_name"]) if s["drink_name"] in last else len(last))
        drinks = [
            (s["drink_name"], s["drink_name"], f"{euro(s['price'])} · {s['total_remaining']} left")
            for s in stock
        ]
        who = "" if user == self.user else f" for {user}"
        when = "today" if day in (None, dt.date.today()) else f"{day:%a %d.%m.}"

        def summary(counts: Counter) -> str:
            return ", ".join(f"{n}× {d}" for d, n in counts.items())

        def picked(drink: str | None) -> None:
            if basket is None:  # plain buy
                if drink:
                    self.push_screen(
                        ConfirmScreen(f"Take {summary(Counter({drink: screen.times}))}{who} "
                                      f"for {euro(prices[drink] * screen.times)}?"),
                        lambda yes: self._book(user, [drink] * screen.times) if yes else None,
                    )
                return
            if drink:  # one more for the tally, then back to the list
                basket[drink] += screen.times
                self._pick_drinks(user, day, basket)
            elif basket:  # esc: done
                total = sum(prices.get(d, 0) * n for d, n in basket.items())
                self.push_screen(
                    ConfirmScreen(f"Book {summary(basket)}{who} on {when} for {euro(total)}?"),
                    lambda yes: self._book(user, list(basket.elements()), day) if yes else None,
                )

        title = "What are you drinking?"
        if basket is not None:
            title = f"Catch up · {when}" + (f" · {summary(basket)}" if basket else "")
        screen = PickScreen(title, drinks, counting=True)
        self.push_screen(screen, picked)

    def _book(self, user: str, drinks: list[str], day: dt.date | None = None) -> None:
        try:
            self.db.add_purchases(user, drinks, day)
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        what = drinks[0] if len(drinks) == 1 else f"{len(drinks)} drinks"
        self.notify(f"{what} for {user}. Prost! 🍻")
        self.refresh_data()

    def action_register(self) -> None:
        if self.key is None:
            self.notify(
                "You connected without an SSH key, so durst can't recognise you. "
                "Make one with: ssh-keygen -t ed25519 (Enter for all questions), "
                "then connect again and press r.",
                title="You need an SSH key",
                severity="warning",
                timeout=30,
            )
            return
        taken = {p["name"] for p in self.db.get_pending_keys()}
        accounts = [u.name for u in self.db.get_all_users() if u.name not in taken]

        def done(result: list[str] | None) -> None:
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

        def check(v: list[str]) -> str | None:
            if not 0 < len(v[0]) <= 40:
                return "Please enter your name."
            if v[1] and "@" not in v[1]:
                return "That doesn't look like an email."
            return None

        self.push_screen(
            FormScreen(
                "Register",
                "Already in the sheet? Type your name there to take over that "
                "account. An admin approves you before you can buy.",
                [
                    ("Name", "Mira Muster", "", accounts),
                    ("Email (optional)", "mira@tu-dortmund.de", "", []),
                ],
                check,
            ),
            done,
        )

    def action_restock(self) -> None:
        drinks = [d.name for d in self.db.get_all_drink_types()]
        payers = [POT] + [u.name for u in self.db.get_all_users()]

        def check(v: list[str]) -> str | None:
            if not v[0]:
                return "Which drink?"
            if not v[1].isdigit() or int(v[1]) <= 0:
                return "Bottles must be a whole number."
            if (total := parse_euro(v[2])) is None or total < 0:
                return "The price should look like 21,60."
            if v[3] not in payers:
                return f"Nobody called {v[3]!r}."
            return None

        def done(v: list[str] | None) -> None:
            if v is None:
                return
            name, qty, total, payer = v[0], int(v[1]), parse_euro(v[2]) or 0.0, v[3]
            # Reuse the existing spelling ("club mate" -> "Club Mate").
            name = next((d for d in drinks if d.lower() == name.lower()), name)
            new = "new drink " if name not in drinks else ""
            who = "from the Kasse" if payer == POT else f"paid by {payer}"

            def save(yes: bool) -> None:
                if not yes:
                    return
                try:
                    self.db.restock(name, qty, total, payer)
                except ValueError as e:
                    self.notify(str(e), severity="error")
                    return
                self.notify(f"{qty} × {name} in stock.")
                self.refresh_data()

            self.push_screen(
                ConfirmScreen(
                    f"Stock {qty} × {new}{name} for {euro(total)}\n"
                    f"({euro(total / qty)} a bottle), {who}?"
                ),
                save,
            )

        self.push_screen(
            FormScreen(
                "Restock",
                "A new name adds a new drink. The price is what the whole order cost.",
                [
                    ("Drink", "Club Mate", "", drinks),
                    ("Bottles", "20", "", []),
                    ("Total price", "18,00", "", []),
                    ("Paid by", POT, POT, payers),
                ],
                check,
            ),
            done,
        )

    def _cursor_key(self, tab_id: str) -> str | None:
        table = self.query_one(f"#{tab_id}", VimTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key.value

    def action_deposit(self) -> None:
        if self.tabs[self.tab][0] == "me":
            self._deposit_mine()
            return
        user = self._cursor_key("balances")
        if user is None:
            return

        def done(v: list[str] | None) -> None:
            amount = parse_euro(v[0]) if v else None
            uid, pot = self.db.get_user_id_by_name(user), self.db.pot_id()
            if not amount or uid is None:
                return
            # Cash into the Kasse settles debt; a payout goes the other way.
            if amount > 0:
                self.db.add_repayment(uid, pot, amount, received_by=self._me_id())
            else:
                self.db.add_repayment(pot, uid, -amount, received_by=self._me_id())
            self.notify(f"{euro(amount, sign=True)} for {user}.")
            self.refresh_data()

        self.push_screen(
            FormScreen(
                f"Deposit · {user}",
                f"Cash {user} gave you for the Kasse. Negative for a payout.",
                [("", "10,00", "", [])],
                lambda v: None if parse_euro(v[0]) else "Enter an amount like 10 or -5,50.",
            ),
            done,
        )

    def _deposit_mine(self) -> None:
        """Users ask for money they handed in; an admin approves it."""
        uid = self._me_id()
        if uid is None:
            return

        def done(v: list[str] | None) -> None:
            amount = parse_euro(v[0]) if v else None
            if not amount:
                return
            try:
                if self.is_admin:  # admins hold the cash themselves
                    self.db.add_repayment(uid, self.db.pot_id(), amount, received_by=uid)
                    self.notify(f"{euro(amount, sign=True)} booked.")
                else:
                    self.db.request_deposit(uid, amount)
                    self.notify("Sent. It counts once an admin confirms they got the money.")
            except ValueError as e:
                self.notify(str(e), severity="error")
            self.refresh_data()

        self.push_screen(
            FormScreen(
                "Add money",
                "How much cash did you give an admin (or put in the Kasse)?",
                [("", "10,00", "", [])],
                lambda v: None if (parse_euro(v[0]) or 0) > 0 else "Enter an amount like 10 or 5,50.",
            ),
            done,
        )

    def action_undo(self) -> None:
        key = self._cursor_key("history")
        p = self.purchases.get(key or "")
        if p is None:
            return
        if not can_undo(p, self.user, self.is_admin):
            minutes = UNDO_WINDOW.seconds // 60
            self.notify(
                f"You can undo your own drinks for {minutes} minutes; ask an admin.",
                severity="warning",
            )
            return

        def done(yes: bool) -> None:
            if not yes:
                return
            try:
                self.db.undo_purchase(p["purchase_id"])
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            self.notify("Undone. The bottle is back in stock.")
            self.refresh_data()

        self.push_screen(
            ConfirmScreen(f"Undo {p['user_name']}'s {p['drink_name']} ({euro(p['cost'])})?"),
            done,
        )

    def _selected_key(self) -> str | None:
        key = self._cursor_key("approvals")
        if key is None:
            self.notify("Nobody is waiting for approval.")
        return key

    def action_approve(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        if not key.startswith("deposit:"):
            self.db.approve_key(key)
            self.notify("Approved. Welcome aboard! 🎉")
            self.refresh_data()
            return
        request_id = int(key.split(":")[1])
        d = next(d for d in self.db.get_deposit_requests() if d["request_id"] == request_id)

        def done(yes: bool) -> None:
            if yes:
                try:
                    self.db.approve_deposit(request_id, self._me_id())
                except ValueError as e:
                    self.notify(str(e), severity="error")
                    return
                self.notify(f"{euro(d['amount'])} booked for {d['name']}.")
                self.refresh_data()

        self.push_screen(ConfirmScreen(f"Did you get {euro(d['amount'])} from {d['name']}?"), done)

    def _me_id(self) -> int | None:
        me = self.db.get_user_by_name(self.user) if self.user else None
        return me.user_id if me else None

    def action_add_key(self) -> None:
        def done(v: list[str] | None) -> None:
            uid = self._me_id()
            if not v or not v[0] or uid is None:
                return
            try:
                self.db.add_ssh_key(uid, v[0])  # already logged in: no approval needed
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            self.notify("Key added. You can log in with it now.")
            self.refresh_data()

        self.push_screen(
            FormScreen(
                "Add SSH key",
                "Paste a public key, e.g. the line in ~/.ssh/id_ed25519.pub on your other machine.",
                [("", "ssh-ed25519 AAAA… laptop", "", [])],
            ),
            done,
        )

    def action_remove_key(self) -> None:
        key, uid = self._cursor_key("me-keys"), self._me_id()
        if key is None or uid is None:
            return
        if self.key and key.split() == self.key.split()[:2]:
            self.notify(
                "That's the key you're logged in with. Log in with another key to remove it.",
                severity="warning",
            )
            return

        def confirmed(yes: bool) -> None:
            if yes:
                self.db.remove_ssh_key(uid, key)
                self.notify("Key removed.")
                self.refresh_data()

        self.push_screen(ConfirmScreen(f"Remove the key {fingerprint(key)[:20]}…?"), confirmed)

    def action_edit_email(self) -> None:
        me = self.db.get_user_by_name(self.user) if self.user else None
        if me is None or me.user_id is None:
            return
        uid = me.user_id

        def done(v: list[str] | None) -> None:
            if v is None:
                return
            try:
                self.db.set_email(uid, v[0])
            except ValueError as e:
                self.notify(str(e), severity="error")
                return
            self.notify("Email saved.")
            self.refresh_data()

        self.push_screen(
            FormScreen(
                "Email", "Leave it empty to remove it.", [("", "mira@tu-dortmund.de", me.email or "", [])]
            ),
            done,
        )

    def action_reject(self) -> None:
        key = self._selected_key()
        if key and key.startswith("deposit:"):
            self.db.reject_deposit(int(key.split(":")[1]))
            self.notify("Request rejected.")
            self.refresh_data()
        elif key:
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
