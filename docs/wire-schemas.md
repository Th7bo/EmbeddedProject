# Wire Schemas — Snakes & Ladders: Hot or Cold

MQTT contract between the rules controller (PC), the control bases (ESP32) and the meeples (ESP-01).
Source of truth for the game rules: `Project_1st_FollowUp_Updated.docx` / the slides. (`info.md` is an older draft.)

## 1. System

```
 Meeple (ESP-01 + PN532, LED, USB pwr) ──┐
 Meeple ...                               │   Wi-Fi (dedicated router / hotspot)
 Control base (ESP32: LCD, button,     ───┼──►  PC: Mosquitto broker + Python rules controller
               buzzer, LED)               │
 Control base ...                       ──┘
```

- Devices never talk to each other. All traffic goes through the broker; the controller decides everything.
- One meeple + one control base per player, 2–4 players.
- Meeples are powered by a USB to ESP-01 adapter (powerbank) and not wired to anything else.

## 2. Conventions

| Item | Rule |
| --- | --- |
| Topic prefix | `snl/` |
| Device id | Wi-Fi STA MAC, lowercase hex, no separators: `a4cf12b3c4d5` |
| MQTT client id | `snl-meeple-<mac>`, `snl-base-<mac>`, `snl-ctrl` |
| Player id | `1`–`4`, assigned by the controller (see §5). `0` = unassigned |
| Meeple payloads | Plain ASCII text. No JSON on the ESP-01 (small RAM, PubSubClient 256-byte packet limit) |
| Base payloads | Compact JSON with short keys (ESP32 + ArduinoJson handles it easily) |
| Keepalive | 5 s on all devices, so a dead device is noticed in about 7.5 s |
| Clean session | `true`. Devices rely on retained messages to get their state back after reconnecting |

**Retained vs not retained:** anything that describes *current state* is retained, so a device that reconnects (or the controller after a restart) gets it immediately. Anything that is a *one-off event* (a button press, a sound) is **not** retained, otherwise it would replay on reconnect.

**QoS:** PubSubClient (ESP-01) can only *publish* with QoS 0. Device→controller messages are therefore QoS 0. That is fine on a local network, and the retained state topics cover the rest. Controller→device messages use QoS 1.

## 3. Topic table

| Topic | Direction | Payload | Retained | QoS |
| --- | --- | --- | --- | --- |
| `snl/meeple/<mac>/online` | meeple → ctrl | `1` on connect, `0` as Last Will | yes | 0 |
| `snl/meeple/<mac>/tag` | meeple → ctrl | tag UID or `-` | yes | 0 |
| `snl/meeple/<mac>/batt` | meeple → ctrl | supply voltage in mV, e.g. `3712` | yes | 0 |
| `snl/meeple/<mac>/led` | ctrl → meeple | `off` \| `on` \| `slow` \| `fast` | yes | 1 |
| `snl/base/<mac>/online` | base → ctrl | `1` on connect, `0` as Last Will | yes | 0 |
| `snl/base/<mac>/button` | base → ctrl | `short` \| `long` | no | 0 |
| `snl/base/<mac>/status` | ctrl → base | JSON, see §4.2 | yes | 1 |
| `snl/base/<mac>/event` | ctrl → base | JSON, see §4.3 | no | 1 |
| `snl/game/state` | ctrl → all bases | JSON, see §4.4 | yes | 1 |
| `snl/ctrl/online` | ctrl → all | `1` on connect, `0` as Last Will | yes | 1 |

Subscriptions:

- **Meeple:** `snl/meeple/<own mac>/led`, `snl/ctrl/online`
- **Base:** `snl/base/<own mac>/status`, `snl/base/<own mac>/event`, `snl/game/state`, `snl/ctrl/online`
- **Controller:** `snl/meeple/+/+`, `snl/base/+/+`

## 4. Payloads

### 4.1 Meeple (ESP-01)

**`tag`**: the UID of the tag currently under the meeple, uppercase hex with no separators (`04A1B2C3D4E5F6`). That is 8, 14 or 20 characters for 4-, 7- or 10-byte UIDs. `-` means no tag (the meeple was lifted or is between cells).

- Publish **only on change**: a new UID, or a UID turning into `-`.
- **Removal debounce:** the PN532 occasionally misses a read, so only publish `-` after the tag has been missing for about 300 ms (for example 3 missed polls at 100 ms). A new UID is published as soon as it is read.
- Re-publish the current value right after every (re)connect.
- The meeple sends the raw UID. The controller maps UID → cell (1–16) with the WP4 table. An unknown UID is treated as "not a cell".

**`batt`**: optional. Read with `ADC_MODE(ADC_VCC)` / `ESP.getVcc()`. Publish on connect and then every 60 s.

**`led`**:

| Value | Meaning | Used for |
| --- | --- | --- |
| `off` | LED off | default |
| `on` | solid on | pairing confirmed, winner |
| `slow` | blink, about 1 Hz | waiting to be paired |
| `fast` | blink, about 4 Hz | it is this player's turn |

When `snl/ctrl/online` is `0`, the meeple turns its LED off.

### 4.2 Base status (`snl/base/<mac>/status`)

This is the complete state the LCD needs. It is re-sent whenever any field changes, and the base draws the screen from it.

```json
{"p":2,"hp":3,"cell":5,"roll":3,"target":8,"dist":2,"turn":true,"phase":"move"}
```

| Key | Type | Meaning |
| --- | --- | --- |
| `p` | int | player id of this base, `0` = unassigned |
| `hp` | int 0–5 | health |
| `cell` | int 1–16 \| null | cell the meeple is on now, `null` = no tag / unknown tag |
| `roll` | int 1–4 \| null | last roll in this turn |
| `target` | int 1–16 \| null | cell the meeple has to reach |
| `dist` | int \| null | **remaining steps along the path** to `target` (counts the bounce at 16, e.g. 14 → roll 4 → path 15, 16, 15, 14). `null` when there is nothing to walk to |
| `turn` | bool | it is this player's turn |
| `phase` | string | see below |
| `skip` | bool, optional | the player will miss the next turn (health reached 0) |

`phase`, which decides the LCD text:

| Phase | LCD |
| --- | --- |
| `unpaired` | "Press button to join" |
| `pairing` | "Place your meeple on the board" |
| `wait` | "Waiting — Player N's turn" |
| `roll` | "Your turn – press to roll" |
| `move` | roll, current cell, target, remaining cells |
| `slide` | "Snake! go to X" / `move` with the new target |
| `climb` | "Ladder! go to X" |
| `done` | turn finished, waiting for the next turn |

**Hot/cold beeps are generated locally from `dist`** while `phase` is `move`, `slide` or `climb` and `turn` is true: `4 → 800 ms`, `3 → 500 ms`, `2 → 250 ms`, `1 → 100 ms`, `0 → silent` (the "reached" sound comes as an event). With `dist` `null` the base stays silent. This way the controller never streams beeps over the network.

### 4.3 Base event (`snl/base/<mac>/event`)

One-off sounds and LCD flashes. Never retained.

```json
{"e":"roll","n":3}
```

| `e` | Extra keys | Sound (from the docx table) |
| --- | --- | --- |
| `turn` | — | 2 short high beeps |
| `roll` | `n`: roll value | `n` short beeps |
| `reached` | — | 1 long tone (1 s) |
| `wrong` | — | 3 short low beeps |
| `ladder` | `to`: cell | rising 3-note melody |
| `snake` | `to`: cell | falling 3-note melody |
| `hp_lost` | — | 1 long low tone |
| `hp_zero` | — | long descending tone |
| `turn_end` | — | 1 short beep |
| `paired` | — | confirmation beep |
| `win` | `p`: winner id | victory melody (sent to every base) |

### 4.4 Game state (`snl/game/state`)

```json
{"state":"running","players":[1,2,3],"turn":2,"winner":null,"paused":false}
```

| Key | Type | Meaning |
| --- | --- | --- |
| `state` | `"lobby"` \| `"running"` \| `"finished"` | |
| `players` | int[] | joined player ids, in turn order |
| `turn` | int \| null | active player |
| `winner` | int \| null | set when `state` is `finished` |
| `paused` | bool | the active player's base or meeple is offline (§7) |

This replaces `game/turn` and `game/state` from the follow-up doc. Meeples don't subscribe to it: the controller drives their LEDs directly, which keeps the ESP-01 side minimal.

## 5. Joining (MAC → player id)

The controller keeps `mac → player id` for bases and meeples. Because the mapping is keyed by MAC, a device that drops and reconnects mid-game gets its player back automatically.

1. Every device connects and publishes `online = 1`. Unassigned bases get `phase: "unpaired"`, unassigned meeples get `led = slow`.
2. A player short-presses an unassigned base. The controller gives it the **next free player id** and sets `phase: "pairing"`.
3. While a base is pairing, the **first unassigned meeple that reports a tag** is linked to the same player id. That meeple gets `led = on` (and `off` after about 1 s), and the base gets the event `paired` and `phase: "wait"`.
4. Only one base can be pairing at a time. Other presses are ignored until step 3 is done.
5. When at least 2 players are paired, a **long press on any paired base** starts the game: `state: "running"`, and turn order = player id order.

## 6. A turn on the wire

```
ctrl  → game/state         {"state":"running","turn":2,...}
ctrl  → meeple(P2)/led     fast
ctrl  → base(P2)/event     {"e":"turn"}
ctrl  → base(P2)/status    {"p":2,"phase":"roll","turn":true,...}
base  → base(P2)/button    short
ctrl  → base(P2)/event     {"e":"roll","n":3}
ctrl  → base(P2)/status    {"phase":"move","roll":3,"cell":5,"target":8,"dist":3,...}
meeple→ meeple(P2)/tag     -
meeple→ meeple(P2)/tag     04A1...        (cell 6)
ctrl  → base(P2)/status    {"cell":6,"dist":2,...}            base beeps every 250 ms
  ...                                                          (cell 8)
ctrl  → base(P2)/status    {"cell":8,"dist":0,...}
ctrl  → base(P2)/event     {"e":"reached"}
  — meeple stays on cell 8 for 2 s, or the player long-presses —
ctrl  → base(P2)/event     {"e":"turn_end"}
ctrl  → meeple(P2)/led     off
ctrl  → game/state         {"turn":3,...}
```

If the target is a ladder foot or a snake head, the controller sends `ladder`/`snake` with `to`, sets the new `target`, and the walk repeats with `phase: "climb"`/`"slide"`.

If the turn is ended with a long press while `cell != target`, the controller sends `wrong` + `hp_lost`, and the turn stays open until the meeple is on the right cell.

## 7. Failure handling

- **Meeple or base offline** (`online = 0`): the controller pauses the game if it belongs to the active player and resumes when it comes back. On reconnect it gets its retained `led`/`status`, and the meeple re-publishes `tag`.
- **Controller offline** (`snl/ctrl/online = 0`): bases show "Controller offline", meeples turn their LED off. On restart the controller rebuilds positions from the retained `tag` topics.
- **Stale retained data:** the controller ignores `tag`/`batt` from a MAC whose `online` is `0`.

## 8. Quick test with mosquitto

```sh
mosquitto_sub -h <pc> -t 'snl/#' -v                                    # watch everything
mosquitto_pub -h <pc> -t snl/meeple/a4cf12b3c4d5/online -m 1 -r        # fake meeple joins
mosquitto_pub -h <pc> -t snl/meeple/a4cf12b3c4d5/tag -m 04A1B2C3 -r    # fake tag read
mosquitto_pub -h <pc> -t snl/base/a4cf12b3c4d6/button -m short         # fake button press
```
