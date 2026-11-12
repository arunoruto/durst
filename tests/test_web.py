import json

import pytest

from durst.db import DurstDB
from durst.web import make_app


@pytest.fixture
def web(tmp_path):
    """Alice (admin), Bob and 24 Colas, plus a Flask test client for the web UI."""
    db = DurstDB(db_file=str(tmp_path / "t.db"))
    alice = db.add_user("Alice", verbose=False)
    db.add_user("Bob", verbose=False)
    db.set_role("Alice", "admin")
    cola = db.add_drink_type("Cola", verbose=False)
    assert alice and cola
    db.stock_new_drinks(alice, 36.0, [{"drink_type_id": cola, "cost_per_item": 1.5, "quantity": 24}], verbose=False)
    app = make_app(db.db_file)
    return db, app, app.server.test_client()


def login(db, client, name):
    assert client.get(f"/login/{db.login_token(db.get_user_id_by_name(name))}").status_code == 302


def click(app, client, button, state=None):
    """POST a button click the way the browser does; returns (version, flash text)."""
    pattern = (
        json.dumps({k: v if k == "type" else ["ALL"] for k, v in button.items()},
                   sort_keys=True, separators=(",", ":"))
        if isinstance(button, dict) else button
    )
    key = next(k for k, cb in app.callback_map.items() if cb["inputs"][0]["id"] == pattern)
    prop = {"id": button, "property": "n_clicks", "value": 1}
    cb = app.callback_map[key]
    body = {
        "output": key,
        "outputs": [{"id": "version", "property": "data"}, {"id": "flash", "property": "children"}],
        "inputs": [[prop] if isinstance(button, dict) else prop],
        "state": [{"id": s["id"], "property": s["property"], "value": (state or {}).get(s["id"])}
                  for s in cb["state"][:-1]] + [{"id": "version", "property": "data", "value": 0}],
        "changedPropIds": [json.dumps(button, sort_keys=True, separators=(",", ":")) + ".n_clicks"
                           if isinstance(button, dict) else f"{button}.n_clicks"],
    }
    r = client.post("/_dash-update-component", json=body)
    if r.status_code == 204:
        return None, None
    out = r.get_json()["response"]
    flash = out["flash"]["children"]["props"]["children"]
    return out.get("version", {}).get("data"), flash


def page(app, client, path):
    r = client.post("/_dash-update-component", json={
        "output": "page.children", "outputs": {"id": "page", "property": "children"},
        "inputs": [{"id": "url", "property": "pathname", "value": path},
                   {"id": "version", "property": "data", "value": 0}],
        "changedPropIds": ["url.pathname"],
    })
    return json.dumps(r.get_json(), ensure_ascii=False)


def test_guest_sees_everything_but_cannot_act(web):
    db, app, client = web
    assert client.get("/").status_code == 200
    assert "Want a drink?" in page(app, client, "/") and "Cola" in page(app, client, "/")
    assert "Bob" in page(app, client, "/balances")
    assert "Drinks per week" in page(app, client, "/stats")
    _, flash = click(app, client, {"type": "buy", "drink": "Cola"})
    assert "Log in first" in flash
    assert db.get_recent_purchases() == []


def test_login_links_work_once(web):
    db, app, client = web
    token = db.login_token(db.get_user_id_by_name("Bob"))
    assert client.get(f"/login/{token}").status_code == 302
    assert client.get(f"/login/{token}").status_code == 400
    assert "Grab a drink" in page(app, client, "/") and "/admin" not in page(app, client, "/")


def test_user_buys_undoes_and_asks_for_money(web):
    db, app, client = web
    login(db, client, "Bob")
    # A user can't buy for someone else, even with a doctored request.
    version, flash = click(app, client, {"type": "buy", "drink": "Cola"}, {"buy-for": "Alice"})
    assert version == 1 and "Cola for Bob" in flash
    assert db.get_user_by_name("Alice").balance == 1.5  # only her orderer credit
    pid = db.get_recent_purchases()[0]["purchase_id"]
    assert "undo" in page(app, client, "/history")
    _, flash = click(app, client, {"type": "undo", "id": pid})
    assert "Undone" in flash and db.get_user_by_name("Bob").balance == 0

    _, flash = click(app, client, "dep-go", {"dep-amount": "10,50"})
    assert "once an admin confirms" in flash
    assert db.get_user_by_name("Bob").balance == 0  # not yet
    request_id = db.get_deposit_requests()[0]["request_id"]
    _, flash = click(app, client, {"type": "approve", "id": f"deposit:{request_id}"})
    assert flash == "Admins only."

    client.get("/logout")
    login(db, client, "Alice")
    assert "deposit 10,50 €" in page(app, client, "/admin")
    _, flash = click(app, client, {"type": "approve", "id": f"deposit:{request_id}"})
    assert flash == "Deposit booked." and db.get_user_by_name("Bob").balance == 10.5


def test_admin_restocks_books_and_buys_for_others(web):
    db, app, client = web
    login(db, client, "Alice")
    _, flash = click(app, client, "rs-go", {"rs-drink": "mate", "rs-qty": "20", "rs-total": "18,00", "rs-payer": "Kasse"})
    assert flash == "20 × mate in stock (0,90 € a bottle)."
    _, flash = click(app, client, "bk-go", {"bk-user": "Bob", "bk-amount": "-2"})
    assert db.get_user_by_name("Bob").balance == -2
    _, flash = click(app, client, {"type": "buy", "drink": "mate"}, {"buy-for": "Bob"})
    assert "mate for Bob" in flash and db.get_user_by_name("Bob").balance == pytest.approx(-2.9)


def test_last_key_cannot_be_removed(web):
    import asyncssh

    db, app, client = web
    bob = db.get_user_id_by_name("Bob")
    key = asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode().strip()
    db.add_ssh_key(bob, key)
    login(db, client, "Bob")
    _, flash = click(app, client, {"type": "key-del", "key": key})
    assert "last key" in flash and db.get_ssh_keys(bob)


def test_catch_up_books_the_basket_on_an_earlier_day(web):
    db, app, client = web
    login(db, client, "Bob")
    # While catching up a tap only counts; nothing is booked yet.
    assert click(app, client, {"type": "buy", "drink": "Cola"}, {"basket": {}}) == (None, None)
    state = {"basket": {"Cola": 2}, "cu-day": "gestern", "buy-for": "Alice"}  # buy-for: admins only
    _, flash = click(app, client, "cu-go", state)
    assert "2 drinks for Bob (" in flash
    bobs = db.get_recent_purchases()
    assert len(bobs) == 2 and {p["user_name"] for p in bobs} == {"Bob"}
    assert bobs[0]["purchase_date"].endswith("12:00:00")
    _, flash = click(app, client, "cu-go", {**state, "cu-day": "31.2."})
    assert "Pick the day" in flash
