import logging

import click

from prost.tui import ProstApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)-8s - %(levelname)s - %(message)s",
)


@click.group(invoke_without_command=True)
@click.option("--db", default="sqlite.db", help="Location of the database")
@click.pass_context
def cli(ctx, db) -> None:
    if ctx.invoked_subcommand is None:
        app = ProstApp(db_file=db)
        app.run()


@cli.command()
# @click.option("--count", default=1, help="Number of greetings.")
# @click.option("--name", prompt="Your name", help="The person to greet.")
def display(
    # count,
    # name,
):
    print("Displaying...")


if __name__ == "__main__":
    print("This is the CLI implementation. Please run the binary!")
