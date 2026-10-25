"""Write your own agent and play it against B0, the random legal baseline.

An agent is any object with ``act(view, rng) -> int``: it receives what its seat may know
(``view``) and a random-number generator, and returns one of ``view.legal``. This one, a
"collector", asks for cards of the set it holds most of, declares a set only when it holds
all six cards itself, and otherwise plays like B0. Team 0 (seats 0 to 2) is three collectors;
team 1 is three B0s. Run: python 02_your_own_agent.py
"""

from collections import Counter

from fish_agents.b0 import B0
from fish_agents.play import play_game
from fish_rules.action_index import PASS_INDEX, decode, encode
from fish_rules.cards import set_cards, set_of
from fish_rules.events import Ask, Assign, Declare
from fish_rules.rng import SplitMix64
from fish_rules.view import PlayerView


class Collector:
    """Builds up whole sets, and calls one only when it can see all six cards."""

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        actions = {index: decode(view.seat, index, view.phase) for index in view.legal}
        held = Counter(set_of(card) for card in view.hand)
        complete = [s for s, count in held.items() if count == len(set_cards(s))]
        if view.window_open:
            for index, action in actions.items():
                if isinstance(action, Declare) and action.set_id in complete:
                    return index
            return PASS_INDEX
        assign = encode(Assign(view.seat, (view.seat,) * 6))
        if assign in actions:
            return assign  # it holds all six cards, so it assigns them all to itself
        asks = {i: a for i, a in actions.items() if isinstance(a, Ask)}
        if asks:  # the set it holds most of; among equals, the lowest index
            return max(asks, key=lambda i: (held[set_of(asks[i].card)], -i))
        return rng.choice(view.legal)


wins: Counter[object] = Counter()
for seed in range(40):
    record = play_game([Collector()] * 3 + [B0()] * 3, seed)
    wins[record["winner"]] += 1
print(f"collectors (team 0) won {wins[0]} of 40 games against B0 (team 1, {wins[1]} wins)")
