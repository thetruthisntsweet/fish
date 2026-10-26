"""Every seat that may hold each card, exactly (Layer 1, T2.7).

A deal at the anchor fits the constraints (``fish_rules.deduce.history``) when every card in
play then is with one seat its ``allowed`` mask permits, every seat holds exactly its hand
size, and each ``AtLeastOne`` seat holds at least one of its cards. That is a flow problem:

    source -> card -> seat -> sink                      for a card with no constraint on the seat
    source -> card -> (seat, set) -> seat -> sink       for a card in an AtLeastOne for the seat

Every source edge carries exactly 1 (each card is dealt once), every sink edge exactly the
seat's hand size, and every (seat, set) edge at least 1. A seat's AtLeastOne constraints are
in different sets, so a card passes through at most one group on its way to a seat, and the
flows that meet these bounds are exactly the deals that fit. One flow is found with the
standard reduction of lower bounds to a maximum flow.

From one such flow, the others differ by cycles in its residual graph. So a card can be with a
seat in some deal that fits if and only if its edge towards that seat carries flow already, or
the edge's two ends lie in one strongly connected component of the residual graph. One flow
and one pass over the components give every possible holder of every card at once, with no
search, and the flow itself is an example deal.

A card still in play now that moved since the anchor is with the seat it moved to; one that
has not moved is with its holder at the anchor.
"""

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from fish_rules.cards import CARDS, SEATS, Card, Hand, Seat, set_of
from fish_rules.deduce.history import Constraints, HistoryError, SeatMask, constraints, seats_in
from fish_rules.events import Event
from fish_rules.view import PlayerView

_INFINITE: Final = 1 << 30


class _Network:
    """A flow network with residual capacities; edge ``e`` and ``e ^ 1`` are each other's
    reverse."""

    def __init__(self, nodes: int) -> None:
        self.out: list[list[int]] = [[] for _ in range(nodes)]
        self.head: list[int] = []
        self.room: list[int] = []

    def add(self, tail: int, head: int, capacity: int) -> int:
        edge = len(self.head)
        self.head += [head, tail]
        self.room += [capacity, 0]
        self.out[tail].append(edge)
        self.out[head].append(edge + 1)
        return edge

    def max_flow(self, source: int, sink: int) -> int:
        """Edmonds-Karp: shortest augmenting paths until none is left."""
        total = 0
        while True:
            via = [-1] * len(self.out)
            via[source] = -2
            queue = deque([source])
            while queue and via[sink] == -1:
                node = queue.popleft()
                for edge in self.out[node]:
                    if self.room[edge] and via[self.head[edge]] == -1:
                        via[self.head[edge]] = edge
                        queue.append(self.head[edge])
            if via[sink] == -1:
                return total
            push, node = _INFINITE, sink
            while node != source:
                push = min(push, self.room[via[node]])
                node = self.head[via[node] ^ 1]
            node = sink
            while node != source:
                self.room[via[node]] -= push
                self.room[via[node] ^ 1] += push
                node = self.head[via[node] ^ 1]
            total += push

    def components(self, nodes: int) -> list[int]:
        """The strongly connected component of each of the first ``nodes`` nodes in the
        residual graph restricted to them (Tarjan's algorithm, without recursion)."""
        index = [-1] * nodes
        low = [0] * nodes
        component = [-1] * nodes
        stack: list[int] = []
        counter = 0
        for root in range(nodes):
            if index[root] != -1:
                continue
            work = [(root, 0)]
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            while work:
                node, position = work[-1]
                edges = self.out[node]
                if position < len(edges):
                    work[-1] = (node, position + 1)
                    edge = edges[position]
                    nxt = self.head[edge]
                    if not self.room[edge] or nxt >= nodes:
                        continue
                    if index[nxt] == -1:
                        index[nxt] = low[nxt] = counter
                        counter += 1
                        stack.append(nxt)
                        work.append((nxt, 0))
                    elif component[nxt] == -1:
                        low[node] = min(low[node], index[nxt])
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    while True:
                        member = stack.pop()
                        component[member] = node
                        if member == node:
                            break
        return component


@dataclass(frozen=True, slots=True)
class _Flow:
    """A deal that fits, as a flow, with what is needed to read the other deals from it."""

    network: _Network
    nodes: int  # the nodes of the deal itself; the reduction's two extra nodes come after
    # For each card dealt at the anchor: (seat, edge from the card towards that seat).
    edges: dict[Card, list[tuple[Seat, int]]]


def _flow(c: Constraints) -> _Flow | None:
    """A flow for a deal that fits ``c``, or None if no deal fits."""
    dealt = [card for card in CARDS if c.allowed[card]]
    groups = {(need.seat, set_of(need.cards[0])): need for need in c.at_least_one}
    group_of = {(card, need.seat): key for key, need in groups.items() for card in need.cards}
    source, sink = 0, 1
    card_node = {card: 2 + i for i, card in enumerate(dealt)}
    group_node = {key: 2 + len(dealt) + i for i, key in enumerate(groups)}
    seat_node = {seat: 2 + len(dealt) + len(groups) + seat for seat in SEATS}
    nodes = 2 + len(dealt) + len(groups) + len(SEATS)
    extra_source, extra_sink = nodes, nodes + 1
    network = _Network(nodes + 2)
    excess = [0] * nodes

    def bounded(tail: int, head: int, lower: int, upper: int) -> int:
        excess[tail] -= lower
        excess[head] += lower
        return network.add(tail, head, upper - lower)

    edges: dict[Card, list[tuple[Seat, int]]] = {}
    for card in dealt:
        bounded(source, card_node[card], 1, 1)
        edges[card] = []
        for seat in seats_in(c.allowed[card]):
            key = group_of.get((card, seat))
            head = seat_node[seat] if key is None else group_node[key]
            edges[card].append((seat, network.add(card_node[card], head, 1)))
    for key, need in groups.items():
        bounded(group_node[key], seat_node[need.seat], 1, len(need.cards))
    for seat in SEATS:
        bounded(seat_node[seat], sink, c.sizes[seat], c.sizes[seat])
    network.add(sink, source, _INFINITE)
    required = 0
    for node, amount in enumerate(excess):
        if amount > 0:
            network.add(extra_source, node, amount)
            required += amount
        elif amount < 0:
            network.add(node, extra_sink, -amount)
    if network.max_flow(extra_source, extra_sink) < required:
        return None
    return _Flow(network, nodes, edges)


def _deal(flow: _Flow) -> tuple[Hand, ...]:
    """The deal the flow describes: each card is with the seat its edge with flow leads to."""
    hands: list[list[Card]] = [[] for _ in SEATS]
    for card, options in flow.edges.items():
        seat = next(seat for seat, edge in options if not flow.network.room[edge])
        hands[seat].append(card)
    return tuple(tuple(hand) for hand in hands)


def example_deal(
    c: Constraints, fixed: Mapping[Card, Seat] | None = None
) -> tuple[Hand, ...] | None:
    """A deal at the anchor that fits ``c`` with each card in ``fixed`` dealt to its seat, or
    None if there is none."""
    allowed = list(c.allowed)
    for card, seat in (fixed or {}).items():
        allowed[card] &= 1 << seat
        if not allowed[card]:
            return None
    flow = _flow(replace(c, allowed=tuple(allowed)))
    return None if flow is None else _deal(flow)


@dataclass(frozen=True, slots=True)
class Deduction:
    """Where every card can be, for ``observer`` (None for the public view), exactly.

    ``holders``: for each card, the seats that may hold it now, as a mask: one seat when its
    place is known, 0 for cards out of play. A seat is in the mask if and only if some deal
    fits everything the observer has seen and remembers with the card there.
    ``anchor``: what was deduced about the deal just before the first remembered event, in the
    same form, for cards in play then.
    ``example``: one deal at that moment that fits.
    """

    constraints: Constraints
    holders: tuple[SeatMask, ...]
    anchor: tuple[SeatMask, ...]
    example: tuple[Hand, ...]

    def possible(self, card: Card) -> tuple[Seat, ...]:
        """The seats that may hold ``card`` now; empty if it is out of play."""
        return seats_in(self.holders[card])

    def known(self, card: Card) -> Seat | None:
        """The seat that certainly holds ``card`` now, or None if there are several (or it is
        out of play)."""
        seats = self.possible(card)
        return seats[0] if len(seats) == 1 else None

    def example_now(self) -> tuple[Hand, ...]:
        """The hands now under ``example``: each card in play with the seat it moved to, or
        else with its holder in the example."""
        c = self.constraints
        hands: list[list[Card]] = [[] for _ in SEATS]
        for seat, hand in enumerate(self.example):
            for card in hand:
                if c.in_play[card]:
                    moved = c.moved[card]
                    hands[seat if moved is None else moved].append(card)
        return tuple(tuple(sorted(hand)) for hand in hands)


def solve(c: Constraints) -> Deduction:
    """Every possible holder of every card under ``c``. Raises ``HistoryError`` if no deal
    fits."""
    flow = _flow(c)
    if flow is None:
        raise HistoryError("no deal fits everything seen")
    component = flow.network.components(flow.nodes)
    anchor = [0] * len(CARDS)
    for card, options in flow.edges.items():
        for seat, edge in options:
            head, tail = flow.network.head[edge], flow.network.head[edge ^ 1]
            if not flow.network.room[edge] or component[head] == component[tail]:
                anchor[card] |= 1 << seat
    holders = [0] * len(CARDS)
    for card in CARDS:
        moved = c.moved[card]
        if c.in_play[card]:
            holders[card] = anchor[card] if moved is None else 1 << moved
    return Deduction(c, tuple(holders), tuple(anchor), _deal(flow))


def deduce(view: PlayerView, events: Sequence[Event], *, use_hand: bool = True) -> Deduction:
    """Layer 1 for ``view.seat``, from its view and the events it remembers (one unbroken run
    ending at ``view.last_event``, or empty); with ``use_hand`` False, for the public view.
    Raises ``HistoryError`` if the events do not fit the view."""
    return solve(constraints(view, events, use_hand=use_hand))
