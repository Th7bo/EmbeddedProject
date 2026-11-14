"""Rules engine. Pure: MQTT messages in, MQTT messages out, no network code.

Contract: docs/wire-schemas.md. Rules: docs/Project_1st_FollowUp_Updated.docx.

Retained topics (base status, meeple led, game state) are *derived* from the game
state after every input and only published when they change. One-off events
(sounds) are queued explicitly.
"""
from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, NamedTuple

from .board import CELLS, LADDERS, SNAKES, jump, roll_path, straight_path

log = logging.getLogger("snl.game")

PREFIX = "snl/"
START_CELL = 1
START_HP = 3
MAX_HP = 5
MAX_PLAYERS = 4
DWELL_S = 2.0          # meeple must stay on the target this long to end the turn
PAIRED_FLASH_S = 1.0   # meeple LED solid after pairing


class Msg(NamedTuple):
    topic: str
    payload: str
    retain: bool = False
    qos: int = 1


@dataclass
class Device:
    online: bool = False
    pid: int = 0
    tag: str = "-"  # meeples only


@dataclass
class Player:
    pid: int
    base: str
    meeple: str = ""
    hp: int = START_HP
    pos: int = START_CELL  # where the meeple should be when it is not moving
    skip: bool = False
    flash_until: float = 0.0


@dataclass
class Turn:
    pid: int
    phase: str = "roll"            # roll | move | climb | slide
    roll: int | None = None
    start: int = START_CELL        # cell this segment starts from
    path: list[int] = field(default_factory=list)
    progress: int = 0              # path[:progress] has been walked
    dist: int | None = None
    reached_at: float | None = None
    wrong_cell: int | None = None  # last cell we beeped "wrong" for

    @property
    def target(self) -> int | None:
        return self.path[-1] if self.path else None


class Game:
    def __init__(self, tags: dict[str, int], rng: random.Random | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.tags = {uid.upper(): cell for uid, cell in tags.items()}
        self.rng = rng or random.Random()
        self.clock = clock
        self.bases: dict[str, Device] = {}
        self.meeples: dict[str, Device] = {}
        self.players: dict[int, Player] = {}
        self.state = "lobby"  # lobby | running | finished
        self.order: list[int] = []
        self.turn: Turn | None = None
        self.winner: int | None = None
        self.pairing: int | None = None  # pid whose base waits for a meeple
        self._out: list[Msg] = []
        self._published: dict[str, str] = {}

    # ------------------------------------------------------------ public API

    def startup(self) -> list[Msg]:
        """Call on every (re)connect: republishes all retained state."""
        self._published.clear()
        self._out.append(Msg(PREFIX + "ctrl/online", "1", retain=True))
        return self._flush()

    def on_message(self, topic: str, payload: str) -> list[Msg]:
        parts = topic.split("/")
        if len(parts) == 4 and parts[0] + "/" == PREFIX:
            _, kind, mac, what = parts
            if kind == "meeple":
                self._on_meeple(mac, what, payload)
            elif kind == "base":
                self._on_base(mac, what, payload)
        return self._flush()

    def tick(self) -> list[Msg]:
        """Call regularly (~10 Hz): timers for dwell and the pairing flash."""
        t = self.turn
        if (self.state == "running" and t and t.reached_at is not None and not self._paused()
                and self.clock() - t.reached_at >= DWELL_S):
            log.info("P%d stayed on %d, turn ends", t.pid, t.target)
            self._end_turn()
        return self._flush()

    def cell_of(self, pid: int) -> int | None:
        m = self.meeples.get(self.players[pid].meeple)
        return self.tags.get(m.tag) if m and m.tag != "-" else None

    # ------------------------------------------------------------ inputs

    def _on_meeple(self, mac: str, what: str, payload: str) -> None:
        dev = self.meeples.setdefault(mac, Device())
        if what == "online":
            dev.online = payload == "1"
            log.info("meeple %s %s", mac, "online" if dev.online else "offline")
        elif what == "tag":
            old, dev.tag = dev.tag, payload.strip().upper() or "-"
            if not dev.online or dev.tag == old:
                return
            if dev.tag != "-" and dev.tag not in self.tags:
                log.warning("unknown tag %s on meeple %s", dev.tag, mac)
            if dev.pid == 0:
                if self.pairing and dev.tag != "-":
                    self._pair_meeple(mac)
            elif self.turn and self.turn.pid == dev.pid and not self._paused():
                self._on_move(self.cell_of(dev.pid))

    def _on_base(self, mac: str, what: str, payload: str) -> None:
        dev = self.bases.setdefault(mac, Device())
        if what == "online":
            dev.online = payload == "1"
            log.info("base %s %s", mac, "online" if dev.online else "offline")
        elif what == "button" and dev.online:
            if payload == "short":
                self._short_press(mac, dev)
            elif payload == "long":
                self._long_press(dev)

    def _short_press(self, mac: str, dev: Device) -> None:
        if dev.pid == 0:
            if self.state == "lobby" and self.pairing is None and len(self.players) < MAX_PLAYERS:
                pid = min(set(range(1, MAX_PLAYERS + 1)) - set(self.players))
                self.players[pid] = Player(pid, base=mac)
                dev.pid = self.pairing = pid
                log.info("base %s is P%d, waiting for a meeple", mac, pid)
            return
        t = self.turn
        if self.state == "running" and t and t.pid == dev.pid and t.phase == "roll" and not self._paused():
            self._roll(t)

    def _long_press(self, dev: Device) -> None:
        if dev.pid == 0 or dev.pid == self.pairing:
            return
        if self.state == "lobby" and self.pairing is None and len(self.players) >= 2:
            self._start_game()
        elif self.state == "finished":
            self._start_game()
        elif self.state == "running" and self.turn and self.turn.pid == dev.pid and not self._paused():
            t = self.turn
            if t.phase == "roll":
                return
            if self.cell_of(t.pid) == t.target and t.reached_at is not None:
                self._end_turn()
            else:
                log.info("P%d ended the turn on the wrong cell", t.pid)
                self._event(t.pid, "wrong")
                self._lose_hp(t.pid)

    # ------------------------------------------------------------ pairing / start

    def _pair_meeple(self, mac: str) -> None:
        pid = self.pairing
        p = self.players[pid]
        p.meeple = mac
        p.flash_until = self.clock() + PAIRED_FLASH_S
        self.meeples[mac].pid = pid
        self.pairing = None
        self._event(pid, "paired")
        log.info("meeple %s paired with P%d", mac, pid)

    def _start_game(self) -> None:
        self.order = sorted(self.players)
        for p in self.players.values():
            p.hp, p.pos, p.skip = START_HP, START_CELL, False
        self.state, self.winner = "running", None
        log.info("game starts, players %s", self.order)
        self._begin_turn(self.order[0])

    # ------------------------------------------------------------ turn flow

    def _begin_turn(self, pid: int) -> None:
        self.turn = Turn(pid, start=self.players[pid].pos)
        log.info("P%d's turn (cell %d, hp %d)", pid, self.players[pid].pos, self.players[pid].hp)
        self._event(pid, "turn")

    def _roll(self, t: Turn) -> None:
        t.roll = self.rng.randint(1, 4)
        self._event(t.pid, "roll", n=t.roll)
        log.info("P%d rolled %d", t.pid, t.roll)
        self._set_segment(t, "move", roll_path(t.start, t.roll))
        self._on_move(self.cell_of(t.pid))

    def _set_segment(self, t: Turn, phase: str, path: list[int]) -> None:
        t.phase, t.path, t.progress = phase, path, 0
        t.reached_at, t.wrong_cell = None, None
        t.dist = len(path)

    def _on_move(self, cell: int | None) -> None:
        t = self.turn
        if t is None or t.phase == "roll":
            return
        if cell is None:          # lifted or unknown tag: keep guiding with the last distance
            t.reached_at = None
            return
        # Accept the next path cell, or the one after it (a missed read while sliding).
        for j in (t.progress, t.progress + 1):
            if j < len(t.path) and t.path[j] == cell:
                t.progress = j + 1
                break
        on_path = cell == t.start or cell in t.path[:t.progress]  # stepping back is only "colder"
        if t.progress < len(t.path):
            t.dist = abs(cell - t.path[t.progress]) + len(t.path) - t.progress - 1
        else:
            t.dist = abs(cell - t.target)

        if not on_path and cell != t.wrong_cell:
            t.wrong_cell = cell
            self._event(t.pid, "wrong")
        if t.dist == 0 and cell == t.target:
            self._reached(t)
        else:
            t.reached_at = None

    def _reached(self, t: Turn) -> None:
        if t.reached_at is not None:
            return
        pid, cell = t.pid, t.target
        self.players[pid].pos = cell
        nxt = jump(cell) if t.phase == "move" else None
        if nxt:
            ladder = cell in LADDERS
            log.info("P%d %s %d -> %d", pid, "ladder" if ladder else "snake", cell, nxt)
            self._event(pid, "ladder" if ladder else "snake", to=nxt)
            t.start = cell
            self._set_segment(t, "climb" if ladder else "slide", straight_path(cell, nxt))
            if ladder:
                self.players[pid].hp = min(MAX_HP, self.players[pid].hp + 1)
            else:
                self._lose_hp(pid, sound=False)
            return
        self._event(pid, "reached")
        if cell == CELLS:
            self._win(pid)
            return
        t.reached_at = self.clock()  # ladder tops / snake tails never chain, so this ends the turn

    def _lose_hp(self, pid: int, sound: bool = True) -> None:
        p = self.players[pid]
        p.hp = max(0, p.hp - 1)
        if p.hp == 0:
            p.skip = True
            self._event(pid, "hp_zero")
            log.info("P%d has 0 hp, skips the next turn", pid)
        elif sound:
            self._event(pid, "hp_lost")

    def _end_turn(self) -> None:
        t = self.turn
        self._event(t.pid, "turn_end")
        self.players[t.pid].pos = t.target
        i = self.order.index(t.pid)
        for k in range(1, len(self.order) + 1):
            nxt = self.order[(i + k) % len(self.order)]
            p = self.players[nxt]
            if p.skip:
                p.skip, p.hp = False, START_HP
                log.info("P%d skips this turn, back to %d hp", nxt, START_HP)
                continue
            self._begin_turn(nxt)
            return
        self._begin_turn(t.pid)  # everyone else skipped

    def _win(self, pid: int) -> None:
        self.state, self.winner, self.turn = "finished", pid, None
        log.info("P%d wins!", pid)
        for p in self.players.values():
            self._event(p.pid, "win", p=pid)

    def _paused(self) -> bool:
        """The active player's base or meeple is offline (wire-schemas §7)."""
        if not self.turn:
            return False
        p = self.players[self.turn.pid]
        base, meeple = self.bases.get(p.base), self.meeples.get(p.meeple)
        return not (base and base.online and meeple and meeple.online)

    # ------------------------------------------------------------ output

    def _event(self, pid: int, e: str, **extra) -> None:
        base = self.players[pid].base
        self._out.append(Msg(f"{PREFIX}base/{base}/event", _json({"e": e, **extra})))

    def _status(self, mac: str, dev: Device) -> dict:
        p = self.players.get(dev.pid)
        if p is None:
            return {"p": 0, "hp": 0, "cell": None, "roll": None, "target": None, "dist": None,
                    "turn": False, "phase": "unpaired"}
        t = self.turn if self.turn and self.turn.pid == p.pid else None
        if self.pairing == p.pid:
            phase = "pairing"
        elif t:
            phase = t.phase
        elif self.state == "finished":
            phase = "done"
        else:
            phase = "wait"
        return {"p": p.pid, "hp": p.hp, "cell": self.cell_of(p.pid) if p.meeple else None,
                "roll": t.roll if t else None, "target": t.target if t else None,
                "dist": t.dist if t else None, "turn": t is not None, "phase": phase,
                "skip": p.skip}

    def _led(self, dev: Device) -> str:
        if dev.pid == 0:
            return "slow"
        p = self.players[dev.pid]
        if self.clock() < p.flash_until or self.winner == p.pid:
            return "on"
        if self.state == "running" and self.turn and self.turn.pid == p.pid:
            return "fast"
        return "off"

    def _game_state(self) -> dict:
        return {"state": self.state, "players": sorted(self.players) if self.state == "lobby" else self.order,
                "turn": self.turn.pid if self.turn else None, "winner": self.winner,
                "paused": self._paused()}

    def _flush(self) -> list[Msg]:
        for mac, dev in self.bases.items():
            self._retain(f"{PREFIX}base/{mac}/status", _json(self._status(mac, dev)))
        for mac, dev in self.meeples.items():
            self._retain(f"{PREFIX}meeple/{mac}/led", self._led(dev))
        self._retain(PREFIX + "game/state", _json(self._game_state()))
        out, self._out = self._out, []
        return out

    def _retain(self, topic: str, payload: str) -> None:
        if self._published.get(topic) != payload:
            self._published[topic] = payload
            self._out.append(Msg(topic, payload, retain=True))


def _json(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"))


__all__ = ["Game", "Msg", "LADDERS", "SNAKES"]
