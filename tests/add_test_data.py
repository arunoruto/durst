# add_test_data.py
from prost.db import setup_database
from prost.db import add_user, stock_new_drinks, add_drink_type, get_orderer_id_by_name, get_drink_type_id_by_name, add_purchase


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
    id_of_alice = get_orderer_id_by_name(who_is_ordering)
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


