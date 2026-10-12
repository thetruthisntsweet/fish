"""Rules engine (T2.2).

State transitions for asking (R.3), two-step calls (R.4), after-call
choices and votes (R.5), run-out (R.6) and end of game (R.7). Timer-free
(R.8.6): opening a declaration window is an explicit transition, called
after every event by the environment and only on a Call press by the server.
"""
