# database_service.py
import sqlite3
from datetime import datetime

DB_FILE = "sqlite.db"


def setup_database(db_file: str = DB_FILE):
    """Create the database table if it doesn't exist."""
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    # Create a simple table for purchases
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            drink_name TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


def add_purchase(user: str, drink: str, db_file: str = DB_FILE):
    """Adds a new purchase record to the database."""
    timestamp = datetime.now().isoformat()
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO purchases (username, drink_name, timestamp) VALUES (?, ?, ?)",
        (user, drink, timestamp),
    )
    con.commit()
    con.close()
    print(f"Database: Added purchase for {user}")


def get_recent_purchases(limit: int = 20, db_file: str = DB_FILE):
    """Fetches the most recent purchase records."""
    con = sqlite3.connect(db_file)
    # This makes the results act like dictionaries
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    res = cur.execute(
        "SELECT username, drink_name, timestamp FROM purchases ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    purchases = [dict(row) for row in res.fetchall()]
    con.close()
    return purchases
