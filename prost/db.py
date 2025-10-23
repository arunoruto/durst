import sqlite3
from sqlite3 import Error
from dataclasses import dataclass
from typing import Optional, List


DB_FILE = "sqlite.db"


#################################
#       Domain Classes          #
#################################
@dataclass
class User:
    """Represents a user in the system."""
    user_id: Optional[int] = None
    name: str = ""
    email: str = ""
    balance: float = 0.0
    
    def is_in_debt(self) -> bool:
        """Check if user owes money."""
        return self.balance < 0
    
    def is_owed(self) -> bool:
        """Check if user is owed money."""
        return self.balance > 0
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'User':
        """Create a User instance from a database row."""
        return cls(
            user_id=row[0],
            name=row[1],
            email=row[2],
            balance=row[3]
        )

@dataclass
class DrinkType:
    """Represents a drink type."""
    drink_type_id: Optional[int] = None
    name: str = ""
    brand: str = ""
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'DrinkType':
        """Create a DrinkType instance from a database row."""
        return cls(
            drink_type_id=row[0],
            name=row[1],
            brand=row[2] if len(row) > 2 else ""
        )

@dataclass
class Order:
    """Represents a bulk order."""
    order_id: Optional[int] = None
    orderer_id: int = 0
    order_date: Optional[str] = None
    total_cost: float = 0.0
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'Order':
        """Create an Order instance from a database row."""
        return cls(
            order_id=row[0],
            orderer_id=row[1],
            order_date=row[2],
            total_cost=row[3]
        )

@dataclass
class StockBatch:
    """Represents a batch of stock."""
    batch_id: Optional[int] = None
    drink_type_id: int = 0
    order_id: int = 0
    orderer_id: int = 0
    cost_per_item: float = 0.0
    initial_qty: int = 0
    remaining_qty: int = 0
    date_added: Optional[str] = None
    
    def is_depleted(self) -> bool:
        """Check if the batch has no remaining stock."""
        return self.remaining_qty <= 0
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'StockBatch':
        """Create a StockBatch instance from a database row."""
        return cls(
            batch_id=row[0],
            drink_type_id=row[1],
            order_id=row[2],
            orderer_id=row[3],
            cost_per_item=row[4],
            initial_qty=row[5],
            remaining_qty=row[6],
            date_added=row[7] if len(row) > 7 else None
        )

@dataclass
class Purchase:
    """Represents a drink purchase."""
    purchase_id: Optional[int] = None
    user_id: int = 0
    batch_id: int = 0
    cost: float = 0.0
    charged_to_orderer_id: int = 0
    purchase_date: Optional[str] = None
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'Purchase':
        """Create a Purchase instance from a database row."""
        return cls(
            purchase_id=row[0],
            user_id=row[1],
            batch_id=row[2],
            cost=row[3],
            charged_to_orderer_id=row[4],
            purchase_date=row[5] if len(row) > 5 else None
        )

@dataclass
class Repayment:
    """Represents a repayment between users."""
    repayment_id: Optional[int] = None
    payer_id: int = 0
    receiver_id: int = 0
    amount: float = 0.0
    payment_date: Optional[str] = None
    
    @classmethod
    def from_db_row(cls, row: tuple) -> 'Repayment':
        """Create a Repayment instance from a database row."""
        return cls(
            repayment_id=row[0],
            payer_id=row[1],
            receiver_id=row[2],
            amount=row[3],
            payment_date=row[4] if len(row) > 4 else None
        )


#################################
#     Database Manager Class    #
#################################
class ProstDB:
    """
    Main database manager class for the Prost application.
    
    Handles all database operations including user management, drink inventory,orders, purchases, and repayments.
    """
    def __init__(self, db_file: str = DB_FILE):
        """
        Initialize the database manager.
        
        Args:
            db_file (str): Path to the SQLite database file.
        """
        self.db_file = db_file
        self.setup_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        return sqlite3.connect(self.db_file)
    
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
            >>> db = ProstDB("/path/to/app.db")
            # After initialization, the specified SQLite file will exist and contain the required tables.
        """
        
        con = self._get_connection()
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
    #          User Operations               #
    ##########################################
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Retrieve a User object by user_id.
        
        Args:
            user_id (int): The ID of the user to retrieve.
        
        Returns:
            Optional[User]: The User object if found, otherwise None.
        
        Raises:
            sqlite3.Error: If an error occurs while querying the database.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id, name, email, balance FROM users WHERE user_id = ?", (user_id,))
        res = cur.fetchone()
        con.close()
        if res:
            return User.from_db_row(res)
        return None
    
    def get_user_by_name(self, name: str) -> Optional[User]:
        """Retrieve a User object by name.
        
        Args:
            name (str): The exact name of the user to look up. Case-sensitive.
        
        Returns:
            Optional[User]: The User object if found, otherwise None.
        
        Raises:
            sqlite3.Error: If an error occurs while querying the database.
        
        Example:
            >>> db = ProstDB()
            >>> user = db.get_user_by_name("alice")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id, name, email, balance FROM users WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        if res:
            return User.from_db_row(res)
        return None
    
    def get_user_id_by_name(self, name: str) -> Optional[int]:
        """Retrieve the user_id for a user with the given name.
        
        Args:
            name (str): The exact name of the user to look up. Case-sensitive.
        
        Returns:
            Optional[int]: The user_id if found, otherwise None.
        
        Example:
            >>> db = ProstDB()
            >>> user_id = db.get_user_id_by_name("alice")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id FROM users WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        return res[0] if res else None
    
    def get_all_users(self) -> List[User]:
        """Retrieve all users from the database.
        
        Returns:
            List[User]: A list of all User objects.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id, name, email, balance FROM users ORDER BY name")
        rows = cur.fetchall()
        con.close()
        return [User.from_db_row(row) for row in rows]
    
    def add_user(self, name: str, email: str, verbose: bool = True) -> Optional[int]:
        """Add a new user to the database.
        
        Args:
            name (str): The user's name.
            email (str): The user's email address (must be unique).
            verbose (bool): If True, prints a confirmation message. Defaults to True.
        
        Returns:
            Optional[int]: The new user_id if created, or existing user_id if email already exists.
        
        Raises:
            sqlite3.Error: If a database error occurs.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT user_id FROM users WHERE email = ?", (email,))
        existing = cur.fetchone()
        if existing:
            if verbose:
                print(f"Database: User with email {email} already exists (id={existing[0]})")
            con.close()
            return existing[0]

        cur.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)",
            (name, email),
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
    
    ##########################################
    #        Drink Type Operations           #
    ##########################################
    def get_drink_type_by_id(self, drink_type_id: int) -> Optional[DrinkType]:
        """Retrieve a DrinkType object by drink_type_id.
        
        Args:
            drink_type_id (int): The ID of the drink type to retrieve.
        
        Returns:
            Optional[DrinkType]: The DrinkType object if found, otherwise None.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id, name, brand FROM drink_types WHERE drink_type_id = ?", (drink_type_id,))
        res = cur.fetchone()
        con.close()
        if res:
            return DrinkType.from_db_row(res)
        return None
    
    def get_drink_type_by_name(self, name: str) -> Optional[DrinkType]:
        """Retrieve a DrinkType object by name.
        
        Args:
            name (str): The exact name of the drink type. Case-sensitive.
        
        Returns:
            Optional[DrinkType]: The DrinkType object if found, otherwise None.
        
        Example:
            >>> db = ProstDB()
            >>> drink = db.get_drink_type_by_name("Cola")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id, name, brand FROM drink_types WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        if res:
            return DrinkType.from_db_row(res)
        return None
    
    def get_drink_type_id_by_name(self, name: str) -> Optional[int]:
        """Retrieve the drink_type_id for a drink type with the given name.

        Args:
            name (str): The exact name of the drink type. Case-sensitive.

        Returns:
            Optional[int]: The drink_type_id if found, otherwise None.

        Example:
            >>> db = ProstDB()
            >>> drink_id = db.get_drink_type_id_by_name("Cola")
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
        res = cur.fetchone()
        con.close()
        return res[0] if res else None
    
    def get_all_drink_types(self) -> List[DrinkType]:
        """Retrieve all drink types from the database.
        
        Returns:
            List[DrinkType]: A list of all DrinkType objects.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id, name, brand FROM drink_types ORDER BY name")
        rows = cur.fetchall()
        con.close()
        return [DrinkType.from_db_row(row) for row in rows]
    
    def add_drink_type(self, name: str, brand: str = "", verbose: bool = True) -> Optional[int]:
        """Add a new drink type to the database.

        Args:
            name (str): The name of the drink type.
            brand (str): The brand of the drink. Defaults to an empty string.
            verbose (bool): If True, prints a confirmation message. Defaults to True.

        Returns:
            Optional[int]: The new drink_type_id if created, or existing id if drink already exists.

        Raises:
            sqlite3.Error: If a database error occurs.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("SELECT drink_type_id FROM drink_types WHERE name = ?", (name,))
        existing = cur.fetchone()
        if existing:
            if verbose:
                print(f"Database: Drink type '{name}' already exists (id={existing[0]})")
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
    def stock_new_drinks(self, orderer_id: int, total_cost: float, items_list: list, verbose: bool = True) -> Optional[int]:
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
                
        Returns:
            Optional[int]: The new order_id if successful, None if an error occurred.
        """
        
        # Use 'with conn:' which automatically begins a transaction
        # and commits it. If an exception occurs, it rolls back.
        try:
            with self._get_connection() as conn:
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

            if verbose:
                print(f"Successfully stocked order ID: {new_order_id} with {len(batches_to_insert)} new batch(es).")
            return new_order_id

        except Error as e:
            print(f"Error during stocking operation: {e}")
            # The 'with conn:' block handles the rollback automatically
            return None
    
    ##########################################
    #        Purchase Operations             #
    ##########################################
    def add_purchase(self, user: str, drink: str) -> int:
        """Add a purchase record for a user buying a drink from the oldest available stock batch.

        This function:
        - Looks up the purchaser and drink type by name.
        - Selects the oldest stock batch for the requested drink type that has remaining stock.
        - Inserts a row into drink_purchases linking the purchaser to the batch and recording the cost.
        - Decrements the remaining quantity on the selected stock batch.
        - Updates balances: subtracts the cost from the purchaser and credits the orderer who paid for the batch.
        - Uses a single SQLite transaction (context manager) so all changes commit together or roll back on error.

        Args:
            user (str): Purchaser's name.
            drink (str): Drink type name.

        Returns:
            int: The newly inserted purchase_id from the drink_purchases table.

        Raises:
            ValueError: If the purchaser name or drink type name cannot be resolved to an ID, or if no stock is available for the requested drink.
            sqlite3.Error: If inserting the purchase or updating the database fails.

        Notes:
            - The batch selection uses ORDER BY date_added ASC and LIMIT 1 to pick the oldest available batch with remaining_qty > 0.
            - Concurrency: SQLite uses coarse-grained locking; concurrent calls may need retry logic or a different DB for high concurrency scenarios.
        """
        purchaser_id = self.get_user_id_by_name(user)
        if purchaser_id is None:
            raise ValueError(f"User not found: {user}")

        drink_type_id = self.get_drink_type_id_by_name(drink)
        if drink_type_id is None:
            raise ValueError(f"Drink type not found: {drink}")

        try:
            with self._get_connection() as conn:
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
    
    ##########################################
    #        Repayment Operations            #
    ##########################################
    def add_repayment(self, payer_id: int, receiver_id: int, amount: float) -> int:
        """Record a repayment and update user balances.

        Inserts a row into repayments and adjusts the payer's and receiver's balances within a single transaction. Returns the new repayment_id.

        Args:
            payer_id (int): The user_id of the person making the payment.
            receiver_id (int): The user_id of the person receiving the payment.
            amount (float): The amount being repaid.

        Returns:
            int: The new repayment_id.

        Raises:
            ValueError: if payer/receiver not found or amount is non-positive.
            sqlite3.Error: on DB errors.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        if payer_id == receiver_id:
            raise ValueError("Payer and receiver must be different users")

        with self._get_connection() as conn:
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
    
    ##########################################
    #        Query & Reporting Methods       #
    ##########################################
    def get_recent_purchases(self, limit: int = 50) -> List[dict]:
        """Get recent purchase records with user and drink details.
        
        Args:
            limit (int): Maximum number of records to return. Defaults to 50.
        
        Returns:
            List[dict]: A list of dictionaries containing purchase details.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("""
            SELECT 
                dp.purchase_id,
                u.name as user_name,
                dt.name as drink_name,
                dp.cost,
                dp.purchase_date,
                orderer.name as orderer_name
            FROM drink_purchases dp
            JOIN users u ON dp.user_id = u.user_id
            JOIN stock_batches sb ON dp.batch_id = sb.batch_id
            JOIN drink_types dt ON sb.drink_type_id = dt.drink_type_id
            JOIN users orderer ON dp.charged_to_orderer_id = orderer.user_id
            ORDER BY dp.purchase_date DESC
            LIMIT ?
        """, (limit,))
        
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        con.close()
        
        return [dict(zip(columns, row)) for row in rows]
    
    def get_stock_status(self) -> List[dict]:
        """Get current stock status for all drink types.
        
        Returns:
            List[dict]: A list of dictionaries with drink name and remaining quantity.
        """
        con = self._get_connection()
        cur = con.cursor()
        cur.execute("""
            SELECT 
                dt.name as drink_name,
                dt.brand,
                COALESCE(SUM(sb.remaining_qty), 0) as total_remaining
            FROM drink_types dt
            LEFT JOIN stock_batches sb ON dt.drink_type_id = sb.drink_type_id
            GROUP BY dt.drink_type_id, dt.name, dt.brand
            ORDER BY dt.name
        """)
        
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        con.close()
        
        return [dict(zip(columns, row)) for row in rows]
    
    def get_user_debts(self) -> List[dict]:
        """Get a summary of who owes money to whom.
        
        Returns:
            List[dict]: A list of dictionaries with debtor, creditor, and amount owed.
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
