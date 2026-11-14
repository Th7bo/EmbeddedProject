"""Simulated meeples + control bases over real MQTT (milestone M3).

    uv run python -m snl.sim --auto            # 2 bots play a full game
    uv run python -m snl.sim -n 3              # 3 players, you type the commands

Run the controller with `--sim` so it knows the fake tag UIDs.

Commands (interactive): press P | long P | put P CELL | lift P | auto | show | quit
"""
from __future__ import annotations

import argparse
import json
import threading
import time

from .board import roll_path, straight_path
from .game import PREFIX
from .mqtt import client
from .tags import sim_uid

STEP_S = 0.4  # time per cell when a bot walks


class Sim:
    def __init__(self, n: int, host: str, port: int, auto: bool):
        self.n, self.auto = n, auto
        self.base = {i: f"5bae000000{i:02x}" for i in range(1, n + 1)}    # sim index -> mac
        self.meeple = {i: f"51ee000000{i:02x}" for i in range(1, n + 1)}
        self.cell: dict[int, int | None] = {i: None for i in self.base}
        self.status: dict[int, dict] = {}
        self.game: dict = {}
        self.walking: dict[int, tuple] = {}   # sim index -> segment being walked
        self.lock = threading.Lock()
        self.c = client("snl-sim")
        self.c.on_connect = self._on_connect
        self.c.on_message = self._on_message
        self.c.connect(host, port, keepalive=5)
        self.c.loop_start()

    # ------------------------------------------------------------ device actions

    def press(self, i: int, kind: str = "short") -> None:
        print(f"  [sim] P{i} base: {kind} press")
        self.c.publish(f"{PREFIX}base/{self.base[i]}/button", kind)

    def put(self, i: int, cell: int | None) -> None:
        self.cell[i] = cell
        uid = sim_uid(cell) if cell else "-"
        self.c.publish(f"{PREFIX}meeple/{self.meeple[i]}/tag", uid, retain=True)

    def online(self, up: bool) -> None:
        for i in self.base:
            self.c.publish(f"{PREFIX}base/{self.base[i]}/online", "1" if up else "0", qos=1, retain=True)
            self.c.publish(f"{PREFIX}meeple/{self.meeple[i]}/online", "1" if up else "0", qos=1, retain=True)
            if up:
                self.put(i, None)

    # ------------------------------------------------------------ MQTT

    def _on_connect(self, cl, *_):
        cl.subscribe([(PREFIX + "base/+/status", 1), (PREFIX + "base/+/event", 1),
                      (PREFIX + "meeple/+/led", 1), (PREFIX + "game/state", 1)])

    def _on_message(self, _c, _u, msg):
        parts, payload = msg.topic.split("/"), msg.payload.decode()
        if msg.topic == PREFIX + "game/state":
            self.game = json.loads(payload)
            print(f"  [game] {payload}")
            return
        idx = self._index(parts[2])
        if idx is None:
            return
        if parts[3] == "status":
            with self.lock:
                self.status[idx] = json.loads(payload)
            print(f"  [P{idx} lcd] {payload}")
        elif parts[3] == "event":
            print(f"  [P{idx} buzzer] {payload}")
        elif parts[3] == "led":
            print(f"  [P{idx} meeple led] {payload}")

    def _index(self, mac: str) -> int | None:
        for i in self.base:
            if mac in (self.base[i], self.meeple[i]):
                return i
        return None

    # ------------------------------------------------------------ bot

    def play(self, timeout: float = 600) -> int | None:
        """Pair everyone, start, and play until someone wins. Returns the winner."""
        for i in self.base:
            self.press(i)
            self._wait(lambda: self.status.get(i, {}).get("phase") == "pairing")
            self.put(i, 1)
            self._wait(lambda: self.status.get(i, {}).get("phase") == "wait")
        self.press(1, "long")
        end = time.time() + timeout
        while time.time() < end:
            if self.game.get("state") == "finished":
                return self.game.get("winner")
            for i in self.base:
                self._bot_step(i)
            time.sleep(0.05)
        return None

    def _bot_step(self, i: int) -> None:
        with self.lock:
            s = dict(self.status.get(i, {}))
        if not s.get("turn"):
            self.walking.pop(i, None)
            return
        phase = s["phase"]
        if phase == "roll" and self.walking.get(i) != ("roll", s.get("hp")):
            self.walking[i] = ("roll", s.get("hp"))
            time.sleep(0.3)
            self.press(i)
            return
        if phase in ("move", "climb", "slide"):
            seg = (phase, s["roll"], s["target"])
            if self.walking.get(i) == seg:
                return
            self.walking[i] = seg
            start = self.cell[i] or 1
            path = roll_path(start, s["roll"]) if phase == "move" else straight_path(start, s["target"])
            print(f"  [sim] P{i} walks {start} -> {path}")
            for cell in path:
                time.sleep(STEP_S)
                self.put(i, cell)

    @staticmethod
    def _wait(cond, timeout: float = 5) -> None:
        end = time.time() + timeout
        while not cond():
            if time.time() > end:
                raise TimeoutError("controller did not answer - is it running with --sim?")
            time.sleep(0.05)

    # ------------------------------------------------------------ CLI

    def repl(self) -> None:
        print(__doc__.split("Commands")[1].strip())
        while True:
            try:
                cmd = input("> ").split()
            except EOFError:
                return
            if not cmd:
                continue
            try:
                if cmd[0] in ("press", "long"):
                    self.press(int(cmd[1]), "long" if cmd[0] == "long" else "short")
                elif cmd[0] == "put":
                    self.put(int(cmd[1]), int(cmd[2]))
                elif cmd[0] == "lift":
                    self.put(int(cmd[1]), None)
                elif cmd[0] == "auto":
                    print(f"winner: P{self.play()}")
                elif cmd[0] == "show":
                    for i in self.base:
                        print(f"P{i} cell={self.cell[i]} {self.status.get(i)}")
                elif cmd[0] == "quit":
                    return
                else:
                    print("?")
            except (IndexError, ValueError):
                print("usage: press P | long P | put P CELL | lift P | auto | show | quit")


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated meeples and control bases")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("-n", type=int, default=2, help="players (2-4)")
    ap.add_argument("--auto", action="store_true", help="bots play a full game, then exit")
    args = ap.parse_args()

    sim = Sim(args.n, args.host, args.port, args.auto)
    time.sleep(0.5)
    sim.online(True)
    try:
        if args.auto:
            winner = sim.play()
            print(f"winner: P{winner}" if winner else "no winner (timeout)")
        else:
            sim.repl()
    finally:
        sim.online(False)
        time.sleep(0.3)
        sim.c.loop_stop()


if __name__ == "__main__":
    main()
