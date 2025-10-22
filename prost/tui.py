import click
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from prost.db import get_recent_purchases, setup_database

# Hardcode data for now to test the UI in isolation
DRINKS_DATA = [
    ("User", "Drink", "Timestamp"),
    ("Anna", "Club-Mate", "2025-10-22 17:00"),
    ("Ben", "Fritz-Kola", "2025-10-22 17:05"),
    ("Carla", "Apfelschorle", "2025-10-22 17:10"),
]


class ProstApp(App):
    """A TUI for managing soft drinks."""

    # CSS_PATH = "prost.css"  # You can add styling later

    def __init__(self, db_file: str = "sqlite.db"):
        self.db_file = db_file
        super().__init__()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(name="Prost! 🍻")
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted to the screen."""
        # Ensure the database file and table are created.
        setup_database(db_file=self.db_file)

        # Just call the function directly. It's fast enough.
        self.populate_table()

    def populate_table(self) -> None:
        """Fetches data from SQLite and populates the DataTable. (No async needed)"""

        # Get a reference to the DataTable widget.
        table = self.query_one(DataTable)

        # Clear any existing data.
        table.clear()

        # Fetch the latest records from the database.
        recent_purchases = get_recent_purchases(limit=50, db_file=self.db_file)

        # If there's data, prepare and add it to the table.
        if recent_purchases:
            # Get the column headers from the keys of the first record.
            headers = [
                key.replace("_", " ").title() for key in recent_purchases[0].keys()
            ]

            # Get the data rows as a list of tuples.
            rows = [tuple(record.values()) for record in recent_purchases]

            # Update the UI directly. No call_from_thread needed.
            table.add_columns(*headers)
            table.add_rows(rows)


@click.command()
@click.option("--db", default="sqlite.db", help="Location of the database")
def tui(db: str) -> None:
    app = ProstApp(db_file=db)
    app.run()


if __name__ == "__main__":
    tui()
