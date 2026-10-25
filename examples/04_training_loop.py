"""The shape of a training loop over the environment, with NumPy only.

A linear softmax policy reads each agent's observation (648 bits) and picks among the actions
its mask allows (913, most of them illegal at any moment). All six seats share the policy.
After each batch of games, every action is credited with its seat's final reward (+1 or -1),
and the weights take one REINFORCE step. A few seconds of this teaches nothing useful; the
point is where the observations, masks, actions and rewards come from. Swap in your own model
and learner. Run: python 04_training_loop.py
"""

import numpy as np

from fish_env import env

OBS, ACTIONS = 648, 913
rng = np.random.default_rng(0)
weights = np.zeros((OBS, ACTIONS))


def policy(observation: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Action probabilities: a softmax over the legal actions only."""
    logits = observation @ weights
    logits[mask == 0] = -np.inf
    logits -= logits[mask == 1].max()
    probs = np.exp(logits)
    return probs / probs.sum()


def play(seed: int) -> tuple[list[tuple[np.ndarray, np.ndarray, int, str]], dict[str, float]]:
    """One self-play game: every decision (observation, probabilities, action, agent) and each
    agent's final reward."""
    game = env()
    game.reset(seed=seed)
    steps: list[tuple[np.ndarray, np.ndarray, int, str]] = []
    rewards: dict[str, float] = {}
    for agent in game.agent_iter():
        observation, reward, terminated, truncated, _ = game.last()
        if terminated or truncated:
            rewards[agent] = reward
            game.step(None)
            continue
        assert observation is not None  # every agent still playing has one
        x = observation["observation"].astype(float)
        probs = policy(x, observation["action_mask"])
        action = int(rng.choice(ACTIONS, p=probs))
        steps.append((x, probs, action, agent))
        game.step(action)
    return steps, rewards


learning_rate = 0.01
for batch in range(3):
    gradient = np.zeros_like(weights)
    lengths, team0 = [], 0
    for game_number in range(4):
        steps, rewards = play(seed=100 * batch + game_number)
        lengths.append(len(steps))
        team0 += rewards["seat_0"] > 0
        x = np.array([s[0] for s in steps])
        target = np.array([np.eye(ACTIONS)[s[2]] - s[1] for s in steps])
        credit = np.array([rewards[s[3]] for s in steps])[:, None]
        gradient += x.T @ (target * credit)  # REINFORCE: reward times d log p(action) / dW
    weights += learning_rate * gradient / len(lengths)
    print(
        f"batch {batch}: {len(lengths)} games, mean {np.mean(lengths):.0f} decisions, "
        f"team 0 won {team0}"
    )
