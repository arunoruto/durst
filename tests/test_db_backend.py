import pytest
import os
import tempfile
from prost.db import ProstDB, User, DrinkType


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    # Create a temporary file
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    yield ProstDB(db_path)
    # Cleanup: remove the temporary database file
    if os.path.exists(db_path):
        os.remove(db_path)

@pytest.fixture
def populated_db(temp_db: ProstDB):
    """Create a database populated with test data."""
    db = temp_db
    
    # Add users
    alice_id = db.add_user("Alice", "alice@example.com", verbose=False)
    bob_id = db.add_user("Bob", "bob@example.com", verbose=False)
    charlie_id = db.add_user("Charlie", "charlie@example.com", verbose=False)
    if alice_id is None or bob_id is None or charlie_id is None:
        raise ValueError("Failed to create test users.")
    
    # Add drink types
    cola_id = db.add_drink_type("Cola", "CocaCola", verbose=False)
    sprite_id = db.add_drink_type("Sprite", "CocaCola", verbose=False)
    fanta_id = db.add_drink_type("Fanta", "CocaCola", verbose=False)
    if cola_id is None or sprite_id is None or fanta_id is None:
        raise ValueError("Failed to create test drink types.")

    # Stock drinks
    alice_order = [
        {"drink_type_id": cola_id, "cost_per_item": 1.50, "quantity": 24},
        {"drink_type_id": sprite_id, "cost_per_item": 1.25, "quantity": 12},
        {"drink_type_id": fanta_id, "cost_per_item": 1.30, "quantity": 18}
    ]
    total_cost = (1.50 * 24) + (1.25 * 12) + (1.30 * 18)  # 74.40
    order_id = db.stock_new_drinks(alice_id, total_cost, alice_order, verbose=False)
    
    return db, {
        'users': {'alice': alice_id, 'bob': bob_id, 'charlie': charlie_id},
        'drinks': {'cola': cola_id, 'sprite': sprite_id, 'fanta': fanta_id},
        'order_id': order_id
    }


class TestUserOperations:
    """Test user management operations."""
    
    def test_add_user(self, temp_db: ProstDB):
        """Test adding a new user."""
        user_id = temp_db.add_user("TestUser", "test@example.com", verbose=False)
        assert user_id is not None
        assert isinstance(user_id, int)
    
    def test_add_duplicate_user_email(self, temp_db: ProstDB):
        """Test that adding a user with duplicate email returns existing ID."""
        user_id_1 = temp_db.add_user("User1", "duplicate@example.com", verbose=False)
        user_id_2 = temp_db.add_user("User2", "duplicate@example.com", verbose=False)
        assert user_id_1 == user_id_2
    
    def test_get_user_by_name(self, temp_db: ProstDB):
        """Test retrieving a user by name."""
        temp_db.add_user("Alice", "alice@example.com", verbose=False)
        user = temp_db.get_user_by_name("Alice")
        assert user is not None
        assert user.name == "Alice"
        assert user.email == "alice@example.com"
        assert user.balance == 0.0
    
    def test_get_user_by_id(self, temp_db: ProstDB):
        """Test retrieving a user by ID."""
        user_id = temp_db.add_user("Bob", "bob@example.com", verbose=False)
        assert user_id is not None, "Failed to create test user Bob."
        user = temp_db.get_user_by_id(user_id)
        assert user is not None
        assert user.user_id == user_id
        assert user.name == "Bob"
    
    def test_get_all_users(self, temp_db: ProstDB):
        """Test retrieving all users."""
        temp_db.add_user("Alice", "alice@example.com", verbose=False)
        temp_db.add_user("Bob", "bob@example.com", verbose=False)
        temp_db.add_user("Charlie", "charlie@example.com", verbose=False)
        
        users = temp_db.get_all_users()
        assert len(users) == 3
        assert all(isinstance(user, User) for user in users)
        assert sorted([u.name for u in users]) == ["Alice", "Bob", "Charlie"]
    
    def test_user_balance_methods(self, temp_db: ProstDB):
        """Test User class helper methods."""
        user_id = temp_db.add_user("TestUser", "test@example.com", verbose=False)
        assert user_id is not None, "Failed to create test user TestUser."
        user = temp_db.get_user_by_id(user_id)
        assert user is not None, "Failed to retrieve TestUser."

        # Initial balance should be 0
        assert not user.is_in_debt()
        assert not user.is_owed()


class TestDrinkTypeOperations:
    """Test drink type management operations."""
    def test_add_drink_type(self, temp_db: ProstDB):
        """Test adding a new drink type."""
        drink_id = temp_db.add_drink_type("Cola", "CocaCola", verbose=False)
        assert drink_id is not None
        assert isinstance(drink_id, int)

    def test_add_duplicate_drink_type(self, temp_db: ProstDB):
        """Test that adding duplicate drink type returns existing ID."""
        drink_id_1 = temp_db.add_drink_type("Cola", "CocaCola", verbose=False)
        drink_id_2 = temp_db.add_drink_type("Cola", "Pepsi", verbose=False)
        assert drink_id_1 == drink_id_2
    
    def test_get_drink_type_by_name(self, temp_db: ProstDB):
        """Test retrieving a drink type by name."""
        temp_db.add_drink_type("Sprite", "CocaCola", verbose=False)
        drink = temp_db.get_drink_type_by_name("Sprite")
        assert drink is not None
        assert drink.name == "Sprite"
        assert drink.brand == "CocaCola"
    
    def test_get_drink_type_by_id(self, temp_db: ProstDB):
        """Test retrieving a drink type by ID."""
        drink_id = temp_db.add_drink_type("Fanta", "CocaCola", verbose=False)
        assert drink_id is not None, "Failed to create test drink type Fanta."
        drink = temp_db.get_drink_type_by_id(drink_id)
        assert drink is not None
        assert drink.drink_type_id == drink_id
        assert drink.name == "Fanta"
    
    def test_get_all_drink_types(self, temp_db: ProstDB):
        """Test retrieving all drink types."""
        temp_db.add_drink_type("Cola", "CocaCola", verbose=False)
        temp_db.add_drink_type("Sprite", "CocaCola", verbose=False)
        temp_db.add_drink_type("Fanta", "CocaCola", verbose=False)
        
        drinks = temp_db.get_all_drink_types()
        assert len(drinks) == 3
        assert all(isinstance(drink, DrinkType) for drink in drinks)
        assert sorted([d.name for d in drinks]) == ["Cola", "Fanta", "Sprite"]


class TestStockOperations:
    """Test stock and order management operations."""
    def test_stock_new_drinks(self, temp_db: ProstDB):
        """Test stocking new drinks."""
        user_id = temp_db.add_user("Alice", "alice@example.com", verbose=False)
        assert user_id is not None, "Failed to create test user Alice."
        cola_id = temp_db.add_drink_type("Cola", "CocaCola", verbose=False)
        assert cola_id is not None, "Failed to create test drink type Cola."

        order_items = [
            {"drink_type_id": cola_id, "cost_per_item": 1.50, "quantity": 24}
        ]
        order_id = temp_db.stock_new_drinks(user_id, 36.0, order_items, verbose=False)
        
        assert order_id is not None
        assert isinstance(order_id, int)

    def test_get_stock_status(self, populated_db: tuple[ProstDB, dict]):
        """Test retrieving stock status."""
        db, _ = populated_db
        stock = db.get_stock_status()
        
        assert len(stock) == 3
        assert all('drink_name' in item for item in stock)
        assert all('total_remaining' in item for item in stock)
        
        # Verify quantities
        stock_dict = {item['drink_name']: item['total_remaining'] for item in stock}
        assert stock_dict['Cola'] == 24
        assert stock_dict['Sprite'] == 12
        assert stock_dict['Fanta'] == 18


class TestPurchaseOperations:
    """Test purchase operations."""
    
    def test_add_purchase(self, populated_db: tuple[ProstDB, dict]):
        """Test adding a purchase."""
        db, data = populated_db
        
        # Bob buys a Cola
        purchase_id = db.add_purchase("Bob", "Cola")
        assert purchase_id is not None
        assert isinstance(purchase_id, int)
    
    def test_purchase_updates_balance(self, populated_db: tuple[ProstDB, dict]):
        """Test that purchases update user balances correctly."""
        db, data = populated_db
        
        # Get initial balances
        alice = db.get_user_by_name("Alice")
        bob = db.get_user_by_name("Bob")
        assert alice is not None, "Failed to retrieve Alice."
        assert bob is not None, "Failed to retrieve Bob."
        initial_alice_balance = alice.balance
        initial_bob_balance = bob.balance
        
        # Bob buys a Cola (costs $1.50)
        db.add_purchase("Bob", "Cola")
        
        # Check updated balances
        alice = db.get_user_by_name("Alice")
        assert alice is not None, "Failed to retrieve Alice."
        bob = db.get_user_by_name("Bob")
        assert bob is not None, "Failed to retrieve Bob."

        # Alice should be credited (she paid for the stock)
        assert alice.balance == initial_alice_balance + 1.50
        assert alice.is_owed()
        
        # Bob should be debited
        assert bob.balance == initial_bob_balance - 1.50
        assert bob.is_in_debt()
    
    def test_purchase_reduces_stock(self, populated_db: tuple[ProstDB, dict]):
        """Test that purchases reduce stock quantities."""
        db, _ = populated_db
        
        # Get initial stock
        initial_stock = db.get_stock_status()
        initial_cola = next(item for item in initial_stock if item['drink_name'] == 'Cola')
        initial_qty = initial_cola['total_remaining']
        
        # Bob buys a Cola
        db.add_purchase("Bob", "Cola")
        
        # Check updated stock
        updated_stock = db.get_stock_status()
        updated_cola = next(item for item in updated_stock if item['drink_name'] == 'Cola')
        
        assert updated_cola['total_remaining'] == initial_qty - 1

    def test_multiple_purchases(self, populated_db: tuple[ProstDB, dict]):
        """Test multiple purchases."""
        db, _ = populated_db
        
        # Make multiple purchases
        db.add_purchase("Bob", "Cola")
        db.add_purchase("Bob", "Sprite")
        db.add_purchase("Charlie", "Cola")
        db.add_purchase("Charlie", "Fanta")
        
        # Check balances
        bob = db.get_user_by_name("Bob")
        charlie = db.get_user_by_name("Charlie")
        alice = db.get_user_by_name("Alice")
        assert bob is not None, "Failed to retrieve Bob."
        assert charlie is not None, "Failed to retrieve Charlie."
        assert alice is not None, "Failed to retrieve Alice."
        
        # Bob bought Cola ($1.50) and Sprite ($1.25) = -$2.75
        assert abs(bob.balance - (-2.75)) < 0.01
        
        # Charlie bought Cola ($1.50) and Fanta ($1.30) = -$2.80
        assert abs(charlie.balance - (-2.80)) < 0.01
        
        # Alice should be credited for all purchases = +$5.55
        assert abs(alice.balance - 5.55) < 0.01
    
    def test_get_recent_purchases(self, populated_db: tuple[ProstDB, dict]):
        """Test retrieving recent purchases."""
        db, _ = populated_db
        
        # Make some purchases
        db.add_purchase("Bob", "Cola")
        db.add_purchase("Charlie", "Sprite")
        
        recent = db.get_recent_purchases(limit=10)
        
        assert len(recent) == 2
        assert all('user_name' in p for p in recent)
        assert all('drink_name' in p for p in recent)
        assert all('cost' in p for p in recent)
        assert all('orderer_name' in p for p in recent)
    
    def test_purchase_no_stock(self, populated_db: tuple[ProstDB, dict]):
        """Test that purchasing when no stock is available raises an error."""
        db, data = populated_db
        
        # Add a drink type with no stock
        db.add_drink_type("Water", "Generic", verbose=False)
        
        with pytest.raises(ValueError, match="No stock available"):
            db.add_purchase("Bob", "Water")


class TestRepaymentOperations:
    """Test repayment operations."""
    
    def test_add_repayment(self, populated_db: tuple[ProstDB, dict]):
        """Test adding a repayment."""
        db, data = populated_db
        
        # Make a purchase first
        db.add_purchase("Bob", "Cola")
        
        bob_id = data['users']['bob']
        alice_id = data['users']['alice']
        
        # Bob pays Alice
        repayment_id = db.add_repayment(bob_id, alice_id, 1.50)
        
        assert repayment_id is not None
        assert isinstance(repayment_id, int)
    
    def test_repayment_updates_balances(self, populated_db: tuple[ProstDB, dict]):
        """Test that repayments update user balances correctly."""
        db, data = populated_db
        
        # Bob buys a Cola (costs $1.50)
        db.add_purchase("Bob", "Cola")
        
        # Get balances before repayment
        bob = db.get_user_by_name("Bob")
        alice = db.get_user_by_name("Alice")
        assert bob is not None, "Failed to retrieve Bob."
        assert alice is not None, "Failed to retrieve Alice."

        bob_balance_before = bob.balance
        alice_balance_before = alice.balance
        
        # Bob pays Alice $1.00
        bob_id = data['users']['bob']
        alice_id = data['users']['alice']
        db.add_repayment(bob_id, alice_id, 1.00)
        
        # Check updated balances
        bob = db.get_user_by_name("Bob")
        assert bob is not None, "Failed to retrieve Bob."
        alice = db.get_user_by_name("Alice")
        assert alice is not None, "Failed to retrieve Alice."

        # Bob's balance should decrease by $1.00
        assert abs(bob.balance - (bob_balance_before - 1.00)) < 0.01
        
        # Alice's balance should increase by $1.00
        assert abs(alice.balance - (alice_balance_before + 1.00)) < 0.01

    def test_repayment_invalid_amount(self, populated_db: tuple[ProstDB, dict]):
        """Test that invalid repayment amounts raise errors."""
        db, data = populated_db
        
        bob_id = data['users']['bob']
        alice_id = data['users']['alice']
        
        with pytest.raises(ValueError, match="Amount must be positive"):
            db.add_repayment(bob_id, alice_id, 0)
        
        with pytest.raises(ValueError, match="Amount must be positive"):
            db.add_repayment(bob_id, alice_id, -10)

    def test_repayment_same_user(self, populated_db: tuple[ProstDB, dict]):
        """Test that repaying oneself raises an error."""
        db, data = populated_db
        
        bob_id = data['users']['bob']
        
        with pytest.raises(ValueError, match="Payer and receiver must be different"):
            db.add_repayment(bob_id, bob_id, 10.0)


class TestDebtReporting:
    """Test debt reporting and query operations."""

    def test_get_user_debts(self, populated_db: tuple[ProstDB, dict]):
        """Test retrieving user debt summary."""
        db, _ = populated_db
        
        # Make some purchases
        db.add_purchase("Bob", "Cola")
        db.add_purchase("Charlie", "Sprite")
        
        debts = db.get_user_debts()
        
        assert len(debts) == 2
        assert all('debtor_name' in d for d in debts)
        assert all('creditor_name' in d for d in debts)
        assert all('amount_owed' in d for d in debts)
        
        # Check that Bob and Charlie owe Alice
        debtor_names = [d['debtor_name'] for d in debts]
        assert 'Bob' in debtor_names
        assert 'Charlie' in debtor_names
    
    def test_full_workflow(self, temp_db: ProstDB):
        """Test a complete workflow from setup to final balances."""
        db = temp_db
        
        # 1. Add users
        alice_id = db.add_user("Alice", "alice@example.com", verbose=False)
        assert alice_id is not None, "Failed to create test user Alice."
        bob_id = db.add_user("Bob", "bob@example.com", verbose=False)
        assert bob_id is not None, "Failed to create test user Bob."
        # charlie_id = db.add_user("Charlie", "charlie@example.com", verbose=False)
        
        # 2. Add drink types
        cola_id = db.add_drink_type("Cola", "CocaCola", verbose=False)
        sprite_id = db.add_drink_type("Sprite", "CocaCola", verbose=False)
        
        # 3. Stock drinks
        order_items = [
            {"drink_type_id": cola_id, "cost_per_item": 1.50, "quantity": 24},
            {"drink_type_id": sprite_id, "cost_per_item": 1.25, "quantity": 12}
        ]
        total_cost = (1.50 * 24) + (1.25 * 12)
        db.stock_new_drinks(alice_id, total_cost, order_items, verbose=False)
        
        # 4. Make purchases
        db.add_purchase("Bob", "Cola")
        db.add_purchase("Bob", "Sprite")
        db.add_purchase("Charlie", "Cola")
        
        # 5. Check balances before repayment
        bob = db.get_user_by_name("Bob")
        assert bob is not None, "Failed to retrieve Bob."
        charlie = db.get_user_by_name("Charlie")
        assert charlie is not None, "Failed to retrieve Charlie."
        alice = db.get_user_by_name("Alice")
        assert alice is not None, "Failed to retrieve Alice."

        assert bob.is_in_debt()
        assert charlie.is_in_debt()
        assert alice.is_owed()
        
        # Bob owes: $1.50 + $1.25 = $2.75
        assert abs(bob.balance - (-2.75)) < 0.01
        # Charlie owes: $1.50
        assert abs(charlie.balance - (-1.50)) < 0.01
        # Alice is owed: $2.75 + $1.50 = $4.25
        assert abs(alice.balance - 4.25) < 0.01
        
        # 6. Bob pays Alice partially
        db.add_repayment(bob_id, alice_id, 2.00)
        
        # 7. Check final balances
        bob = db.get_user_by_name("Bob")
        assert bob is not None, "Failed to retrieve Bob."
        alice = db.get_user_by_name("Alice")
        assert alice is not None, "Failed to retrieve Alice."

        # Bob now owes: -$2.75 - $2.00 = -$4.75
        assert abs(bob.balance - (-4.75)) < 0.01
        # Alice is now owed: $4.25 + $2.00 = $6.25
        assert abs(alice.balance - 6.25) < 0.01
