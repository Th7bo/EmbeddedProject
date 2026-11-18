"""Rules engine. Pure: MQTT messages in, MQTT messages out, no network code.

Contract: docs/wire-schemas.md. Rules: docs/Project_1st_FollowUp_Updated.docx.

One shared control base serves every player; each player has a meeple.
Retained topics (game state, meeple LEDs) are *derived* from the game state after
every input and only published when they change. One-off events (sounds) are
queued explicitly.
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
T_STATE = PREFIX + "game/state"
T_EVENT = PREFIX + "game/event"
START_CELL = 1
START_HP = 3
MAX_HP = 5
MAX_PLAYERS = 4
DWELL_S = 2.0          # meeple must stay on the target this long to end the turn
JOINED_FLASH_S = 1.0   # meeple LED solid after joining


class Msg(NamedTuple):
    topic: str
    payload: str
    retain: bool = False
    qos: int = 1


@dataclass
class Meeple:
    online: bool = False
    pid: int = 0
    tag: str = "-"
    batt: int | None = None  # supply voltage in mV
    flash_until: float = 0.0  # LED solid until then (tag scanned for mapping)


@dataclass
class Player:
    pid: int
    meeple: str = ""       # mac, "" while joining
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
        self.bases: dict[str, bool] = {}       # mac -> online
        self.meeples: dict[str, Meeple] = {}
        self.players: dict[int, Player] = {}
        self.state = "lobby"                   # lobby | running | finished
        self.turn: Turn | None = None
        self.winner: int | None = None
        self.joining: int | None = None        # pid waiting for its meeple
        self.scanned: list[str] = []           # unknown tags read so far, in order (for mapping the board)
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
        """Call regularly (~10 Hz): timers for the dwell and the joined flash."""
        t = self.turn
        if (self.state == "running" and t and t.reached_at is not None and not self._paused()
                and self.clock() - t.reached_at >= DWELL_S):
            log.info("P%d stayed on %d, turn ends", t.pid, t.target)
            self._end_turn()
        return self._flush()

    def set_tag(self, uid: str, cell: int) -> list[Msg]:
        """Map a tag to a cell at runtime (dashboard). A cell has one tag: the old one is dropped."""
        uid = uid.upper()
        self.tags = {u: c for u, c in self.tags.items() if c != cell or u.startswith("5100")} | {uid: cell}
        self.scanned = [u for u in self.scanned if u != uid]
        log.info("tag %s is cell %d", uid, cell)
        return self._flush()

    def clear_scanned(self) -> list[Msg]:
        self.scanned = []
        return self._flush()

    def press(self, kind: str) -> list[Msg]:
        """A button press that doesn't come from a base (the dashboard on the PC)."""
        if kind == "short":
            self._short_press()
        elif kind == "long":
            self._long_press()
        return self._flush()

    def snapshot(self) -> dict:
        """Everything the dashboard shows: the base's game state plus devices and the board."""
        t = self.turn
        return {**self._game_state(),
                "path": t.path if t else [], "progress": t.progress if t else 0, "start": t.start if t else None,
                "meeples": [{"mac": mac, "p": m.pid, "online": m.online, "tag": m.tag, "batt": m.batt,
                             "cell": self.tags.get(m.tag) if m.tag != "-" else None,
                             "known": m.tag == "-" or m.tag in self.tags}
                            for mac, m in sorted(self.meeples.items())],
                "bases": [{"mac": mac, "online": on} for mac, on in sorted(self.bases.items())],
                "scanned": self.scanned,
                "ladders": LADDERS, "snakes": SNAKES}

    def cell_of(self, pid: int) -> int | None:
        m = self.meeples.get(self.players[pid].meeple)
        return self.tags.get(m.tag) if m and m.tag != "-" else None

    # ------------------------------------------------------------ inputs

    def _on_meeple(self, mac: str, what: str, payload: str) -> None:
        m = self.meeples.setdefault(mac, Meeple())
        if what == "online":
            m.online = payload == "1"
            log.info("meeple %s %s", mac, "online" if m.online else "offline")
            if not m.online and m.pid and self.state == "lobby":
                log.info("P%d left the lobby (meeple offline)", m.pid)
                del self.players[m.pid]
                m.pid = 0
        elif what == "batt":
            m.batt = int(payload) if payload.strip().isdigit() else None
        elif what == "tag":
            old, m.tag = m.tag, payload.strip().upper() or "-"
            if not m.online or m.tag == old:
                return
            if m.tag != "-" and m.tag not in self.tags:
                log.warning("unknown tag %s on meeple %s", m.tag, mac)
                if m.tag not in self.scanned:
                    self.scanned.append(m.tag)
                    m.flash_until = self.clock() + 0.6  # "got it" at the board, no laptop needed
            if m.pid == 0:
                if self.joining and m.tag != "-":
                    self._join_meeple(mac)
            elif self.turn and self.turn.pid == m.pid and not self._paused():
                self._on_move(self.cell_of(m.pid))

    def _on_base(self, mac: str, what: str, payload: str) -> None:
        if what == "online":
            self.bases[mac] = payload == "1"
            log.info("base %s %s", mac, "online" if self.bases[mac] else "offline")
        elif what == "button" and self.bases.get(mac):
            if payload == "short":
                self._short_press()
            elif payload == "long":
                self._long_press()

    def _short_press(self) -> None:
        if self.state == "lobby":
            if self.joining:
                log.info("joining P%d cancelled", self.joining)
                del self.players[self.joining]
                self.joining = None
            elif len(self.players) < MAX_PLAYERS:
                pid = min(set(range(1, MAX_PLAYERS + 1)) - set(self.players))
                self.players[pid] = Player(pid)
                self.joining = pid
                log.info("P%d joining, waiting for a meeple", pid)
            return
        t = self.turn
        if self.state == "running" and t and t.phase == "roll" and not self._paused():
            self._roll(t)

    def _long_press(self) -> None:
        if self.state == "lobby" and self.joining is None and len(self.players) >= 2:
            self._start_game()
        elif self.state == "finished":
            self._to_lobby()
        elif self.state == "running" and self.turn and self._meeple_offline():
            self._remove_player(self.turn.pid)
        elif self.state == "running" and self.turn and not self._paused():
            t = self.turn
            if t.phase == "roll":
                return
            if t.reached_at is not None:  # target reached (the meeple may already be lifted)
                self._end_turn()
            else:
                log.info("P%d ended the turn on the wrong cell", t.pid)
                self._event(t.pid, "wrong")
                self._lose_hp(t.pid)

    # ------------------------------------------------------------ lobby

    def _join_meeple(self, mac: str) -> None:
        pid = self.joining
        p = self.players[pid]
        p.meeple = mac
        p.flash_until = self.clock() + JOINED_FLASH_S
        self.meeples[mac].pid = pid
        self.joining = None
        self._event(pid, "joined")
        log.info("meeple %s is P%d", mac, pid)

    def _to_lobby(self) -> None:
        """After a game: back to adding players; everyone joins again."""
        for m in self.meeples.values():
            m.pid = 0
        self.players, self.state, self.turn, self.winner, self.joining = {}, "lobby", None, None, None
        log.info("back to the lobby")

    def _start_game(self) -> None:
        for p in self.players.values():
            p.hp, p.pos, p.skip = START_HP, START_CELL, False
        # Meeples come off the board after every turn, so positions are kept here, not read
        # from the tags: everyone is on the start cell again, whatever the meeples read now.
        self.state, self.winner, self.turn = "running", None, None
        log.info("game starts, players %s", sorted(self.players))
        self._begin_turn(min(self.players))

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
        if cell is None:  # lifted or unknown tag: keep guiding with the last distance. Lifting
            return        # after reaching the target is normal (meeples leave the board after a turn).
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
            log.info("P%d has 0 hp: turn over, skips the next one", pid)
            if self.turn and self.turn.pid == pid:
                self._end_turn()  # the meeple counts as on its target; no endless penalty loop
        elif sound:
            self._event(pid, "hp_lost")

    def _end_turn(self) -> None:
        t = self.turn
        self._event(t.pid, "turn_end")
        self.players[t.pid].pos = t.target
        self._next_turn(t.pid)

    def _next_turn(self, after: int) -> None:
        """Start the turn of the first player after `after` (by id) that doesn't have to skip."""
        order = sorted(set(self.players) | {after})
        i = order.index(after)
        for k in range(1, len(order) + 1):
            nxt = order[(i + k) % len(order)]
            p = self.players.get(nxt)
            if p is None:
                continue
            if p.skip:
                p.skip, p.hp = False, START_HP
                log.info("P%d skips this turn, back to %d hp", nxt, START_HP)
                continue
            self._begin_turn(nxt)
            return
        self._begin_turn(after)  # everyone else skipped

    def _remove_player(self, pid: int) -> None:
        """Active player's meeple is gone (no power): drop the player, the others play on."""
        log.info("P%d removed (meeple offline)", pid)
        m = self.meeples.get(self.players[pid].meeple)
        if m:
            m.pid = 0
        del self.players[pid]
        self.turn = None
        if len(self.players) < 2:
            log.info("fewer than 2 players left, back to the lobby")
            self._to_lobby()
        else:
            self._next_turn(pid)

    def _win(self, pid: int) -> None:
        self.state, self.winner, self.turn = "finished", pid, None
        log.info("P%d wins!", pid)
        self._event(pid, "win")

    def _meeple_offline(self) -> bool:
        m = self.turn and self.meeples.get(self.players[self.turn.pid].meeple)
        return bool(self.turn) and not (m and m.online)

    def _paused(self) -> bool:
        """The active meeple or every base is offline (wire-schemas §7)."""
        if not self.turn:
            return False
        m = self.meeples.get(self.players[self.turn.pid].meeple)
        return not (m and m.online and any(self.bases.values()))

    # ------------------------------------------------------------ output

    def _event(self, pid: int, e: str, **extra) -> None:
        self._out.append(Msg(T_EVENT, _json({"e": e, "p": pid, **extra})))

    def _phase(self) -> str:
        if self.state == "finished":
            return "over"
        if self.state == "lobby":
            return "pairing" if self.joining else "join"
        return self.turn.phase

    def _game_state(self) -> dict:
        t = self.turn
        def where(p):
            live = self.cell_of(p.pid) if t and t.pid == p.pid and p.meeple else None
            return live if live is not None else p.pos
        players = [{"p": p.pid, "hp": p.hp, "cell": where(p),
                    "skip": p.skip, "on": bool(p.meeple and self.meeples[p.meeple].online)}
                   for p in sorted(self.players.values(), key=lambda p: p.pid) if p.meeple]
        return {"state": self.state, "phase": self._phase(), "turn": t.pid if t else None,
                "roll": t.roll if t else None, "target": t.target if t else None,
                "dist": t.dist if t else None, "cell": self.cell_of(t.pid) if t else None,
                "joining": self.joining, "winner": self.winner, "paused": self._paused(),
                "players": players}

    def _led(self, m: Meeple) -> str:
        if m.pid == 0:
            return "on" if self.clock() < m.flash_until else "slow"
        p = self.players[m.pid]
        if self.clock() < p.flash_until or self.winner == p.pid:
            return "on"
        if self.state == "running" and self.turn and self.turn.pid == p.pid:
            return "fast"
        return "off"

    def _flush(self) -> list[Msg]:
        for mac, m in self.meeples.items():
            self._retain(f"{PREFIX}meeple/{mac}/led", self._led(m))
        self._retain(T_STATE, _json(self._game_state()))
        out, self._out = self._out, []
        return out

    def _retain(self, topic: str, payload: str) -> None:
        if self._published.get(topic) != payload:
            self._published[topic] = payload
            self._out.append(Msg(topic, payload, retain=True))


def _json(d: dict) -> str:
    return json.dumps(d, separators=(",", ":"))
