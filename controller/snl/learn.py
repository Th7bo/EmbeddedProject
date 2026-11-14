"""Build tags.toml: put a meeple on each cell, type the cell number. `uv run python -m snl.learn`"""
import argparse
import queue

from . import tags
from .game import PREFIX
from .mqtt import client


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    args = ap.parse_args()

    table = tags.load()
    seen: queue.Queue[str] = queue.Queue()
    c = client("snl-learn")
    c.on_connect = lambda cl, *_: cl.subscribe(PREFIX + "meeple/+/tag")
    c.on_message = lambda _c, _u, m: seen.put(m.payload.decode().strip().upper())
    c.connect(args.host, args.port, keepalive=5)
    c.loop_start()
    print(f"{len(table)} tags known. Put a meeple on a cell (Ctrl+C to stop).")
    try:
        while True:
            uid = seen.get()
            if uid == "-":
                continue
            if uid in table:
                print(f"{uid} is cell {table[uid]}")
                continue
            cell = input(f"new tag {uid} - cell number (empty = skip): ").strip()
            if cell.isdigit() and 1 <= int(cell) <= 16:
                table[uid] = int(cell)
                tags.save(table)
                print(f"saved, {len(table)}/16 cells known")
    except KeyboardInterrupt:
        pass
    c.loop_stop()


if __name__ == "__main__":
    main()
