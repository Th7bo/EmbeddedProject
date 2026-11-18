"""Simulated meeples + control base over real MQTT (milestone M3).

    uv run python -m snl.sim --auto            # 2 bots play a full game
    uv run python -m snl.sim -n 3              # 3 meeples, you type the commands
    uv run python -m snl.sim -n 1 --no-base    # 1 extra meeple next to the real base + meeples
    uv run python -m snl.sim -n 2 --assist     # next to a real base: fake meeples join on your presses,
                                               # then roll and walk their own turns

Run the controller with `--sim` so it knows the fake tag UIDs.

Commands (interactive): press | long | put M CELL | lift M | auto | show | quit
(M = simulated meeple 1..n. Meeple M becomes player M when they join in order.)
"""
from __future__ import annotations

import argparse
import json
import threading
import time

from .board import roll_path, straight_path
from .game import PREFIX, T_EVENT, T_STATE
from .mqtt import client
from .tags import sim_uid

STEP_S = 0.4  # time per cell when a bot walks
BASE = "5bae00000001"


class Sim:
    def __init__(self, n: int, host: str, port: int, base: bool = True):
        self.base = base
        self.meeple = {i: f"51ee000000{i:02x}" for i in range(1, n + 1)}   # sim index -> mac
        self.cell: dict[int, int | None] = {i: None for i in self.meeple}
        self.game: dict = {}
        self.walked = None             # (turn, phase, target) the bot already walked
        self.pid: dict[int, int] = {}  # player id -> sim meeple index (real meeples can join too)
        self.lock = threading.Lock()
        self.c = client("snl-sim")
        self.c.on_connect = self._on_connect
        self.c.on_message = self._on_message
        self.c.connect(host, port, keepalive=5)
        self.c.loop_start()

    # ------------------------------------------------------------ device actions

    def press(self, kind: str = "short") -> None:
        print(f"  [sim] base: {kind} press")
        self.c.publish(f"{PREFIX}base/{BASE}/button", kind)

    def put(self, i: int, cell: int | None) -> None:
        self.cell[i] = cell
        uid = sim_uid(cell) if cell else "-"
        self.c.publish(f"{PREFIX}meeple/{self.meeple[i]}/tag", uid, retain=True)

    def online(self, up: bool) -> None:
        v = "1" if up else "0"
        if self.base:
            self.c.publish(f"{PREFIX}base/{BASE}/online", v, qos=1, retain=True)
        for i, mac in self.meeple.items():
            self.c.publish(f"{PREFIX}meeple/{mac}/online", v, qos=1, retain=True)
            if up:
                self.put(i, None)

    # ------------------------------------------------------------ MQTT

    def _on_connect(self, cl, *_):
        cl.subscribe([(T_STATE, 1), (T_EVENT, 1), (PREFIX + "meeple/+/led", 1)])

    def _on_message(self, _c, _u, msg):
        payload = msg.payload.decode()
        if msg.topic == T_STATE:
            with self.lock:
                self.game = json.loads(payload)
            print(f"  [lcd] {payload}")
        elif msg.topic == T_EVENT:
            print(f"  [buzzer] {payload}")
        elif msg.topic.endswith("/led"):
            mac = msg.topic.split("/")[2]
            idx = next((i for i, m in self.meeple.items() if m == mac), None)
            if idx:
                print(f"  [meeple {idx} led] {payload}")

    def _state(self) -> dict:
        with self.lock:
            return dict(self.game)

    # ------------------------------------------------------------ bot

    def play(self, timeout: float = 600) -> int | None:
        """Join every simulated meeple, start, and play until someone wins."""
        for i in self.meeple:
            self.press()
            self._wait(lambda: self._state().get("phase") == "pairing")
            self.pid[self._state()["joining"]] = i
            self.put(i, 1)
            self._wait(lambda: self._state().get("phase") == "join")
        self.press("long")
        end = time.time() + timeout
        while time.time() < end:
            s = self._state()
            if s.get("state") == "finished":
                return s.get("winner")
            if s.get("state") == "running" and not s.get("paused"):
                self._bot_step(s)
            time.sleep(0.05)
        return None

    def assist(self) -> None:
        """Meeples only: a real base presses the buttons; these meeples join and walk on their own."""
        joined = 0
        while True:
            s = self._state()
            if s.get("phase") == "pairing" and joined < len(self.meeple):
                joined += 1
                self.pid[s["joining"]] = joined
                time.sleep(0.5)
                print(f"  [sim] meeple {joined} put on cell 1 to join")
                self.put(joined, 1)
                self._wait(lambda: self._state().get("phase") != "pairing", timeout=10)
            elif s.get("state") == "running" and not s.get("paused") and s.get("phase") != "roll":
                self._bot_step(s)
            elif s.get("state") == "lobby" and not s.get("players"):
                joined, self.pid = 0, {}
            time.sleep(0.05)

    def _bot_step(self, s: dict) -> None:
        pid, phase = s["turn"], s["phase"]
        i = self.pid.get(pid)
        if i is None:
            return  # a real player's turn
        key = (pid, phase, s["target"], s["roll"])
        if key == self.walked:
            return
        self.walked = key
        if phase == "roll":
            time.sleep(0.3)
            self.press()
            return
        # Start where the meeple stands, or where the game says it is if it is off the board.
        start = self.cell[i] or next(p["cell"] for p in s["players"] if p["p"] == pid)
        path = roll_path(start, s["roll"]) if phase == "move" else straight_path(start, s["target"])
        print(f"  [sim] meeple {i} (P{pid}) walks {start} -> {path}")
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
                    self.press("long" if cmd[0] == "long" else "short")
                elif cmd[0] == "put":
                    self.put(int(cmd[1]), int(cmd[2]))
                elif cmd[0] == "lift":
                    self.put(int(cmd[1]), None)
                elif cmd[0] == "auto":
                    print(f"winner: P{self.play()}")
                elif cmd[0] == "show":
                    print(f"cells {self.cell}\nstate {self._state()}")
                elif cmd[0] == "quit":
                    return
                else:
                    print("?")
            except (IndexError, ValueError, KeyError):
                print("usage: press | long | put M CELL | lift M | auto | show | quit")


def main() -> None:
    ap = argparse.ArgumentParser(description="Simulated meeples and control base")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("-n", type=int, default=2, help="simulated meeples (1-4)")
    ap.add_argument("--no-base", action="store_true", help="don't simulate the base (a real one is used)")
    ap.add_argument("--auto", action="store_true", help="bots play a full game, then exit")
    ap.add_argument("--assist", action="store_true",
                    help="real base presses the button; simulated meeples join and walk by themselves")
    args = ap.parse_args()

    # --assist keeps the fake base online too: the bots press it for their own rolls.
    sim = Sim(args.n, args.host, args.port, base=not args.no_base)
    time.sleep(0.5)
    sim.online(True)
    try:
        if args.assist:
            sim.assist()
        elif args.auto:
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
