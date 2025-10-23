# add_test_data.py
from prost.db import ProstDB, User, DrinkType


if __name__ == "__main__":
    # Initialize the database (creates the DB instance and sets up tables)
    print("=" * 60)
    print("Initializing database with class-based API...")
    print("=" * 60)
    db = ProstDB("test_class_api.db")
    
    # Add users - returns User objects
    print("\n1. Adding users...")
    alice_id = db.add_user("Alice", "alice@example.com")
    bob_id = db.add_user("Bob", "bob@example.com")
    charlie_id = db.add_user("Charlie", "charlie@example.com")
    print(f"   Created users: Alice (ID: {alice_id}), Bob (ID: {bob_id}), Charlie (ID: {charlie_id})")
    
    # Get user objects
    print("\n2. Retrieving user objects...")
    alice = db.get_user_by_name("Alice")
    if alice:
        print(f"   {alice.name} - {alice.email} - Balance: ${alice.balance:.2f}")
        print(f"   Is in debt? {alice.is_in_debt()}")
        print(f"   Is owed money? {alice.is_owed()}")
    
    # Add drink types
    print("\n3. Adding drink types...")
    cola_id = db.add_drink_type("Cola", "CocaCola")
    sprite_id = db.add_drink_type("Sprite", "CocaCola")
    fanta_id = db.add_drink_type("Fanta", "CocaCola")
    print(f"   Created drinks: Cola (ID: {cola_id}), Sprite (ID: {sprite_id}), Fanta (ID: {fanta_id})")
    
    # Get all drink types
    print("\n4. Listing all drink types...")
    all_drinks = db.get_all_drink_types()
    for drink in all_drinks:
        print(f"   - {drink.name} ({drink.brand})")
    
    # Stock new drinks
    print("\n5. Stocking drinks ordered by Alice...")
    alice_order = [
        {"drink_type_id": cola_id, "cost_per_item": 1.50, "quantity": 24},
        {"drink_type_id": sprite_id, "cost_per_item": 1.25, "quantity": 12},
        {"drink_type_id": fanta_id, "cost_per_item": 1.30, "quantity": 18}
    ]
    total_cost = (1.50 * 24) + (1.25 * 12) + (1.30 * 18)  # 74.40
    if alice_id is not None:
        order_id = db.stock_new_drinks(alice_id, total_cost, alice_order)
        print(f"   Order ID {order_id} created. Total cost: ${total_cost:.2f}")
    
    # Check stock status
    print("\n6. Current stock status...")
    stock = db.get_stock_status()
    for item in stock:
        qty = item['total_remaining'] if item['total_remaining'] else 0
        print(f"   - {item['drink_name']} ({item['brand']}): {qty} remaining")
    
    # Make purchases
    print("\n7. Recording purchases...")
    print("   Bob buys a Cola")
    db.add_purchase("Bob", "Cola")
    print("   Bob buys a Sprite")
    db.add_purchase("Bob", "Sprite")
    print("   Charlie buys a Cola")
    db.add_purchase("Charlie", "Cola")
    print("   Charlie buys a Fanta")
    db.add_purchase("Charlie", "Fanta")
    
    # Check balances
    print("\n8. Checking user balances after purchases...")
    for user_name in ["Alice", "Bob", "Charlie"]:
        user = db.get_user_by_name(user_name)
        if user:
            status = "OWED" if user.is_owed() else "OWES" if user.is_in_debt() else "EVEN"
            print(f"   {user.name}: ${user.balance:.2f} ({status})")
    
    # Show recent purchases
    print("\n9. Recent purchase history...")
    recent = db.get_recent_purchases(limit=10)
    for purchase in recent:
        print(f"   - {purchase['user_name']} bought {purchase['drink_name']} "
              f"for ${purchase['cost']:.2f} (charged to {purchase['orderer_name']})")
    
    # Show debt summary
    print("\n10. Debt summary...")
    debts = db.get_user_debts()
    if debts:
        for debt in debts:
            print(f"   - {debt['debtor_name']} owes {debt['creditor_name']} ${debt['amount_owed']:.2f}")
    else:
        print("   No debts recorded")
    
    # Record a repayment
    print("\n11. Bob pays Alice $2.75...")
    if bob_id is not None and alice_id is not None:
        repayment_id = db.add_repayment(bob_id, alice_id, 2.75)
        print(f"   Repayment recorded (ID: {repayment_id})")
    
    # Final balances
    print("\n12. Final balances after repayment...")
    all_users = db.get_all_users()
    for user in all_users:
        status = "OWED" if user.is_owed() else "OWES" if user.is_in_debt() else "EVEN"
        print(f"   {user.name}: ${user.balance:.2f} ({status})")
    
    print("\n" + "=" * 60)
    print("Demo complete! Check test_class_api.db to see the results.")
    print("=" * 60)
