# Wire Schemas — Snakes & Ladders: Hot or Cold

MQTT contract between the rules controller (PC), the control base (ESP32) and the meeples (ESP-01).
Source of truth for the game rules: `Project_1st_FollowUp_Updated.docx` / the slides. (`info.md` is an older draft.)

## 1. System

```
 Meeple P1 (ESP-01 + PN532, LED) ──┐
 Meeple P2 ...                     │   Wi-Fi (laptop hotspot / router)
 Meeple P3 ...                     ├──►  PC: Mosquitto broker + Python rules controller
 Meeple P4 ...                     │
 Control base (ESP32: 128x64 LCD, ─┘
   button, buzzer, LED)
```

- **One shared control base** for the whole table, plus one meeple per player, 2–4 players.
- Devices never talk to each other. All traffic goes through the broker; the controller decides everything.
- The base serves whoever's turn it is: the LCD names the active player, the button rolls and ends turns for them.
- More than one base may be online (e.g. a spare): they all show the same screen and every button counts.
- Meeples are powered by a USB to ESP-01 adapter (powerbank) and not wired to anything else.

## 2. Conventions

| Item | Rule |
| --- | --- |
| Topic prefix | `snl/` |
| Device id | Wi-Fi STA MAC, lowercase hex, no separators: `a4cf12b3c4d5` |
| MQTT client id | `snl-meeple-<mac>`, `snl-base-<mac>`, `snl-ctrl` |
| Player id | `1`–`4`, assigned by the controller when a meeple joins (§5) |
| Meeple payloads | Plain ASCII text. No JSON on the ESP-01 (small RAM, PubSubClient 256-byte packet limit) |
| Base payloads | Compact JSON with short keys (ESP32 + ArduinoJson) |
| Keepalive | 5 s on all devices, so a dead device is noticed in about 7.5 s |
| Clean session | `true`. Devices rely on retained messages to get their state back after reconnecting |

**Retained vs not retained:** anything that describes *current state* is retained, so a device that reconnects (or the controller after a restart) gets it immediately. Anything that is a *one-off event* (a button press, a sound) is **not** retained, otherwise it would replay on reconnect.

**QoS:** PubSubClient can only *publish* with QoS 0, so device→controller messages are QoS 0. Fine on a local network; the retained state topics cover the rest. Controller→device messages use QoS 1.

## 3. Topic table

| Topic | Direction | Payload | Retained | QoS |
| --- | --- | --- | --- | --- |
| `snl/meeple/<mac>/online` | meeple → ctrl | `1` on connect, `0` as Last Will | yes | 0 |
| `snl/meeple/<mac>/tag` | meeple → ctrl | tag UID or `-` | yes | 0 |
| `snl/meeple/<mac>/led` | ctrl → meeple | `off` \| `on` \| `slow` \| `fast` | yes | 1 |
| `snl/base/<mac>/online` | base → ctrl | `1` on connect, `0` as Last Will | yes | 0 |
| `snl/base/<mac>/button` | base → ctrl | `short` \| `long` | no | 0 |
| `snl/game/state` | ctrl → bases | JSON, see §4.2 — everything the LCD shows | yes | 1 |
| `snl/game/event` | ctrl → bases | JSON, see §4.3 — sounds | no | 1 |
| `snl/ctrl/online` | ctrl → all | `1` on connect, `0` as Last Will | yes | 1 |

Subscriptions:

- **Meeple:** `snl/meeple/<own mac>/led`, `snl/ctrl/online`
- **Base:** `snl/game/state`, `snl/game/event`, `snl/ctrl/online`
- **Controller:** `snl/meeple/+/+`, `snl/base/+/+`

## 4. Payloads

### 4.1 Meeple (ESP-01)

**`tag`**: the UID of the tag currently under the meeple, uppercase hex with no separators (`04A1B2C3D4E5F6`). That is 8, 14 or 20 characters for 4-, 7- or 10-byte UIDs. `-` means no tag (the meeple was lifted or is between cells).

- Publish **only on change**: a new UID, or a UID turning into `-`.
- **Removal debounce:** the PN532 occasionally misses a read, so `-` is only published after about 300 ms without a read (3 missed polls of 100 ms). A new UID is published at once.
- Re-publish the current value right after every (re)connect.
- The meeple sends the raw UID. The controller maps UID → cell (1–16) with `controller/tags.toml`. An unknown UID is treated as "not a cell".

**`led`**:

| Value | Meaning | Used for |
| --- | --- | --- |
| `off` | LED off | default |
| `on` | solid on | just joined (1 s), winner |
| `slow` | blink, about 1 Hz | not in the game yet (shows which meeples can still join) |
| `fast` | blink, about 4 Hz | it is this player's turn |

When `snl/ctrl/online` is `0`, the meeple turns its LED off.

### 4.2 Game state (`snl/game/state`)

The complete state the base needs, re-published whenever any field changes. The base draws its screen from it and generates the hot/cold beeps from `dist`.

```json
{"state":"running","phase":"move","turn":2,"roll":3,"target":8,"dist":2,"cell":6,
 "joining":null,"winner":null,"paused":false,
 "players":[{"p":1,"hp":3,"cell":5,"skip":false,"on":true},{"p":2,"hp":4,"cell":6,"skip":false,"on":true}]}
```

| Key | Type | Meaning |
| --- | --- | --- |
| `state` | `"lobby"` \| `"running"` \| `"finished"` | |
| `phase` | string | see below |
| `turn` | int \| null | active player |
| `roll` | int 1–4 \| null | die value of this turn |
| `target` | int 1–16 \| null | cell the active meeple has to reach now |
| `dist` | int \| null | **remaining steps along the path** to `target`, counting the bounce at 16 (14 → roll 4 → path 15, 16, 15, 14). `null` when there is nothing to walk to |
| `cell` | int \| null | cell the active meeple is on now, `null` = lifted / unknown tag |
| `joining` | int \| null | player id waiting for its meeple (lobby only) |
| `winner` | int \| null | set when `state` is `finished` |
| `paused` | bool | the active meeple or every base is offline (§7) |
| `players` | array | joined players in turn order: `p` id, `hp` 0–5, `cell` (null = unknown), `skip` (misses its next turn), `on` (meeple online) |

`phase`:

| Phase | State | LCD |
| --- | --- | --- |
| `join` | lobby | "Short press: add player", and "Hold: start" once 2+ players joined |
| `pairing` | lobby | "Put meeple of P`joining` on the board" (short press cancels) |
| `setup` | running | new game: "Put meeples on cell 1". Starts by itself once every meeple reads cell 1; a long press starts anyway |
| `roll` | running | "P`turn`: press to roll" |
| `move` | running | roll, cell, target, steps left |
| `climb` | running | "Ladder! go to `target`" + steps left |
| `slide` | running | "Snake! go to `target`" + steps left |
| `over` | finished | "P`winner` wins!", "Hold: new game" (back to the lobby) |

**Hot/cold beeps are generated on the base from `dist`** while `state` is `running`, `phase` is `move`/`climb`/`slide` and `paused` is false: `4 → 800 ms`, `3 → 500 ms`, `2 → 250 ms`, `1 → 100 ms`, `0 → silent` (the "reached" sound comes as an event). With `dist` `null` the base stays silent. The controller never streams beeps over the network.

### 4.3 Game event (`snl/game/event`)

One-off sounds (and short LCD flashes). Never retained. `p` is the player it is about.

```json
{"e":"roll","p":2,"n":3}
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
| `joined` | — | confirmation beep |
| `win` | — | victory melody |

## 5. Joining (lobby)

The controller keeps `meeple mac → player id`, so a meeple that drops and reconnects mid-game gets its player back.

1. Meeples connect and publish `online = 1`. Meeples that are not in the game get `led = slow`.
2. **Short press** on the base: the controller reserves the next free player id and sets `phase: "pairing"`, `joining: N`.
3. The **first not-yet-joined meeple that reports a new tag** becomes player N: `led = on` for about 1 s, event `joined`, back to `phase: "join"`.
4. A short press while pairing cancels it. At most 4 players.
5. **Long press** with 2+ players starts a game: `state: "running"`, `phase: "setup"`, everyone 3 hp, turn order = player id order. Meeples that are not on cell 1 yet blink `slow`; as soon as all of them read cell 1, P1's turn starts (a long press starts anyway, e.g. when a tag won't read).
6. After a win (`state: "finished"`), a long press goes back to the lobby with no players: everyone joins again (short press + meeple), then a long press starts the new game.

## 6. A turn on the wire

```
ctrl  → game/event     {"e":"turn","p":2}
ctrl  → meeple(P2)/led fast
ctrl  → game/state     {"state":"running","phase":"roll","turn":2,...}
base  → base/button    short
ctrl  → game/event     {"e":"roll","p":2,"n":3}
ctrl  → game/state     {"phase":"move","roll":3,"cell":5,"target":8,"dist":3,...}
meeple→ meeple(P2)/tag -
meeple→ meeple(P2)/tag 04A1...        (cell 6)
ctrl  → game/state     {"cell":6,"dist":2,...}              base beeps every 250 ms
  ...                                                         (cell 8)
ctrl  → game/state     {"cell":8,"dist":0,...}
ctrl  → game/event     {"e":"reached","p":2}
  — meeple stays on cell 8 for 2 s, or the player long-presses —
ctrl  → game/event     {"e":"turn_end","p":2}
ctrl  → meeple(P2)/led off
ctrl  → game/event     {"e":"turn","p":3} ...
```

If the target is a ladder foot or a snake head, the controller sends `ladder`/`snake` with `to`, sets the new `target`, and the walk repeats with `phase: "climb"`/`"slide"` until the turn ends.

If the turn is ended with a long press before the target was reached, the controller sends `wrong` + `hp_lost`, and the turn stays open until the meeple is on the right cell. If that (or a snake) brings health to 0, it sends `hp_zero` and the turn ends at once: the meeple counts as on its target and the player sits out the next turn (then back to 3 hp).

Positions come from the rules, not from the tags: meeples are taken off the board after their turn, so each player's `cell` in `players` is where they last ended (the active meeple's live cell while it is on the board). After reaching the target the meeple may be lifted; the turn still ends after 2 s or with a long press. Stepping onto a cell that is not on the path sends `wrong` (no hp lost); stepping back along the path is only "colder".

## 7. Failure handling

- **Active meeple offline, or no base online:** the game pauses (`paused: true`) and resumes when it comes back. On reconnect a device gets its retained state, and the meeple re-publishes `tag`. If the active meeple stays offline (e.g. no power), a **long press removes that player** and the others play on; with fewer than 2 players left it goes back to the lobby.
- **Meeple offline in the lobby:** its player leaves, so the slot is free again.
- **Controller offline** (`snl/ctrl/online = 0`): the base shows "Controller offline", meeples turn their LED off. The controller keeps no state on disk: after a restart the players join again.
- **Stale retained data:** the controller ignores `tag` from a meeple whose `online` is `0`.

## 8. Quick test with mosquitto

```sh
mosquitto_sub -t 'snl/#' -v                                    # watch everything
mosquitto_pub -t snl/meeple/a4cf12b3c4d5/online -m 1 -r        # fake meeple online
mosquitto_pub -t snl/base/a4cf12b3c4d6/online -m 1 -r          # fake base online
mosquitto_pub -t snl/base/a4cf12b3c4d6/button -m short         # add a player
mosquitto_pub -t snl/meeple/a4cf12b3c4d5/tag -m 51000001 -r    # its meeple reads cell 1 (controller --sim)
```
