import asyncio

import asyncssh

from durst.db import DurstDB
from durst.ssh import DurstSSHServer
from durst.tui import DurstApp


class FakeConn:
    def __init__(self):
        self.extra = {}

    def set_extra_info(self, **kw):
        self.extra.update(kw)


def test_key_maps_to_user_else_guest(tmp_path):
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    alice = db.add_user("Alice", "a@x.de", verbose=False)
    assert alice is not None
    key = asyncssh.generate_private_key("ssh-ed25519")
    other = asyncssh.generate_private_key("ssh-ed25519")
    db.add_ssh_key(alice, key.export_public_key().decode() + " laptop")

    server = DurstSSHServer(db)
    server.conn = FakeConn()
    assert server.validate_public_key("x", key.convert_to_public())
    assert server.conn.extra["durst_user"] == "Alice"
    # A probe of Alice's key followed by keyless (guest) login must not stay Alice.
    assert server.get_kbdint_challenge("x", "", "") is True
    assert server.conn.extra["durst_user"] is None
    # Unknown keys get in as guests, carrying the key so they can register it.
    assert server.validate_public_key("x", other.convert_to_public())
    assert server.conn.extra["durst_user"] is None
    assert server.conn.extra["durst_key"].startswith("ssh-ed25519 ")


def test_guest_cannot_buy(tmp_path):
    async def run():
        app = DurstApp(str(tmp_path / "t.db"), guest=True)
        async with app.run_test():
            assert not app.check_action("buy", ())
            assert not app.check_action("register", ())  # no key, nothing to register
            assert not app.check_action("approve", ())

    asyncio.run(run())
