# Examples

Each example is a short script that runs on its own after installing the packages:

```bash
pip install "fish-agents[env]"    # also installs fish-env and fish-rules
python 01_random_game.py
```

From a clone of the repository, run them with `uv run python examples/01_random_game.py`.
CI runs every example against the built packages on every change, so they always work with
the current release.

| Example | Shows |
|---|---|
| [01_random_game.py](01_random_game.py) | the PettingZoo loop: observations, action masks, rewards, and that a seed fixes the game |
| [02_your_own_agent.py](02_your_own_agent.py) | writing an agent (`act(view, rng) -> int`), reading its view, decoding action indices, and playing it against B0 |
| [03_replay_and_inspect.py](03_replay_and_inspect.py) | saving a game record as JSON, replaying it, reading its public events, and what one seat could see |
| [04_training_loop.py](04_training_loop.py) | where a learner gets its data: a NumPy softmax policy over masked actions, trained by REINFORCE from final rewards |
