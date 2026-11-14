import json
import random

import pytest

from snl.board import roll_path, straight_path
from snl.game import Game
from snl.tags import sim_uid

B1, B2 = "b00000000001", "b00000000002"
M1, M2 = "m00000000001", "m00000000002"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FixedDie(random.Random):
    def __init__(self, rolls):
        super().__init__()
        self.rolls = list(rolls)

    def randint(self, a, b):
        return self.rolls.pop(0)


def make(rolls=()):
    clock = Clock()
    g = Game({sim_uid(c): c for c in range(1, 17)}, rng=FixedDie(rolls), clock=clock)
    g.startup()
    return g, clock


def send(g, topic, payload):
    return g.on_message("snl/" + topic, payload)


def put(g, meeple, cell):
    return send(g, f"meeple/{meeple}/tag", sim_uid(cell) if cell else "-")


def events(msgs, base):
    return [json.loads(m.payload)["e"] for m in msgs if m.topic == f"snl/base/{base}/event"]


def status(g, base):
    return json.loads(g._published[f"snl/base/{base}/status"])


def led(g, meeple):
    return g._published[f"snl/meeple/{meeple}/led"]


def lobby(g, n=2):
    pairs = [(B1, M1), (B2, M2)][:n]
    for b, m in pairs:
        send(g, f"base/{b}/online", "1")
        send(g, f"meeple/{m}/online", "1")
    for b, m in pairs:
        send(g, f"base/{b}/button", "short")
        assert status(g, b)["phase"] == "pairing"
        out = put(g, m, 1)
        assert "paired" in events(out, b)
        assert status(g, b)["phase"] == "wait"


def walk(g, meeple, cells):
    out = []
    for c in cells:
        out += put(g, meeple, c)
    return out


# ---------------------------------------------------------------- board

def test_roll_path_bounces_at_16():
    assert roll_path(14, 4) == [15, 16, 15, 14]
    assert roll_path(1, 3) == [2, 3, 4]
    assert roll_path(15, 1) == [16]


def test_straight_path():
    assert straight_path(3, 6) == [4, 5, 6]
    assert straight_path(14, 11) == [13, 12, 11]


# ---------------------------------------------------------------- pairing / start

def test_pairing_and_start():
    g, _ = make()
    send(g, f"base/{B1}/online", "1")
    send(g, f"meeple/{M1}/online", "1")
    assert status(g, B1)["phase"] == "unpaired"
    assert led(g, M1) == "slow"
    lobby(g, 1)
    assert led(g, M1) == "on"          # paired flash
    send(g, f"base/{B1}/button", "long")
    assert g.state == "lobby"          # 1 player is not enough


def test_only_one_base_pairs_at_a_time():
    g, _ = make()
    for b in (B1, B2):
        send(g, f"base/{b}/online", "1")
    send(g, f"base/{B1}/button", "short")
    send(g, f"base/{B2}/button", "short")
    assert status(g, B2)["phase"] == "unpaired"


def test_game_starts_with_player_1():
    g, clock = make()
    lobby(g)
    clock.t += 1.1                     # pairing flash over
    g.tick()
    out = send(g, f"base/{B2}/button", "long")
    assert g.state == "running"
    assert "turn" in events(out, B1)
    assert status(g, B1)["phase"] == "roll"
    assert led(g, M1) == "fast" and led(g, M2) == "off"


# ---------------------------------------------------------------- a turn

def started(rolls):
    g, clock = make(rolls)
    lobby(g)
    send(g, f"base/{B1}/button", "long")
    return g, clock


def test_roll_move_dwell_end():
    g, clock = started([1])        # 1 -> 2
    out = send(g, f"base/{B1}/button", "short")
    assert ("roll" in events(out, B1))
    s = status(g, B1)
    assert (s["phase"], s["roll"], s["target"], s["dist"]) == ("move", 1, 2, 1)
    out = put(g, M1, 2)
    assert "reached" in events(out, B1)
    assert status(g, B1)["dist"] == 0
    clock.t += 1.9
    assert g.tick() == [] or g.turn.pid == 1
    clock.t += 0.2
    out = g.tick()
    assert "turn_end" in events(out, B1) and "turn" in events(out, B2)
    assert g.turn.pid == 2


def test_hot_cold_distance_counts_down_and_up():
    g, _ = started([3])            # 1 -> 4
    send(g, f"base/{B1}/button", "short")
    assert status(g, B1)["dist"] == 3
    put(g, M1, 2)
    assert status(g, B1)["dist"] == 2
    out = put(g, M1, 1)              # walked back: colder, but no "wrong" beep
    assert status(g, B1)["dist"] == 3 and events(out, B1) == []
    out = put(g, M1, 7)              # off the path: colder + wrong beep
    assert status(g, B1)["dist"] == 5 and events(out, B1) == ["wrong"]


def test_lifting_keeps_distance():
    g, _ = started([2])
    send(g, f"base/{B1}/button", "short")
    put(g, M1, 2)
    put(g, M1, None)
    s = status(g, B1)
    assert s["cell"] is None and s["dist"] == 1


def test_ladder_climb_gives_hp():
    g, clock = started([2])        # 1 -> 3, ladder to 6
    send(g, f"base/{B1}/button", "short")
    out = walk(g, M1, [2, 3])
    assert json.loads([m.payload for m in out if '"ladder"' in m.payload][0])["to"] == 6
    s = status(g, B1)
    assert (s["phase"], s["target"], s["hp"], s["dist"]) == ("climb", 6, 4, 3)
    walk(g, M1, [4, 5, 6])
    assert status(g, B1)["dist"] == 0 and status(g, B1)["phase"] == "climb"   # phase kept until turn end
    clock.t += 2.1
    g.tick()
    assert g.turn.pid == 2 and g.players[1].pos == 6


def test_snake_costs_hp():
    g, clock = started([1, 1, 1])
    g.players[1].pos = 7
    g.turn.start = 7
    put(g, M1, 7)
    send(g, f"base/{B1}/button", "short")       # 7 -> 8, snake to 1
    out = put(g, M1, 8)
    assert "snake" in events(out, B1)
    s = status(g, B1)
    assert (s["phase"], s["target"], s["hp"]) == ("slide", 1, 2)


def test_long_press_on_wrong_cell_costs_hp_and_keeps_turn():
    g, _ = started([3])            # 1 -> 4
    send(g, f"base/{B1}/button", "short")
    put(g, M1, 2)
    out = send(g, f"base/{B1}/button", "long")
    assert events(out, B1) == ["wrong", "hp_lost"]
    assert g.turn.pid == 1 and g.players[1].hp == 2


def test_long_press_on_target_ends_turn():
    g, _ = started([3])
    send(g, f"base/{B1}/button", "short")
    walk(g, M1, [2, 3, 4])
    out = send(g, f"base/{B1}/button", "long")
    assert "turn_end" in events(out, B1) and g.turn.pid == 2


def test_hp_zero_skips_next_turn():
    g, clock = started([3, 1])
    send(g, f"base/{B1}/button", "short")
    for _ in range(3):
        send(g, f"base/{B1}/button", "long")      # 3 wrong long presses: hp 3 -> 0
    assert g.players[1].hp == 0 and g.players[1].skip
    walk(g, M1, [2, 3, 4])
    clock.t += 2.1
    g.tick()                                      # P2's turn
    send(g, f"base/{B2}/button", "short")
    put(g, M2, 2)
    clock.t += 2.1
    g.tick()                                      # P1 skipped -> P2 again
    assert g.turn.pid == 2
    assert g.players[1].hp == 3 and not g.players[1].skip


def test_overshoot_bounces_back_from_16():
    g, _ = started([4])
    g.players[1].pos = g.turn.start = 14
    put(g, M1, 14)
    send(g, f"base/{B1}/button", "short")         # 14 + 4 -> 15, 16, 15, 14
    assert status(g, B1)["target"] == 14 and status(g, B1)["dist"] == 4
    walk(g, M1, [15, 16])
    assert status(g, B1)["dist"] == 2 and g.state == "running"   # passing 16 is no win
    out = walk(g, M1, [15, 14])
    assert "snake" in events(out, B1)                             # 14 is a snake head


def test_reaching_16_wins():
    g, _ = started([2])
    g.players[1].pos = g.turn.start = 14
    put(g, M1, 14)
    send(g, f"base/{B1}/button", "short")
    out = walk(g, M1, [15, 16])
    assert "win" in events(out, B1) and "win" in events(out, B2)
    assert g.state == "finished" and g.winner == 1
    assert led(g, M1) == "on" and status(g, B2)["phase"] == "done"


def test_offline_active_player_pauses():
    g, _ = started([1])
    send(g, f"meeple/{M1}/online", "0")
    send(g, f"base/{B1}/button", "short")
    assert status(g, B1)["phase"] == "roll"       # ignored while paused
    assert json.loads(g._published["snl/game/state"])["paused"]
    send(g, f"meeple/{M1}/online", "1")
    send(g, f"base/{B1}/button", "short")
    assert status(g, B1)["phase"] == "move"


def test_retained_only_published_on_change():
    g, _ = started([1])
    out = send(g, f"base/{B2}/button", "short")   # not P2's turn: nothing changes
    assert out == []


@pytest.mark.parametrize("payload", ["", "garbage"])
def test_bad_payloads_are_ignored(payload):
    g, _ = started([1])
    send(g, f"base/{B1}/button", payload)
    send(g, "nonsense", payload)
    assert status(g, B1)["phase"] == "roll"


def test_long_press_ends_turn_on_ladder_top():
    g, _ = started([2])
    send(g, f"base/{B1}/button", "short")
    walk(g, M1, [2, 3, 4, 5, 6])
    out = send(g, f"base/{B1}/button", "long")
    assert "turn_end" in events(out, B1) and g.turn.pid == 2
