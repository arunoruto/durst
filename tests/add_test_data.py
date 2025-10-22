# add_test_data.py
from prost.db import add_purchase, setup_database

if __name__ == "__main__":
    setup_database()  # Ensure table exists
    print("Adding test data...")
    add_purchase("Alice", "Club-Mate")
    add_purchase("Bob", "Fritz-Kola")
    add_purchase("Charlie", "Apfelschorle")
    add_purchase("Alice", "Water")  # Another for Alice
    print("Test data added. Run your 'prost.py' app now.")
