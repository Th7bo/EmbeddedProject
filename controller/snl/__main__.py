"""Rules controller: `uv run python -m snl [--host PC] [--sim]`. Dashboard: http://localhost:8080"""
import argparse
import json
import logging
import threading
import time

from . import tags
from .dashboard import Hub, serve
from .game import Game, PREFIX, T_EVENT
from .mqtt import client


def main() -> None:
    ap = argparse.ArgumentParser(description="Snakes & Ladders: Hot or Cold rules controller")
    ap.add_argument("--host", default="localhost", help="MQTT broker (default: localhost)")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--sim", action="store_true", help="also accept the simulator's fake tag UIDs")
    ap.add_argument("--seed", type=int, help="fixed die seed, for repeatable runs")
    ap.add_argument("--web", default="127.0.0.1:8080",
                    help="dashboard address (default 127.0.0.1:8080; 0.0.0.0:8080 = whole network)")
    ap.add_argument("--no-web", action="store_true", help="no dashboard")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("snl.ctrl")

    import random
    real = tags.load()                      # tags.toml only: what gets saved
    table = tags.load(sim=args.sim)
    log.info("%d tags loaded", len(table))
    game = Game(table, rng=random.Random(args.seed))
    lock = threading.Lock()
    c = client("snl-ctrl", will=(PREFIX + "ctrl/online", "0"))

    hub = Hub()

    def send(msgs):
        for m in msgs:
            log.debug("tx %s %s", m.topic, m.payload)
            c.publish(m.topic, m.payload, qos=m.qos, retain=m.retain)
        snap = {**game.snapshot(), "board_tags": {cell: uid for uid, cell in real.items()}}
        hub.update(snap, [json.loads(m.payload) for m in msgs if m.topic == T_EVENT])

    def press(kind):
        with lock:
            send(game.press(kind))

    def set_tag(uid, cell):
        with lock:
            for u in [u for u, c in real.items() if c == cell or u == uid]:
                del real[u]
            real[uid] = cell
            tags.save(real)
            log.info("saved %d/16 board tags to tags.toml", len(real))
            send(game.set_tag(uid, cell))

    def clear_scanned():
        with lock:
            send(game.clear_scanned())

    if not args.no_web:
        host, _, port = args.web.rpartition(":")
        serve(hub, press, set_tag, clear_scanned, host or "127.0.0.1", int(port))

    def on_connect(cl, _ud, _flags, rc, _props):
        if rc.is_failure:
            log.error("connect failed: %s", rc)
            return
        log.info("connected to %s:%d", args.host, args.port)
        cl.subscribe([(PREFIX + "meeple/+/+", 0), (PREFIX + "base/+/+", 0)])
        with lock:
            send(game.startup())

    def on_message(_cl, _ud, msg):
        payload = msg.payload.decode(errors="replace")
        log.debug("rx %s %s", msg.topic, payload)
        with lock:
            send(game.on_message(msg.topic, payload))

    c.on_connect, c.on_message = on_connect, on_message
    c.connect_async(args.host, args.port, keepalive=5)
    c.loop_start()
    try:
        while True:
            time.sleep(0.1)
            with lock:
                send(game.tick())
    except KeyboardInterrupt:
        c.publish(PREFIX + "ctrl/online", "0", qos=1, retain=True).wait_for_publish(2)
        c.disconnect()
        c.loop_stop()


if __name__ == "__main__":
    main()
