"""Layer 1: where each card can be, deduced exactly from what one seat has seen (T2.7).

- ``history.constraints`` turns a seat's view and the events it remembers into constraints
  on one unknown: the deal at the start of the remembered events.
- ``solve.solve`` finds from them every seat that may hold each card; ``solve.deduce`` does
  both steps.
- ``tracker.Tracker`` follows one seat's views as a game goes on, for agents.
- ``games.knowledge`` and ``games.certain_misses`` work over a recorded game, for analysis.
"""
