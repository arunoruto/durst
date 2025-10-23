# add_test_data.py
from prost.db import setup_database
from prost.db import add_user, stock_new_drinks, add_drink_type, get_id_by_name, get_drink_type_id_by_name
from prost.db import add_purchase, add_repayment, get_user_balance


if __name__ == "__main__":
    verbose = False
    # TEST 1: Setup database and add test data
    print("Setting up database....")
    setup_database()  # Ensure table exists

    # TEST 2: Add users
    print("Adding test users....")
    add_user("Alice", "alice@example.com", verbose=verbose)
    add_user("Bob", "bob@example.com", verbose=verbose)
    add_user("Charlie", "charlie@example.com", verbose=verbose)

    # TEST 3: Add drink types
    print("Adding test drink types....")
    add_drink_type("Cola", "CocaCola", verbose=verbose)
    add_drink_type("Sprite", "CocaCola", verbose=verbose)

    # TEST 4: Stock new drinks
    print("Stocking up test drinks....")
    who_is_ordering = "Alice"
    id_of_alice = get_id_by_name(who_is_ordering)
    if id_of_alice is None:
        raise ValueError(f"User '{who_is_ordering}' not found in database.")
    alice_order = [
            {"drink_type_id": get_drink_type_id_by_name("Cola"), "cost_per_item": 1.50, "quantity": 24},
            {"drink_type_id": get_drink_type_id_by_name("Sprite"), "cost_per_item": 1.25, "quantity": 12}
        ]
    total_order_cost = (1.50 * 24) + (1.25 * 12) # 36.00 + 15.00 = 51.00
    # Call the function
    stock_new_drinks(
        orderer_id=id_of_alice,  # Alice's ID
        total_cost=total_order_cost,
        items_list=alice_order,
        verbose=verbose
    )

    # TEST 5: Make a purchase
    print("Adding test purchases....")
    add_purchase("Bob", "Cola")

    # TEST 6: Make repayments
    id_bob = get_id_by_name("Bob")
    id_charlie = get_id_by_name("Charlie")
    id_alice = get_id_by_name("Alice")
    if id_bob is None or id_charlie is None or id_alice is None:
        raise ValueError("One of the test users was not found in the database.")
    print("Adding test repayments....")
    add_repayment(id_alice, id_bob, 5.00)
    add_repayment(id_bob, id_charlie, 10.00)

    # TEST 7: Check balances
    print("Final balances after test data insertion:")
    for user_name in ["Alice", "Bob", "Charlie"]:
        usr_id = get_id_by_name(user_name)
        if usr_id is None:
            raise ValueError(f"User '{user_name}' not found in database.")
        balance = get_user_balance(usr_id)
        print(f"  {user_name}: {balance:.2f}")
