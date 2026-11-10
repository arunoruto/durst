"""Two-way sync with the legacy Google Sheet ("Getränkekasse Büro").

The sheet runs a shared-pot model; durst maps it onto its own:

- sheet orders     -> stock ordered by the pot user (Kasse)
- sheet drinks     -> purchases at the sheet's price
- sheet deposits   -> repayments to the pot (column B of Kontenübersicht)
- durst-only money -> column E "Einzahlungen durst", so Guthaben = B + E - C

Every synced row carries a key in a spare column headed "durst" (F of the
orders, J of the drinks): ``s…`` for rows that came from the sheet,
``b<id>``/``p<id>`` for rows durst added. Keys are written to
the sheet *before* importing, so a crashed sync just resumes next time.

ponytail: edits/deletions of already-synced rows are not propagated; deleted
rows are re-added from durst. Fix mistakes in durst once a row is synced.
"""

import datetime as dt
import fcntl
import re
import uuid

from durst.db import POT, DurstDB

ORDERS, DRINKS, ACCOUNTS = "Preise & Bestellungen", "Getränkeentnahmen", "Kontenübersicht"
EPS = 0.005
KEY = re.compile(r"s[0-9a-f]{8}|[bp]\d+")
HEADER = "durst"
_DATE = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?,?\s*(?:(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def num(v) -> float:
    """Sheet number or German money string ("1.234,56 €") -> float."""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("€", "").replace("\xa0", "").strip()
    return float(s.replace(".", "").replace(",", ".")) if s else 0.0


def parse_date(v, prev: dt.datetime | None) -> dt.datetime | None:
    """Sheet serial number or hand-typed date ("12.6.25, 13:08", "25.07.")."""
    if isinstance(v, (int, float)):
        return dt.datetime(1899, 12, 30) + dt.timedelta(days=v)
    m = _DATE.fullmatch(str(v).strip())
    if not m:
        try:
            return dt.datetime.fromisoformat(str(v).strip())
        except ValueError:
            return None
    d, mo, y, h, mi, sec = m.groups()
    year = int(y) if y else (prev or dt.datetime.now()).year  # "25.07." -> row above
    year += 2000 if year < 100 else 0
    try:
        return dt.datetime(year, int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0))
    except ValueError:
        return None


def _pad(row: list, n: int) -> list:
    return list(row) + [""] * (n - len(row))


def _iso(date: str | dt.datetime) -> str:
    return date if isinstance(date, str) else date.strftime("%Y-%m-%d %H:%M:%S")


class SheetClient:
    """Thin Google Sheets REST client authenticated with a service account."""

    def __init__(self, sheet_id: str, credentials_file: str) -> None:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.http = AuthorizedSession(creds)
        self.url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"

    def _req(self, method: str, path: str = "", **kw) -> dict:
        r = self.http.request(method, self.url + path, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def read(self, ranges: list[str], render: str = "UNFORMATTED_VALUE") -> list[list[list]]:
        j = self._req(
            "GET",
            "/values:batchGet",
            params={
                "ranges": ranges,
                "valueRenderOption": render,
                "dateTimeRenderOption": "SERIAL_NUMBER",
            },
        )
        return [vr.get("values", []) for vr in j["valueRanges"]]

    def write(self, cells: dict[str, list]) -> None:
        """Write one row of values per A1 range, parsed as if typed in."""
        if cells:
            self._req(
                "POST",
                "/values:batchUpdate",
                json={
                    "valueInputOption": "USER_ENTERED",
                    "data": [{"range": r, "values": [v]} for r, v in cells.items()],
                },
            )

    def meta(self) -> dict:
        """Locale plus the dropdown rules of the Getränkeentnahmen name/drink columns."""
        j = self._req(
            "GET",
            params={
                "ranges": [f"'{DRINKS}'!B2:C2"],
                "fields": "properties.locale,sheets(properties(sheetId,gridProperties.rowCount),"
                "data.rowData.values.dataValidation)",
            },
        )
        sheet = j["sheets"][0]
        cells = sheet["data"][0]["rowData"][0]["values"]
        return {
            "locale": j["properties"]["locale"],
            "sheet_id": sheet["properties"]["sheetId"],
            "row_count": sheet["properties"]["gridProperties"]["rowCount"],
            "rules": [c.get("dataValidation") for c in cells],
        }

    def batch_update(self, requests: list[dict]) -> None:
        if requests:
            self._req("POST", ":batchUpdate", json={"requests": requests})


def sync(db: DurstDB, client, seen: dict | None = None) -> list[str]:
    """Run one two-way sync and return a log of what happened.

    ``seen`` carries sheet rows between runs: a new row is only imported once
    it is unchanged since the previous run, so half-typed rows wait. Pass
    ``None`` to import everything immediately (one-shot CLI sync).
    """
    log: list[str] = []
    meta = client.meta()
    sep = "," if meta["locale"].startswith("en") else ";"  # formula argument separator
    orders, drinks, accounts = client.read(
        [f"'{ORDERS}'!A2:F", f"'{DRINKS}'!A2:J", f"'{ACCOUNTS}'!A2:E"]
    )
    (account_formulas,) = client.read([f"'{ACCOUNTS}'!A2:E"], render="FORMULA")
    pot = db.pot_id()
    known = db.known_sheet_keys()
    new_seen: dict = {}

    def stable(tag: tuple, row: list) -> bool:
        new_seen[tag] = tuple(row)
        return seen is None or seen.get(tag) == tuple(row)

    def drink_id(name: str) -> int:
        i = db.add_drink_type(name, verbose=False)
        assert i is not None
        return i

    # 1. Stamp new, settled sheet rows with keys -- before importing anything.
    stamps: dict[str, list] = {}
    order_rows, drink_rows = [], []
    def reserved(tab: str, col: str, r: int, cell) -> bool:
        if cell and not KEY.fullmatch(str(cell).strip()):
            log.append(f"{tab} {col}{r}: column {col} is reserved for durst, row skipped")
            return True
        return False

    for r, row in enumerate(orders, start=2):
        row = _pad(row, 6)
        if row[0] in ("", None) or reserved(ORDERS, "F", r, row[5]):
            continue
        if not row[5] and row[1] and row[2] and stable(("o", r), row):
            row[5] = "s" + uuid.uuid4().hex[:8]
            stamps[f"'{ORDERS}'!F{r}"] = [row[5]]
        order_rows.append((r, row))
    free_rows: list[int] = []  # empty rows (prefilled formulas only) to append into
    for r, row in enumerate(drinks, start=2):
        row = _pad(row, 10)
        if row[0] in ("", None) and not row[1] and not row[2] and not row[9]:
            free_rows.append(r)
            continue
        if reserved(DRINKS, "J", r, row[9]):
            continue
        # no date is fine (the sheet still counts the row): it takes the row above's
        if not row[9] and row[1] and row[2] and stable(("d", r), row):
            row[9] = "s" + uuid.uuid4().hex[:8]
            stamps[f"'{DRINKS}'!J{r}"] = [row[9]]
        drink_rows.append((r, row))
    client.write(stamps)
    if seen is not None:
        seen.clear()
        seen.update(new_seen)

    # 2. Import stamped rows durst doesn't know yet.
    for name in {str(a[0]).strip() for a in accounts if a and a[0]}:
        db.add_user(name, verbose=False)
    prev = None
    for r, row in order_rows:
        date = parse_date(row[0], prev) or prev
        prev = date or prev
        key = str(row[5])
        if not key.startswith("s") or key in known or date is None:
            continue
        qty = int(num(row[2]))
        total = num(row[3])
        if qty <= 0:
            log.append(f"skipped order row {r}: quantity {row[2]!r}")
            continue
        db.stock_new_drinks(
            pot,
            total,
            [{"drink_type_id": drink_id(str(row[1]).strip()), "cost_per_item": total / qty, "quantity": qty}],
            verbose=False,
            date=_iso(date),
            sheet_key=key,
        )
        log.append(f"imported order: {qty} x {row[1]}")
    prev = None
    imported = 0
    for r, row in drink_rows:
        date = parse_date(row[0], prev) or prev
        prev = date or prev
        key = str(row[9])
        if not key.startswith("s") or key in known:
            continue
        user_id = db.add_user(str(row[1]).strip(), verbose=False)
        assert user_id is not None
        count = int(num(row[3]) or 1)
        price = num(row[4]) if row[4] not in ("", None) else None
        try:
            db.import_purchases(
                user_id, drink_id(str(row[2]).strip()), count, price,
                _iso(date or dt.datetime.now()), key,
            )
            imported += count
        except ValueError as e:
            log.append(f"skipped drink row {r}: {e}")
    if imported:
        log.append(f"imported {imported} drink(s)")

    # 3. Append durst rows the sheet doesn't have yet.
    out: dict[str, list] = {}
    in_sheet = {str(row[5]).strip() for _, row in order_rows}
    r = max([1] + [r for r, _ in order_rows])
    for b in db.all_batches():
        key = b["sheet_key"] or f"b{b['batch_id']}"
        if key in in_sheet:
            continue
        r += 1
        total = round(b["initial_qty"] * b["cost_per_item"], 2)
        out[f"'{ORDERS}'!A{r}:F{r}"] = [
            _iso(b["date_added"]), b["drink"], b["initial_qty"], total, f"=D{r}/C{r}", key,
        ]
        log.append(f"added order to sheet: {b['initial_qty']} x {b['drink']}")
    in_sheet = {str(row[9]).strip() for _, row in drink_rows}
    next_row = len(drinks) + 2  # past the last prefilled row
    added = 0
    for p in db.all_purchases():
        key = p["sheet_key"] or f"p{p['purchase_id']}"
        if key in in_sheet:
            continue
        in_sheet.add(key)  # one row per sheet key, even for count > 1 imports
        if free_rows:
            r = free_rows.pop(0)
        else:
            r, next_row = next_row, next_row + 1
        out[f"'{DRINKS}'!A{r}:F{r}"] = [
            _iso(p["purchase_date"]), p["user"], p["drink"], 1, p["cost"], f"=D{r}*E{r}",
        ]
        out[f"'{DRINKS}'!J{r}"] = [key]
        added += 1
    if added:
        log.append(f"added {added} drink(s) to sheet")

    # 4. Accounts: sheet deposits (B) in, durst-side money (E) out.
    rows = {
        str(a[0]).strip(): (r, _pad(a, 5), _pad(f, 5))
        for r, (a, f) in enumerate(zip(accounts, account_formulas), start=2)
        if a and a[0]
    }
    out[f"'{ORDERS}'!F1"] = [HEADER]
    out[f"'{DRINKS}'!J1"] = [HEADER]
    out[f"'{ACCOUNTS}'!E1"] = ["Einzahlungen durst"]
    last = max([1] + [r for r, *_ in rows.values()])
    for user in db.get_all_users():
        if user.name == POT:
            continue
        uid = user.user_id
        assert uid is not None
        if user.name in rows:
            r, values, formulas = rows[user.name]
            deposits = num(values[1])
            delta = db.sync_sheet_deposits(uid, deposits)
            if delta:
                log.append(f"deposit {delta:+.2f} € from sheet: {user.name}")
        else:
            last += 1
            r, values, formulas = last, [""] * 5, [""] * 5
            deposits = db.sheet_deposits(uid)  # 0 for new users; restores a deleted row
            out[f"'{ACCOUNTS}'!A{r}:C{r}"] = [
                user.name, deposits, f"=SUMIF('{DRINKS}'!$B:$B{sep}A{r}{sep}'{DRINKS}'!$F:$F)",
            ]
            log.append(f"added account to sheet: {user.name}")
        durst_side = round(db.credits(uid) - deposits, 2)
        if values[4] in ("", None) or abs(num(values[4]) - durst_side) > EPS:
            out[f"'{ACCOUNTS}'!E{r}"] = [durst_side]
        if str(formulas[3]).replace(" ", "") != f"=B{r}+E{r}-C{r}":
            out[f"'{ACCOUNTS}'!D{r}"] = [f"=B{r}+E{r}-C{r}"]

    # 5. Keep the sheet's dropdowns in step with durst's users and drinks.
    wanted = [
        [u.name for u in db.get_all_users()],
        [d.name for d in db.get_all_drink_types()],
    ]
    requests = []
    for col, (rule, names) in enumerate(zip(meta["rules"], wanted), start=1):
        if not rule:
            continue
        values = rule["condition"]["values"]
        have = {v["userEnteredValue"] for v in values}
        missing = [n for n in names if n not in have]
        if missing:
            values += [{"userEnteredValue": n} for n in missing]
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": meta["sheet_id"],
                        "startRowIndex": 1,
                        "endRowIndex": meta["row_count"],
                        "startColumnIndex": col,
                        "endColumnIndex": col + 1,
                    },
                    "rule": rule,
                }
            })
    client.write(out)
    client.batch_update(requests)
    return log


def locked_sync(db: DurstDB, client, seen: dict | None = None) -> list[str]:
    """``sync`` under a lock file, so the server loop and ``durst sync`` never overlap."""
    with open(db.db_file + ".sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return sync(db, client, seen)
