"""Shared board fixtures for search and benchmark tests."""

from pathlib import Path

from cursed_words_solver.models import Board, CurseType, Tile, TileColor


def _make_wordlist(tmp_path: Path) -> Path:
    words = ["cat", "car", "tar", "rat", "art", "the", "buy", "game", "boo", "book"]
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p

def _board_cat_horizontal() -> Board:
    tiles = []
    letters = [
        list("catxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
    ]
    for r in range(5):
        row = []
        for c in range(5):
            ch = letters[r][c] if letters[r][c] != "x" else "Q"
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch,
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles)

def _board_hit_shiny_h_fixture() -> Board:
    """Melmod-like board: shiny H (50) tempts DFS to depth 15 via M before I."""

    def letter(
        r: int,
        c: int,
        ch: str,
        base_score: float = 1.0,
        color: TileColor = TileColor.COLORLESS,
    ) -> Tile:
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch.upper(),
            base_score=base_score,
            color=color,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    def number(r: int, c: int, ch: str, face: int) -> Tile:
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=0.0,
            color=TileColor.VOID,
            curse=CurseType.NUMBER,
            number_value=face,
            metadata={"source": "melmod"},
        )

    grid = [[letter(r, c, "Q") for c in range(5)] for r in range(5)]
    grid[0][0] = letter(0, 0, "e")
    grid[0][1] = Tile(
        row=0,
        col=1,
        char="t",
        letter="T",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    grid[0][2] = number(0, 2, "9", 9)
    grid[0][3] = number(0, 3, "8", 8)
    grid[0][4] = letter(0, 4, "n")
    grid[1][0] = letter(1, 0, "e")
    grid[1][1] = letter(1, 1, "m", base_score=4.0, color=TileColor.RED)
    grid[1][2] = letter(1, 2, "h", base_score=50.0, color=TileColor.SHINY)
    grid[1][3] = letter(1, 3, "i")
    grid[1][4] = letter(1, 4, "t")
    for r, c, ch in [
        (2, 0, "h"),
        (2, 1, "s"),
        (2, 2, "e"),
        (2, 3, "u"),
        (2, 4, "c"),
        (3, 0, "c"),
        (3, 1, "i"),
        (3, 2, "y"),
        (3, 3, "i"),
        (3, 4, "e"),
        (4, 0, "d"),
        (4, 1, "a"),
        (4, 2, "r"),
        (4, 3, "w"),
        (4, 4, "b"),
    ]:
        grid[r][c] = letter(r, c, ch)
    return Board(tiles=grid)

def _board_wildcard_quill_fixture() -> Board:
    """Full 5×5 board: ?u?ll must start on wildcard at index 8."""
    def letter_tile(r, c, ch, score=1, color=TileColor.COLORLESS):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    def wildcard_tile(r, c, score=10):
        return Tile(
            row=r,
            col=c,
            char="?",
            letter="?",
            base_score=score,
            color=TileColor.COLORLESS,
            curse=CurseType.WILDCARD,
            metadata={"source": "melmod"},
        )

    layout = [
        "PDSPL",
        "EYE?N",
        "E?ULV",
        "IAVUL",
        "SESAT",
    ]
    grid = []
    for r, row_chars in enumerate(layout):
        row = []
        for c, ch in enumerate(row_chars):
            if ch == "?":
                row.append(wildcard_tile(r, c))
            else:
                row.append(letter_tile(r, c, ch))
        grid.append(row)
    return Board(tiles=grid)

def _wildcard_quill_wordlist(tmp_path: Path) -> Path:
    words = ["quill", "skull", "ulva", "null", "pull", "full", "gull", "dull", "mull"]
    p = tmp_path / "wildcard_quill.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p

def _board_boo4_fixture() -> Board:
    """Minimal board: boo4 with number 4 at position 4 (1-indexed)."""
    def tile(r, c, ch, score, curse=CurseType.LETTER, number_value=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[2][1] = tile(2, 1, "B", 3)
    grid[2][2] = tile(2, 2, "O", 1)
    grid[2][3] = tile(2, 3, "O", 1)
    grid[2][4] = tile(2, 4, "4", 4, CurseType.NUMBER, number_value=4)
    return Board(tiles=grid)

def _board_1r3vo_fixture() -> Board:
    """1 at index 0, r at 1, 3 at index 2, v at 3, o at 4 — number positions 1 and 3."""
    def tile(r, c, ch, score, curse=CurseType.LETTER, number_value=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = tile(0, 0, "1", 1, CurseType.NUMBER, number_value=1)
    grid[0][1] = tile(0, 1, "R", 1)
    grid[0][2] = tile(0, 2, "3", 3, CurseType.NUMBER, number_value=3)
    grid[0][3] = tile(0, 3, "V", 4)
    grid[0][4] = tile(0, 4, "O", 1)
    return Board(tiles=grid)

def _board_v2o4_fixture() -> Board:
    """v2o4: V + number 2 at pos 2 + O + number 4 at pos 4 (path along row 3-4)."""
    def tile(
        r,
        c,
        ch,
        score,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[3][2] = tile(3, 2, "V", 5, color=TileColor.BLUE)
    grid[4][2] = tile(4, 2, "2", 2, CurseType.NUMBER, number_value=2)
    grid[3][3] = tile(3, 3, "O", 1)
    grid[3][4] = tile(
        3, 4, "4", 5, CurseType.NUMBER, number_value=4, color=TileColor.RED
    )
    return Board(tiles=grid)

def _board_fu34s6s_fixture() -> Board:
    """Path [11,17,18,19,14,13,9] → fu34s6s (7 letters); shorter fu34s6 also valid."""
    def tile(
        r,
        c,
        ch,
        score,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[2][1] = tile(2, 1, "F", 2)
    grid[3][2] = tile(3, 2, "U", 2)
    grid[3][3] = tile(3, 3, "3", 3, CurseType.NUMBER, number_value=3)
    grid[3][4] = tile(3, 4, "4", 4, CurseType.NUMBER, number_value=4)
    grid[2][4] = tile(2, 4, "S", 2)
    grid[2][3] = tile(2, 3, "6", 6, CurseType.NUMBER, number_value=6)
    grid[1][4] = tile(1, 4, "S", 2)
    return Board(tiles=grid)

def _board_123ifer_fixture() -> Board:
    """Debug board where 123ifer (143) beats a23ifer (107); must start DFS on the 1 tile."""
    from pathlib import Path

    from tests.integration.test_loadout_scoring import _board_from_debug_json

    path = Path.home() / ".cursed_words_solver" / "debug" / "parse_20260522_163602.json"
    if path.exists():
        return _board_from_debug_json(path.name)
    # Minimal inline fallback (same layout as melmod export)
    def tile(r, c, ch, score, *, curse=CurseType.LETTER, nv=None, color=TileColor.COLORLESS):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][1] = tile(0, 1, "3", 3, curse=CurseType.NUMBER, nv=3)
    grid[1][4] = tile(1, 4, "2", 2, curse=CurseType.NUMBER, nv=2)
    grid[2][2] = tile(2, 2, "I", 1)
    grid[2][3] = tile(2, 3, "A", 1)
    grid[3][0] = tile(3, 0, "M", 3)
    grid[3][1] = tile(3, 1, "F", 4)
    grid[3][2] = tile(3, 2, "R", 1)
    grid[3][3] = tile(3, 3, "3", 3, curse=CurseType.NUMBER, nv=3)
    grid[3][4] = tile(3, 4, "2", 2, curse=CurseType.NUMBER, nv=2)
    grid[4][0] = tile(4, 0, "E", 1)
    grid[4][1] = tile(4, 1, "R", 1)
    grid[4][3] = tile(4, 3, "1", 1, curse=CurseType.NUMBER, nv=1)
    grid[4][4] = tile(4, 4, "5", 5, curse=CurseType.NUMBER, nv=5)
    return Board(tiles=grid, money=8)

def _board_tobiano_fixture() -> Board:
    """Melmod board where T-2-B-I-5-6-O spells TOBIANO (12bi56o with Flamingo T→1)."""
    def tile(
        r,
        c,
        ch,
        score,
        *,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    rows = [
        "GPEVE",
        "B2T1T",
        "YI5IR",
        "O6ERI",
        "7ROON",
    ]
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch.isdigit():
                grid[r][c] = tile(
                    r,
                    c,
                    ch,
                    0,
                    curse=CurseType.NUMBER,
                    number_value=int(ch),
                    color=(
                        TileColor.VOID
                        if ch in "127"
                        else TileColor.SHINY
                    ),
                )
            else:
                grid[r][c] = tile(r, c, ch, 2)
    grid[1][2] = tile(1, 2, "T", 50, color=TileColor.SHINY)
    grid[2][2] = tile(2, 2, "5", 50, curse=CurseType.NUMBER, number_value=5, color=TileColor.SHINY)
    grid[3][1] = tile(3, 1, "6", 50, curse=CurseType.NUMBER, number_value=6, color=TileColor.SHINY)
    grid[2][1] = tile(2, 1, "I", 1, color=TileColor.VOID)
    grid[4][2] = tile(4, 2, "O", 1, color=TileColor.BLUE)
    return Board(tiles=grid, money=37)

