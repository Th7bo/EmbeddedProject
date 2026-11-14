# Rules controller (PC)

Python rules controller, device simulator and tag learner for Snakes & Ladders: Hot or Cold.
MQTT contract: `../docs/wire-schemas.md`. Rules: `../docs/Project_1st_FollowUp_Updated.docx`.

| File | What |
| --- | --- |
| `snl/board.py` | board: ladders, snakes, paths with the bounce at 16 |
| `snl/game.py` | the rules engine: MQTT messages in, MQTT messages out, no network code |
| `snl/__main__.py` | the controller: connects the engine to the broker |
| `snl/sim.py` | simulated meeples + bases (bots or typed commands) |
| `snl/learn.py` | fills `tags.toml` (tag UID → cell) from real meeple reads |
| `tests/` | engine tests: `uv run pytest` |

## Run

```sh
mosquitto -c mosquitto.conf -v                  # broker (Arch: sudo pacman -S mosquitto)
uv run python -m snl --sim                      # controller; --sim accepts the simulator's fake tags
uv run python -m snl.sim --auto                 # 2 bots play a whole game
uv run python -m snl.sim -n 3                   # or play by typing: press 1, put 1 3, long 1, ...
```

With real hardware: set `MQTT_HOST` to this PC's IP in `firmware/include/secrets.h`, run
`uv run python -m snl.learn` once to map the 16 board tags, then `uv run python -m snl`.
Real and simulated devices can play in the same game.
