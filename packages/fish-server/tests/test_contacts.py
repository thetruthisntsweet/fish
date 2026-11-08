"""Requests about an email address and the 31 March deletion (fish_server.contacts; T3.8):
what is held is shown; an address can be corrected, or deleted with its sign-in links and its
sign-ins ended; and on 31 March every address and sign-in record goes, while games,
acceptances and withdrawals stay. Games are written as the export tests write them. Skipped
without FISH_TEST_DATABASE_URL."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, func, pool, select

from fish_server import db
from fish_server.consent import accept, withdraw
from fish_server.contacts import NotFoundError, correct, forget, forget_everyone, held, main
from fish_server.settings import database_url
from fish_server.signin import (
    player_for,
    request_link,
    session_player,
    start_session,
    use_link,
)


def _games() -> ModuleType:
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GAMES = _games()


@pytest.fixture
def owner(server_env: str) -> Engine:
    """The database as its owner, as these commands connect (FISH_ADMIN_DATABASE_URL)."""
    return create_engine(server_env, poolclass=pool.NullPool)


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    """The server's own login."""
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def count(engine: Engine, table: object) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()  # pyright: ignore[reportArgumentType]


def signed_in(engine: Engine, email: str) -> str:
    """A person who signed in with a link, accepted, and holds a session: its token."""
    with engine.begin() as conn:
        token = request_link(
            conn, email, daily_limit=90, consent_version="v1.0", terms_version="v1.0"
        )
        player = use_link(conn, token, cohort_seed=1)
        assert player is not None
        return start_session(conn, player)


def test_show_lists_what_is_held(owner: Engine) -> None:
    signed_in(owner, "jo@example.org")
    with owner.begin() as conn:
        (player,) = conn.execute(select(db.players.c.player_id)).scalars()
        seats = [player, *GAMES.people(conn, 5)]
        GAMES.add_game(conn, 5, seats)
        withdraw(conn, player, "website")
        lines = held(conn, "jo@example.org")
    assert lines[0] == "Email address: jo@example.org"
    assert lines[1] == f"Random player ID: {player}"
    assert lines[2].startswith("Signed up: ")
    assert any(
        line.startswith("Accepted the study information v1.0, terms v1.0 on ") for line in lines
    )
    assert any(line.startswith("Withdrew on ") and line.endswith(", website") for line in lines)
    assert any(line.startswith("Games played: 1, from ") for line in lines)
    assert "Sign-ins: 1, each kept only in scrambled form" in lines
    with owner.connect() as conn, pytest.raises(NotFoundError):
        held(conn, "nobody@example.org")


def test_an_address_is_corrected_but_never_to_someone_elses(owner: Engine) -> None:
    signed_in(owner, "old@example.org")
    signed_in(owner, "taken@example.org")
    with owner.begin() as conn:
        correct(conn, "old@example.org", "new@example.org")
        assert held(conn, "new@example.org")[0] == "Email address: new@example.org"
        links = conn.execute(select(db.sign_in_links.c.email)).scalars().all()
        assert "old@example.org" not in links  # the old address is kept nowhere
        with pytest.raises(ValueError, match="another player's address"):
            correct(conn, "new@example.org", "taken@example.org")


def test_forgetting_an_address_deletes_it_and_signs_the_person_out(owner: Engine) -> None:
    token = signed_in(owner, "gone@example.org")
    kept = signed_in(owner, "kept@example.org")
    with owner.begin() as conn:
        assert forget(conn, "gone@example.org") == (1, 1)
    with owner.connect() as conn:
        assert session_player(conn, token) is None  # signed out
        assert session_player(conn, kept) is not None  # nobody else is
        emails = conn.execute(select(db.player_contacts.c.email)).scalars().all()
        links = conn.execute(select(db.sign_in_links.c.email)).scalars().all()
    assert emails == ["kept@example.org"]
    assert links == ["kept@example.org"]
    assert count(owner, db.players) == 2  # the player and their acceptance stay
    assert count(owner, db.consents) == 2
    with owner.begin() as conn:
        assert player_for(conn, "gone@example.org", cohort_seed=1)  # a new sign-up is a new player
    assert count(owner, db.players) == 3


def test_on_31_march_every_address_and_sign_in_goes_and_nothing_else(owner: Engine) -> None:
    for n in range(3):
        signed_in(owner, f"p{n}@example.org")
    with owner.begin() as conn:
        GAMES.add_game(conn, 5, GAMES.table(conn))
        withdraw(conn, conn.execute(select(db.players.c.player_id)).scalars().first(), "email")
    kept = {
        t.name: count(owner, t)
        for t in (db.players, db.consents, db.withdrawals, db.games, db.actions)
    }
    with owner.begin() as conn:
        deleted = forget_everyone(conn)
    assert deleted == {"addresses": 9, "sign-in links": 3, "sign-ins": 3}
    for table in (
        db.player_contacts,
        db.sign_in_links,
        db.sign_in_uses,
        db.sessions,
        db.session_ends,
    ):
        assert count(owner, table) == 0, table.name
    assert {
        t.name: count(owner, t)
        for t in (db.players, db.consents, db.withdrawals, db.games, db.actions)
    } == kept


def test_the_command_line(owner: Engine, capsys: pytest.CaptureFixture[str]) -> None:
    signed_in(owner, "cli@example.org")
    assert main(["show", " CLI@Example.org "], owner) == 0
    assert "Email address: cli@example.org" in capsys.readouterr().out
    assert main(["show", "nobody@example.org"], owner) == 1
    assert (
        "No player has the address nobody@example.org. Nothing changed." in capsys.readouterr().out
    )
    assert main(["correct", "cli@example.org", "cli2@example.org"], owner) == 0
    assert "In Resend, change the contact's address" in capsys.readouterr().out
    assert main(["forget", "cli2@example.org"], owner) == 0
    out = capsys.readouterr().out
    assert "Deleted cli2@example.org, with 0 sign-in links, and ended 1 sign-ins." in out
    with pytest.raises(SystemExit):
        main(["forget-everyone"], owner)  # needs --yes
    assert "add --yes" in capsys.readouterr().err
    assert main(["forget-everyone", "--yes"], owner) == 0
    assert "Deleted: 0 addresses, 0 sign-in links, 1 sign-ins" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["show", "not an address"], owner)


def test_the_server_s_own_login_cannot_do_any_of_it(app: Engine) -> None:
    """These change private tables, which the server's login may only add to: the owner's
    login is needed (FISH_ADMIN_DATABASE_URL)."""
    with app.begin() as conn:
        player = player_for(conn, "x@example.org", cohort_seed=1)
        accept(conn, player, "v1.0", "v1.0")
    with pytest.raises(Exception, match="permission denied"), app.begin() as conn:
        forget(conn, "x@example.org")
