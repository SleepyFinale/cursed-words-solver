"""DLC-era word rules, ported from the decompiled game (Assembly-CSharp, DLC build).

* ``Tile.GetStringRepresentation(forWordValidity: true)`` -> :func:`word_srep`
* ``InventoryCache`` -> :class:`Inventory`
* ``Brackets`` helpers -> :func:`brackets_satisfied` / :func:`in_bracket` / :func:`bracket_depth`
* ``Tile.IsWildcard`` / ``IsNumericWildcard`` -> :meth:`Inventory.is_wildcard`
* ``WordTrie.IsTileMatchingChar`` -> :meth:`Inventory.letter_codes`
* ``Vocabulary.GetValidWordFromTiles`` / ``GetValidUpperAndLowerCaseWordsFromTiles`` /
  ``GetConcatenatedValidWordsFromTiles`` -> :class:`WordRules`
* ``Tile.IsDisplayingAsVariableLetter`` -> :func:`variable_letter`

``WordTrie.MatchRecursive`` walks a tile's whole permutation string, or lets the tile stand
for one trie character that ``IsTileMatchingChar`` accepts; the trie is
``TriesByLength[sum of permutation string lengths]``, so a bracket tile (string "")
contributes no letter and the matched word must have exactly that many letters. Existence
is all that matters for validity, so the match steps sets of trie nodes (keyed by the
remaining length difference) instead of recursing; the spelled word is the smallest
matching trie node (the game shuffles, so any match is the game's).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from cursed_words_solver.engine.model import (
    CURRENCY_MAP_LOWER,
    G_ARROW,
    G_BLANK,
    G_BRACKET,
    G_CARD,
    G_CHESS,
    G_CURRENCY,
    G_DICE,
    G_DOMINO,
    G_FRACTION,
    G_HYPER,
    G_ITEM,
    G_LETTER,
    G_NONE,
    G_NUMBER,
    G_WIRE,
    G_ZODIAC,
    LETTERS,
    NORMAL,
    SUIT_JOKER,
    SUIT_NONE,
    ETile,
    ItemInst,
)
from cursed_words_solver.engine.trie import CsrTrie

# Item classes whose colours InventoryCache / IsDisplayingAsVariableLetter collect.
COLOUR_CLASSES = ("Flamingo", "RedEnvelope", "SpicyPepper", "Automobile", "CreepyCrawly")
CONTAINERS = ("RandomAccessMemory", "Snapshot", "Frankenstein", "IceCube")

# Chameleon: TileType -> the letter it can stand for (IsTileMatchingChar) and the letter
# it does not wobble on (IsDisplayingAsVariableLetter; same table).
CHAMELEON = {
    "red": "r", "blue": "b", "void": "v", "shiny": "s", "purple": "p", "gold": "g",
    "green": "g", "white": "w", "cactus": "c", "pink": "p", "glitch": "g",
}
_SUIT_LETTER = {"clubs": "c", "spades": "s", "diamonds": "d", "hearts": "h"}


# Item classes added by the DLC build (absent from the pre-DLC item data). Plans holding any
# of them score with the reference port (``EnginePlan.dlc_ref``).
NEW_ITEM_CLASSES = frozenset({
    'Alien', 'AntiqueClock', 'Astronaut', 'AudioMixerItem', 'Baby', 'BactrianCamel',
    'BadmintonRacket', 'Bagel', 'Basket', 'Bat', 'BettingSlip', 'Bin', 'Bingo',
    'BoonOfTheAxolotl', 'BoonOfTheBadger', 'BoonOfTheBat', 'BoonOfTheBison',
    'BoonOfTheCapybara', 'BoonOfTheCobra', 'BoonOfTheFox', 'BoonOfTheHyena',
    'BoonOfTheMorayEel', 'BoonOfTheWhale', 'BoonOfTheYetiCrab', 'Bouquet', 'BowlAndSpoon',
    'Bride', 'Bubbles', 'BulletTrain', 'Butterfly', 'Casino', 'Chains', 'Chameleon',
    'ChickenFoot', 'Chopsticks', 'Cigarette', 'Clown', 'Comet', 'Compass', 'Conifer',
    'Cookie', 'Coral', 'Crayon', 'CreepyCrawly', 'CremeCaramel', 'CricketBat',
    'CrossedFlags', 'DNDPlayer', 'DeadBattery', 'DepartmentStore', 'DesertIsland',
    'Diplodocus', 'Dodo', 'Dolphin', 'DoubleVision', 'Dracula', 'DropOfBlood', 'Duck',
    'ElectricPlug', 'Electrician', 'Elephant', 'Elevator', 'EmptyPlate', 'EurekaLemon',
    'EvilMonkey', 'Eyes', 'FigureEightKnot', 'FingersCrossed', 'Flashlight', 'FlipFlop',
    'Football', 'Frisbee', 'FrostBite', 'FuelPump', 'Garlic', 'Gloves', 'GoldStar',
    'GoldenEagle', 'Goose', 'Hamburger', 'Handbag', 'Headphones', 'Helicopter', 'HoleInOne',
    'Horoscope', 'HoroscopeWriter', 'HotDog', 'Hyacinth', 'IceCube', 'IceSkate',
    'InfiniteLoop', 'Joystick', 'Juggler', 'Karategi', 'Koala', 'Ladder', 'LifeBelt',
    'LightBulb', 'LiterarySaga', 'Lotus', 'LucrativeInvestment', 'Mage', 'MagicBeans',
    'MagnifyingGlass', 'Mammoth', 'ManInTheMoon', 'Matcha', 'Medallion', 'Meditator',
    'Megaphone', 'Mermaid', 'MexicanTrain', 'MolluscShell', 'MoneyAutomobile', 'MoonCake',
    'MoonRock', 'Motorcycle', 'MouseTrap', 'NatH1', 'NationalPark', 'NaughtyList',
    'NestingDolls', 'NightLife', 'NoEntrySign', 'NorthWind', 'NutAndBolt', 'OilDrum',
    'Orangutan', 'Owl', 'Paintbrush', 'PartyTime', 'Peanuts', 'Phoenix', 'PieceOfString',
    'Placebo', 'Platform6', 'PlummetingAnchor', 'Plunger', 'PolarBear', 'PopStar',
    'Popcorn', 'PostOffice', 'PowerOfFriendship', 'PowerOfLove', 'PrayerBeads', 'Pretzel',
    'PrismaticCrystal', 'Programmer', 'Quatrefoil', 'RaceCar', 'Racehorse', 'RailwayTrack',
    'Raven', 'Razor', 'RockClimber', 'Rocket', 'Rosette', 'SafetyGoggles', 'SaltShaker',
    'Satellite', 'Saw', 'ScaredToLook', 'Scientist', 'Screwdriver', 'Selfie',
    'ShootingStar', 'ShoshinshaMark', 'Shrugger', 'SilverLining', 'SkiBoots',
    'SkullAndCrossbones', 'Skunk', 'Sloth', 'SmoothJazz', 'SnowStorm', 'Snowboarder',
    'Snowflake', 'Sparkles', 'Spider', 'SpiderWeb', 'Squid', 'Stopwatch', 'Strawberry',
    'StrawberrySwirl', 'StrongSignal', 'Sunrise', 'Sunset', 'Sunshine', 'Surfer', 'Syringe',
    'Taco', 'TakeshisCastle', 'Tangerine', 'Taxi', 'TeddyBear', 'TemperTantrum',
    'TennisBall', 'Thermometer', 'TollingBell', 'Tornado', 'Tractor', 'Tram', 'TreeRings',
    'Trident', 'TrustyWrench', 'Tsukimi', 'Tube', 'Turtle', 'Twinsies', 'WatermelonSlice',
    'Weightlifter', 'WheelOfFortune', 'Whiskey', 'WiltedFlower', 'WinterCoat', 'Witch',
    'YinYang', 'Yoyo', 'Zap', 'Zoologist',
})


def word_srep(t: ETile) -> str:
    """``GetStringRepresentation(forWordValidity: true)``."""
    g = t.glyph
    if g == G_CARD and t.suit == SUIT_JOKER:
        return "!"
    if g == G_LETTER:
        return t.letter
    if g == G_CURRENCY:
        return t.symbol.lower()
    if g in (G_WIRE, G_DICE):
        return t.symbol.lower()
    if g in (G_ZODIAC, G_DOMINO):
        return "*"
    if g == G_ARROW:
        return t.letter
    if g in (G_FRACTION, G_NUMBER, G_CHESS, G_ITEM):
        return "!"
    if g == G_BLANK:
        return "?"
    if g == G_HYPER:
        return "#"
    if g in (G_BRACKET, G_NONE):
        return ""
    return t.letter


# ------------------------------------------------------------------ brackets


def _is_close(b: str) -> bool:
    return bool(b) and b[0] == ")"


def brackets_satisfied(tiles: Iterable[ETile]) -> bool:
    """``Brackets.AreBracketsSatisfied``."""
    stack: list[str] = []
    for t in tiles:
        if t.glyph != G_BRACKET:
            continue
        for b in t.brackets():
            if _is_close(b):
                if not stack or stack[-1] != "(":
                    return False
                stack.pop()
            else:
                stack.append(b)
    return not stack


def in_bracket(tiles: Iterable[ETile]) -> bool:
    """``Brackets.InBracket``: an open bracket is left unclosed."""
    stack: list[str] = []
    for t in tiles:
        if t.glyph != G_BRACKET:
            continue
        for b in t.brackets():
            if _is_close(b):
                if stack and stack[-1] == "(":
                    stack.pop()
            else:
                stack.append(b)
    return any(b and b[0] == "(" for b in stack)


def bracket_depth(tiles: list[ETile], index: int) -> int:
    """``Brackets.GetBracketDepth``."""
    depth = 0
    for i in range(index):
        if tiles[i].glyph != G_BRACKET:
            continue
        for b in tiles[i].brackets():
            if _is_close(b):
                if depth > 0:
                    depth -= 1
            else:
                depth += 1
    if tiles[index].glyph == G_BRACKET:
        for b in tiles[index].brackets():
            if _is_close(b) and depth > 0:
                depth -= 1
    return depth


def tiles_contained_by_brackets(tiles: list[ETile]) -> dict[int, list[ETile]]:
    """``Brackets.TilesContainedByBrackets`` keyed by position of each bracket tile."""
    out: dict[int, list[ETile]] = {}
    pos = {id(t): i for i, t in enumerate(tiles)}
    stack: list[ETile] = []
    for t in tiles:
        if t.glyph == G_BRACKET:
            out.setdefault(pos[id(t)], [])
            for b in t.brackets():
                if _is_close(b):
                    if stack:
                        for item in out[pos[id(stack[-1])]]:
                            if item not in out[pos[id(t)]]:
                                out[pos[id(t)]].append(item)
                        stack.pop()
                    for open_t in stack:
                        lst = out[pos[id(open_t)]]
                        if open_t is not t and t not in lst:
                            lst.append(t)
                    continue
                for open_t in stack:
                    lst = out[pos[id(open_t)]]
                    if open_t is not t and t not in lst:
                        lst.append(t)
                stack.append(t)
            continue
        for open_t in stack:
            lst = out[pos[id(open_t)]]
            if t not in lst:
                lst.append(t)
    return out


def non_bracket_tiles_contained(tiles: list[ETile], index: int) -> int:
    """``Brackets.GetNonBracketTilesContainedByBracket``."""
    target = tiles[index]
    scopes: list[list] = []  # [opening tile, non-bracket count]
    total = 0
    for t in tiles:
        if t.glyph != G_BRACKET:
            for sc in scopes:
                sc[1] += 1
            continue
        for b in t.brackets():
            if _is_close(b):
                if scopes:
                    sc = scopes.pop()
                    if sc[0] is target or t is target:
                        total += sc[1]
            else:
                scopes.append([t, 0])
    for sc in scopes:
        if sc[0] is target:
            total += sc[1]
    return total


def max_bracket_depth(tiles: Iterable[ETile]) -> int:
    """``Brackets.GetMaximumBracketDepth``."""
    depth = best = 0
    for t in tiles:
        if t.glyph != G_BRACKET:
            continue
        for b in t.brackets():
            if _is_close(b):
                if depth > 0:
                    depth -= 1
                continue
            depth += 1
            best = max(best, depth)
    return best


# ------------------------------------------------------------------ inventory


class Inventory:
    """``InventoryCache`` for one ``currentWordTiles`` list (items already resolved)."""

    def __init__(self, items: list[ItemInst], money: int, word_tiles: list[ETile], grid) -> None:
        classes = {i.cls for i in items}
        self.classes = classes
        colours: dict[str, list[str]] = {}
        for it in items:
            if it.cls in COLOUR_CLASSES:
                colours.setdefault(it.cls, []).extend(it.colours)
        self.colours = colours
        self.money = money
        self.queen = "Queen" in classes
        self.test_tube = "TestTube" in classes
        self.syringe = "Syringe" in classes
        self.number_go_up = "NumberGoUp" in classes
        self.microscope = "Microscope" in classes
        self.mollusc = "MolluscShell" in classes
        self.coral = "Coral" in classes
        self.moon_cake = "MoonCake" in classes
        self.bagel = "Bagel" in classes
        self.chameleon = "Chameleon" in classes
        self.flamingo_first = (colours.get("Flamingo") or [None])[0] if "Flamingo" in classes else None
        monkey = next((i for i in items if i.cls == "EvilMonkey"), None)
        self.evil_monkey = monkey is not None
        self.evil_monkey_level = monkey.var(1) if monkey is not None else 0
        self.creme_letters: list[str] = []
        for it in items:
            if it.cls == "CremeCaramel":
                self.creme_letters.extend(str(x).lower() for x in item_field(it, "ChosenLetters", []) or [])
        # ShoshinshaMarkStrings: per currentWordTiles position, the letter tiles below a
        # cursed tile (IsCursed(currentWordTiles)) in its column.
        self.shoshinsha = "ShoshinshaMark" in classes
        self.shoshinsha_strings: list[list[str]] = []
        self._grid = grid
        self._word_tiles = word_tiles

    def init_shoshinsha(self, is_cursed) -> None:
        if not self.shoshinsha:
            return
        out: list[list[str]] = []
        for t in self._word_tiles:
            out.append(column_letters_below(self._grid, t) if is_cursed(t, self._word_tiles) else [])
        self.shoshinsha_strings = out

    # IsNumericWildcard
    def numeric_wildcard(self, t: ETile, index: int, word_length: int) -> bool:
        allowed = {index + 1}
        if self.test_tube:
            allowed.update((index, index + 2))
        allowed.add(index - word_length)
        if self.test_tube:
            allowed.update((index - word_length + 1, index - word_length - 1))
        if t.glyph == G_NUMBER:
            n = int(t.number or 0)
            if n in allowed or (self.syringe and -n in allowed):
                return True
        if t.glyph == G_FRACTION and t.fraction:
            a, b = t.fraction
            if a in allowed or b in allowed or (self.syringe and (-a in allowed or -b in allowed)):
                return True
        if self.flamingo_first is not None and t.is_type(self.flamingo_first) and index == 0:
            return True
        if self.mollusc and index == 6:
            return True
        if self.coral and not t.is_type(NORMAL) and index == word_length - 1:
            return True
        if self.microscope and (t.value == index + 1 or t.value == index - word_length):
            return True
        if self.moon_cake and t.glyph == G_CURRENCY and index == self.money - 1:
            return True
        return False

    def is_wildcard(self, t: ETile, index: int, tiles: list[ETile]) -> bool:
        """``Tile.IsWildcard(index, tiles)`` (``tiles`` = allSelectedTiles)."""
        g = t.glyph
        if g in (G_BLANK, G_CHESS, G_ARROW, G_ITEM, G_WIRE, G_DICE, G_ZODIAC, G_DOMINO) or t.suit == SUIT_JOKER:
            return True
        if self.evil_monkey and 6 - self.evil_monkey_level <= index < 6:
            return True
        if self.number_go_up and 0 <= index < len(tiles) and tiles[index].is_number():
            nums = [x.number_float() for x in tiles if x.is_number()]
            if all(nums[i] > nums[i - 1] for i in range(1, len(nums))):
                return True
        if g == G_BRACKET and brackets_satisfied(tiles):
            return True
        return self.numeric_wildcard(t, index, len(tiles))

    def letter_codes(self, t: ETile, s: str, tile_index: int, in_brackets: bool, is_cursed_bare: bool) -> set[str]:
        """Characters ``IsTileMatchingChar`` accepts for a non-wildcard tile."""
        out: set[str] = set()
        if len(s) == 1:
            out.add(s)
        if self.shoshinsha and is_cursed_bare and tile_index < len(self.shoshinsha_strings):
            out.update(x for x in self.shoshinsha_strings[tile_index] if len(x) == 1)
        cl = self.colours
        if "RedEnvelope" in self.classes and any(t.is_type(c) for c in cl.get("RedEnvelope", ())):
            out.add("e")
        if "CreepyCrawly" in self.classes and any(t.is_type(c) for c in cl.get("CreepyCrawly", ())):
            out.add("o")
        if self.creme_letters and is_cursed_bare:
            out.update(x for x in self.creme_letters if len(x) == 1)
        if "SpicyPepper" in self.classes and any(t.is_type(c) for c in cl.get("SpicyPepper", ())):
            out.add("s")
        if "Automobile" in self.classes and t.glyph == G_LETTER and any(t.is_type(c) for c in cl.get("Automobile", ())):
            k = LETTERS.index(s) if s in LETTERS else -1
            for j, c in enumerate(LETTERS):
                if abs(j - k) < 2:
                    out.add(c)
        if "SluggishZombie" in self.classes and s == "z":
            out.add("s")
        if "Jellyfish" in self.classes and s == "j":
            out.update("yh")
        if "CardShark" in self.classes and t.suit in _SUIT_LETTER:
            out.add(_SUIT_LETTER[t.suit])
        if self.chameleon and t.tile_type in CHAMELEON:
            out.add(CHAMELEON[t.tile_type])
        if t.glyph == G_CURRENCY:
            mapped = CURRENCY_MAP_LOWER.get(s)
            if mapped:
                out.add(mapped)
        if "NumbersBunchOfGrapes" in self.classes and t.glyph == G_NUMBER:
            out.update({1: "i", 5: "v", 10: "x"}.get(t.number, ""))
        if self.bagel and in_brackets:
            out.add("a")
        return {c for c in out if "a" <= c <= "z"}


def item_field(inst: ItemInst, name: str, default=None):
    """Raw game field of an item (melmod item_states ``fields``)."""
    fields = inst.state.get("_fields")
    if isinstance(fields, dict) and name in fields:
        return fields[name]
    return default


def column_letters_below(grid, t: ETile) -> list[str]:
    """Word strings of the available Letter tiles below ``t`` in its column (nearest first)."""
    out: list[str] = []
    for y in range(t.y + 1, grid.height):
        below = grid.at(t.x, y)
        if below is not None and not below.in_void and below.glyph == G_LETTER:
            out.append(word_srep(below))
    return out


# ------------------------------------------------------------------ matching


def _np_arrays(trie: CsrTrie):
    from cursed_words_solver.engine.search import _numpy_trie

    return _numpy_trie(trie)


def _np_children(arrays, nodes):
    import numpy as np

    starts_np, counts_np, childs_np = arrays[0], arrays[1], arrays[2]
    cnt = counts_np[nodes]
    total = int(cnt.sum())
    if not total:
        return np.zeros(0, dtype=np.int32)
    st = starts_np[nodes]
    offs = np.repeat(st - np.concatenate(([0], np.cumsum(cnt)[:-1])), cnt)
    return childs_np[np.arange(total) + offs]


def _np_letter(arrays, nodes, ch: str):
    import numpy as np

    edge_keys, childs_np = arrays[3], arrays[2]
    if not len(edge_keys) or not nodes.size:
        return np.zeros(0, dtype=np.int32)
    code = ord(ch) - 97
    if not 0 <= code < 32:
        return np.zeros(0, dtype=np.int32)
    keys = nodes.astype(np.int64) * 32 + code
    pos = np.searchsorted(edge_keys, keys)
    pos = np.minimum(pos, len(edge_keys) - 1)
    hit = edge_keys[pos] == keys
    return childs_np[pos[hit]]


def _np_text(arrays, nodes, text: str):
    for ch in text:
        nodes = _np_letter(arrays, nodes, ch)
        if not nodes.size:
            break
    return nodes


_LEN_MATS: dict[int, tuple] = {}


def length_matrices(trie: CsrTrie) -> dict[int, "object"]:
    """Every word of the trie as a (words x L) uint8 letter matrix per length L, rows in
    trie-node order (BFS ids, children by letter: alphabetical within a length)."""
    import numpy as np

    hit = _LEN_MATS.get(id(trie))
    if hit is not None and hit[0] is trie:
        return hit[1]
    starts, counts, childs, _keys, is_word, parent, letter = _np_arrays(trie)
    n = len(starts)
    mats: dict[int, np.ndarray] = {}
    lo, hi, depth = 0, 1, 0
    while lo < hi and hi <= n:
        if depth > 0:
            nodes = np.nonzero(is_word[lo:hi])[0] + lo
            if nodes.size:
                m = np.empty((nodes.size, depth), dtype=np.uint8)
                cur = nodes.astype(np.int64)
                for col in range(depth - 1, -1, -1):
                    m[:, col] = letter[cur]
                    cur = parent[cur]
                mats[depth] = m
        # BFS ids: the next level is the contiguous block of this level's children.
        last = hi - 1
        end = int(starts[last] + counts[last])
        first_edge = int(starts[lo])
        if end <= first_edge:
            nxt_hi = hi
            for k in range(hi - 1, lo - 1, -1):
                if counts[k]:
                    nxt_hi = int(childs[starts[k] + counts[k] - 1]) + 1
                    break
        else:
            nxt_hi = int(childs[end - 1]) + 1
        lo, hi, depth = hi, max(nxt_hi, hi), depth + 1
        if nxt_hi <= lo:
            break
    _LEN_MATS[id(trie)] = (trie, mats)
    return mats


def _match_by_length(trie: CsrTrie, wild: list[bool], texts: list[list[str]], codes: list[set[str]]) -> str | None:
    """``match_tiles`` when every tile has one string of at most one letter: tiles with ""
    (brackets) can only pass through (a consumed character can never be paid back), so
    the word has exactly one letter per remaining tile, filtered column by column."""
    import numpy as np

    cols: list[set[str] | None] = []
    for i, opts in enumerate(texts):
        s = opts[0]
        if s == "":
            continue
        if wild[i]:
            cols.append(None)
        else:
            allowed = set(codes[i])
            if "a" <= s <= "z":
                allowed.add(s)
            cols.append(allowed)
    mats = length_matrices(trie)
    m = mats.get(len(cols))
    if m is None or not len(cols):
        return None
    mask = None
    for k, allowed in enumerate(cols):
        if allowed is None:
            continue
        if not allowed:
            return None
        lut = np.zeros(256, dtype=bool)
        lut[[ord(c) for c in allowed]] = True
        hit = lut[m[:, k]]
        mask = hit if mask is None else (mask & hit)
        if not mask.any():
            return None
    row = 0 if mask is None else int(np.argmax(mask))
    return bytes(m[row]).decode("ascii")


def match_tiles(trie: CsrTrie, tiles: list[ETile], wild: list[bool], texts: list[list[str]], codes: list[set[str]]) -> str | None:
    """``WordTrie.TryMatchTiles`` over every permutation; the matched word or None."""
    import numpy as np

    from cursed_words_solver.engine.search import _np_spell

    if all(len(o) == 1 and len(o[0]) <= 1 for o in texts):
        return _match_by_length(trie, wild, texts, codes)
    arrays = _np_arrays(trie)
    # frontier: ldiff (permutation letters - trie depth) -> node array
    frontier: dict[int, np.ndarray] = {0: np.zeros(1, dtype=np.int32)}
    for i in range(len(tiles)):
        nxt: dict[int, list] = {}
        for ldiff, nodes in frontier.items():
            kids = None
            for text in texts[i]:
                n = len(text)
                walked = _np_text(arrays, nodes, text) if text else nodes
                if walked.size:
                    nxt.setdefault(ldiff, []).append(walked)
                # one trie character standing for the tile
                if wild[i]:
                    if kids is None:
                        kids = _np_children(arrays, nodes)
                    step = kids
                else:
                    parts = [_np_letter(arrays, nodes, c) for c in codes[i]]
                    parts = [p for p in parts if p.size]
                    step = np.concatenate(parts) if parts else None
                if step is not None and step.size:
                    nxt.setdefault(ldiff + n - 1, []).append(step)
        frontier = {}
        for ld, parts in nxt.items():
            arr = parts[0] if len(parts) == 1 else np.unique(np.concatenate(parts))
            if arr.size:
                frontier[ld] = arr
        if not frontier:
            return None
    nodes = frontier.get(0)
    if nodes is None or not nodes.size:
        return None
    words = nodes[arrays[4][nodes]]
    if not words.size:
        return None
    return _np_spell(arrays, int(words.min()))


@dataclass
class Submitted:
    """``SubmittedWords`` with tiles as path positions."""

    words: list[str] = field(default_factory=list)
    groups: list[list[int]] = field(default_factory=list)  # uppercase word tile positions
    lower_words: list[str] = field(default_factory=list)
    lower_groups: list[list[int]] = field(default_factory=list)

    def all_words(self) -> list[str]:
        return self.words + self.lower_words

    def all_groups(self) -> list[list[int]]:
        return self.groups + self.lower_groups

    def text(self) -> str:
        return " ".join(self.all_words())


class WordRules:
    """``Vocabulary`` validity for paths on one plan (exact, path-dependent inventory)."""

    def __init__(self, plan, trie: CsrTrie, acc_words: list[str], min_len: int, max_len: int) -> None:
        self.plan = plan
        self.trie = trie
        self.acc_words = sorted(set(acc_words))
        self.acc_trie = CsrTrie.from_words(self.acc_words) if self.acc_words else None
        self.min_len = min_len
        self.max_len = max_len
        self.grid = plan.grid

    # InventoryCache(tiles)
    def inventory(self, tiles: list[ETile]) -> Inventory:
        items = self.plan.inventory_insts_for(tiles)
        inv = Inventory(items, self.plan.money, tiles, self.grid)
        inv.init_shoshinsha(lambda t, lst: self.plan.is_cursed_in(t, lst))
        return inv

    def _contained(self, inv: Inventory, word: list[ETile], all_tiles: list[ETile], trie: CsrTrie) -> str | None:
        """``IsWordContainedInList``."""
        pos = {id(t): i for i, t in enumerate(all_tiles)}
        wild = [inv.is_wildcard(t, pos.get(id(t), -1), all_tiles) for t in word]
        texts: list[list[str]] = []
        codes: list[set[str]] = []
        for i, t in enumerate(word):
            s = word_srep(t)
            opts = [s]
            if s == "q" and inv.queen:
                opts.append("qu")
            texts.append(opts)
            if wild[i]:
                codes.append(set())
            else:
                inb = bracket_depth(word, i) > 0
                codes.append(inv.letter_codes(t, s, i, inb, self.plan.is_cursed_in(t, [])))
        return match_tiles(trie, word, wild, texts, codes)

    def _accumulator(self, inv_classes_tiles: list[ETile], word: list[ETile], words: list[str] | None = None) -> str | None:
        """``TryGetAccumulatorWordFromTiles`` (AreWordsFunctionallyEqual per word)."""
        if not self.acc_words if words is None else not words:
            return None
        inv = self.inventory(inv_classes_tiles)
        trie = self.acc_trie if words is None else CsrTrie.from_words(words)
        if trie is None:
            return None
        return self._contained(inv, word, word, trie)

    def valid_word(self, word: list[ETile], all_tiles: list[ETile], inv: Inventory, inv_tiles: list[ETile],
                   min_len: int, max_len: int) -> str | None:
        """``GetValidWordFromTiles(tilesInWord, allSelectedTiles)``."""
        n = len(word)
        if n < min_len or n > max_len:
            return None
        if not brackets_satisfied(word):
            return None
        acc = self._accumulator(inv_tiles, word)
        if acc is not None:
            return acc
        return self._contained(inv, word, all_tiles, self.trie)

    def upper_lower(self, path: list[int], min_len: int | None = None, max_len: int | None = None) -> Submitted | None:
        """``GetValidUpperAndLowerCaseWordsFromTiles``."""
        lo = self.min_len if min_len is None else min_len
        hi = self.max_len if max_len is None else max_len
        tiles = [self.grid.tiles[i] for i in path]
        inv = self.inventory(tiles)
        lower = [k for k, t in enumerate(tiles) if t.is_lowercase_letter()]
        upper = [k for k, t in enumerate(tiles) if not t.is_lowercase_letter()]
        out = Submitted()
        if lower:
            w = self.valid_word([tiles[k] for k in lower], tiles, inv, tiles, lo, hi)
            if w is None:
                return None
            out.lower_words = [w]
            out.lower_groups = [[path[k] for k in lower]]
        if upper:
            w = self.valid_word([tiles[k] for k in upper], tiles, inv, tiles, lo, hi)
            if w is None:
                return None
            out.words = [w]
            out.groups = [[path[k] for k in upper]]
        return out

    def concatenated(self, path: list[int], part_max: int) -> Submitted | None:
        """``GetConcatenatedValidWordsFromTiles`` (Honeypot)."""
        tiles = [self.grid.tiles[i] for i in path]
        for first, second in self.plan.accumulator_pairs:
            k = len(first)
            if k > len(tiles):
                continue
            a = self._accumulator(tiles, tiles[:k], [first])
            if a is None:
                continue
            b = self._accumulator(tiles, tiles[k:], [second]) if k < len(tiles) else None
            if b is not None:
                return Submitted(words=[a, b], groups=[list(path[:k]), list(path[k:])])
        whole = self.upper_lower(path)
        if whole is not None:
            return whole
        for k in range(1, len(path)):
            a = self.upper_lower(path[:k], max_len=part_max)
            if a is None:
                continue
            b = self.upper_lower(path[k:], max_len=part_max)
            if b is not None:
                return Submitted(
                    words=a.words + b.words,
                    groups=a.groups + b.groups,
                    lower_words=a.lower_words + b.lower_words,
                    lower_groups=a.lower_groups + b.lower_groups,
                )
        return None


# ------------------------------------------------------------------ variable letter


def variable_letter(plan, t: ETile, lst: list[ETile], sel: list[ETile], manager_items: bool) -> bool:
    """``Tile.IsDisplayingAsVariableLetter(tileSelectionManager, wordTiles)``.

    ``lst`` is the word-tile list the game reads (``wordTiles`` when non-empty, else the
    passed manager's selection, else empty); ``sel`` is the live selection
    (``GameStatics.CurrentTileSelectionManager``), used by Evil Monkey and Mollusc Shell;
    ``manager_items``: the manager was passed, so its selection's scattered items count.
    """
    g = t.glyph
    if g in (G_BLANK, G_CHESS, G_ARROW, G_ITEM, G_WIRE, G_DICE, G_ZODIAC, G_BRACKET, G_DOMINO) or t.suit == SUIT_JOKER:
        return False
    base = list(plan.inventory_top)
    if manager_items:
        base += [plan.scattered_inst(x) for x in sel if x.glyph == G_ITEM and x.item]
    items = list(base)
    for it in base:
        if it.cls in ("RandomAccessMemory", "Snapshot", "IceCube"):
            items.extend(it.nested)
    items += [plan.scattered_inst(x) for x in lst if x.glyph == G_ITEM and x.item]
    colours: dict[str, list[str]] = {}
    for it in items:
        if it.cls in COLOUR_CLASSES:
            colours.setdefault(it.cls, []).extend(it.colours)
    for it in base:
        if it.cls == "Frankenstein":
            items.extend(it.nested)
    classes = {i.cls for i in items}
    rep = t.srep
    is_letter = g == G_LETTER

    def has(c: str) -> bool:
        return c in classes

    if has("EvilMonkey") and sel is not None:
        monkey = next(i for i in items if i.cls == "EvilMonkey")
        lvl = monkey.var(1)
        contains = any(x is t for x in lst)
        if not contains and 6 - lvl <= len(lst) < 6:
            return True
        if contains:
            idx = next(k for k, x in enumerate(lst) if x is t)
            if 6 - lvl <= idx < 6:
                return True
    if has("Bagel") and (not is_letter or rep != "a"):
        if in_bracket(lst):
            return True
        idx = next((k for k, x in enumerate(lst) if x is t), -1)
        if idx >= 0 and bracket_depth(lst, idx) > 0:
            return True
    if has("RedEnvelope") and any(t.is_type(c) for c in colours.get("RedEnvelope", ())):
        if (not is_letter or rep != "e") and (g != G_CURRENCY or t.symbol != "€"):
            return True
    if has("CreepyCrawly") and any(t.is_type(c) for c in colours.get("CreepyCrawly", ())):
        if not is_letter or rep != "o":
            return True
    if has("MolluscShell") and sel is not None:
        if len(sel) == 6 and not any(x is t for x in sel):
            return True
        if len(sel) >= 7 and sel[6] is t:
            return True
    if has("MoonCake") and g == G_CURRENCY and plan.money > 0:
        return True
    if has("ShoshinshaMark") and (not is_letter or t.suit != SUIT_NONE):
        if column_letters_below(plan.grid, t):
            return True
    if has("CremeCaramel") and (not is_letter or t.suit != SUIT_NONE):
        return True
    if has("SpicyPepper") and any(t.is_type(c) for c in colours.get("SpicyPepper", ())):
        if (not is_letter or rep != "s") and (g != G_CURRENCY or t.symbol != "$"):
            return True
    if has("Automobile") and any(t.is_type(c) for c in colours.get("Automobile", ())) and is_letter:
        return True
    if has("SluggishZombie") and is_letter and rep == "z":
        return True
    if has("Jellyfish") and is_letter and rep == "j":
        return True
    if has("CardShark"):
        suit = t.suit
        if suit == "clubs" and rep != "c":
            return True
        if suit == "diamonds" and rep != "d":
            return True
        if suit == "hearts" and rep != "h":
            return True
        if suit == "spades" and rep != "s" and t.symbol != "$":
            return True
    if has("Chameleon"):
        want = CHAMELEON.get(t.tile_type)
        if want is not None and rep != want and not (t.tile_type == "shiny" and t.symbol == "$"):
            return True
    if has("Queen") and is_letter and rep == "q":
        return True
    if has("Flamingo") and any(t.is_type(c) for c in colours.get("Flamingo", ())):
        if g not in (G_NUMBER, G_FRACTION):
            return True
        if g == G_NUMBER and t.number != 1:
            return True
        if g == G_FRACTION and 1 not in (t.fraction or ()):
            return True
    if has("Coral") and not t.is_type(NORMAL):
        if g not in (G_NUMBER, G_FRACTION):
            return True
        if g == G_NUMBER and t.number != -1:
            return True
        if g == G_FRACTION and -1 not in (t.fraction or ()):
            return True
    if has("TestTube") and t.is_number():
        return True
    if has("Syringe") and g == G_NUMBER:
        return True
    if has("Microscope") and t.value != 0:
        if g not in (G_NUMBER, G_FRACTION):
            return True
        if g == G_NUMBER and t.number != t.value:
            return True
        if g == G_FRACTION and t.value not in (t.fraction or ()):
            return True
    if has("NumbersBunchOfGrapes") and g == G_NUMBER and t.number in (1, 5, 10):
        return True
    return False
