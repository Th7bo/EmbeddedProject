"""Tag UID -> cell table (tags.toml), plus fake UIDs for the simulator."""
import tomllib
from pathlib import Path

from .board import CELLS

DEFAULT = Path(__file__).resolve().parent.parent / "tags.toml"


def sim_uid(cell: int) -> str:
    """Fake 4-byte UID used by the simulator for `cell`: 51000001 .. 51000010."""
    return f"5100{cell:04X}"


def load(path: Path = DEFAULT, sim: bool = False) -> dict[str, int]:
    tags = {}
    if path.exists():
        tags = {uid.upper(): int(cell) for uid, cell in tomllib.loads(path.read_text()).get("tags", {}).items()}
    if sim:
        tags.update({sim_uid(c): c for c in range(1, CELLS + 1)})
    return tags


def save(tags: dict[str, int], path: Path = DEFAULT) -> None:
    lines = [l for l in path.read_text().splitlines() if l.startswith("#")] if path.exists() else []
    lines.append("[tags]")
    lines += [f'"{uid}" = {cell}' for uid, cell in sorted(tags.items(), key=lambda kv: kv[1])]
    path.write_text("\n".join(lines) + "\n")
