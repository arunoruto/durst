import logging

import click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)-8s - %(levelname)s - %(message)s",
)


@click.group()
def cli() -> None:
    pass


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
