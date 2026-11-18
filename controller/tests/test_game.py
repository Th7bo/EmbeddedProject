import json
import random

import pytest

from snl.board import roll_path, straight_path
from snl.game import Game
from snl.tags import sim_uid

BASE = "b00000000001"
M1, M2, M3 = "m00000000001", "m00000000002", "m00000000003"


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
    send(g, f"base/{BASE}/online", "1")
    return g, clock


def send(g, topic, payload):
    return g.on_message("snl/" + topic, payload)


def press(g, kind="short"):
    return send(g, f"base/{BASE}/button", kind)


def put(g, meeple, cell):
    return send(g, f"meeple/{meeple}/tag", sim_uid(cell) if cell else "-")


def events(msgs, pid=None):
    evs = [json.loads(m.payload) for m in msgs if m.topic == "snl/game/event"]
    return [e["e"] for e in evs if pid is None or e["p"] == pid]


def state(g):
    return json.loads(g._published["snl/game/state"])


def led(g, meeple):
    return g._published[f"snl/meeple/{meeple}/led"]


def join(g, meeple, cell=1):
    press(g)
    pid = state(g)["joining"]
    assert state(g)["phase"] == "pairing"
    out = put(g, meeple, cell)
    assert events(out, pid) == ["joined"]
    assert state(g)["phase"] == "join"
    return pid


def lobby(g, meeples=(M1, M2)):
    for m in meeples:
        send(g, f"meeple/{m}/online", "1")
    return [join(g, m) for m in meeples]


def started(rolls, meeples=(M1, M2)):
    g, clock = make(rolls)
    lobby(g, meeples)
    clock.t += 1.1  # joined flash over
    g.tick()
    press(g, "long")
    return g, clock


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


# ---------------------------------------------------------------- lobby

def test_join_assigns_player_ids_in_order():
    g, _ = make()
    send(g, f"meeple/{M1}/online", "1")
    assert led(g, M1) == "slow" and state(g)["phase"] == "join"
    assert lobby(g, (M1, M2, M3)) == [1, 2, 3]
    assert [p["p"] for p in state(g)["players"]] == [1, 2, 3]
    assert led(g, M1) == "on"          # joined flash


def test_meeple_already_on_board_must_report_a_new_tag():
    g, _ = make()
    send(g, f"meeple/{M1}/online", "1")
    put(g, M1, 1)                      # was lying on the board before anyone pressed
    press(g)
    assert state(g)["phase"] == "pairing"
    put(g, M1, None)
    put(g, M1, 1)                      # lifted and put back: joins
    assert g.meeples[M1].pid == 1


def test_short_press_while_pairing_cancels():
    g, _ = make()
    press(g)
    press(g)
    assert state(g)["phase"] == "join" and g.players == {}


def test_at_most_4_players():
    g, _ = make()
    macs = [f"m0000000000{i}" for i in range(1, 6)]
    for m in macs[:4]:
        send(g, f"meeple/{m}/online", "1")
        join(g, m)
    press(g)
    assert state(g)["phase"] == "join" and len(g.players) == 4


def test_needs_two_players_to_start():
    g, _ = make()
    lobby(g, (M1,))
    press(g, "long")
    assert state(g)["state"] == "lobby"


def test_game_starts_with_player_1():
    g, clock = make()
    lobby(g)
    clock.t += 1.1
    g.tick()
    out = press(g, "long")
    s = state(g)
    assert (s["state"], s["phase"], s["turn"]) == ("running", "roll", 1)
    assert events(out, 1) == ["turn"]
    assert led(g, M1) == "fast" and led(g, M2) == "off"


# ---------------------------------------------------------------- a turn

def test_roll_move_dwell_end():
    g, clock = started([1])        # 1 -> 2
    out = press(g)
    assert events(out, 1) == ["roll"]
    s = state(g)
    assert (s["phase"], s["roll"], s["target"], s["dist"]) == ("move", 1, 2, 1)
    out = put(g, M1, 2)
    assert events(out, 1) == ["reached"]
    assert state(g)["dist"] == 0 and state(g)["cell"] == 2
    clock.t += 1.9
    g.tick()
    assert g.turn.pid == 1
    clock.t += 0.2
    out = g.tick()
    assert events(out) == ["turn_end", "turn"]
    assert state(g)["turn"] == 2 and led(g, M1) == "off" and led(g, M2) == "fast"


def test_hot_cold_distance():
    g, _ = started([3])            # 1 -> 4
    press(g)
    assert state(g)["dist"] == 3
    put(g, M1, 2)
    assert state(g)["dist"] == 2
    out = put(g, M1, 1)            # walked back: colder, no "wrong"
    assert state(g)["dist"] == 3 and events(out) == []
    out = put(g, M1, 7)            # off the path: colder + wrong
    assert state(g)["dist"] == 5 and events(out) == ["wrong"]


def test_lifting_keeps_distance():
    g, _ = started([2])
    press(g)
    put(g, M1, 2)
    put(g, M1, None)
    s = state(g)
    assert s["cell"] is None and s["dist"] == 1


def test_other_meeples_moving_do_not_count():
    g, _ = started([2])
    press(g)
    put(g, M2, 3)
    assert state(g)["dist"] == 2 and g.turn.progress == 0


def test_ladder_climb_gives_hp():
    g, clock = started([2])        # 1 -> 3, ladder to 6
    press(g)
    out = walk(g, M1, [2, 3])
    assert "ladder" in events(out, 1)
    s = state(g)
    assert (s["phase"], s["target"], s["dist"]) == ("climb", 6, 3)
    assert s["players"][0]["hp"] == 4
    walk(g, M1, [4, 5, 6])
    assert state(g)["dist"] == 0 and state(g)["phase"] == "climb"
    clock.t += 2.1
    g.tick()
    assert g.turn.pid == 2 and g.players[1].pos == 6


def test_snake_costs_hp():
    g, _ = started([1])
    g.players[1].pos = g.turn.start = 7
    put(g, M1, 7)
    press(g)                       # 7 -> 8, snake to 1
    out = put(g, M1, 8)
    assert events(out, 1) == ["snake"]
    s = state(g)
    assert (s["phase"], s["target"], s["players"][0]["hp"]) == ("slide", 1, 2)


def test_long_press_on_wrong_cell_costs_hp_and_keeps_turn():
    g, _ = started([3])
    press(g)
    put(g, M1, 2)
    out = press(g, "long")
    assert events(out, 1) == ["wrong", "hp_lost"]
    assert g.turn.pid == 1 and g.players[1].hp == 2


def test_long_press_on_target_ends_turn():
    g, _ = started([3])
    press(g)
    walk(g, M1, [2, 3, 4])
    out = press(g, "long")
    assert "turn_end" in events(out, 1) and g.turn.pid == 2


def test_long_press_ends_turn_on_ladder_top():
    g, _ = started([2])
    press(g)
    walk(g, M1, [2, 3, 4, 5, 6])
    out = press(g, "long")
    assert "turn_end" in events(out, 1) and g.turn.pid == 2


def test_hp_zero_ends_the_turn_and_skips_the_next():
    g, clock = started([3, 1])
    press(g)                       # 1 -> 4
    press(g, "long")
    press(g, "long")               # hp 3 -> 1, turn still open
    assert g.turn.pid == 1
    out = press(g, "long")         # hp 0: turn over right away
    assert events(out, 1) == ["wrong", "hp_zero", "turn_end"]
    assert g.players[1].hp == 0 and state(g)["players"][0]["skip"]
    assert g.turn.pid == 2 and g.players[1].pos == 4   # counts as on its target
    press(g)
    put(g, M2, 2)
    clock.t += 2.1
    g.tick()                       # P1 skipped -> P2 again
    assert g.turn.pid == 2
    assert g.players[1].hp == 3 and not g.players[1].skip


def test_overshoot_bounces_back_from_16():
    g, _ = started([4])
    g.players[1].pos = g.turn.start = 14
    put(g, M1, 14)
    press(g)                       # 14 + 4 -> 15, 16, 15, 14
    assert state(g)["target"] == 14 and state(g)["dist"] == 4
    walk(g, M1, [15, 16])
    assert state(g)["dist"] == 2 and state(g)["state"] == "running"   # passing 16 is no win
    out = walk(g, M1, [15, 14])
    assert "snake" in events(out, 1)                                   # 14 is a snake head


def test_reaching_16_wins_and_long_press_goes_back_to_the_lobby():
    g, _ = started([2, 1])
    g.players[1].pos = g.turn.start = 14
    put(g, M1, 14)
    press(g)
    out = walk(g, M1, [15, 16])
    assert events(out, 1) == ["reached", "win"]
    s = state(g)
    assert (s["state"], s["phase"], s["winner"]) == ("finished", "over", 1)
    assert led(g, M1) == "on"
    press(g, "long")
    s = state(g)
    assert (s["state"], s["phase"], s["players"], s["winner"]) == ("lobby", "join", [], None)
    assert led(g, M1) == "slow" and led(g, M2) == "slow"     # both can join again
    put(g, M2, None)
    assert join(g, M2) == 1                                  # first to join is P1 again

def test_positions_come_from_the_rules_not_the_tags():
    g, clock = started([2])
    press(g)
    walk(g, M1, [2, 3, 4, 5, 6])                  # 1 -> 3, ladder to 6
    put(g, M1, None)                              # meeple off the board after the turn
    clock.t += 2.1
    g.tick()
    assert [p["cell"] for p in state(g)["players"]] == [6, 1]   # M2 never on the board


def test_lifting_after_reaching_still_ends_the_turn():
    g, clock = started([1])
    press(g)
    put(g, M1, 2)
    put(g, M1, None)                              # lifted right away
    clock.t += 2.1
    g.tick()
    assert g.turn.pid == 2


def test_long_press_after_lifting_from_target_ends_turn_without_penalty():
    g, _ = started([1])
    press(g)
    put(g, M1, 2)
    put(g, M1, None)
    out = press(g, "long")
    assert events(out, 1) == ["turn_end"] and g.players[1].hp == 3


def test_unknown_tags_are_cached_in_scan_order_with_led_flash():
    g, clock = make()
    send(g, f"meeple/{M1}/online", "1")
    for uid in ("04AA0001", "04AA0002", "04AA0001", "04AA0003"):   # 0001 scanned twice
        send(g, f"meeple/{M1}/tag", uid)
        send(g, f"meeple/{M1}/tag", "-")
    assert g.snapshot()["scanned"] == ["04AA0001", "04AA0002", "04AA0003"]
    send(g, f"meeple/{M1}/tag", "04AA0004")
    assert led(g, M1) == "on"                      # "got it" flash at the board
    clock.t += 0.7
    g.tick()
    assert led(g, M1) == "slow"
    g.set_tag("04AA0002", 2)
    assert g.snapshot()["scanned"] == ["04AA0001", "04AA0003", "04AA0004"]
    g.clear_scanned()
    assert g.snapshot()["scanned"] == []


def test_meeple_going_offline_in_the_lobby_leaves():
    g, _ = make()
    lobby(g, (M1, M2))
    send(g, f"meeple/{M1}/online", "0")
    assert [p["p"] for p in state(g)["players"]] == [2]
    send(g, f"meeple/{M1}/online", "1")
    put(g, M1, None)
    assert join(g, M1) == 1                       # its slot is free again


def test_long_press_removes_the_offline_active_player():
    g, _ = started([1], meeples=(M1, M2, M3))
    send(g, f"meeple/{M1}/online", "0")
    assert state(g)["paused"]
    out = press(g, "long")
    s = state(g)
    assert [p["p"] for p in s["players"]] == [2, 3] and s["turn"] == 2 and not s["paused"]
    assert events(out) == ["turn"]


def test_removing_down_to_one_player_goes_back_to_the_lobby():
    g, _ = started([1])
    send(g, f"meeple/{M1}/online", "0")
    press(g, "long")
    s = state(g)
    assert (s["state"], s["players"]) == ("lobby", [])
