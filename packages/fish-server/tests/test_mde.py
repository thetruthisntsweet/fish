"""Minimum detectable effects from the pilot (fish_server.mde; T4.2, Research Questions §5.4):
Layer 1's log loss scored exactly as T1.1 scores beliefs, the hand-count leakage of every
person's ask, the MDE arithmetic, and a report with nothing that names a game or person. The
database test is skipped without FISH_TEST_DATABASE_URL."""

import importlib.util
import math
import random
import re
import statistics
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, create_engine, pool

from fish_rules.cards import SEATS, set_cards, set_of
from fish_rules.corpus import read_corpus_record
from fish_rules.deduce.games import knowledge
from fish_rules.deduce.solve import deduce
from fish_rules.engine import apply, legal_actions
from fish_rules.events import Ask, AskEvent, CallEvent, ChoiceEvent
from fish_rules.state import new_game
from fish_rules.view import project
from fish_server.corpus_export import export
from fish_server.mde import (
    GAMES,
    RESAMPLES,
    GameFigures,
    Z,
    _leak,  # pyright: ignore[reportPrivateUsage]
    _scored,  # pyright: ignore[reportPrivateUsage]
    bootstrap_se,
    figures,
    main,
    mde,
    result,
    win_rate_mde,
)
from fish_server.settings import database_url


def _games_writer() -> ModuleType:
    path = Path(__file__).with_name("test_corpus_export.py")
    spec = importlib.util.spec_from_file_location("corpus_games", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


written = _games_writer()
DAY = 24 * 60


# ---------------------------------------------------------------- the proxies


@pytest.fixture
def app(server_env: str) -> Iterator[Engine]:
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    yield engine
    engine.dispose()


def test_at_the_deal_every_hidden_card_has_five_possible_holders() -> None:
    loss, cards = _scored(new_game(3), None, [])
    assert cards == 6 * 45  # each seat, every card it does not hold
    assert loss == pytest.approx(cards * math.log2(5))


def test_the_log_loss_is_layer_1s_after_every_event_for_every_seat(app: Engine) -> None:
    """The same sum, worked out another way: each seat's and the public deductions from
    ``knowledge``, at the deal and after every event (T1.1 §1)."""
    record = _record(app, 17)
    actions = [step.action for step in read_corpus_record(record).steps]
    state = new_game(17)
    states = [state]
    for action in actions:
        state, records = apply(state, action)
        if any(isinstance(r, AskEvent | CallEvent | ChoiceEvent) for r in records):
            states.append(state)
    seats = [list(knowledge(new_game(17), actions, s)) for s in SEATS]
    public = list(knowledge(new_game(17), actions, None))
    loss, cards = 0.0, 0
    for n, state in enumerate(states):
        holder = {c: s for s, hand in enumerate(state.hands) for c in hand}
        for seat in SEATS:
            for card, owner in holder.items():
                if owner != seat and public[n].known(card) is None:
                    loss += math.log2(len(seats[seat][n].possible(card)))
                    cards += 1
    game = figures(read_corpus_record(record))
    assert (game.loss_bits, game.cards) == (pytest.approx(loss), cards)
    assert len(states) > 5


def test_an_ask_at_the_deal_leaks_by_how_its_sets_count_differs_from_the_average() -> None:
    """At the deal the public view expects one card of each set in every hand, so the
    policy's public probability is one over the sets the asker could ask for."""
    state = new_game(5)
    ask = next(a for a in legal_actions(state, state.current or 0) if isinstance(a, Ask))
    hand = state.hands[ask.seat]
    counts = [sum(c in hand for c in set_cards(s)) for s in range(9)]
    askable = [n for n in counts if 0 < n < 6]
    public = deduce(project(state, 0, None), [], use_hand=False)
    expected = math.log2(counts[set_of(ask.card)] / sum(askable) * len(askable))
    assert _leak(state, ask, public) == pytest.approx(expected)


def test_only_peoples_asks_are_counted(app: Engine) -> None:
    record = _record(app, 23, persons=4)  # B1 holds seats 4 and 5 from the start
    game = read_corpus_record(record)
    asks = sum(isinstance(s.action, Ask) and s.action.seat < 4 for s in game.steps)
    assert figures(game).asks == asks
    assert asks < sum(isinstance(s.action, Ask) for s in game.steps)


# ---------------------------------------------------------------- the arithmetic


def test_the_mde_is_2_8_standard_errors_and_shrinks_with_the_root_of_the_games() -> None:
    assert pytest.approx(2.8016, abs=1e-4) == Z
    assert mde(0.01, 30, 30) == pytest.approx(Z * 0.01)
    assert mde(0.01, 100, 400) == pytest.approx(mde(0.01, 100, 100) / 2)
    assert win_rate_mde(0.5, 1_000) == pytest.approx(Z * math.sqrt(0.5 / 1_000))
    assert GAMES == (150, 1_000)
    assert RESAMPLES == 10_000


def test_with_equal_games_the_bootstrap_se_is_the_spread_over_root_n() -> None:
    rng = random.Random(1)
    values = [rng.gauss(2.0, 0.3) for _ in range(60)]
    se = bootstrap_se([v * 100 for v in values], [100] * 60)
    expected = statistics.stdev(values) / math.sqrt(60)
    assert se == pytest.approx(expected, rel=0.08)
    assert bootstrap_se([v * 100 for v in values], [100] * 60) == se  # seeded


def test_win_rates_count_only_finished_games() -> None:
    games = [GameFigures(1.0, 1, 0.0, 1, won) for won in (True, False, True, None)]
    r = result(games)
    assert r.win == (pytest.approx(2 / 3), 3)
    assert result(games[:1]).loss is None  # one game has no spread


# ---------------------------------------------------------------- from the database


def _record(app: Engine, seed: int, persons: int = 6) -> dict[str, object]:
    """A real website game's corpus record: written to the tables, then exported."""
    with app.begin() as conn:
        written.add_game(conn, seed, written.table(conn, persons=persons))
    with app.connect() as conn:
        records, _ = export(conn)
    return next(r for r in records if read_corpus_record(r).seed == seed)


def test_the_command_prints_the_mdes_and_names_nothing(
    app: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    with app.begin() as conn:
        written.add_game(conn, 60, written.table(conn), minutes=-2 * DAY)  # before the pilot
        ids = [written.add_game(conn, s, written.table(conn), minutes=DAY)[0] for s in (61, 62, 63)]
    engine = create_engine(database_url(), poolclass=pool.NullPool)
    assert main(["--since", "2026-12-01"], engine) == 0
    printed = capsys.readouterr().out
    assert printed.startswith(
        "Fish MDEs from the pilot: 3 corpus games, games started from 1 December 2026"
    )
    assert "too few for these to mean much" in printed
    assert "| RQ1 information gain | Layer 1 log loss |" in printed
    assert "| MDE at 150 games | MDE at 1,000 games |" in printed
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", printed)
    for game_id in ids:
        assert str(game_id) not in printed
