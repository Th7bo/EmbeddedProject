"""4x4 board: 16 cells, fixed ladders and snakes (Project_1st_FollowUp_Updated.docx)."""

CELLS = 16
LADDERS = {3: 6, 5: 12, 10: 15}  # foot -> top
SNAKES = {8: 1, 13: 4, 14: 11}   # head -> tail


def roll_path(start: int, roll: int) -> list[int]:
    """Cells visited when moving `roll` steps from `start`, bouncing back at 16.

    >>> roll_path(14, 4)
    [15, 16, 15, 14]
    """
    path, cell, step = [], start, 1
    for _ in range(roll):
        if cell == CELLS:
            step = -1
        cell += step
        path.append(cell)
    return path


def straight_path(start: int, end: int) -> list[int]:
    """Cells passed on a ladder/snake, excluding `start`: 3 -> 6 gives [4, 5, 6]."""
    step = 1 if end > start else -1
    return list(range(start + step, end + step, step))


def jump(cell: int) -> int | None:
    """Ladder top or snake tail when `cell` is a ladder foot or snake head."""
    return LADDERS.get(cell) or SNAKES.get(cell)
