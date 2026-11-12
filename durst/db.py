import base64
import datetime as dt
import secrets
import sqlite3
from sqlite3 import Error
from typing import Any

from pydantic import BaseModel

DB_FILE = "sqlite.db"
POT = "Kasse"  # the shared pot: pays sheet orders, receives deposits
NOW = "(datetime('now', 'localtime'))"
USER_COLS = "user_id, name, email, balance, role, approved"
UNDO_WINDOW = dt.timedelta(minutes=15)  # users may undo their own drinks this long
LOGIN_TTL = dt.timedelta(minutes=10)  # web login links from `ssh … login`


def can_undo(purchase: dict, user: str | None, admin: bool) -> bool:
    """Admins undo any durst purchase, users their own for UNDO_WINDOW after typing it in."""
    if purchase.get("sheet_key"):
        return False
    entered = purchase.get("entered") or purchase["purchase_date"]
    age = dt.datetime.now() - dt.datetime.fromisoformat(entered)
    return admin or (purchase["user_name"] == user and age <= UNDO_WINDOW)


#################################
#       Domain Classes          #
#################################
class User(BaseModel):
    """Represents a user in the system."""

    user_id: int | None = None
    name: str = ""
    email: str | None = None
    balance: float = 0.0
    role: str = "user"  # user | admin | pot
    approved: bool = True

    def is_in_debt(self) -> bool:
        """Check if user owes money."""
        return self.balance < 0

    def is_owed(self) -> bool:
        """Check if user is owed money."""
        return self.balance > 0

    @classmethod
    def from_db_row(cls, row: tuple) -> "User":
        """Create a User instance from a database row."""
        return cls(
            user_id=row[0],
            name=row[1],
            email=row[2],
            balance=row[3],
            role=row[4] if len(row) > 4 else "user",
            approved=bool(row[5]) if len(row) > 5 else True,
        )


class DrinkType(BaseModel):
    """Represents a drink type."""

    drink_type_id: int | None = None
    name: str = ""
    brand: str = ""

    @classmethod
    def from_db_row(cls, row: tuple) -> "DrinkType":
        """Create a DrinkType instance from a database row."""
        return cls(
            drink_type_id=row[0], name=row[1], brand=row[2] if len(row) > 2 else ""
        )


class Order(BaseModel):
    """Represents a bulk order."""

    order_id: int | None = None
    orderer_id: int = 0
    order_date: str | None = None
    total_cost: float = 0.0

    @classmethod
    def from_db_row(cls, row: tuple) -> "Order":
        """Create an Order instance from a database row."""
        return cls(
            order_id=row[0], orderer_id=row[1], order_date=row[2], total_cost=row[3]
        )


class StockBatch(BaseModel):
    """Represents a batch of stock."""

    batch_id: int | None = None
    drink_type_id: int = 0
    order_id: int = 0
    orderer_id: int = 0
    cost_per_item: float = 0.0
    initial_qty: int = 0
    remaining_qty: int = 0
    date_added: str | None = None

    def is_depleted(self) -> bool:
        """Check if the batch has no remaining stock."""
        return self.remaining_qty <= 0

    @classmethod
    def from_db_row(cls, row: tuple) -> "StockBatch":
        """Create a StockBatch instance from a database row."""
        return cls(
            batch_id=row[0],
            drink_type_id=row[1],
            order_id=row[2],
            orderer_id=row[3],
            cost_per_item=row[4],
            initial_qty=row[5],
            remaining_qty=row[6],
            date_added=row[7] if len(row) > 7 else None,
        )


class Purchase(BaseModel):
    """Represents a drink purchase."""

    purchase_id: int | None = None
    user_id: int = 0
    batch_id: int = 0
    cost: float = 0.0
    charged_to_orderer_id: int = 0
    purchase_date: str | None = None

    @classmethod
    def from_db_row(cls, row: tuple) -> "Purchase":
        """Create a Purchase instance from a database row."""
        return cls(
            purchase_id=row[0],
            user_id=row[1],
            batch_id=row[2],
            cost=row[3],
            charged_to_orderer_id=row[4],
            purchase_date=row[5] if len(row) > 5 else None,
        )


class Repayment(BaseModel):
    """Represents a repayment between users."""

    repayment_id: int | None = None
    payer_id: int = 0
    receiver_id: int = 0
    amount: float = 0.0
    payment_date: str | None = None

    @classmethod
    def from_db_row(cls, row: tuple) -> "Repayment":
        """Create a Repayment instance from a database row."""
        return cls(
            repayment_id=row[0],
            payer_id=row[1],
            receiver_id=row[2],
            amount=row[3],
            payment_date=row[4] if len(row) > 4 else None,
        )


def _normalize_key(key: str) -> str:
    """Validate an OpenSSH public key line and strip its comment."""
    parts = key.split()
    bad = ValueError("Expected an OpenSSH public key like 'ssh-ed25519 AAAA... laptop'")
    if len(parts) < 2:
        raise bad
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except ValueError:
        raise bad from None
    n = int.from_bytes(blob[:4], "big")
    if blob[4 : 4 + n].decode(errors="replace") != parts[0]:  # blob starts with its type
        raise bad
    return " ".join(parts[:2])


def _key_label(key: str) -> str:
    """The comment of a public key line ("laptop"), if any."""
    return " ".join(key.split()[2:])[:40]


#################################
#     Database Manager Class    #
#################################
class DurstDB(BaseModel):
    """
    Main database manager class for the Durst application.

    Handles all database operations including user management, drink inventory,orders, purchases, and repayments.
    """

    db_file: str = DB_FILE

    def model_post_init(self, __context: Any) -> None:
        """
        Initialize the database manager.
        """
        self.setup_database()

    @property
    def db_id(self) -> str:
        """Random id of this database (hex), set when it is created."""
        con = self._get_connection()
        v = con.execute("PRAGMA user_version").fetchone()[0]
        con.close()
        return f"{v:x}"

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection (WAL: cheap commits, readers never block)."""
        con = sqlite3.connect(self.db_file, timeout=30)
        con.execute("PRAGMA synchronous = NORMAL")
        return con

    def setup_database(self):
        """
        Initialize and set up the SQLite database used by the application.
        This function opens (and creates if it does not exist) an SQLite database at the
        given path and ensures that the schema required by the application is present.
        It creates the following tables if they do not already exist:
        - `users`: stores user records (id, name, unique email, balance).
        - `drink_types`: catalog of drink types (id, unique name, price, stock).
        - `orders`: aggregated orders placed by users; stores order metadata and items as JSON.
        - `drink_purchases`: individual purchase records (one row per purchased item).
        - `repayments`: records of repayments from one user to another.
        The function commits any changes and closes the connection before returning.

        Raises:
            sqlite3.Error: If connecting to the database or executing any DDL statements
                fails, the underlying sqlite3 exception is propagated.

        Example:
            >>> db = DurstDB("/path/to/app.db")
            # After initialization, the specified SQLite file will exist and contain the required tables.
        """

        con = self._get_connection()
        con.execute("PRAGMA journal_mode = WAL")
        if not con.execute("PRAGMA user_version").fetchone()[0]:
            # random id telling databases apart in the sheet sync
            con.execute(f"PRAGMA user_version = {secrets.randbelow(2**31 - 1) + 1}")
        cur = con.cursor()
        # 1. users: Stores user information and their credit balance.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                balance REAL NOT NULL DEFAULT 0.00,
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin', 'pot')),
                -- self-registered users wait for an admin
                approved INTEGER NOT NULL DEFAULT 1,
                -- deposits seen in the sheet so far (sheet sync)
                sheet_deposits REAL NOT NULL DEFAULT 0
            );
        """)
        # 2. drink_types: A catalog of all available drink types.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS drink_types (
                drink_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                brand TEXT
            );
        """)
        # 3. orders: A log of bulk drink orders placed by users.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                orderer_id INTEGER NOT NULL,
                order_date TIMESTAMP NOT NULL DEFAULT {NOW},
                total_cost REAL NOT NULL,
                -- Links this order to the user who placed it
                FOREIGN KEY (orderer_id) REFERENCES users(user_id)
            );
        """)
        # 4. stock_batches: The main inventory table, tracking each batch.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS stock_batches (
                batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
                drink_type_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                orderer_id INTEGER NOT NULL,
                cost_per_item REAL NOT NULL,
                initial_qty INTEGER NOT NULL,
                remaining_qty INTEGER NOT NULL,
                sheet_key TEXT, -- set when imported from the sheet
                date_added TIMESTAMP NOT NULL DEFAULT {NOW},
                -- Links to the specific drink type
                FOREIGN KEY (drink_type_id) REFERENCES drink_types(drink_type_id),
                -- Links to the bulk order this batch came from
                FOREIGN KEY (order_id) REFERENCES orders(order_id),
                -- Links to the user who ordered this batch
                FOREIGN KEY (orderer_id) REFERENCES users(user_id)
            );
        """)
        # 5. drink_purchases: A log of every single drink taken by a user.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS drink_purchases (
                purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                batch_id INTEGER NOT NULL,
                -- 'cost' is copied from the batch for historical accuracy
                cost REAL NOT NULL,
                charged_to_orderer_id INTEGER NOT NULL,
                sheet_key TEXT, -- set when imported from the sheet
                purchase_date TIMESTAMP NOT NULL DEFAULT {NOW},
                -- Links to the user who took the drink
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                -- Links to the specific batch the drink came from
                FOREIGN KEY (batch_id) REFERENCES stock_batches(batch_id),
                -- Links to the user who is owed money for this drink
                FOREIGN KEY (charged_to_orderer_id) REFERENCES users(user_id)
            );
        """)
        # 6. repayments: A log of users paying back other users directly.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS repayments (
                repayment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payer_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                payment_date TIMESTAMP NOT NULL DEFAULT {NOW},
                -- Links to the user who is paying
                FOREIGN KEY (payer_id) REFERENCES users(user_id),
                -- Links to the user who is receiving money
                FOREIGN KEY (receiver_id) REFERENCES users(user_id)
            );
        """)
        # 7. ssh_keys: public keys that let a user log in over SSH.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ssh_keys (
                key TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                approved INTEGER NOT NULL DEFAULT 1,
                label TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        # 8. deposit_requests: money a user says they handed in, until an admin confirms it.
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS deposit_requests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL CHECK (amount > 0),
                created TIMESTAMP NOT NULL DEFAULT {NOW},
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        # 9. login_tokens: one-time web login links
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS login_tokens (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created TIMESTAMP NOT NULL DEFAULT {NOW},
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
        if "received_by" not in {c[1] for c in cur.execute("PRAGMA table_info(repayments)")}:
            # the admin who took the cash for the Kasse
            cur.execute("ALTER TABLE repayments ADD COLUMN received_by INTEGER REFERENCES users(user_id)")
        if "entered" not in {c[1] for c in cur.execute("PRAGMA table_info(drink_purchases)")}:
            # when it was typed in; purchase_date can be earlier for drinks booked late
            cur.execute("ALTER TABLE drink_purchases ADD COLUMN entered TIMESTAMP")
        if "label" not in {c[1] for c in cur.execute("PRAGMA table_info(ssh_keys)")}:
            cur.execute("ALTER TABLE ssh_keys ADD COLUMN label TEXT NOT NULL DEFAULT ''")
        cur.execute("INSERT OR IGNORE INTO users (name, role) VALUES (?, 'pot')", (POT,))
        con.commit()
        con.close()

    ##########################################
    #          User Operations               #
    ##########################################
    def get_user_by_id(self, user_id: int) -> User | None:
        """Retrieve a User object by user_id.

        Args:
            user_id (int): The ID of the user to retrieve.

        Returns:
            User|None: The User object if found, otherwise None.

        Raises:
            sqlite3.Error: If an error occurs while querying the database.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            f"SELECT {USER_COLS} FROM users WHERE user_id = ?",
            (user_id,),
        )
        res = cur.fetchone()
        con.close()
        if res:
            return User.from_db_row(res)
        return None

    def get_user_by_name(self, name: str) -> User | None:
        """Retrieve a User object by name.

        Args:
            name (str): The exact name of the user to look up. Case-sensitive.

        Returns:
            User|None: The User object if found, otherwise None.

        Raises:
            sqlite3.Error: If an error occurs while querying the database.

        Example:
            >>> db = DurstDB()
            >>> user = db.get_user_by_name("alice")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            f"SELECT {USER_COLS} FROM users WHERE name = ?", (name,)
        )
        res = cur.fetchone()
        con.close()
        if res:
            return User.from_db_row(res)
        return None

    def get_user_by_email(self, email: str) -> User | None:
        """Retrieve a User object by email address.

        Args:
            email (str): The email address of the user to look up.

        Returns:
            User|None: The User object if found, otherwise None.

        Raises:
            sqlite3.Error: If an error occurs while querying the database.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            f"SELECT {USER_COLS} FROM users WHERE email = ?", (email,)
        )
        res = cur.fetchone()
        con.close()
        if res:
            return User.from_db_row(res)
        return None

    def get_user_id_by_name(self, name: str) -> int | None:
        """Retrieve the user_id for a user with the given name.

        Args:
            name (str): The exact name of the user to look up. Case-sensitive.

        Returns:
            int|None: The user_id if found, otherwise None.

        Example:
            >>> db = DurstDB()
            >>> user_id = db.get_user_id_by_name("alice")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id FROM users WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        return res[0] if res else None

    def get_all_users(self) -> list[User]:
        """Retrieve all users from the database.

        Returns:
            list[User]: A list of all User objects.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            f"SELECT {USER_COLS} FROM users WHERE role != 'pot' AND approved = 1 ORDER BY name"
        )
        rows = cur.fetchall()
        con.close()
        return [User.from_db_row(row) for row in rows]

    def add_user(
        self,
        name: str,
        email: str | None = None,
        verbose: bool = True,
        approved: bool = True,
        role: str = "user",
    ) -> int | None:
        """Add a new user to the database.

        Args:
            name (str): The user's name.
            email (str): The user's email address (must be unique).
            verbose (bool): If True, prints a confirmation message. Defaults to True.

        Returns:
            int|None: The new user_id if created, or the existing user_id if the
            name or email is already taken.

        Raises:
            sqlite3.Error: If a database error occurs.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            "SELECT user_id FROM users WHERE email = ? OR name = ?", (email, name)
        )
        existing = cur.fetchone()
        if existing:
            if verbose:
                print(f"Database: User {name} <{email}> already exists (id={existing[0]})")
            con.close()
            return existing[0]

        cur.execute(
            "INSERT INTO users (name, email, approved, role) VALUES (?, ?, ?, ?)",
            (name, email or None, int(approved), role),
        )
        user_id = cur.lastrowid
        con.commit()
        con.close()
        if verbose:
            print(f"Database: Added user {name} with email {email}")
        return user_id

    def get_user_balance(self, user_id: int) -> float:
        """Retrieve the current balance for a user by user_id.

        Args:
            user_id (int): The ID of the user whose balance to retrieve.

        Returns:
            float: The user's current balance.

        Raises:
            ValueError: If the user_id does not exist in the database.
            sqlite3.Error: If a database error occurs.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        res = cur.fetchone()
        con.close()
        if res is None:
            raise ValueError(f"User ID {user_id} not found.")
        return res[0]

    def add_ssh_key(self, user_id: int, key: str, approved: bool = True) -> None:
        """Register an OpenSSH public key (``type base64 [comment]``) for a user.

        Raises ValueError for a malformed key or one that belongs to someone else.
        """
        normalized = _normalize_key(key)
        with self._get_connection() as con:
            owner = con.execute(
                "SELECT user_id FROM ssh_keys WHERE key = ?", (normalized,)
            ).fetchone()
            if owner and owner[0] != user_id:
                raise ValueError("That key is already registered to another account.")
            con.execute(
                "INSERT OR REPLACE INTO ssh_keys (key, user_id, approved, label) VALUES (?, ?, ?, ?)",
                (normalized, user_id, int(approved), _key_label(key)),
            )

    def get_ssh_keys(self, user_id: int) -> list[dict]:
        """A user's keys (approved first), as ``{key, label, approved}``."""
        return self._rows(
            "SELECT key, label, approved FROM ssh_keys WHERE user_id = ? ORDER BY approved DESC, label",
            (user_id,),
        )

    def remove_ssh_key(self, user_id: int, key: str) -> None:
        """Remove one of a user's own keys."""
        with self._get_connection() as con:
            con.execute(
                "DELETE FROM ssh_keys WHERE user_id = ? AND key = ?", (user_id, _normalize_key(key))
            )

    def set_email(self, user_id: int, email: str | None) -> None:
        """Change a user's email (None clears it)."""
        if email and "@" not in email:
            raise ValueError("That doesn't look like an email.")
        if email and (other := self.get_user_by_email(email)) and other.user_id != user_id:
            raise ValueError(f"The email {email} is already taken.")
        with self._get_connection() as con:
            con.execute("UPDATE users SET email = ? WHERE user_id = ?", (email or None, user_id))

    def get_user_by_ssh_key(self, key: str) -> User | None:
        """Return the user owning an OpenSSH public key, or None."""
        con = self._get_connection()
        res = con.execute(
            "SELECT u.user_id, u.name, u.email, u.balance, u.role, u.approved"
            " FROM users u JOIN ssh_keys k ON k.user_id = u.user_id"
            " WHERE k.key = ? AND k.approved = 1",
            (_normalize_key(key),),
        ).fetchone()
        con.close()
        return User.from_db_row(res) if res else None

    def is_key_pending(self, key: str) -> bool:
        """Whether a key was registered but not yet approved by an admin."""
        con = self._get_connection()
        res = con.execute(
            "SELECT 1 FROM ssh_keys WHERE key = ? AND approved = 0", (_normalize_key(key),)
        ).fetchone()
        con.close()
        return res is not None

    def register(self, name: str, email: str | None, key: str) -> bool:
        """Self-registration on first SSH login; waits for admin approval.

        Claims the existing account called ``name`` (e.g. imported from the
        sheet) or creates a new, unapproved one. Returns True for a claim.
        """
        name = name.strip()
        if not name or name == POT:
            raise ValueError("Please pick another name.")
        existing = self.get_user_by_name(name)
        if existing and existing.role == "pot":
            raise ValueError("Please pick another name.")
        if existing is None and email and self.get_user_by_email(email):
            raise ValueError(f"The email {email} is already taken.")
        user_id = existing.user_id if existing else self.add_user(
            name, email, verbose=False, approved=False
        )
        assert user_id is not None
        self.add_ssh_key(user_id, key, approved=False)
        return existing is not None

    def get_pending_keys(self) -> list[dict]:
        """Keys waiting for approval, with the account they belong to."""
        con = self._get_connection()
        rows = con.execute(
            "SELECT k.key, u.name, u.email, u.approved FROM ssh_keys k"
            " JOIN users u ON u.user_id = k.user_id WHERE k.approved = 0 ORDER BY u.name"
        ).fetchall()
        con.close()
        return [
            {"key": k, "name": n, "email": e or "", "new_user": not a}
            for k, n, e, a in rows
        ]

    def approve_key(self, key: str) -> None:
        """Approve a pending key (and its user, if they are new)."""
        with self._get_connection() as con:
            con.execute("UPDATE ssh_keys SET approved = 1 WHERE key = ?", (key,))
            con.execute(
                "UPDATE users SET approved = 1"
                " WHERE user_id = (SELECT user_id FROM ssh_keys WHERE key = ?)",
                (key,),
            )

    def reject_key(self, key: str) -> None:
        """Drop a pending key, and its user if they were never approved."""
        with self._get_connection() as con:
            row = con.execute("SELECT user_id FROM ssh_keys WHERE key = ?", (key,)).fetchone()
            con.execute("DELETE FROM ssh_keys WHERE key = ?", (key,))
            if row:
                con.execute(
                    "DELETE FROM users WHERE user_id = ? AND approved = 0", (row[0],)
                )

    def set_role(self, name: str, role: str) -> None:
        """Make a user an ``admin`` or a plain ``user``."""
        if role not in ("user", "admin"):
            raise ValueError(f"Unknown role: {role}")
        with self._get_connection() as con:
            cur = con.execute(
                "UPDATE users SET role = ? WHERE name = ? AND role != 'pot'", (role, name)
            )
            if cur.rowcount == 0:
                raise ValueError(f"User not found: {name}")

    def pot_id(self) -> int:
        """The pot user (Kasse), created on first use."""
        with self._get_connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO users (name, role) VALUES (?, 'pot')", (POT,)
            )
            return con.execute(
                "SELECT user_id FROM users WHERE name = ?", (POT,)
            ).fetchone()[0]

    ##########################################
    #        Drink Type Operations           #
    ##########################################
    def get_drink_type_by_id(self, drink_type_id: int) -> DrinkType | None:
        """Retrieve a DrinkType object by drink_type_id.

        Args:
            drink_type_id (int): The ID of the drink type to retrieve.

        Returns:
            DrinkType|None: The DrinkType object if found, otherwise None.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            "SELECT drink_type_id, name, brand FROM drink_types WHERE drink_type_id = ?",
            (drink_type_id,),
        )
        res = cur.fetchone()
        con.close()
        if res:
            return DrinkType.from_db_row(res)
        return None

    def get_drink_type_by_name(self, name: str) -> DrinkType | None:
        """Retrieve a DrinkType object by name.

        Args:
            name (str): The exact name of the drink type. Case-sensitive.

        Returns:
            DrinkType|None: The DrinkType object if found, otherwise None.

        Example:
            >>> db = DurstDB()
            >>> drink = db.get_drink_type_by_name("Cola")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            "SELECT drink_type_id, name, brand FROM drink_types WHERE name = ?", (name,)
        )
        res = cur.fetchone()
        con.close()
        if res:
            return DrinkType.from_db_row(res)
        return None

    def get_drink_type_id_by_name(self, name: str) -> int | None:
        """Retrieve the drink_type_id for a drink type with the given name.

        Args:
            name (str): The exact name of the drink type. Case-sensitive.

        Returns:
            int|None: The drink_type_id if found, otherwise None.

        Example:
            >>> db = DurstDB()
            >>> drink_id = db.get_drink_type_id_by_name("Cola")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        return res[0] if res else None

    def get_all_drink_types(self) -> list[DrinkType]:
        """Retrieve all drink types from the database.

        Returns:
            list[DrinkType]: A list of all DrinkType objects.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id, name, brand FROM drink_types ORDER BY name")
        rows = cur.fetchall()
        con.close()
        return [DrinkType.from_db_row(row) for row in rows]

    def add_drink_type(
        self, name: str, brand: str = "", verbose: bool = True
    ) -> int | None:
        """Add a new drink type to the database.

        Args:
            name (str): The name of the drink type.
            brand (str): The brand of the drink. Defaults to an empty string.
            verbose (bool): If True, prints a confirmation message. Defaults to True.

        Returns:
            int|None: The new drink_type_id if created, or existing id if drink already exists.

        Raises:
            sqlite3.Error: If a database error occurs.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
        existing = cur.fetchone()
        if existing:
            if verbose:
                print(
                    f"Database: Drink type '{name}' already exists (id={existing[0]})"
                )
            con.close()
            return existing[0]

        cur.execute(
            "INSERT INTO drink_types (name, brand) VALUES (?, ?)",
            (name, brand),
        )
        drink_type_id = cur.lastrowid
        con.commit()
        con.close()
        if verbose:
            print(f"Database: Added drink type '{name}' with brand '{brand}'")
        return drink_type_id

    ##########################################
    #        Stock & Order Operations        #
    ##########################################
    def stock_new_drinks(
        self,
        orderer_id: int,
        total_cost: float,
        items_list: list,
        verbose: bool = True,
        date: str | None = None,
        sheet_key: str | None = None,
    ) -> int | None:
        """
        Add a new stock order to the database.

        This function executes a transaction to:
        1. Create a new record in the 'orders' table.
        2. Create one or more records in the 'stock_batches' table, one for
           each type of drink included in the order, linking them to the new order.

        Args:
            orderer_id (int): The user_id of the person who placed the order.
            total_cost (float): The total cost of the entire order.
            items_list (list): A list of dictionaries, where each dict contains:
                {
                    "drink_type_id": int,
                    "cost_per_item": float,
                    "quantity": int
                }
            verbose (bool): If True, prints a confirmation message. Defaults to True.
            date (str|None): Order date (``YYYY-MM-DD HH:MM:SS``); defaults to now.
            sheet_key (str|None): Key of the sheet row this order came from.

        Returns:
            int|None: The new order_id if successful, None if an error occurred.
        """

        # Use 'with conn:' which automatically begins a transaction
        # and commits it. If an exception occurs, it rolls back.
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Step 1: Create the new record in the 'orders' table
                sql_order = f"INSERT INTO orders (orderer_id, total_cost, order_date) VALUES (?, ?, COALESCE(?, {NOW}))"
                cursor.execute(sql_order, (orderer_id, total_cost, date))

                # Get the 'order_id' of the order we just created
                new_order_id = cursor.lastrowid

                if not new_order_id:
                    raise Error("Failed to create order, lastrowid not found.")

                # Step 2: Prepare the data for the 'stock_batches' table
                batches_to_insert = []
                for item in items_list:
                    batch_data = (
                        item["drink_type_id"],
                        new_order_id,
                        orderer_id,
                        item["cost_per_item"],
                        item["quantity"],
                        item["quantity"],  # remaining_qty starts equal to initial_qty
                        date,
                        sheet_key,
                    )
                    batches_to_insert.append(batch_data)

                # Step 3: Insert all batches using executemany for efficiency
                sql_batch = f"""
                    INSERT INTO stock_batches
                        (drink_type_id, order_id, orderer_id, cost_per_item, initial_qty, remaining_qty, date_added, sheet_key)
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, {NOW}), ?)
                """
                cursor.executemany(sql_batch, batches_to_insert)

            if verbose:
                print(
                    f"Successfully stocked order ID: {new_order_id} with {len(batches_to_insert)} new batch(es)."
                )
            return new_order_id

        except Error as e:
            print(f"Error during stocking operation: {e}")
            # The 'with conn:' block handles the rollback automatically
            return None

    def restock(self, drink: str, qty: int, total: float, payer: str) -> str:
        """Stock ``qty`` bottles bought for ``total`` by ``payer`` (a name or the Kasse).

        A drink spelled like an existing one in another case is that one; any
        other new name adds a drink. Returns the drink's name as stored.
        """
        drink = drink.strip()
        if not drink:
            raise ValueError("Which drink?")
        if qty <= 0 or total < 0:
            raise ValueError("Bottles must be positive and the price can't be negative.")
        payer_id = self.get_user_id_by_name(payer)
        if payer_id is None:
            raise ValueError(f"Nobody called {payer!r}.")
        names = {d.name.lower(): d.name for d in self.get_all_drink_types()}
        drink = names.get(drink.lower(), drink)
        drink_id = self.add_drink_type(drink, verbose=False)
        assert drink_id is not None
        item = {"drink_type_id": drink_id, "cost_per_item": total / qty, "quantity": qty}
        if self.stock_new_drinks(payer_id, total, [item], verbose=False) is None:
            raise ValueError("Could not save the order.")
        return drink

    ##########################################
    #        Purchase Operations             #
    ##########################################
    def add_purchase(self, user: str, drink: str) -> int:
        """Book one drink for ``user`` from the oldest batch with stock; returns its purchase_id."""
        return self.add_purchases(user, [drink])[0]

    def add_purchases(self, user: str, drinks: list[str], day: dt.date | None = None) -> list[int]:
        """Book several drinks at once, all or nothing.

        ``day`` books them for an earlier day (someone forgot to); they land at
        noon of that day, since nobody remembers the hour.

        Raises:
            ValueError: unknown user or drink, nothing to book, a future day,
                or not enough stock.
        """
        purchaser_id = self.get_user_id_by_name(user)
        if purchaser_id is None:
            raise ValueError(f"User not found: {user}")
        if not drinks:
            raise ValueError("Nothing to book.")
        today = dt.date.today()
        if day and day > today:
            raise ValueError("That day hasn't happened yet.")
        date = f"{day} 12:00:00" if day and day != today else None
        ids = []
        for drink in drinks:
            drink_type_id = self.get_drink_type_id_by_name(drink)
            if drink_type_id is None:
                raise ValueError(f"Drink type not found: {drink}")
            ids.append(drink_type_id)
        with self._get_connection() as conn:
            cur = conn.cursor()
            return [self._take(cur, purchaser_id, d, date=date) for d in ids]

    def import_purchases(
        self,
        user_id: int,
        drink_type_id: int,
        count: int,
        cost: float | None,
        date: str,
        sheet_key: str,
    ) -> list[int]:
        """Record ``count`` drinks from a sheet row at the sheet's price, atomically."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            return [
                self._take(cur, user_id, drink_type_id, cost, date, sheet_key, strict=False)
                for _ in range(count)
            ]

    @staticmethod
    def _take(
        cur: sqlite3.Cursor,
        user_id: int,
        drink_type_id: int,
        cost: float | None = None,
        date: str | None = None,
        sheet_key: str | None = None,
        strict: bool = True,
    ) -> int:
        """Take one drink from the oldest batch with stock left and settle balances.

        ``cost`` overrides the batch price. With ``strict=False`` (sheet imports,
        where the sheet is the truth) an empty stock is drawn from the newest batch.
        """
        cur.execute(
            """
            SELECT batch_id, cost_per_item, orderer_id FROM stock_batches
            WHERE drink_type_id = ? AND remaining_qty > 0
            ORDER BY date_added ASC, batch_id ASC LIMIT 1
            """,
            (drink_type_id,),
        )
        batch = cur.fetchone()
        if not batch and not strict:
            cur.execute(
                "SELECT batch_id, cost_per_item, orderer_id FROM stock_batches"
                " WHERE drink_type_id = ? ORDER BY date_added DESC, batch_id DESC LIMIT 1",
                (drink_type_id,),
            )
            batch = cur.fetchone()
        if not batch:
            name = cur.execute(
                "SELECT name FROM drink_types WHERE drink_type_id = ?", (drink_type_id,)
            ).fetchone()
            raise ValueError(f"No stock available for drink: {name[0] if name else drink_type_id}")

        batch_id, batch_cost, orderer_id = batch
        cost = batch_cost if cost is None else cost
        cur.execute(
            f"""
            INSERT INTO drink_purchases
                (user_id, batch_id, cost, charged_to_orderer_id, purchase_date, sheet_key, entered)
            VALUES (?, ?, ?, ?, COALESCE(?, {NOW}), ?, {NOW})
            """,
            (user_id, batch_id, cost, orderer_id, date, sheet_key),
        )
        purchase_id = cur.lastrowid
        if purchase_id is None:
            raise sqlite3.Error("Failed to record purchase.")
        cur.execute(
            "UPDATE stock_batches SET remaining_qty = remaining_qty - 1 WHERE batch_id = ?",
            (batch_id,),
        )
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (cost, user_id))
        cur.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?", (cost, orderer_id)
        )
        return purchase_id

    ##########################################
    #        Repayment Operations            #
    ##########################################
    def add_repayment(
        self,
        payer_id: int,
        receiver_id: int,
        amount: float,
        date: str | None = None,
        received_by: int | None = None,
    ) -> int:
        """Record a repayment and update both balances; returns the repayment_id.

        The payer hands cash to the receiver, settling debt: the payer's balance
        increases (toward zero) and the receiver's balance decreases, since they
        are owed that much less. ``received_by`` is the admin who took the cash
        when the receiver is the Kasse.

        Raises:
            ValueError: if payer/receiver not found or amount is non-positive.
        """
        with self._get_connection() as conn:
            return self._repay(conn.cursor(), payer_id, receiver_id, amount, date, received_by)

    @staticmethod
    def _repay(
        cur: sqlite3.Cursor,
        payer_id: int,
        receiver_id: int,
        amount: float,
        date: str | None = None,
        received_by: int | None = None,
    ) -> int:
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if payer_id == receiver_id:
            raise ValueError("Payer and receiver must be different users")
        for who, uid in (("Payer", payer_id), ("Receiver", receiver_id)):
            if not cur.execute("SELECT 1 FROM users WHERE user_id = ?", (uid,)).fetchone():
                raise ValueError(f"{who} not found: {uid}")
        cur.execute(
            "INSERT INTO repayments (payer_id, receiver_id, amount, payment_date, received_by)"
            f" VALUES (?, ?, ?, COALESCE(?, {NOW}), ?)",
            (payer_id, receiver_id, amount, date, received_by),
        )
        repayment_id = cur.lastrowid
        if repayment_id is None:
            raise sqlite3.Error("Failed to record repayment")
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, payer_id))
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, receiver_id))
        return repayment_id

    def request_deposit(self, user_id: int, amount: float) -> None:
        """A user says they handed in cash; it counts once an admin approves it."""
        if not 0 < amount <= 1000:
            raise ValueError("Enter an amount between 0 and 1000 €.")
        with self._get_connection() as con:
            con.execute(
                "INSERT INTO deposit_requests (user_id, amount) VALUES (?, ?)",
                (user_id, round(amount, 2)),
            )

    def get_deposit_requests(self, user_id: int | None = None) -> list[dict]:
        """Deposits waiting for an admin (only ``user_id``'s, if given), oldest first."""
        return self._rows(
            "SELECT r.request_id, r.amount, r.created, u.name, u.email FROM deposit_requests r"
            " JOIN users u ON u.user_id = r.user_id"
            " WHERE ? IS NULL OR r.user_id = ? ORDER BY r.request_id",
            (user_id, user_id),
        )

    def approve_deposit(self, request_id: int, admin_id: int | None) -> None:
        """Book a requested deposit into the Kasse, received by ``admin_id``."""
        pot = self.pot_id()
        with self._get_connection() as con:
            cur = con.cursor()
            row = cur.execute(
                "SELECT user_id, amount FROM deposit_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise ValueError("That request is gone already.")
            cur.execute("DELETE FROM deposit_requests WHERE request_id = ?", (request_id,))
            self._repay(cur, row[0], pot, row[1], received_by=admin_id)

    def login_token(self, user_id: int) -> str:
        """A one-time token for a web login link."""
        token = secrets.token_urlsafe(24)
        with self._get_connection() as con:
            con.execute("INSERT INTO login_tokens (token, user_id) VALUES (?, ?)", (token, user_id))
        return token

    def use_login_token(self, token: str) -> int | None:
        """The user a fresh token belongs to; every token works once."""
        oldest = (dt.datetime.now() - LOGIN_TTL).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as con:
            row = con.execute(
                "SELECT user_id FROM login_tokens WHERE token = ? AND created >= ?", (token, oldest)
            ).fetchone()
            con.execute("DELETE FROM login_tokens WHERE token = ? OR created < ?", (token, oldest))
        return row[0] if row else None

    def reject_deposit(self, request_id: int) -> None:
        """Drop a deposit request (also how a user withdraws their own)."""
        with self._get_connection() as con:
            con.execute("DELETE FROM deposit_requests WHERE request_id = ?", (request_id,))

    ##########################################
    #        Query & Reporting Methods       #
    ##########################################
    def get_recent_purchases(self, limit: int = 50) -> list[dict]:
        """Get recent purchase records with user and drink details.

        Args:
            limit (int): Maximum number of records to return. Defaults to 50.

        Returns:
            list[dict]: A list of dictionaries containing purchase details.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute(
            """
            SELECT
                dp.purchase_id,
                dp.sheet_key,
                u.name as user_name,
                dt.name as drink_name,
                dp.cost,
                dp.purchase_date,
                dp.entered,
                orderer.name as orderer_name
            FROM drink_purchases dp
            JOIN users u ON dp.user_id = u.user_id
            JOIN stock_batches sb ON dp.batch_id = sb.batch_id
            JOIN drink_types dt ON sb.drink_type_id = dt.drink_type_id
            JOIN users orderer ON dp.charged_to_orderer_id = orderer.user_id
            ORDER BY dp.purchase_date DESC, dp.purchase_id DESC
            LIMIT ?
        """,
            (limit,),
        )

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        con.close()

        return [dict(zip(columns, row)) for row in rows]

    def last_taken(self, user_id: int) -> list[str]:
        """The drinks a user has taken, most recent first."""
        rows = self._rows(
            "SELECT d.name AS drink FROM drink_purchases p"
            " JOIN stock_batches b ON b.batch_id = p.batch_id"
            " JOIN drink_types d ON d.drink_type_id = b.drink_type_id"
            " WHERE p.user_id = ? GROUP BY d.name"
            " ORDER BY MAX(p.purchase_date) DESC, MAX(p.purchase_id) DESC",
            (user_id,),
        )
        return [r["drink"] for r in rows]

    def undo_purchase(self, purchase_id: int) -> None:
        """Reverse a purchase made in durst: the bottle goes back, balances too."""
        with self._get_connection() as con:
            row = con.execute(
                "SELECT user_id, batch_id, cost, charged_to_orderer_id, sheet_key"
                " FROM drink_purchases WHERE purchase_id = ?",
                (purchase_id,),
            ).fetchone()
            if row is None:
                raise ValueError("That purchase is gone already.")
            user_id, batch_id, cost, orderer_id, sheet_key = row
            if sheet_key:  # the sheet would just bring it back
                raise ValueError("That one came from the sheet; it can't be undone here.")
            con.execute("DELETE FROM drink_purchases WHERE purchase_id = ?", (purchase_id,))
            con.execute(
                "UPDATE stock_batches SET remaining_qty = remaining_qty + 1 WHERE batch_id = ?",
                (batch_id,),
            )
            con.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (cost, user_id))
            con.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (cost, orderer_id))

    def get_stock_status(self) -> list[dict]:
        """Get current stock status for all drink types.

        Returns:
            list[dict]: A list of dictionaries with drink name and remaining quantity.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("""
            SELECT
                dt.name as drink_name,
                dt.brand,
                COALESCE(SUM(MAX(sb.remaining_qty, 0)), 0) as total_remaining,
                (SELECT cost_per_item FROM stock_batches b
                 WHERE b.drink_type_id = dt.drink_type_id AND b.remaining_qty > 0
                 ORDER BY b.date_added, b.batch_id LIMIT 1) as price
            FROM drink_types dt
            LEFT JOIN stock_batches sb ON dt.drink_type_id = sb.drink_type_id
            GROUP BY dt.drink_type_id, dt.name, dt.brand
            ORDER BY dt.name
        """)

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        con.close()

        return [dict(zip(columns, row)) for row in rows]

    def get_user_debts(self) -> list[dict]:
        """Get a summary of who owes money to whom.

        Returns:
            list[dict]: A list of dictionaries with debtor, creditor, and amount owed.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("""
            SELECT
                debtor.name as debtor_name,
                creditor.name as creditor_name,
                SUM(dp.cost) as amount_owed
            FROM drink_purchases dp
            JOIN users debtor ON dp.user_id = debtor.user_id
            JOIN users creditor ON dp.charged_to_orderer_id = creditor.user_id
            WHERE debtor.user_id != creditor.user_id
            GROUP BY debtor.user_id, creditor.user_id
            HAVING amount_owed > 0
            ORDER BY amount_owed DESC
        """)

        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        con.close()

        return [dict(zip(columns, row)) for row in rows]

    ##########################################
    #        Sheet Sync Helpers              #
    ##########################################
    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        con = self._get_connection()
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        con.close()
        return rows

    def known_sheet_keys(self) -> set[str]:
        """Keys of all sheet rows already imported."""
        rows = self._rows(
            "SELECT sheet_key FROM drink_purchases WHERE sheet_key IS NOT NULL"
            " UNION SELECT sheet_key FROM stock_batches WHERE sheet_key IS NOT NULL"
        )
        return {r["sheet_key"] for r in rows}

    def all_batches(self) -> list[dict]:
        return self._rows(
            "SELECT b.batch_id, b.sheet_key, b.date_added, d.name AS drink,"
            " b.initial_qty, b.cost_per_item FROM stock_batches b"
            " JOIN drink_types d ON d.drink_type_id = b.drink_type_id ORDER BY b.batch_id"
        )

    def all_purchases(self) -> list[dict]:
        return self._rows(
            "SELECT p.purchase_id, p.sheet_key, p.purchase_date, u.name AS user,"
            " d.name AS drink, p.cost FROM drink_purchases p"
            " JOIN users u ON u.user_id = p.user_id"
            " JOIN stock_batches b ON b.batch_id = p.batch_id"
            " JOIN drink_types d ON d.drink_type_id = b.drink_type_id ORDER BY p.purchase_id"
        )

    def credits(self, user_id: int) -> float:
        """Everything paid in by a user (deposits, orders, repayments) = balance + drinks."""
        row = self._rows(
            "SELECT u.balance + COALESCE((SELECT SUM(cost) FROM drink_purchases"
            " WHERE user_id = u.user_id), 0) AS c FROM users u WHERE u.user_id = ?",
            (user_id,),
        )
        return row[0]["c"]

    def sheet_deposits(self, user_id: int) -> float:
        """Deposits of a user last seen in the sheet."""
        return self._rows("SELECT sheet_deposits AS d FROM users WHERE user_id = ?", (user_id,))[0]["d"]

    def sync_sheet_deposits(self, user_id: int, sheet_total: float) -> float:
        """Book the change in a user's sheet deposits as a repayment to/from the pot.

        Booking and remembering the new total happen in one transaction, so a
        crashed sync can never count a deposit twice. Returns the change.
        """
        pot = self.pot_id()
        with self._get_connection() as con:
            seen = con.execute(
                "SELECT sheet_deposits FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()[0]
            delta = round(sheet_total - seen, 2)
            if delta:
                payer, receiver = (user_id, pot) if delta > 0 else (pot, user_id)
                con.execute(
                    "INSERT INTO repayments (payer_id, receiver_id, amount) VALUES (?, ?, ?)",
                    (payer, receiver, abs(delta)),
                )
                con.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id)
                )
                con.execute(
                    "UPDATE users SET balance = balance - ? WHERE user_id = ?", (delta, pot)
                )
            con.execute(
                "UPDATE users SET sheet_deposits = ? WHERE user_id = ?", (sheet_total, user_id)
            )
        return delta
