import re

import pytest

from durst.db import DurstDB
from durst.sheet import ACCOUNTS, DRINKS, ORDERS, num, parse_date, sync


class FakeSheet:
    """In-memory stand-in for SheetClient: tabs are row lists incl. the header."""

    def __init__(self, tabs: dict[str, list[list]], names=(), drinks=()):
        self.tabs = {t: [list(r) for r in rows] for t, rows in tabs.items()}
        self.formulas: dict[tuple, str] = {}
        self.requests: list[dict] = []
        self.merges: dict[str, list[dict]] = {}
        self.rules = [
            {"condition": {"values": [{"userEnteredValue": n} for n in names]}},
            {"condition": {"values": [{"userEnteredValue": d} for d in drinks]}},
        ]

    @staticmethod
    def _range(a1: str):
        m = re.fullmatch(r"'(.+)'!([A-Z])(\d+)(?::([A-Z])(\d*))?", a1)
        assert m, a1
        tab, c1, r1, c2, r2 = m.groups()
        c1 = ord(c1) - 65
        c2 = ord(c2) - 65 if c2 else c1
        return tab, int(r1) - 1, c1, c2, int(r2) if r2 else None

    def cell(self, tab: str, row: int, col: str):
        rows = self.tabs[tab]
        r, c = row - 1, ord(col) - 65
        return rows[r][c] if r < len(rows) and c < len(rows[r]) else ""

    def read(self, ranges, render="UNFORMATTED_VALUE"):
        out = []
        for a1 in ranges:
            tab, r1, c1, c2, r2 = self._range(a1)
            rows = []
            for r, row in enumerate(self.tabs[tab][r1:r2], start=r1):
                vals = [
                    self.formulas.get((tab, r, c), row[c] if c < len(row) else "")
                    if render == "FORMULA"
                    else (row[c] if c < len(row) else "")
                    for c in range(c1, c2 + 1)
                ]
                while vals and vals[-1] == "":
                    vals.pop()
                rows.append(vals)
            while rows and not rows[-1]:
                rows.pop()
            out.append(rows)
        return out

    def write(self, cells):
        for a1, values in cells.items():
            tab, r, c1, _, _ = self._range(a1)
            rows = self.tabs[tab]
            while len(rows) <= r:
                rows.append([])
            row = rows[r]
            for i, v in enumerate(values):
                while len(row) <= c1 + i:
                    row.append("")
                row[c1 + i] = v
                if isinstance(v, str) and v.startswith("="):
                    self.formulas[(tab, r, c1 + i)] = v

    def meta(self):
        return {
            "locale": "de_DE", "sheet_id": 1, "row_count": 2000,
            "rules": self.rules, "merges": self.merges,
            "tab_ids": {ACCOUNTS: 2, DRINKS: 1, ORDERS: 0},
        }

    def batch_update(self, requests):
        self.requests += requests


def make_sheet():
    return FakeSheet(
        {
            ORDERS: [
                ["Datum", "Getränkeart", "Menge", "Preis", "Preis pro Flasche"],
                [45812, "Club Mate", 40, 36.0, 0.9],
                [45813, "Wasser", 12, 7.44, 0.62],
            ],
            DRINKS: [
                ["Datum", "Name", "Getränk", "Anzahl", "Preis", "Kosten", "Index", "Notiz"],
                ["05.06.2025 09:19", "Tom", "Club Mate", 3, 0.9, 2.7, 2],
                ["25.07.", "Kay", "Wasser", 1, 0.62, 0.62, 3, "no year"],
                ["", "Kay", "", 1, "", 0, 1000, "", "a note"],  # half-typed: ignored
                ["", "", "", 1, "", 0, 1000],  # template row: free
            ],
            ACCOUNTS: [
                ["Name", "Einzahlungen", "Kosten", "Guthaben"],
                ["Tom", 10, 2.7, 7.3],
                ["Kay", "19,65 €", 0.62, 19.03],
            ],
        },
        names=["Tom", "Kay"],
        drinks=["Club Mate", "Wasser"],
    )


def test_parsers():
    assert num("1.234,56 €") == pytest.approx(1234.56)
    assert parse_date("12.6.25, 13:08", None).isoformat() == "2025-06-12T13:08:00"
    prev = parse_date("24.07.2025", None)
    assert parse_date("25.07.", prev).isoformat() == "2025-07-25T00:00:00"
    assert parse_date(45812, None).date().isoformat() == "2025-06-04"


def test_sync_two_way(tmp_path):
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    sheet = make_sheet()

    sync(db, sheet)
    balances = {u.name: round(u.balance, 2) for u in db.get_all_users()}
    assert balances == {"Tom": 7.3, "Kay": 19.03}
    assert {s["drink_name"]: s["total_remaining"] for s in db.get_stock_status()} == {
        "Club Mate": 37,
        "Wasser": 11,
    }
    assert sheet.cell(DRINKS, 2, "Z").startswith("s")  # stamped with a sync key
    assert sheet.cell(ACCOUNTS, 2, "D") == "=B2+E2-C2"
    assert sheet.cell(ACCOUNTS, 2, "E") == "0 €"

    # Idempotent: a second run imports nothing and adds no rows.
    assert sync(db, sheet) == []
    assert len(db.all_purchases()) == 4

    # durst -> sheet: a purchase, a durst-side deposit and a new user.
    db.add_purchase("Tom", "Wasser")
    tom = db.get_user_id_by_name("Tom")
    assert tom is not None
    db.add_repayment(tom, db.pot_id(), 5)
    db.add_user("Neu", verbose=False)
    log = sync(db, sheet)
    assert "added 1 drink(s) to sheet" in log
    assert sheet.tabs[DRINKS][4][1:5] == ["Tom", "Wasser", 1, "0,62 €"]
    assert re.fullmatch(r"\d\d\.\d\d\.\d{4} \d\d:\d\d:\d\d", sheet.cell(DRINKS, 5, "A"))
    assert sheet.cell(DRINKS, 5, "Z").startswith("p")
    assert sheet.cell(ACCOUNTS, 2, "E") == "5 €"  # durst-side money shows up in E
    assert sheet.cell(ACCOUNTS, 4, "A") == "Neu"
    assert [v["userEnteredValue"] for v in sheet.rules[0]["condition"]["values"]][-1] == "Neu"

    # sheet -> durst: a new deposit typed into the sheet.
    sheet.tabs[ACCOUNTS][2][1] = 30
    assert "deposit +10.35 € from sheet: Kay" in sync(db, sheet)
    assert round(db.get_user_by_name("Kay").balance, 2) == 29.38


def test_unsettled_rows_wait_one_round(tmp_path):
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    sheet = make_sheet()
    seen: dict = {}
    sync(db, sheet, seen)
    assert db.all_purchases() == []  # first sight: not settled yet
    sync(db, sheet, seen)
    assert len(db.all_purchases()) == 4


def test_merged_key_cells_are_never_written(tmp_path):
    """Google drops writes into merged cells; such rows must not loop."""
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    sheet = make_sheet()
    # Row 3's key cell and the free row 5 sit inside merges (0-based indices).
    sheet.merges[DRINKS] = [
        {"startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 24, "endColumnIndex": 26},
        {"startRowIndex": 4, "endRowIndex": 5, "startColumnIndex": 20, "endColumnIndex": 26},
    ]
    log = sync(db, sheet)
    assert f"{DRINKS} row 3: Z3 is merged, unmerge it to sync this row" in log
    assert sheet.cell(DRINKS, 3, "Z") == ""
    db.add_purchase("Tom", "Wasser")
    sync(db, sheet)
    assert sheet.cell(DRINKS, 5, "A") == ""  # merged free row skipped
    assert sheet.cell(DRINKS, 6, "B") == "Tom"  # appended past the end instead


def test_rows_from_another_database_are_left_alone(tmp_path):
    """A reset/restored DB restarts its ids; old durst rows must not count as its own."""
    sheet = make_sheet()
    old = DurstDB(db_file=str(tmp_path / "old.db"))
    sync(old, sheet)
    old.add_purchase("Tom", "Wasser")
    sync(old, sheet)

    new = DurstDB(db_file=str(tmp_path / "new.db"))
    assert new.db_id != old.db_id
    log = sync(new, sheet)
    assert "1 row(s) were added by another durst database; ignored" in log
    new.add_purchase("Kay", "Wasser")  # same purchase id the old DB used
    assert "added 1 drink(s) to sheet" in sync(new, sheet)


def test_future_dates_are_typos(tmp_path):
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    sheet = make_sheet()
    sheet.tabs[DRINKS][2][0] = "19.11.2035"  # meant 2025
    log = sync(db, sheet)
    assert "row 3: date 19.11.2035 is in the future, using 05.06.2025" in log
    assert max(p["purchase_date"] for p in db.all_purchases()) < "2026"
    assert sync(db, sheet) == []  # reported once, not on every sync


def test_undone_purchases_leave_the_sheet(tmp_path):
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    sheet = make_sheet()
    sync(db, sheet)
    pid = db.add_purchase("Tom", "Wasser")
    sync(db, sheet)
    assert sheet.cell(DRINKS, 5, "B") == "Tom"
    db.undo_purchase(pid)
    assert "removed undone drink from sheet: Tom Wasser" in sync(db, sheet)
    assert sheet.cell(DRINKS, 5, "B") == "" and sheet.cell(DRINKS, 5, "Z") == ""
    imported = next(p for p in db.all_purchases() if p["sheet_key"])
    with pytest.raises(ValueError, match="came from the sheet"):
        db.undo_purchase(imported["purchase_id"])
