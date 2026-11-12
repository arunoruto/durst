"""Serve the durst TUI over SSH, ``ssh terminal.shop`` style.

An approved public key logs you in as its owner. Any other key gets a
read-only guest session that can register the key (admins approve it);
clients without a key get a plain guest session.

ponytail: every key is accepted, so with several keys the client's first one
wins; register that one too, or pick one with ``ssh -i``.
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
        line = key.export_public_key().decode()
        user = self.db.get_user_by_ssh_key(line)
        self.conn.set_extra_info(durst_user=user.name if user else None, durst_key=line)
        return True

    def kbdint_auth_supported(self) -> bool:
        return True

    def get_kbdint_challenge(self, username: str, lang: str, submethods: str):
        # No registered key: let them in without a prompt, as a guest.
        self.conn.set_extra_info(durst_user=None, durst_key=None)
        return True


def _make_ctty() -> None:
    """Make the pty our controlling terminal (SIGWINCH/SIGHUP just work)."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def login_link(db: DurstDB, user: str | None) -> str:
    """What ``ssh … login`` prints: a one-time link into the web UI."""
    base = os.environ.get("DURST_WEB_URL", "").rstrip("/")
    uid = db.get_user_id_by_name(user) if user else None
    if not base:
        return "The web UI isn't set up here (DURST_WEB_URL)."
    if uid is None:
        return "Your key isn't approved yet. Run ssh without 'login' to register."
    return f"Open this within 10 minutes to log in (works once):\n\n  {base}/login/{db.login_token(uid)}\n"


def session_handler(db_file: str):
    async def handle(process: asyncssh.SSHServerProcess) -> None:
        if (process.command or "").strip() == "login":
            text = login_link(DurstDB(db_file=db_file), process.get_extra_info("durst_user"))
            process.stdout.write((text + "\n").replace("\n", "\r\n").encode())
            process.exit(0)
            return
        term = process.get_terminal_type()
        if not term:
            process.stdout.write(b"durst needs a terminal, try: ssh -t\r\n")
            process.exit(1)
            return

        user = process.get_extra_info("durst_user")
        key = process.get_extra_info("durst_key")
        args = [sys.executable, "-m", "durst.tui", db_file]
        args += (["--user", user] if user else []) + (["--key", key] if key else [])
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


async def sync_forever(db_file: str, sheet_id: str, credentials: str, interval: int) -> None:
    """Sync with the Google Sheet every ``interval`` seconds; errors are logged, not fatal."""
    from durst.sheet import SheetClient, locked_sync

    db = DurstDB(db_file=db_file)
    client = SheetClient(sheet_id, credentials)
    seen: dict = {}
    while True:
        try:
            for line in await asyncio.to_thread(locked_sync, db, client, seen):
                print(f"sync: {line}", flush=True)
        except Exception as e:  # keep serving even if Google is unreachable
            print(f"sync failed: {e!r}", flush=True)
        await asyncio.sleep(interval)


async def serve(
    db_file: str,
    host: str,
    port: int,
    host_key: str,
    sheet: tuple[str, str, int] | None = None,
) -> None:
    """Run the SSH server forever (and the sheet sync, given ``(id, credentials, interval)``)."""
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
    if sheet:
        await sync_forever(db_file, *sheet)
    await asyncio.Future()
