"""B0, the random legal agent (T5.1).

At every decision B0 chooses uniformly at random among its legal actions, with one exception:
in a declaration window it passes, and declares (a set chosen uniformly among those it may
declare) only one time in ``DECLARE_ODDS``. Uniform play in windows would declare about nine
times in ten, so almost every window would end in a call and no game would ever reach an
ask (measured over 200 games: none did).

B0 looks at nothing but its legal actions and whether a window is open, so its choices carry
no information about its hand beyond what the legal set itself reveals (Research Questions,
H1c). It draws from the generator it is given, in a fixed order (in a window: first whether to
declare, then which set), so a B0 game is reproduced from its seed (``fish_agents.play``).

FROZEN: placebo games (H1c), the property tests (T2.5) and the performance numbers depend on
this definition. It is named ``b0-v1``; a different B0 needs a new name.
"""

from typing import Final

from fish_rules.action_index import PASS_INDEX
from fish_rules.rng import SplitMix64
from fish_rules.view import PlayerView

B0_VERSION: Final = "b0-v1"
"""Names this definition of B0."""

DECLARE_ODDS: Final = 100
"""In a window, B0 declares one time in this many and otherwise passes."""


class B0:
    """The random legal agent. Holds no state, so one instance can play every seat."""

    def act(self, view: PlayerView, rng: SplitMix64) -> int:
        """A uniformly random legal action; in a window, a pass unless one draw in
        ``DECLARE_ODDS`` says declare."""
        if view.window_open:
            declarations = [index for index in view.legal if index != PASS_INDEX]
            if rng.below(DECLARE_ODDS) == 0 and declarations:
                return rng.choice(declarations)
            return PASS_INDEX
        return rng.choice(view.legal)
