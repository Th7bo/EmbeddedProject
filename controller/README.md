# Rules controller (PC)

Python rules controller, device simulator and tag learner for Snakes & Ladders: Hot or Cold.
MQTT contract: `../docs/wire-schemas.md`. Rules: `../docs/Project_1st_FollowUp_Updated.docx`.

| File | What |
| --- | --- |
| `snl/board.py` | board: ladders, snakes, paths with the bounce at 16 |
| `snl/game.py` | the rules engine: MQTT messages in, MQTT messages out, no network code |
| `snl/__main__.py` | the controller: connects the engine to the broker |
| `snl/dashboard.py` + `dashboard.html` | live dashboard at http://localhost:8080: board, players, devices, events, button |
| `snl/sim.py` | simulated meeples + base (bots or typed commands) |
| `snl/learn.py` | fills `tags.toml` (tag UID → cell) from real meeple reads |
| `tests/` | engine tests: `uv run pytest` |

## Run

Everything for a game, from the repo root:

```sh
./start.sh            # Mosquitto + controller + dashboard (opens http://localhost:8080); Ctrl+C stops it all
./start.sh --sim      # same, and accept the simulator's fake tags
```

It warns when this PC's IP differs from `MQTT_HOST` in `firmware/include/secrets.h` (then the ESPs can't find the broker).

By hand:

```sh
mosquitto -c mosquitto.conf -v                  # broker
uv run python -m snl --sim                      # controller + dashboard on http://localhost:8080
                                                # (--sim accepts the simulator's fake tags, --web 0.0.0.0:8080 = phones too)
uv run python -m snl.sim --auto -n 4            # simulated base + 4 bots play a whole game
uv run python -m snl.sim -n 2                   # or type: press, put 1 1, press, put 2 1, long, ...
```

One shared control base serves every player: short press adds a player (then put their meeple
on the board), long press starts. See `../docs/wire-schemas.md` §5.

With real hardware: set `MQTT_HOST` to this PC's IP in `firmware/include/secrets.h`, run
`uv run python -m snl.learn` once to map the 16 board tags, then `uv run python -m snl`.
To mix in simulated meeples next to the real base: `uv run python -m snl.sim -n 1 --no-base`
(controller started with `--sim`).
