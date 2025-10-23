# database_service.py
import sqlite3
from sqlite3 import Error
from datetime import datetime

from typing import Union

DB_FILE = "sqlite.db"

#################################
#   Initialization and Setup    #
#################################
def setup_database(db_file: str = DB_FILE):
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
    Args:
        db_file (str): Filesystem path to the SQLite database file. If the file does
            not exist, it will be created. Defaults to the module-level DB_FILE.
    Returns:
        None
    Raises:
        sqlite3.Error: If connecting to the database or executing any DDL statements
            fails, the underlying sqlite3 exception is propagated.
    Example:
        >>> setup_database("/path/to/app.db")
        # After calling, the specified SQLite file will exist and contain the required tables.
    """
    
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    # 1. users: Stores user information and their credit balance.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            balance REAL NOT NULL DEFAULT 0.00
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            orderer_id INTEGER NOT NULL,
            order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            total_cost REAL NOT NULL,
            -- Links this order to the user who placed it
            FOREIGN KEY (orderer_id) REFERENCES users(user_id)
        );
    """)
    # 4. stock_batches: The main inventory table, tracking each batch.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_batches (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            drink_type_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            orderer_id INTEGER NOT NULL,
            cost_per_item REAL NOT NULL,
            initial_qty INTEGER NOT NULL,
            remaining_qty INTEGER NOT NULL,
            date_added TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Links to the specific drink type
            FOREIGN KEY (drink_type_id) REFERENCES drink_types(drink_type_id),
            -- Links to the bulk order this batch came from
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            -- Links to the user who ordered this batch
            FOREIGN KEY (orderer_id) REFERENCES users(user_id)
        );
    """)
    # 5. drink_purchases: A log of every single drink taken by a user.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drink_purchases (
            purchase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            batch_id INTEGER NOT NULL,
            -- 'cost' is copied from the batch for historical accuracy
            cost REAL NOT NULL,
            charged_to_orderer_id INTEGER NOT NULL,
            purchase_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Links to the user who took the drink
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            -- Links to the specific batch the drink came from
            FOREIGN KEY (batch_id) REFERENCES stock_batches(batch_id),
            -- Links to the user who is owed money for this drink
            FOREIGN KEY (charged_to_orderer_id) REFERENCES users(user_id)
        );
    """)
    # 6. repayments: A log of users paying back other users directly.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS repayments (
            repayment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            payer_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Links to the user who is paying
            FOREIGN KEY (payer_id) REFERENCES users(user_id),
            -- Links to the user who is receiving money
            FOREIGN KEY (receiver_id) REFERENCES users(user_id)
        );
    """)
    con.commit()
    con.close()

##########################################
#   Helper Functions for DB Operations   #
##########################################
def get_id_by_name(name: str, db_file: str = DB_FILE) -> Union[int, None]:
    """ Retrieve the user_id for a user with the given name from the SQLite database.

    Args:
        name (str): The exact name of the user to look up. Matching is performed using SQL equality and is therefore case-sensitive.
        db_file (str): Path to the SQLite database file. Defaults to the module-level DB_FILE constant.

    Returns:
        int or None: The user_id of the first matching user if found; otherwise None.

    Raises:
        sqlite3.Error: If an error occurs while connecting to or querying the database.
    
    Example:
        >>> get_orderer_id_by_name("alice", "/path/to/db.sqlite")
        42
    """
    
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT user_id FROM users WHERE name = ?", (name,))
    res = cur.fetchone()
    con.close()
    if res:
        return res[0]
    else:
        return None

def get_drink_type_id_by_name(name: str, db_file: str = DB_FILE) -> Union[int, None]:
    """ Retrieve the drink_type_id for a drink type with the given name from the SQLite database.

    Args:
        name (str): The exact name of the drink type to look up. Matching is performed using SQL equality and is therefore case-sensitive.
        db_file (str): Path to the SQLite database file. Defaults to the module-level DB_FILE constant.

    Returns:
        int or None: The drink_type_id of the first matching drink type if found; otherwise None.

    Raises:
        sqlite3.Error: If an error occurs while connecting to or querying the database.
    
    Example:
        >>> get_drink_type_id_by_name("Cola", "/path/to/db.sqlite")
        7
    """
    
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
    res = cur.fetchone()
    con.close()
    if res:
        return res[0]
    else:
        return None

def add_user(name: str, email: str, db_file: str = DB_FILE, verbose: bool = True):
    """Adds a new user record to the SQLite database.

    Args:
        name (str): The user's name.
        email (str): The user's email address.
        db_file (str, optional): Path to the SQLite database file. Defaults to DB_FILE.
        verbose (bool, optional): If True, prints a confirmation message. Defaults to True.

    Raises:
        sqlite3.Error: If a database connection, insertion, or commit fails.
        TypeError: If the provided arguments are not of the expected types.

    Notes:
        - This function assumes a "users" table exists with columns "name" and "email".
        - Caller should validate or enforce uniqueness of email as required by the application.
    """
    
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT user_id FROM users WHERE email = ?", (email,))
    existing = cur.fetchone()
    if existing:
        if verbose:
            print(f"Database: User with email {email} already exists (id={existing[0]})")
        con.close()
        return

    cur.execute(
        "INSERT INTO users (name, email) VALUES (?, ?)",
        (name, email),
    )
    con.commit()
    con.close()
    if verbose:
        print(f"Database: Added user {name} with email {email}")

def add_drink_type(name: str, brand: str = "", db_file: str = DB_FILE, verbose: bool = True):
    """Adds a new drink type to the SQLite database.

    Args:
        name (str): The name of the drink type.
        brand (str, optional): The brand of the drink. Defaults to an empty string.
        db_file (str, optional): Path to the SQLite database file. Defaults to DB_FILE.
        verbose (bool, optional): If True, prints a confirmation message. Defaults to True.

    Raises:
        sqlite3.Error: If a database connection, insertion, or commit fails.
        TypeError: If the provided arguments are not of the expected types.

    Notes:
        - This function assumes a "drink_types" table exists with columns "name" and "brand".
        - Caller should validate or enforce uniqueness of drink names as required by the application.
    """
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
    existing = cur.fetchone()
    if existing:
        if verbose:
            print(f"Database: Drink type '{name}' already exists (id={existing[0]})")
        con.close()
        return

    cur.execute(
        "INSERT INTO drink_types (name, brand) VALUES (?, ?)",
        (name, brand),
    )
    con.commit()
    con.close()
    if verbose:
        print(f"Database: Added drink type '{name}' with brand '{brand}'")

#################
#    Actions    #
#################
def stock_new_drinks(orderer_id: int, total_cost: float, items_list: list, db_file: str = DB_FILE, verbose: bool = True):
    """
    Adds a new stock order to the SQLite database.

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
        db_file (str): Path to the SQLite database file. Defaults to DB_FILE.
        verbose (bool): If True, prints a confirmation message. Defaults to True.
            
    Returns:
        int: The new order_id if successful, None if an error occurred.
    """
    
    # Use 'with conn:' which automatically begins a transaction
    # and commits it. If an exception occurs, it rolls back.
    try:
        with sqlite3.connect(db_file) as conn:
            cursor = conn.cursor()

            # Step 1: Create the new record in the 'orders' table
            sql_order = "INSERT INTO orders (orderer_id, total_cost) VALUES (?, ?)"
            cursor.execute(sql_order, (orderer_id, total_cost))
            
            # Get the 'order_id' of the order we just created
            new_order_id = cursor.lastrowid
            
            if not new_order_id:
                raise Error("Failed to create order, lastrowid not found.")

            # Step 2: Prepare the data for the 'stock_batches' table
            batches_to_insert = []
            for item in items_list:
                batch_data = (
                    item['drink_type_id'],
                    new_order_id,
                    orderer_id,
                    item['cost_per_item'],
                    item['quantity'],
                    item['quantity']  # remaining_qty starts equal to initial_qty
                )
                batches_to_insert.append(batch_data)

            # Step 3: Insert all batches using executemany for efficiency
            sql_batch = """
                INSERT INTO stock_batches 
                    (drink_type_id, order_id, orderer_id, cost_per_item, initial_qty, remaining_qty)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            cursor.executemany(sql_batch, batches_to_insert)

        print(f"Successfully stocked order ID: {new_order_id} with {len(batches_to_insert)} new batch(es).")
        return new_order_id

    except Error as e:
        print(f"Error during stocking operation: {e}")
        # The 'with conn:' block handles the rollback automatically
        return None
    
def add_purchase(user: str, drink: str, db_file: str = DB_FILE):
    """Add a purchase record for a user buying a drink from the oldest available stock batch.

    This function:
    - Looks up the purchaser and drink type by name.
    - Selects the oldest stock batch for the requested drink type that has remaining stock.
    - Inserts a row into drink_purchases linking the purchaser to the batch and recording the cost.
    - Decrements the remaining quantity on the selected stock batch.
    - Updates balances: subtracts the cost from the purchaser and credits the orderer who paid for the batch.
    - Uses a single SQLite transaction (context manager) so all changes commit together or roll back on error.

    Args:
        user (str): Purchaser's name (used to resolve purchaser_id via get_orderer_id_by_name).
        drink (str): Drink type name (used to resolve drink_type_id via get_drink_type_id_by_name).
        db_file (str): Path to the SQLite database file. Defaults to DB_FILE.

    Returns:
        int: The newly inserted purchase_id from the drink_purchases table.

    Raises:
        ValueError: If the purchaser name or drink type name cannot be resolved to an ID, or if no stock is available for the requested drink.
        sqlite3.Error: If inserting the purchase or updating the database fails.

    Notes:
        - The function expects helper functions get_orderer_id_by_name and get_drink_type_id_by_name to be available and return integer IDs or None.
        - The batch selection uses ORDER BY date_added ASC and LIMIT 1 to pick the oldest available batch with remaining_qty > 0.
        - Concurrency: SQLite uses coarse-grained locking; concurrent calls may need retry logic or a different DB for high concurrency scenarios.
    """
    purchaser_id = get_id_by_name(user, db_file)
    if purchaser_id is None:
        raise ValueError(f"User not found: {user}")

    drink_type_id = get_drink_type_id_by_name(drink, db_file)
    if drink_type_id is None:
        raise ValueError(f"Drink type not found: {drink}")

    try:
        with sqlite3.connect(db_file) as conn:
            cur = conn.cursor()

            # Find oldest batch with remaining stock for this drink
            cur.execute(
                """
                SELECT batch_id, cost_per_item, orderer_id, remaining_qty
                FROM stock_batches
                WHERE drink_type_id = ? AND remaining_qty > 0
                ORDER BY date_added ASC
                LIMIT 1
                """,
                (drink_type_id,),
            )
            batch = cur.fetchone()
            if not batch:
                raise ValueError(f"No stock available for drink: {drink}")

            batch_id, cost_per_item, charged_to_orderer_id, remaining_qty = batch

            # Insert purchase record (purchase_date defaults in DB)
            cur.execute(
                """
                INSERT INTO drink_purchases
                    (user_id, batch_id, cost, charged_to_orderer_id)
                VALUES (?, ?, ?, ?)
                """,
                (purchaser_id, batch_id, cost_per_item, charged_to_orderer_id),
            )
            purchase_id = cur.lastrowid

            if purchase_id is None:
                raise sqlite3.Error("Failed to record purchase.")

            # Decrement remaining quantity on the batch
            cur.execute(
                "UPDATE stock_batches SET remaining_qty = remaining_qty - 1 WHERE batch_id = ?",
                (batch_id,),
            )

            # Decrease purchaser's balance by the cost
            cur.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (cost_per_item, purchaser_id),
            )

            # Credit the orderer who paid for the batch (so their balance reflects being owed)
            cur.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (cost_per_item, charged_to_orderer_id),
            )

        return purchase_id

    except sqlite3.Error as e:
        raise e

def add_repayment(payer_id: int, receiver_id: int, amount: float, db_file: str = DB_FILE) -> int:
    """Record a repayment and update user balances.

    Inserts a row into repayments and adjusts the payer's and receiver's balances within a single transaction. Returns the new repayment_id.

    Raises:
        ValueError: if payer/receiver not found or amount is non-positive.
        sqlite3.Error: on DB errors.
    """
    if amount <= 0:
        raise ValueError("Amount must be positive")

    if payer_id == receiver_id:
        raise ValueError("Payer and receiver must be different users")

    with sqlite3.connect(db_file) as conn:
        cur = conn.cursor()

        # Verify payer exists
        cur.execute("SELECT 1 FROM users WHERE user_id = ?", (payer_id,))
        if not cur.fetchone():
            raise ValueError(f"Payer not found: {payer_id}")

        # Verify receiver exists
        cur.execute("SELECT 1 FROM users WHERE user_id = ?", (receiver_id,))
        if not cur.fetchone():
            raise ValueError(f"Receiver not found: {receiver_id}")

        # Insert repayment record
        cur.execute(
            "INSERT INTO repayments (payer_id, receiver_id, amount) VALUES (?, ?, ?)",
            (payer_id, receiver_id, amount),
        )
        repayment_id = cur.lastrowid
        if repayment_id is None:
            raise sqlite3.Error("Failed to record repayment")

        # Update balances
        cur.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ?",
            (amount, payer_id),
        )
        cur.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, receiver_id),
        )

    return repayment_id

def get_user_balance(user_id: int, db_file: str = DB_FILE) -> float:
    """Retrieve the current balance for a user by user_id.

    Args:
        user_id (int): The ID of the user whose balance to retrieve.
        db_file (str): Path to the SQLite database file. Defaults to DB_FILE.

    Returns:
        float: The user's current balance.

    Raises:
        ValueError: If the user_id does not exist in the database.
        sqlite3.Error: If a database error occurs.
    """
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = cur.fetchone()
    con.close()
    if res is None:
        raise ValueError(f"User ID {user_id} not found.")
    return res[0]

