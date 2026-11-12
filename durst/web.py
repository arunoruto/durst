"""durst in the browser: everything the TUI does, styled with Tailwind, charts by Plotly.

Login works through SSH: ``ssh … login`` prints a one-time link, then the
browser keeps a signed session cookie. Without one you get the guest view.
"""

import datetime as dt
import os
import secrets
from collections import Counter
from pathlib import Path

import flask
import plotly.graph_objects as go
import plotly.io as pio
from dash import ALL, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate

from durst.db import POT, DurstDB, User, can_undo
from durst.tui import FUCHSIA, GREEN, PINK, PURPLE, YELLOW, euro, fingerprint, parse_day, parse_euro

TAILWIND = "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.1.13"
COLORS = [
    PURPLE, PINK, GREEN, YELLOW, "#3AB7BF", "#F2A65A", FUCHSIA,
    "#6CB6FF", "#A3A3A3", "#B45309", "#DC2626", "#65A30D", "#F5F5F4",
]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

CARD = "min-w-0 rounded-2xl border border-neutral-800 bg-neutral-900/60 p-5"
TITLE = "mb-4 text-sm font-semibold uppercase tracking-wider text-neutral-400"
INPUT = "durst-input block w-full"
# Form fields in plain CSS: Dash 4 styles its inputs (and wraps dcc.Input in a
# container) with unlayered CSS, which beats Tailwind's layered utilities.
CSS = """<style>
.durst-input { background: #0a0a0a !important; border: 1px solid #404040 !important;
  border-radius: .5rem !important; color: #f5f5f5 !important; padding: .5rem .75rem !important;
  font-size: .875rem !important; box-shadow: none !important; height: auto !important; }
.durst-input:focus-within { border-color: #f472b6 !important; outline: none !important; }
.durst-input .dash-input-element { all: unset; width: 100%; color: inherit; }
.durst-input::placeholder, .durst-input .dash-input-element::placeholder { color: #525252; }
</style>"""
BAR = "sticky bottom-4 mt-4 flex-wrap items-center gap-3 rounded-xl border border-pink-400/60 bg-neutral-900 p-3 shadow-lg"
BTN = "rounded-lg px-4 py-2 text-sm font-semibold text-white hover:brightness-110 cursor-pointer"
BTN_GHOST = (
    "rounded-lg border border-neutral-700 px-3 py-1 text-xs text-neutral-300"
    " hover:border-pink-400 hover:text-pink-300 cursor-pointer"
)

# plotly_dark, see-through and in Charm colors; a figure's own settings win
TEMPLATE = go.layout.Template(pio.templates["plotly_dark"])
TEMPLATE.layout.update(
    margin=dict(l=8, r=8, t=8, b=8),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    colorway=COLORS,
    font=dict(family="ui-sans-serif, system-ui, sans-serif", color="#d4d4d4"),
    legend=dict(orientation="h", y=-0.15),
    hoverlabel=dict(bgcolor="#1a1a1a"),
)


# ------------------------------------------------------------------ helpers
def _ssh(suffix: str = "") -> str:
    return (os.environ.get("DURST_SSH") or "ssh <durst host>") + suffix


def _graph(fig: go.Figure, height: int = 320) -> dcc.Graph:
    # responsive: follows its card when Tailwind (loaded at runtime) changes the layout
    return dcc.Graph(
        figure=fig.update_layout(template=TEMPLATE),
        config={"displayModeBar": False, "responsive": True},
        style={"height": f"{height}px"},
    )


def _card(title: str, *children, wide: bool = False) -> html.Div:
    return html.Div(
        [html.H2(title, className=TITLE), *children],
        className=CARD + (" lg:col-span-2" if wide else ""),
    )


def _kpi(label: str, value: str, color: str = "text-neutral-100") -> html.Div:
    return html.Div(
        [
            html.Div(label, className="text-sm text-neutral-400"),
            html.Div(value, className=f"mt-1 text-3xl font-bold {color}"),
        ],
        className=CARD,
    )


def _table(headers: list[str], rows: list[list]) -> html.Table:
    return html.Table(
        [
            html.Thead(html.Tr([
                html.Th(h, className="pb-2 text-left font-medium text-neutral-400 last:text-right")
                for h in headers
            ])),
            html.Tbody([
                html.Tr(
                    [html.Td(c, className="py-1.5 pr-3 last:pr-0 last:text-right tabular-nums") for c in row],
                    className="border-t border-neutral-800",
                )
                for row in rows
            ]),
        ],
        className="w-full text-sm",
    )


def _money(amount: float) -> html.Span:
    color = "text-emerald-400" if amount > 0.004 else "text-rose-400" if amount < -0.004 else "text-neutral-500"
    return html.Span(euro(amount, sign=True), className=color)


def _field(label: str, component) -> html.Label:
    return html.Label(
        [html.Span(label, className="mb-1 block text-xs text-neutral-400"), component],
        className="block",
    )


def _input(id_: str, placeholder: str = "", value: str = "", **kw) -> dcc.Input:
    return dcc.Input(id=id_, placeholder=placeholder, value=value, className=INPUT, type="text", **kw)


def _button(id_, label: str, color: str = PINK) -> html.Button:
    return html.Button(label, id=id_, className=BTN, style={"background": color})


def _date(value: str) -> str:
    """``2026-11-10 14:30:00`` -> ``10.11. 14:30``."""
    return f"{value[8:10]}.{value[5:7]}. {value[11:16]}" if value and len(value) >= 16 else value or ""


def _toast(message: str, error: bool = False) -> html.Div:
    color = "border-rose-500/50 text-rose-200" if error else "border-pink-400/50 text-neutral-100"
    return html.Div(message, className=f"rounded-xl border bg-neutral-900 px-4 py-3 text-sm {color}")


def current_user(db: DurstDB) -> User | None:
    """The logged-in user (from the session cookie), if still approved."""
    uid = flask.session.get("uid")
    user = db.get_user_by_id(uid) if uid else None
    return user if user and user.approved and user.role != "pot" else None


# -------------------------------------------------------------------- pages
def header(db: DurstDB, me: User | None, admin: bool, path: str) -> html.Header:
    tabs = [("/", "Drinks"), ("/history", "History"), ("/balances", "Balances"), ("/stats", "Stats")]
    if me:
        tabs.append(("/me", "Me"))
    if admin:
        n = len(db.get_pending_keys()) + len(db.get_deposit_requests())
        tabs.append(("/admin", f"Admin ({n})" if n else "Admin"))
    nav = html.Nav(
        [
            dcc.Link(
                label,
                href=href,
                className="rounded-md px-3 py-1 text-sm "
                + ("font-semibold text-white" if href == path else "text-neutral-400 hover:text-neutral-100"),
                style={"background": PINK} if href == path else {},
            )
            for href, label in tabs
        ],
        className="flex flex-wrap gap-1",
    )
    if me:
        right = html.Div(
            [
                html.Span(me.name, className="text-neutral-200"),
                _money(me.balance),
                html.Span("admin", className="rounded px-1.5 text-xs font-bold text-white",
                          style={"background": FUCHSIA}) if admin else None,
                html.A("log out", href="/logout", className="text-xs text-neutral-500 hover:text-neutral-300"),
            ],
            className="flex items-center gap-3 text-sm",
        )
    else:
        right = html.Div(
            [
                html.Span("Log in: ", className="text-neutral-500"),
                html.Code(_ssh(" login"), className="rounded bg-neutral-900 px-2 py-1", style={"color": PINK}),
            ],
            className="text-sm",
        )
    return html.Header(
        [
            html.Div(
                [
                    html.Span("durst", className="rounded px-2 py-0.5 text-xl font-bold text-white",
                              style={"background": PURPLE}),
                    nav,
                ],
                className="flex flex-wrap items-center gap-4",
            ),
            right,
        ],
        className="flex flex-wrap items-center justify-between gap-4",
    )


def drinks_page(db: DurstDB, me: User | None, admin: bool) -> list:
    stock = db.get_stock_status()
    available = [s for s in stock if s["total_remaining"] > 0]
    cards = []
    if me and me.user_id is not None:
        last = db.last_taken(me.user_id)  # move-to-front: what you took last comes first
        available.sort(key=lambda s: last.index(s["drink_name"]) if s["drink_name"] in last else len(last))
        users = [u.name for u in db.get_all_users()]
        who = (
            html.Div(
                [
                    _field("For", _input("buy-for", value=me.name, list="buy-users",
                                         persistence=True, persistence_type="session")),
                    html.Datalist([html.Option(value=u) for u in users], id="buy-users"),
                ],
                className="mb-4 max-w-xs",
            )
            if admin
            else dcc.Input(id="buy-for", type="hidden", value=me.name)
        )
        tiles = [
            html.Div(
                [
                    html.Button(
                        [
                            html.Div(s["drink_name"], className="font-semibold text-neutral-100"),
                            html.Div(f"{euro(s['price'])} · {s['total_remaining']} left",
                                     className="mt-1 text-xs text-neutral-400"),
                            html.Span(id={"type": "count", "drink": s["drink_name"]}, className="hidden"),
                        ],
                        id={"type": "buy", "drink": s["drink_name"]},
                        className="w-full h-full cursor-pointer rounded-xl border border-neutral-800 bg-neutral-950"
                        " p-4 text-left transition hover:border-pink-400 hover:bg-neutral-900 active:scale-95",
                    ),
                    html.Button("−", id={"type": "unbuy", "drink": s["drink_name"]}, className="hidden",
                                title="one less"),
                ],
                className="relative",
            )
            for s in available
        ]
        today = dt.date.today()
        days = [today - dt.timedelta(days=i) for i in range(1, 8)]
        catch_up = html.Div(
            [
                html.Span(id="cu-summary", className="text-sm text-neutral-200 sm:mr-auto"),
                html.Div(
                    [
                        _input("cu-day", "yesterday, 3.11.", value="yesterday", list="cu-days"),
                        html.Datalist([html.Option(value="yesterday")] + [
                            html.Option(value=f"{d.day}.{d.month}.", label=f"{d:%A}") for d in days
                        ], id="cu-days"),
                    ],
                    className="w-40",
                ),
                _button("cu-go", "Book"),
                html.Button("clear", id="cu-clear", className=BTN_GHOST),
            ],
            id="cu-bar",
            className=BAR + " hidden",
        )
        cards.append(_card(
            "Grab a drink",
            dcc.Store(id="basket", data=None),  # None: one tap books; a dict: catching up
            html.Div(
                [who, html.Button("Forgot to book? Catch up", id="cu-toggle", className=BTN_GHOST + " mb-4")],
                className="flex flex-wrap items-end justify-between gap-3",
            ),
            html.Div(tiles, className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4")
            if tiles else html.P("Nothing in stock right now.", className="text-neutral-400"),
            html.P("One tap books it. Tapped the wrong one? Undo it in History.",
                   id="buy-hint", className="mt-4 text-xs text-neutral-500"),
            catch_up,
            wide=True,
        ))
    else:
        cards.append(_card(
            "Want a drink?",
            html.P(["Log in with ", html.Code(_ssh(" login"), style={"color": PINK}),
                    ". New here? Run ", html.Code(_ssh(), style={"color": PINK}),
                    " and press r to register your SSH key."],
                   className="text-sm leading-relaxed text-neutral-300"),
            wide=True,
        ))
    rows = [
        [s["drink_name"], euro(s["price"]) if s["price"] is not None else "–",
         str(s["total_remaining"]) if s["total_remaining"] else html.Span("sold out", className="text-neutral-500")]
        for s in sorted(stock, key=lambda s: (s["total_remaining"] == 0, s["drink_name"]))
    ]
    cards.append(_card("Stock", _table(["Drink", "Price", "In stock"], rows), wide=True))
    return cards


def history_page(db: DurstDB, me: User | None, admin: bool) -> list:
    rows = []
    for p in db.get_recent_purchases(limit=200):
        undo = (
            html.Button("undo", id={"type": "undo", "id": p["purchase_id"]}, className=BTN_GHOST)
            if me and can_undo(p, me.name, admin)
            else ""
        )
        rows.append([html.Span(_date(p["purchase_date"]), className="text-neutral-500"),
                     p["user_name"], p["drink_name"], euro(p["cost"]), undo])
    return [_card("History", _table(["When", "Who", "Drink", "Price", ""], rows))]


def balances_page(db: DurstDB, me: User | None, admin: bool) -> list:
    rows = [
        [html.Span(u.name, className="font-semibold text-pink-300" if me and u.name == me.name else ""),
         _money(u.balance)]
        for u in db.get_all_users()
    ]
    return [_card("Balances", _table(["Name", "Balance"], rows))]


def stats_page(db: DurstDB, me: User | None, admin: bool) -> list:
    now = dt.datetime.now()
    rows = [(dt.datetime.fromisoformat(p["purchase_date"]), p) for p in db.all_purchases()]
    stock = db.get_stock_status()
    monday = (now - dt.timedelta(days=now.weekday())).date()

    def since(days: int) -> list[tuple[dt.datetime, dict]]:
        return [(d, p) for d, p in rows if (now - d).days < days]

    # One color per drink in every chart, the most popular ones get the palette's best.
    color = {
        name: COLORS[i % len(COLORS)]
        for i, (name, _) in enumerate(Counter(p["drink"] for _, p in rows).most_common())
    }

    # Drinks per week, stacked by drink (26 weeks).
    weeks = [monday - dt.timedelta(weeks=i) for i in range(25, -1, -1)]
    per_week = Counter(
        ((d.date() - dt.timedelta(days=d.weekday())), p["drink"]) for d, p in since(26 * 7)
    )
    drinks = [name for name, _ in Counter(p["drink"] for _, p in since(26 * 7)).most_common()]
    weekly = go.Figure([
        go.Bar(name=name, x=weeks, y=[per_week[(w, name)] for w in weeks], marker_color=color[name])
        for name in drinks
    ])
    weekly.update_layout(barmode="stack", xaxis=dict(tickformat="KW %V"), bargap=0.25)

    # Favourite drinks (90 days).
    share = Counter(p["drink"] for _, p in since(90)).most_common()
    donut = go.Figure(go.Pie(
        labels=[n for n, _ in share], values=[c for _, c in share], hole=0.6, sort=False,
        textinfo="percent", textposition="inside",
        marker=dict(colors=[color[n] for n, _ in share], line=dict(color="#171717", width=2)),
    ))
    donut.update_layout(
        uniformtext=dict(minsize=11, mode="hide"),
        legend=dict(orientation="v", x=1, y=0.5, xanchor="left"),
    )

    # When are we thirsty? (rows imported without a time sit at 00:00; skip them)
    timed = [d for d, _ in rows if d.time() != dt.time()]
    hours = list(range(7, 21))
    slots = Counter((d.weekday(), d.hour) for d in timed)
    heat = go.Figure(go.Heatmap(
        x=[f"{h}:00" for h in hours], y=WEEKDAYS,
        z=[[slots[(wd, h)] for h in hours] for wd in range(5)],
        colorscale=[[0, "#171717"], [0.5, PURPLE], [1, FUCHSIA]], showscale=False,
        hovertemplate="%{y} %{x}: %{z} drinks<extra></extra>",
    ))
    heat.update_yaxes(autorange="reversed")

    # Thirstiest (90 days).
    top = Counter(p["user"] for _, p in since(90)).most_common(10)[::-1]
    people = go.Figure(go.Bar(
        x=[c for _, c in top], y=[n for n, _ in top], orientation="h",
        marker=dict(color=[c for _, c in top], colorscale=[[0, "#5A56E0"], [1, FUCHSIA]]),
    ))

    in_stock = sum(s["total_remaining"] for s in stock)
    kpis = html.Div(
        [
            _kpi("Today", str(sum(d.date() == now.date() for d, _ in rows))),
            _kpi("This week", str(sum(d.date() >= monday for d, _ in rows))),
            _kpi("Last 30 days", str(len(since(30)))),
            _kpi("Bottles in stock", str(in_stock), "text-emerald-400" if in_stock else "text-rose-400"),
        ],
        className="grid grid-cols-2 gap-4 md:grid-cols-4",
    )
    return [
        kpis,
        html.Div(
            [
                _card("Drinks per week", _graph(weekly), wide=True),
                _card("Favourites · 90 days", _graph(donut)),
                _card("Thirstiest · 90 days", _graph(people)),
                _card("When we get thirsty", _graph(heat, 260), wide=True),
            ],
            className="grid gap-4 lg:grid-cols-2",
        ),
    ]


def me_page(db: DurstDB, me: User | None, admin: bool) -> list:
    if me is None or me.user_id is None:
        return [_card("Me", html.P(["Log in first: ", html.Code(_ssh(" login"))]))]
    pending = db.get_deposit_requests(me.user_id)
    profile = _card(
        "Profile",
        html.Div(
            [
                html.Div([html.Span("Name", className="w-20 text-neutral-500"),
                          html.Span(me.name, className="font-semibold text-pink-300")], className="flex"),
                html.Div([html.Span("Role", className="w-20 text-neutral-500"), me.role], className="flex"),
                html.Div([html.Span("Balance", className="w-20 text-neutral-500"), _money(me.balance)],
                         className="flex"),
            ],
            className="mb-4 space-y-1 text-sm",
        ),
        html.Div(
            [
                html.Div(_field("Email", _input("email-input", "mira@tu-dortmund.de", me.email or "")),
                         className="grow"),
                _button("email-save", "Save", PURPLE),
            ],
            className="flex items-end gap-2",
        ),
        html.P("Your name links you to the sheet; ask an admin to change it.",
               className="mt-3 text-xs text-neutral-500"),
    )
    money = _card(
        "Add money",
        html.P("Gave an admin cash (or put it in the Kasse)? Enter it here; it counts once "
               "an admin confirms they got it." if not admin else
               "Put cash in the Kasse yourself? Book it here.",
               className="mb-3 text-sm text-neutral-400"),
        html.Div(
            [
                html.Div(_field("Amount (€)", _input("dep-amount", "10,00", inputMode="decimal")),
                         className="grow"),
                _button("dep-go", "Book" if admin else "Send"),
            ],
            className="flex items-end gap-2",
        ),
        html.Div(
            [
                html.Div(
                    [
                        html.Span(f"+{euro(d['amount'])} · {_date(d['created'])} · waiting for an admin",
                                  className="text-yellow-200"),
                        html.Button("cancel", id={"type": "dep-cancel", "id": d["request_id"]},
                                    className=BTN_GHOST),
                    ],
                    className="flex items-center justify-between text-sm",
                )
                for d in pending
            ],
            className="mt-4 space-y-2",
        ),
    )
    keys = db.get_ssh_keys(me.user_id)
    key_rows = [
        [
            k["label"] or html.Span("(no label)", className="text-neutral-500"),
            html.Code(fingerprint(k["key"])[:30] + "…", className="text-xs text-neutral-500"),
            "active" if k["approved"] else html.Span("waiting for approval", className="text-yellow-200"),
            html.Button("remove", id={"type": "key-del", "key": k["key"]}, className=BTN_GHOST),
        ]
        for k in keys
    ]
    ssh_keys = _card(
        "SSH keys",
        _table(["Key", "Fingerprint", "Status", ""], key_rows),
        html.Div(
            [
                html.Div(_field("Add a key", dcc.Textarea(
                    id="key-input", placeholder="ssh-ed25519 AAAA… laptop", className=INPUT + " h-20 font-mono",
                )), className="grow"),
                _button("key-add", "Add", PURPLE),
            ],
            className="mt-4 flex items-end gap-2",
        ),
        wide=True,
    )
    return [html.Div([profile, money, ssh_keys], className="grid gap-4 lg:grid-cols-2")]


def admin_page(db: DurstDB, me: User | None, admin: bool) -> list:
    if not admin:
        return [_card("Admin", html.P("Admins only.", className="text-neutral-400"))]
    keys = db.get_pending_keys()
    deposits = db.get_deposit_requests()

    def buttons(id_: str, ok: str) -> html.Div:
        return html.Div(
            [
                html.Button(ok, id={"type": "approve", "id": id_}, className=BTN + " py-1 text-xs",
                            style={"background": GREEN}),
                html.Button("reject", id={"type": "reject", "id": id_}, className=BTN_GHOST),
            ],
            className="flex justify-end gap-2",
        )

    approvals = [
        [k["name"], html.Span("new account" if k["new_user"] else "claims account",
                              className="text-emerald-400" if k["new_user"] else "text-yellow-200"),
         html.Span(fingerprint(k["key"])[:23] + "…", className="text-xs text-neutral-500"),
         buttons(k["key"], "approve")]
        for k in keys
    ] + [
        [d["name"], html.Span(f"deposit {euro(d['amount'])}", className="text-pink-300"),
         html.Span(_date(d["created"]), className="text-xs text-neutral-500"),
         buttons(f"deposit:{d['request_id']}", "got the cash")]
        for d in deposits
    ]
    users = [u.name for u in db.get_all_users()]
    drinks = [d.name for d in db.get_all_drink_types()]
    restock = _card(
        "Restock",
        html.P("A new name adds a new drink. The price is what the whole order cost.",
               className="mb-3 text-sm text-neutral-400"),
        html.Div(
            [
                _field("Drink", _input("rs-drink", "Club Mate", list="rs-drinks")),
                _field("Bottles", _input("rs-qty", "20", inputMode="numeric")),
                _field("Total price (€)", _input("rs-total", "18,00", inputMode="decimal")),
                _field("Paid by", _input("rs-payer", value=POT, list="rs-payers")),
            ],
            className="grid grid-cols-2 gap-3",
        ),
        html.Datalist([html.Option(value=d) for d in drinks], id="rs-drinks"),
        html.Datalist([html.Option(value=u) for u in [POT, *users]], id="rs-payers"),
        html.Div(_button("rs-go", "Stock it"), className="mt-4"),
    )
    book = _card(
        "Deposit / payout",
        html.P("Cash someone gave you for the Kasse. Negative for a payout.",
               className="mb-3 text-sm text-neutral-400"),
        html.Div(
            [
                _field("Who", _input("bk-user", "Mira Muster", list="bk-users")),
                _field("Amount (€)", _input("bk-amount", "10,00", inputMode="decimal")),
            ],
            className="grid grid-cols-2 gap-3",
        ),
        html.Datalist([html.Option(value=u) for u in users], id="bk-users"),
        html.Div(_button("bk-go", "Book"), className="mt-4"),
    )
    return [
        _card("Approvals", _table(["Name", "What", "Details", ""], approvals)
              if approvals else html.P("Nothing to approve.", className="text-sm text-neutral-400")),
        html.Div([restock, book], className="grid gap-4 lg:grid-cols-2"),
    ]


PAGES = {
    "/": drinks_page,
    "/history": history_page,
    "/balances": balances_page,
    "/stats": stats_page,
    "/me": me_page,
    "/admin": admin_page,
}


# ---------------------------------------------------------------------- app
def make_app(db_file: str) -> Dash:
    db = DurstDB(db_file=db_file)
    server = flask.Flask(__name__)
    secret = Path(db_file).with_name("web_secret")  # signs the session cookies
    if not secret.exists():
        secret.write_text(secrets.token_hex(32))
        secret.chmod(0o600)
    server.secret_key = secret.read_text().strip()
    server.config.update(
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("DURST_WEB_URL", "").startswith("https"),
        PERMANENT_SESSION_LIFETIME=dt.timedelta(days=90),
    )

    @server.route("/login/<token>")
    def login(token: str):
        uid = db.use_login_token(token)
        if uid is None:
            return (f"That link expired or was used already. Run '{_ssh(' login')}' again.", 400,
                    {"Content-Type": "text/plain; charset=utf-8"})
        flask.session.clear()
        flask.session["uid"] = uid
        flask.session.permanent = True
        return flask.redirect("/")

    @server.route("/logout")
    def logout():
        flask.session.clear()
        return flask.redirect("/")

    app = Dash(
        __name__, server=server, title="durst", external_scripts=[TAILWIND],
        update_title=None, suppress_callback_exceptions=True,
    )
    app.index_string = app.index_string.replace("{%css%}", "{%css%}" + CSS)
    app.layout = html.Div(
        [
            dcc.Location(id="url"),
            dcc.Store(id="version", data=0),
            html.Div(
                [html.Div(id="flash"), html.Div(id="page", className="flex flex-col gap-6")],
                className="mx-auto flex max-w-6xl flex-col gap-4",
            ),
        ],
        className="min-h-screen bg-neutral-950 p-4 text-neutral-200 sm:p-8",
    )

    @app.callback(Output("page", "children"), Input("url", "pathname"), Input("version", "data"))
    def render(path: str, _):
        me = current_user(db)
        admin = bool(me and me.role == "admin")
        page = PAGES.get(path or "/")
        body = page(db, me, admin) if page else [_card("Not found", html.P("Nothing here."))]
        return [header(db, me, admin, path), *body]

    @app.callback(Output("flash", "children", allow_duplicate=True), Input("url", "pathname"),
                  prevent_initial_call=True)
    def clear_flash(_):
        return None

    def action(*deps):
        """Register a button callback: ``fn(me, admin, clicked_id, *values) -> message``."""

        def register(fn):
            @app.callback(
                Output("version", "data", allow_duplicate=True),
                Output("flash", "children", allow_duplicate=True),
                *deps,
                State("version", "data"),
                prevent_initial_call=True,
            )
            def run(*args):
                if not ctx.triggered or not ctx.triggered[0]["value"]:
                    raise PreventUpdate  # a button was just (re)rendered, not clicked
                me = current_user(db)
                if me is None or me.user_id is None:
                    return no_update, _toast(f"Log in first: {_ssh(' login')}", error=True)
                try:
                    message = fn(me, me.role == "admin", ctx.triggered_id, *args[:-1])
                except ValueError as e:
                    return no_update, _toast(str(e), error=True)
                return (args[-1] or 0) + 1, _toast(message)

            return fn

        return register

    def admins_only(admin: bool) -> None:
        if not admin:
            raise ValueError("Admins only.")

    def buyer(me: User, admin: bool, buy_for: str | None) -> str:
        return ((buy_for or "").strip() if admin else "") or me.name

    @action(Input({"type": "buy", "drink": ALL}, "n_clicks"), State("buy-for", "value"),
            State("basket", "data"))
    def buy(me, admin, clicked, _, buy_for, basket):
        if basket is not None:
            raise PreventUpdate  # catching up: the tap goes into the basket instead
        who = buyer(me, admin, buy_for)
        db.add_purchase(who, clicked["drink"])
        return f"{clicked['drink']} for {who}. Prost! 🍻"

    @app.callback(
        Output("basket", "data"),
        Input({"type": "buy", "drink": ALL}, "n_clicks"),
        Input({"type": "unbuy", "drink": ALL}, "n_clicks"),
        Input("cu-toggle", "n_clicks"),
        Input("cu-clear", "n_clicks"),
        State("basket", "data"),
        prevent_initial_call=True,
    )
    def tally(_, __, ___, ____, basket):
        """Catch-up mode keeps a tally per drink, in the browser until booked."""
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        clicked = ctx.triggered_id
        if clicked == "cu-toggle":
            return None if basket is not None else {}
        if clicked == "cu-clear":
            return {}
        if basket is None:
            raise PreventUpdate
        drink = clicked["drink"]
        n = basket.get(drink, 0) + (1 if clicked["type"] == "buy" else -1)
        return {**{d: c for d, c in basket.items() if d != drink}, **({drink: n} if n > 0 else {})}

    @app.callback(
        Output({"type": "count", "drink": ALL}, "children"),
        Output({"type": "count", "drink": ALL}, "className"),
        Output({"type": "unbuy", "drink": ALL}, "className"),
        Output("cu-bar", "className"),
        Output("cu-summary", "children"),
        Output("cu-toggle", "children"),
        Output("buy-hint", "children"),
        Input("basket", "data"),
    )
    def show_basket(basket):
        drinks = [o["id"]["drink"] for o in ctx.outputs_list[0]]
        counts = [(basket or {}).get(d, 0) for d in drinks]
        prices = {s["drink_name"]: s["price"] or 0 for s in db.get_stock_status()}
        n = sum((basket or {}).values())
        total = sum(prices.get(d, 0) * c for d, c in (basket or {}).items())
        badge = "absolute right-2 bottom-2 rounded-full px-2 text-sm font-bold text-white bg-pink-500"
        minus = (
            "absolute -left-2 -top-2 h-7 w-7 cursor-pointer rounded-full border border-neutral-600"
            " bg-neutral-900 text-neutral-200 hover:border-pink-400"
        )
        return (
            [f"×{c}" if c else "" for c in counts],
            [badge if c else "hidden" for c in counts],
            [minus if c else "hidden" for c in counts],
            BAR + (" flex" if basket is not None else " hidden"),
            f"{n} drink{'s' if n != 1 else ''} · {euro(total)}" if n else "Tap what you had, as often as you had it.",
            "Back to one-tap" if basket is not None else "Forgot to book? Catch up",
            "Catching up: taps count up instead of booking. Pick the day below and book them all at once."
            if basket is not None else "One tap books it. Tapped the wrong one? Undo it in History.",
        )

    @action(Input("cu-go", "n_clicks"), State("basket", "data"), State("cu-day", "value"),
            State("buy-for", "value"))
    def catch_up(me, admin, clicked, _, basket, raw_day, buy_for):
        day = parse_day(raw_day or "")
        if day is None:
            raise ValueError("Pick the day like yesterday or 3.11. (not in the future).")
        drinks = [d for d, c in (basket or {}).items() for _ in range(c)]
        if not drinks:
            raise ValueError("Tap the drinks you had first.")
        who = buyer(me, admin, buy_for)
        db.add_purchases(who, drinks, day)
        when = "today" if day == dt.date.today() else f"{day:%a %d.%m.}"
        return f"Booked {len(drinks)} drink{'s' if len(drinks) != 1 else ''} for {who} ({when}). Prost! 🍻"

    @action(Input({"type": "undo", "id": ALL}, "n_clicks"))
    def undo(me, admin, clicked, _):
        p = next((p for p in db.get_recent_purchases(limit=500) if p["purchase_id"] == clicked["id"]), None)
        if p is None or not can_undo(p, me.name, admin):
            raise ValueError("You can undo your own drinks for 15 minutes; ask an admin.")
        db.undo_purchase(p["purchase_id"])
        return f"Undone: {p['user_name']}'s {p['drink_name']}. The bottle is back in stock."

    @action(Input("email-save", "n_clicks"), State("email-input", "value"))
    def save_email(me, admin, clicked, _, email):
        db.set_email(me.user_id, (email or "").strip())
        return "Email saved."

    @action(Input("key-add", "n_clicks"), State("key-input", "value"))
    def add_key(me, admin, clicked, _, key):
        db.add_ssh_key(me.user_id, (key or "").strip())  # logged in: no approval needed
        return "Key added. You can log in with it now."

    @action(Input({"type": "key-del", "key": ALL}, "n_clicks"))
    def remove_key(me, admin, clicked, _):
        active = [k["key"] for k in db.get_ssh_keys(me.user_id) if k["approved"]]
        if active == [clicked["key"]]:
            raise ValueError("That's your last key. Add another one first, or you're locked out.")
        db.remove_ssh_key(me.user_id, clicked["key"])
        return "Key removed."

    @action(Input("dep-go", "n_clicks"), State("dep-amount", "value"))
    def add_money(me, admin, clicked, _, raw):
        amount = parse_euro(raw or "")
        if not amount or amount <= 0:
            raise ValueError("Enter an amount like 10 or 5,50.")
        if admin:  # admins hold the cash themselves
            db.add_repayment(me.user_id, db.pot_id(), amount, received_by=me.user_id)
            return f"{euro(amount, sign=True)} booked."
        db.request_deposit(me.user_id, amount)
        return "Sent. It counts once an admin confirms they got the money."

    @action(Input({"type": "dep-cancel", "id": ALL}, "n_clicks"))
    def cancel_deposit(me, admin, clicked, _):
        if clicked["id"] not in {d["request_id"] for d in db.get_deposit_requests(me.user_id)}:
            raise ValueError("That request is gone already.")
        db.reject_deposit(clicked["id"])
        return "Request cancelled."

    @action(Input({"type": "approve", "id": ALL}, "n_clicks"))
    def approve(me, admin, clicked, _):
        admins_only(admin)
        what = clicked["id"]
        if what.startswith("deposit:"):
            db.approve_deposit(int(what.split(":")[1]), me.user_id)
            return "Deposit booked."
        db.approve_key(what)
        return "Approved. Welcome aboard! 🎉"

    @action(Input({"type": "reject", "id": ALL}, "n_clicks"))
    def reject(me, admin, clicked, _):
        admins_only(admin)
        what = clicked["id"]
        if what.startswith("deposit:"):
            db.reject_deposit(int(what.split(":")[1]))
        else:
            db.reject_key(what)
        return "Request rejected."

    @action(Input("rs-go", "n_clicks"), State("rs-drink", "value"), State("rs-qty", "value"),
            State("rs-total", "value"), State("rs-payer", "value"))
    def restock(me, admin, clicked, _, drink, qty, total, payer):
        admins_only(admin)
        price = parse_euro(total or "")
        if not (qty or "").strip().isdigit() or price is None:
            raise ValueError("Bottles must be a whole number and the price look like 21,60.")
        name = db.restock(drink or "", int(qty), price, (payer or POT).strip())
        return f"{qty} × {name} in stock ({euro(price / int(qty))} a bottle)."

    @action(Input("bk-go", "n_clicks"), State("bk-user", "value"), State("bk-amount", "value"))
    def book(me, admin, clicked, _, who, raw):
        admins_only(admin)
        amount = parse_euro(raw or "")
        uid = db.get_user_id_by_name((who or "").strip())
        if uid is None or not amount:
            raise ValueError("Pick a person and an amount like 10 or -5,50.")
        # Cash into the Kasse settles debt; a payout goes the other way.
        if amount > 0:
            db.add_repayment(uid, db.pot_id(), amount, received_by=me.user_id)
        else:
            db.add_repayment(db.pot_id(), uid, -amount, received_by=me.user_id)
        return f"{euro(amount, sign=True)} for {who}."

    return app
