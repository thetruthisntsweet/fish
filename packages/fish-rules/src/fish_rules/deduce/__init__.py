"""Layer 1: where each card can be, deduced exactly from what one seat has seen (T2.7).

``history.constraints`` turns a seat's view and the events it remembers into constraints on
one unknown: the deal at the start of the remembered events. The solver (T2.7 subtask 2)
finds, from those constraints, every seat that may hold each card.
"""
