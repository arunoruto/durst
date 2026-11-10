"""Serve the durst TUI over SSH, ``ssh terminal.shop`` style.

A registered public key logs you in as its owner; any other key (or none)
lands you in a read-only guest session.
"""

import asyncio
import fcntl
import os
import pty
import sys
import termios

import asyncssh

from durst.db import DurstDB


class DurstSSHServer(asyncssh.SSHServer):
    """Maps the client's SSH key to a durst user; everyone else is a guest."""

    def __init__(self, db: DurstDB) -> None:
        self.db = db

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self.conn = conn

    def begin_auth(self, username: str) -> bool:
        return True

    def public_key_auth_supported(self) -> bool:
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        # Also called for unsigned probes, but the last call before auth
        # succeeds is always the key that signed; kbdint (guest) resets it.
        user = self.db.get_user_by_ssh_key(key.export_public_key().decode())
        self.conn.set_extra_info(durst_user=user.name if user else None)
        return user is not None

    def kbdint_auth_supported(self) -> bool:
        return True

    def get_kbdint_challenge(self, username: str, lang: str, submethods: str):
        # No registered key: let them in without a prompt, as a guest.
        self.conn.set_extra_info(durst_user=None)
        return True


def _make_ctty() -> None:
    """Make the pty our controlling terminal (SIGWINCH/SIGHUP just work)."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def session_handler(db_file: str):
    async def handle(process: asyncssh.SSHServerProcess) -> None:
        term = process.get_terminal_type()
        if not term:
            process.stdout.write(b"durst needs a terminal, try: ssh -t\r\n")
            process.exit(1)
            return

        user = process.get_extra_info("durst_user")
        args = [sys.executable, "-m", "durst.tui", db_file] + ([user] if user else [])
        master, slave = pty.openpty()
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            preexec_fn=_make_ctty,
            env={**os.environ, "TERM": term, "COLORTERM": "truecolor"},
        )
        os.close(slave)
        try:
            await process.redirect(stdin=master, stdout=os.dup(master))
            await proc.wait()
        finally:
            if proc.returncode is None:
                proc.kill()
        process.exit(proc.returncode or 0)

    return handle


async def serve(db_file: str, host: str, port: int, host_key: str) -> None:
    """Run the SSH server forever."""
    if not os.path.exists(host_key):
        asyncssh.generate_private_key("ssh-ed25519").write_private_key(host_key)
    db = DurstDB(db_file=db_file)
    await asyncssh.create_server(
        lambda: DurstSSHServer(db),
        host,
        port,
        server_host_keys=[host_key],
        process_factory=session_handler(db_file),
        encoding=None,
        line_editor=False,
    )
    print(f"durst listening on {host}:{port}", flush=True)
    await asyncio.Future()
