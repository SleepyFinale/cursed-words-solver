"""Self-learning Cursed Words agent (plan: docs/game-research/ai-agent-plan.md).

- ``obs``      human-visible observation: global vector + entity tokens
- ``actions``  every legal human action as a scored candidate list
- ``env``      ``CWEnv`` over ``sim.game.Game`` (reward = outcome increments)
- ``model``    PyTorch set-transformer policy / value (pointer head over candidates)
- ``store``    atomic, append-only shards and checkpoints (pause / resume anywhere)
- ``teacher``  behaviour-cloning data from the rules + plan AI
- ``bc`` / ``ppo``  trainers (GPU learner, CPU actors)
"""
