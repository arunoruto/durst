import os

import click

from durst.db import POT, DurstDB


#################################
#           Helpers             #
#################################
def fmt_money(amount: float) -> str:
    """Format a float as a currency string."""
    return f"{amount:.2f} €"


def echo_table(headers: list[str], rows: list[tuple]) -> None:
    """Print rows as a simple aligned text table."""
    if not rows:
        click.echo("(no entries)")
        return
    str_rows = [[str(cell) for cell in row] for row in rows]
    widths = [
        max(len(header), *(len(row[i]) for row in str_rows))
        for i, header in enumerate(headers)
    ]
    click.echo("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    click.echo("  ".join("-" * w for w in widths))
    for row in str_rows:
        click.echo("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))


def resolve_user_id(db: DurstDB, name: str) -> int:
    """Resolve a user name to an ID or fail with a helpful message."""
    user_id = db.get_user_id_by_name(name)
    if user_id is None:
        raise click.ClickException(
            f"User not found: {name}. Add them with 'durst user add'."
        )
    return user_id


def parse_item(raw: str) -> tuple[str, float, int]:
    """Parse a stock item spec of the form DRINK:PRICE:QTY."""
    parts = raw.rsplit(":", 2)
    if len(parts) != 3:
        raise click.BadParameter(
            f"'{raw}' — expected DRINK:PRICE:QTY (e.g. 'Cola:1.50:24')"
        )
    name, price_raw, qty_raw = parts
    try:
        price = float(price_raw)
        qty = int(qty_raw)
    except ValueError:
        raise click.BadParameter(
            f"'{raw}' — PRICE must be a number and QTY an integer"
        )
    if price < 0 or qty <= 0:
        raise click.BadParameter(
            f"'{raw}' — PRICE must be >= 0 and QTY must be positive"
        )
    return name, price, qty


#################################
#         Entry Point           #
#################################
@click.group(invoke_without_command=True)
@click.option(
    "--db",
    "db_file",
    default="sqlite.db",
    show_default=True,
    envvar="DURST_DB",
    help="Location of the database",
)
@click.pass_context
def cli(ctx: click.Context, db_file: str) -> None:
    """Durst — track drinks, stock, and who owes whom.

    Run without a subcommand to launch the interactive TUI.
    """
    ctx.obj = DurstDB(db_file=db_file)
    if ctx.invoked_subcommand is None:
        from durst.tui import DurstApp

        DurstApp(db_file=db_file).run()


#################################
#        User Commands          #
#################################
@cli.group()
def user() -> None:
    """Manage users."""


@user.command("add")
@click.argument("name")
@click.argument("email", required=False)
@click.pass_obj
def user_add(db: DurstDB, name: str, email: str | None) -> None:
    """Add a new user with NAME and optional EMAIL."""
    existing = db.get_user_by_name(name) or (email and db.get_user_by_email(email))
    if existing:
        raise click.ClickException(
            f"User already exists: {existing.name} <{existing.email or '-'}> "
            f"(id={existing.user_id})"
        )
    user_id = db.add_user(name, email, verbose=False)
    click.echo(f"Added user {name} <{email or '-'}> (id={user_id})")


@user.command("key")
@click.argument("name")
@click.argument("key")
@click.pass_obj
def user_key(db: DurstDB, name: str, key: str) -> None:
    """Let NAME log in over SSH with public KEY ('ssh-ed25519 AAAA...')."""
    try:
        db.add_ssh_key(resolve_user_id(db, name), key)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"Added SSH key for {name}.")


@user.command("promote")
@click.argument("name")
@click.pass_obj
def user_promote(db: DurstDB, name: str) -> None:
    """Make NAME an admin (approves sign-ups, buys for others)."""
    try:
        db.set_role(name, "admin")
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{name} is now an admin.")


@user.command("demote")
@click.argument("name")
@click.pass_obj
def user_demote(db: DurstDB, name: str) -> None:
    """Make admin NAME a normal user again."""
    try:
        db.set_role(name, "user")
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{name} is a normal user again.")


@user.command("list")
@click.pass_obj
def user_list(db: DurstDB) -> None:
    """List all users and their balances."""
    users = db.get_all_users()
    echo_table(
        ["ID", "Name", "Email", "Role", "Balance"],
        [(u.user_id, u.name, u.email or "", u.role, fmt_money(u.balance)) for u in users],
    )


@user.command("balance")
@click.argument("name")
@click.pass_obj
def user_balance(db: DurstDB, name: str) -> None:
    """Show the balance of the user with NAME."""
    found = db.get_user_by_name(name)
    if found is None:
        raise click.ClickException(f"User not found: {name}")
    if found.is_in_debt():
        status = "owes money"
    elif found.is_owed():
        status = "is owed money"
    else:
        status = "is settled"
    click.echo(f"{found.name}: {fmt_money(found.balance)} ({status})")


#################################
#        Drink Commands         #
#################################
@cli.group()
def drink() -> None:
    """Manage the drink catalog."""


@drink.command("add")
@click.argument("name")
@click.option("--brand", default="", help="Brand of the drink")
@click.pass_obj
def drink_add(db: DurstDB, name: str, brand: str) -> None:
    """Add a new drink type with NAME to the catalog."""
    existing = db.get_drink_type_by_name(name)
    if existing:
        raise click.ClickException(
            f"Drink type '{name}' already exists (id={existing.drink_type_id})"
        )
    drink_type_id = db.add_drink_type(name, brand, verbose=False)
    click.echo(f"Added drink type '{name}' (id={drink_type_id})")


@drink.command("list")
@click.pass_obj
def drink_list(db: DurstDB) -> None:
    """List all drink types in the catalog."""
    drinks = db.get_all_drink_types()
    echo_table(
        ["ID", "Name", "Brand"],
        [(d.drink_type_id, d.name, d.brand) for d in drinks],
    )


#################################
#        Stock Commands         #
#################################
@cli.group()
def stock() -> None:
    """Manage drink stock."""


@stock.command("add")
@click.argument("orderer")
@click.option(
    "--item",
    "-i",
    "items",
    multiple=True,
    required=True,
    metavar="DRINK:PRICE:QTY",
    help="Item in the order, e.g. 'Cola:1.50:24'. Repeatable.",
)
@click.option(
    "--total-cost",
    type=float,
    default=None,
    help="Total cost of the order. Defaults to the sum of all items.",
)
@click.pass_obj
def stock_add(
    db: DurstDB, orderer: str, items: tuple[str, ...], total_cost: float | None
) -> None:
    """Record a stock order placed by ORDERER."""
    orderer_id = resolve_user_id(db, orderer)

    parsed_items = []
    for raw in items:
        name, price, qty = parse_item(raw)
        drink_type_id = db.get_drink_type_id_by_name(name)
        if drink_type_id is None:
            raise click.ClickException(
                f"Drink type not found: {name}. Add it with 'durst drink add'."
            )
        parsed_items.append(
            {"drink_type_id": drink_type_id, "cost_per_item": price, "quantity": qty}
        )

    if total_cost is None:
        total_cost = sum(i["cost_per_item"] * i["quantity"] for i in parsed_items)

    order_id = db.stock_new_drinks(orderer_id, total_cost, parsed_items, verbose=False)
    if order_id is None:
        raise click.ClickException("Failed to record the stock order.")
    click.echo(
        f"Order {order_id}: {orderer} stocked {len(parsed_items)} item(s) "
        f"for {fmt_money(total_cost)}"
    )


@stock.command("status")
@click.pass_obj
def stock_status(db: DurstDB) -> None:
    """Show remaining stock per drink type."""
    status = db.get_stock_status()
    echo_table(
        ["Drink", "Brand", "Remaining"],
        [(s["drink_name"], s["brand"] or "", s["total_remaining"]) for s in status],
    )


#################################
#     Transaction Commands      #
#################################
@cli.command()
@click.argument("user")
@click.argument("drink")
@click.option(
    "--count",
    default=1,
    show_default=True,
    type=click.IntRange(min=1),
    help="Number of drinks to buy",
)
@click.pass_obj
def buy(db: DurstDB, user: str, drink: str, count: int) -> None:
    """Record USER taking a DRINK from stock."""
    bought = 0
    try:
        for _ in range(count):
            db.add_purchase(user, drink)
            bought += 1
    except ValueError as e:
        if bought:
            raise click.ClickException(
                f"Recorded {bought} of {count} purchase(s), then failed: {e}"
            )
        raise click.ClickException(str(e))

    buyer = db.get_user_by_name(user)
    balance_note = f" New balance: {fmt_money(buyer.balance)}" if buyer else ""
    click.echo(f"{user} bought {count} x {drink}. Prost! 🍻{balance_note}")


@cli.command()
@click.argument("payer")
@click.argument("receiver")
@click.argument("amount", type=float)
@click.pass_obj
def repay(db: DurstDB, payer: str, receiver: str, amount: float) -> None:
    """Record PAYER paying AMOUNT back to RECEIVER."""
    payer_id = resolve_user_id(db, payer)
    receiver_id = resolve_user_id(db, receiver)
    try:
        db.add_repayment(payer_id, receiver_id, amount)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{payer} paid {fmt_money(amount)} to {receiver}.")


@cli.command()
@click.argument("name")
@click.argument("amount", type=float)
@click.pass_obj
def deposit(db: DurstDB, name: str, amount: float) -> None:
    """Record NAME putting AMOUNT of cash into the pot (Kasse)."""
    try:
        db.add_repayment(resolve_user_id(db, name), db.pot_id(), amount)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"{name} put {fmt_money(amount)} into the {POT}.")


@cli.command()
@click.option(
    "--limit",
    default=20,
    show_default=True,
    type=click.IntRange(min=1),
    help="Maximum number of purchases to show",
)
@click.pass_obj
def history(db: DurstDB, limit: int) -> None:
    """Show the most recent purchases."""
    purchases = db.get_recent_purchases(limit=limit)
    echo_table(
        ["#", "User", "Drink", "Cost", "Date", "Ordered by"],
        [
            (
                p["purchase_id"],
                p["user_name"],
                p["drink_name"],
                fmt_money(p["cost"]),
                p["purchase_date"],
                p["orderer_name"],
            )
            for p in purchases
        ],
    )


@cli.command()
@click.pass_obj
def debts(db: DurstDB) -> None:
    """Show who owes money to whom (gross purchase totals, repayments not deducted)."""
    rows = db.get_user_debts()
    echo_table(
        ["Debtor", "Creditor", "Owed"],
        [
            (d["debtor_name"], d["creditor_name"], fmt_money(d["amount_owed"]))
            for d in rows
        ],
    )


#################################
#          SSH Server           #
#################################
sheet_options = [
    click.option(
        "--sheet-id",
        envvar="DURST_SHEET_ID",
        help="Google Sheet to sync with (the ID from its URL)",
    ),
    click.option(
        "--google-credentials",
        envvar="GOOGLE_APPLICATION_CREDENTIALS",
        type=click.Path(dir_okay=False),
        help="Service account key file (JSON) with edit access to the sheet",
    ),
]


def with_sheet_options(f):
    for option in reversed(sheet_options):
        f = option(f)
    return f


@cli.command()
@with_sheet_options
@click.pass_obj
def sync(db: DurstDB, sheet_id: str | None, google_credentials: str | None) -> None:
    """Sync once with the Google Sheet (the first run imports everything)."""
    from durst.sheet import SheetClient, locked_sync

    if not sheet_id or not google_credentials or not os.path.exists(google_credentials):
        raise click.ClickException(
            "Set --sheet-id and --google-credentials to an existing key file (or their env vars)."
        )
    for line in locked_sync(db, SheetClient(sheet_id, google_credentials)) or ["nothing to do"]:
        click.echo(line)


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=2222, show_default=True, type=int)
@click.option(
    "--host-key",
    default="ssh_host_key",
    show_default=True,
    help="Server host key; generated on first start",
)
@with_sheet_options
@click.option(
    "--sync-interval",
    default=300,
    show_default=True,
    type=click.IntRange(min=30),
    help="Seconds between sheet syncs",
)
@click.pass_obj
def serve(
    db: DurstDB,
    host: str,
    port: int,
    host_key: str,
    sheet_id: str | None,
    google_credentials: str | None,
    sync_interval: int,
) -> None:
    """Serve the TUI over SSH, and sync with the sheet if one is configured."""
    import asyncio

    from durst.ssh import serve as ssh_serve

    sheet = None
    if sheet_id and google_credentials and os.path.exists(google_credentials):
        sheet = (sheet_id, google_credentials, sync_interval)
    elif sheet_id:
        click.echo(f"sheet sync disabled: no credentials file at {google_credentials!r}")
    asyncio.run(ssh_serve(db.db_file, host, port, host_key, sheet))


if __name__ == "__main__":
    cli()
