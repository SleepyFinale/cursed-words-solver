"""``EncounterController`` port: one encounter (or one Michael phase) end to end.

Scoring is the engine (``engine.calc.EnginePlan``) fed the simulator's state as
``game_state/1``; everything around scoring is ported here: grid counts, rerolls,
start-of-grid viz-step effects, consumable placement, Capybara shuffles, Cable Car,
glitch settling, per-step money / rack / item side effects, accumulator items,
payouts, Michael's drafted phases and the finale puzzle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import GridData, Rng, Tile
from cursed_words_solver.sim.game.grid_util import GenCtx, add_tile_to_array, remove_tile_from_array
from cursed_words_solver.sim.game.gridgen import generate_grid
from cursed_words_solver.sim.game.items import Item, make_item
from cursed_words_solver.sim.game.player import (
    GRIDS_PER_ROUND,
    GRID_DIMENSION,
    MICHAEL_STAGE,
    BossModifier,
    HistoricWord,
    Node,
    restore_meg_inventory,
)

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.engine.calc import EngineResult
    from cursed_words_solver.sim.game.run import Game

# engine Ctx state key -> game field name, per class where ambiguous.
_STATE_TO_FIELD = {
    "distance": "Distance",
    "bonus": None,  # WordScoreBonus or Bonus (by class)
    "count": None,  # MulticolouredWordsSubmitted or Count (by class)
    "current_word": "CurrentWord",
    "used": "ConsumableTilesUsed",
    "freezes": "Freezes",
    "dice_number": "_diceNumber",
    "target_number": "_targetNumber",
    "selected_piece": "_selectedPiece",
    "chosen_curse": "ChosenCurseType",
    "mushy": "IsMushy",
    "glitch_used": "NumberOfGlitchTilesUsed",
    "broken": "IsBroken",
    "letter_counts": "LetterUseCounts",
    "red_count": "RedCount",
    "blue_used": "BlueTilesUsed",
}
_COUNT_FIELD = {"Neapolitan": "MulticolouredWordsSubmitted", "CreakyChair": "MulticolouredWordsSubmitted"}
_BONUS_FIELD = {"Lollipop": "Bonus"}


def write_back_state(item: Item, state: dict[str, Any]) -> None:
    for key, value in state.items():
        field_name = _STATE_TO_FIELD.get(key, "?")
        if key == "count":
            field_name = _COUNT_FIELD.get(item.game_class, "Count")
        elif key == "bonus":
            field_name = _BONUS_FIELD.get(item.game_class, "WordScoreBonus")
        if field_name and field_name != "?":
            item.fields[field_name] = value


@dataclass
class SubmitResult:
    score: int
    words: list[str]
    remaining_target: int
    money_before: int
    money_after: int
    won: bool = False
    lost: bool = False
    nondeterministic: bool = False
    payout: int = 0
    steps: list[Any] = field(default_factory=list)


class Encounter:
    """One ``EncounterScene`` visit (all grids of one encounter)."""

    def __init__(self, game: "Game") -> None:
        self.game = game
        self.player = game.player
        self.rng: Rng = game.rng
        self.bosses: list[BossModifier] = []
        self.previous_words: list[HistoricWord] = []
        self.grid = GridData()
        self.total_target = 0
        self.remaining_target = 0
        self.total_grids = GRIDS_PER_ROUND
        self.remaining_grids = GRIDS_PER_ROUND
        self.rerolls = 1
        self.reroll_tracker = 0
        self.twinkle_available = False
        self.awaiting_forced_sell = False
        self.entered_with_no_money = False
        self.piggy_savings = 0
        self.earnings: dict[str, int] = {}
        self.won = False
        self.lost = False
        self.lost_reason = ""
        self.payout = 0
        self.michael: BossModifier | None = None
        self.michael_draft: list[BossModifier] | None = None
        self.finale = False
        self.run_won = False

    # ------------------------------------------------------------------ queries

    @property
    def grids_generated(self) -> int:
        """``CurrentGridsGenerated``."""
        return self.total_grids - self.remaining_grids

    def boss_active(self, cls: str) -> bool:
        return any(b.game_class == cls for b in self.bosses)

    def boss(self, cls: str) -> BossModifier | None:
        return next((b for b in self.bosses if b.game_class == cls), None)

    def grid_dims(self) -> tuple[int, int]:
        """``GetGridDimensions``."""
        w = h = GRID_DIMENSION
        if self.player.run.challenge_is("CallOfTheVoid"):
            w += 1
            h += 1
        bat = self.boss("SmallGrid")
        if bat is not None:
            for i in range(bat.floor_mod + 1):
                if i % 2 == 0:
                    h -= 1
                else:
                    w -= 1
        return w, h

    @property
    def can_submit(self) -> bool:
        return not (self.won or self.lost or self.awaiting_forced_sell or self.michael_draft is not None)

    # ------------------------------------------------------------------ setup

    def start(self) -> None:
        """``EncounterController.Start`` + ``GameSetup``."""
        player, run = self.player, self.player.run
        if run.node == Node.ENCOUNTER_FIRST:
            if run.stage == 1:
                player.piggy_bank = 0
            else:
                self.piggy_savings = 2 * player.piggy_bank
                player.piggy_bank = 0
                player.change_money(self.piggy_savings)
        self.entered_with_no_money = player.money == 0
        self.setup()

    def setup(self) -> None:
        player, run, rng = self.player, self.player.run, self.rng
        if run.stage == MICHAEL_STAGE and run.node == Node.BOSS:
            self.michael = player.active_bosses[0] if player.active_bosses else None
            m = self.michael
            if m is not None:
                self.total_target = run.current_encounter_target(player)
                self.remaining_target = self.total_target
                self.rerolls = 1
                self.reroll_tracker = 0
                if not m.drafts:
                    populate_michael_drafts(m, rng)
                if "DestroyGrid" in [b.game_class for b in m.drafted]:
                    next(b for b in m.drafted if b.game_class == "DestroyGrid").fields["DestroyedCoordinates"] = []
                if len(m.drafted) < m.floor_mod:
                    self.michael_draft = list(m.drafts[len(m.drafted)])
                    return  # wait for choose_michael_draft()
        self._setup_rest()

    def choose_michael_draft(self, index: int) -> None:
        assert self.michael is not None and self.michael_draft is not None
        pick = self.michael_draft[index]
        self.michael.drafted.append(pick)
        self.michael_draft = None
        self.bosses = list(self.michael.drafted)
        if len(self.michael.drafted) == 1:
            self.player.run.stats.bosses.append("MichaelBoss")
        self._setup_rest()

    def _setup_rest(self) -> None:
        player, run, rng = self.player, self.player.run, self.rng
        if run.node == Node.BOSS and (not player.active_bosses or player.active_bosses[0].game_class != "MichaelBoss"):
            self.bosses = list(player.active_bosses)
            player.bosses_faced.extend(b.game_class for b in self.bosses)
            run.stats.bosses.extend(b.game_class for b in self.bosses)
            player.active_bosses = []
            hyena = self.boss("ForcedSell")
            if hyena is not None:
                sellable = [i for i in player.all_items(for_comparison=True) if i.rarity != "Unique" and not i.selling_prevented]
                stickers = [i for i in player.stickers_list(for_comparison=True) if i.rarity != "Unique" and not i.selling_prevented]
                if (hyena.floor_mod == 1 and sellable) or (hyena.floor_mod == 2 and stickers):
                    self.awaiting_forced_sell = True
        for it in player.all_items_including_nested(for_comparison=False):
            it.start_of_encounter(player, rng)
        self.total_target = run.current_encounter_target(player)
        self.remaining_target = self.total_target
        self.rerolls = 1
        badger = self.boss("FewerGrids")
        total = GRIDS_PER_ROUND - (badger.floor_mod if badger is not None else 0)
        for diya in player.unpacked_of("Diya"):
            total += 1
            if player.is_hb_favourite_stamp(diya) and player.pin is not None and player.pin.var(1) > 1:
                total += player.pin.var(1) - 1
            overhand = next((s for s in player.stickers if s is not None and s.game_class == "Overhand"), None)
            if overhand is not None and player.is_overhand_target(diya):
                total += overhand.var(0)
        if run.asc(7):
            total -= 1
        self.total_grids = total
        self.remaining_grids = total
        self.build_grid()

    # ------------------------------------------------------------------ grids

    def _gen(self, is_reroll: bool, static: list[Tile] | None) -> GenCtx:
        if not is_reroll:
            self.remaining_grids -= 1
        w, h = self.grid_dims()
        g = GenCtx(
            player=self.player,
            rng=self.rng,
            grid=self.grid,
            grid_number=self.grids_generated,
            number_of_grids=self.total_grids,
            previous_words=self.previous_words,
            is_reroll=is_reroll,
            word_source=self.game.random_word,
        )
        generate_grid(g, w, h, self.bosses, static)
        return g

    def _apply_viz(self, g: GenCtx) -> None:
        """``ShowGridGenerationViz`` side effects."""
        player = self.player
        if g.money_change:
            player.change_money(g.money_change)
        for k, v in g.earnings.items():
            self.earnings[k] = self.earnings.get(k, 0) + v
        self.rerolls += g.rerolls_change
        for it in g.items_to_remove:
            player.remove_item(it)
        player.consumables = list(g.rack)
        self.grid = g.grid
        whale = self.boss("BigBoss")
        if whale is not None and self.total_grids - 1 == self.remaining_grids and self.reroll_tracker == 0:
            self.total_target = int(round(float(self.total_target) * (whale.floor_mod / 100.0)))
            self.remaining_target = self.total_target
        if player.unpacked_of("TwinkleToes"):
            self.twinkle_available = True

    def build_grid(self) -> None:
        """``BuildGrid`` (new grid, not a reroll)."""
        g = self._gen(False, None)
        self._apply_viz(g)
        if g.grid.has_lost_challenge:
            self.lost = True
            self.lost_reason = "challenge"

    def can_reroll(self) -> bool:
        if not self.can_submit or self.rerolls <= 0 or self.finale:
            return False
        if self.player.unpacked_of("Wheel") and self.player.money < 1:
            return False
        return True

    def reroll(self) -> bool:
        """``TryReroll``."""
        if not self.can_reroll():
            return False
        player = self.player
        if player.unpacked_of("Wheel"):
            player.change_money(-1)
        for coaster in player.unpacked_of("Rollercoaster"):
            rollercoaster_check(player, self.rng)
        self.rerolls -= 1
        self.reroll_tracker += 1
        static: list[Tile] = []
        for fan in player.unpacked_of("Fan"):
            if fan.relevant_colours:
                static.extend(t for t in self.grid.available() if t.is_type(fan.relevant_colours[0]))
        g = self._gen(True, static or None)
        self._apply_viz(g)
        return True

    # ------------------------------------------------------------------ actions

    def place_consumable(self, rack_index: int, x: int, y: int) -> bool:
        """``GridLayoutController.ApplyConsumableTile``."""
        if not self.can_submit or self.finale:
            return False
        player = self.player
        if not (0 <= rack_index < len(player.consumables)):
            return False
        src = player.consumables[rack_index]
        target = self.grid.available_at(x, y)
        if src is None or target is None or not target.consumable_replacement_allowed(player):
            return False
        # ItemReorderController: picking up a rack tile rolls Piece of Cake (50% to keep it).
        src.safe_from_destruction = bool(player.unpacked_of("PieceOfCake")) and self.rng.range(0, 2) == 0
        new = src.get_copy(True)
        new.x, new.y = target.x, target.y
        run = player.run
        if run.challenge_is("SupplyAndDemand") and run.stats.words_submitted:
            reps = {t.srep() for t in run.stats.words_submitted[-1].tiles}
            new.crossed_out = new.srep() in reps
        self.grid.tiles[self.grid.tiles.index(target)] = new
        player.consumables = remove_tile_from_array(player, src, True, player.consumables)
        return True

    def twinkle_swap(self, a: tuple[int, int], b: tuple[int, int]) -> bool:
        if not self.twinkle_available or a == b:
            return False
        ta, tb = self.grid.at(*a), self.grid.at(*b)
        if ta is None or tb is None:
            return False
        na, nb = Tile(), Tile()
        na.set_as_copy(tb, False)
        nb.set_as_copy(ta, False)
        na.x, na.y = ta.x, ta.y
        nb.x, nb.y = tb.x, tb.y
        self.grid.tiles[self.grid.tiles.index(ta)] = na
        self.grid.tiles[self.grid.tiles.index(tb)] = nb
        self.twinkle_available = False
        return True

    def sell(self, item: Item) -> int:
        """Sell during the encounter (also clears Hyena's forced sell)."""
        from cursed_words_solver.sim.game.shop import sell_item

        gained = sell_item(self.player, item, self.rng, encounter=self)
        if gained is None:
            return 0
        hyena = self.boss("ForcedSell")
        if self.awaiting_forced_sell and hyena is not None:
            if hyena.floor_mod == 1 or item.components:
                self.awaiting_forced_sell = False
        if item.game_class == "TwinkleToes":
            self.twinkle_available = False
        return gained

    # ------------------------------------------------------------------ scoring

    def score_preview(self, path: list[tuple[int, int]], words: list[str]) -> "EngineResult":
        from cursed_words_solver.engine.calc import EnginePlan
        from cursed_words_solver.sim.game.bridge import board_and_loadout, coords_to_index

        board, loadout = board_and_loadout(self)
        plan = EnginePlan.build(board, loadout)
        idx = [coords_to_index(self, x, y) for x, y in path]
        return plan.score(idx, " ".join(words), words=[w.lower() for w in words])

    def _settle_glitch(self, tiles: list[Tile]) -> None:
        """``ScoreCalculation.SettleGlitchTiles``."""
        rng = self.rng
        types = [C.NORMAL, C.BLUE, C.CACTUS, C.GOLD, C.GREEN, C.PURPLE, C.PINK, C.WHITE, C.RED, C.VOID, C.SHINY]
        for t in tiles:
            if not t.is_type(C.GLITCH):
                continue
            t.tile_type = types[rng.range(0, len(types))]
            suited = rng.range(0, 4) < 1
            kind = rng.range(0, 8)
            if suited:
                t.set_suit(C.random_card_suit(rng))
            if kind == 0:
                t.set_to_random_letter(rng)
            elif kind == 1:
                t.set_to_random_currency(rng)
            elif kind == 2:
                t.set_to_random_fraction(rng)
            elif kind == 3:
                t.set_to_random_number(rng)
            elif kind == 4:
                t.set_glyph(C.G_BLANK)
            elif kind == 5:
                t.set_to_random_item(rng, self.player)
            elif kind == 6:
                t.set_to_random_chess(rng)
            elif kind == 7:
                t.set_glyph(C.G_CARD)
                t.set_suit(C.SUIT_JOKER)
            t.was_glitch = True

    def submit(self, path: list[tuple[int, int]], words: list[str]) -> SubmitResult:
        """``SubmitWord`` → ``ShowScoreCalculation`` → ``TryGoToNextGrid``."""
        if not self.can_submit:
            raise RuntimeError("cannot submit now")
        player, run, rng = self.player, self.player.run, self.rng
        words = [w.lower() for w in words]
        tiles = [self.grid.at(x, y) for x, y in path]
        if any(t is None for t in tiles):
            raise ValueError("path leaves the grid")
        money_before = player.money

        if self.finale:
            return self._submit_finale(tiles, words, money_before)

        capy = self.boss("RandomiseItemOrder")
        if capy is not None:
            player.randomise_item_order(rng, capy.floor_mod == 2)
        self._settle_glitch(tiles)

        # The engine applies Cable Car to its copies of the path's scattered stickers
        # (captures are pre-submit), so persist the upgrade only after scoring.
        result = self.score_preview(path, words)
        cable_cars = len(player.unpacked_of("CableCar"))
        if cable_cars:
            for t in tiles:
                if t.get_glyph() == C.G_ITEM and t.item is not None and t.item.is_sticker:
                    for _ in range(cable_cars):
                        t.item.upgrade(0)
        score = int(result.int_score)
        if run.challenge_is("TwoWrongs"):
            score = -score
        new_remaining = self.remaining_target - score
        if run.challenge_is("Bullseye"):
            new_remaining = abs(new_remaining)

        values = [t.get_value(player) for t in tiles]
        wobbly = [t.is_variable_letter(player) for t in tiles]
        hw = HistoricWord(
            tiles=tiles, words=words, skipped=False, score=score, remainder=new_remaining,
            submitted_round=self.grids_generated, dims=(self.grid.width, self.grid.height),
            wobbly=wobbly, values=values,
        )
        self.previous_words.append(hw)
        run.stats.words_submitted.append(hw)

        self._apply_step_effects(result, tiles, words)
        self._post_submit_items(result, tiles, words)

        self.remaining_target = new_remaining
        res = SubmitResult(
            score=score, words=words, remaining_target=new_remaining,
            money_before=money_before, money_after=player.money,
            nondeterministic=result.nondeterministic, steps=result.steps,
        )
        self._try_next_grid(res)
        res.money_after = player.money
        return res

    def _apply_step_effects(self, result: "EngineResult", tiles: list[Tile], words: list[str]) -> None:
        """Per-step money, piggy bank, rack and inventory changes (``DisplayScoreSteps``)."""
        player, rng = self.player, self.rng
        steps = result.steps
        # Piggy bank: pink tiles bank $1 each while money remains (after currency).
        pinks = sum(1 for t in tiles if t.tile_type == C.PINK)
        if pinks:
            m = player.money
            fox = self.boss("StealsMoney")
            if fox is not None and m > 0:
                m = max(m - fox.floor_mod, 0)
            kokeshi = bool(player.unpacked_of("KokeshiDolls"))
            for t in tiles:
                if t.get_glyph() == C.G_CURRENCY:
                    m += C.LETTER_VALUES.get(C.CURRENCY_LETTERS.get(t.letter, ""), 1) if kokeshi else 1
            player.piggy_bank += min(pinks, m)
        if steps:
            final_money = int(steps[-1].money)
            if final_money != player.money:
                player.change_money(final_money - player.money)
        # Persistent counters on inventory items.
        by_slug: dict[str, Item] = {}
        for it in player.all_items(for_comparison=True):
            by_slug.setdefault(it.slug, it)
        for slug, state in (result.final_states or {}).items():
            it = by_slug.get(slug)
            if it is not None and isinstance(state, dict):
                write_back_state(it, state)
        # Rack-changing items, in scoring order (scattered path items, then inventory).
        order: list[Item] = [t.item for t in tiles if t.get_glyph() == C.G_ITEM and t.item is not None]
        order += player.all_items()
        rack = list(player.consumables)
        took_first = False
        for it in order:
            cls = it.game_class
            if cls == "HiVisJacket":
                held = [t for t in rack if t is not None]
                if held:
                    rack = remove_tile_from_array(player, held[rng.range(0, len(held))], False, rack)
            elif cls == "BarOfSoap" and tiles:
                types = []
                for t in tiles:
                    if t.tile_type != C.NORMAL and t.tile_type not in types:
                        types.append(t.tile_type)
                for _ in types:
                    blank = Tile()
                    blank.tile_type = it.relevant_colours[0] if it.relevant_colours else C.SHINY
                    blank.set_glyph(C.G_BLANK)
                    rack = add_tile_to_array(player, blank, rack)
            elif cls == "GoldenRecord" and tiles:
                cp = tiles[rng.range(0, len(tiles))].get_copy(True)
                cp.already_on_rack = False
                rack = add_tile_to_array(player, cp, rack)
            elif cls == "JollyRoger" and not took_first:
                took_first = True
                taken = _first_take(self, tiles)
                if taken is not None:
                    cp = taken.get_copy(True)
                    cp.already_on_rack = False
                    rack = add_tile_to_array(player, cp, rack)
            elif cls == "Microphone":
                add_cls = microphone_item(words, player)
                if add_cls and add_cls not in {i.game_class for i in player.all_items()}:
                    player.add_item(make_item(add_cls), rng)
        player.consumables = rack

    def _post_submit_items(self, result: "EngineResult", tiles: list[Tile], words: list[str]) -> None:
        """Accumulator items the engine does not track (Bar Chart, Book of Openings, ...)."""
        player, run = self.player, self.player.run
        single = words[0] if len(words) == 1 else None
        for it in player.all_items_including_nested():
            cls = it.game_class
            if cls == "BarChart" and single in it.WORDS:
                it.fields["NumbersFound"][it.WORDS.index(single)] += 1
            elif cls == "ChessStrategyGuide" and single in it.WORDS:
                it.fields["PiecesFound"][it.WORDS.index(single)] += 1
            elif cls == "FlashyFountainPen" and single is not None:
                order = ("red", "blue", "void", "shiny", "purple", "gold", "white", "cactus", "green", "pink", "glitch")
                for colour in order:
                    if single == colour:
                        if colour == "pink" and run.challenge is not None:
                            break
                        it.fields[it.FIELD[colour]] += 1
                        if colour in ("purple", "gold", "white", "cactus", "green", "pink"):
                            run.add_available_colour(colour)
                        break
            elif cls == "MichaelsBook":
                cur = str(it.fields.get("CurrentWord", "")).lower()
                if cur and cur in words:
                    length = int(it.fields.get("WordLength", len(cur))) + 1
                    nxt = self.game.random_word(length)
                    if nxt is None:
                        length -= 1
                        nxt = self.game.random_word(length)
                    it.fields["WordLength"] = length
                    it.fields["CurrentWord"] = nxt or cur
                    it.words_at_level.setdefault(it.level(0), []).append(it.fields["CurrentWord"])

    def skip(self) -> SubmitResult:
        """``SkipWordSubmission``."""
        if not self.can_submit:
            raise RuntimeError("cannot skip now")
        hw = HistoricWord(
            tiles=[], words=[""], skipped=True, score=0, remainder=self.remaining_target,
            submitted_round=self.grids_generated, dims=(self.grid.width, self.grid.height),
        )
        self.previous_words.append(hw)
        res = SubmitResult(0, [], self.remaining_target, self.player.money, self.player.money)
        self._try_next_grid(res)
        res.money_after = self.player.money
        return res

    # ------------------------------------------------------------------ resolution

    def _try_next_grid(self, res: SubmitResult) -> None:
        """``TryGoToNextGrid``."""
        player, run = self.player, self.player.run
        if self.remaining_target <= 0:
            m = self.michael
            if m is not None and len(m.drafted) < m.floor_mod:
                self._setup_next_michael_phase()
                return
            if m is not None:
                m.summoned_defeated = True
                self.finale = True
                self.bosses = [m]
                return
            if run.is_final_stage() and (run.ascension < 1 or player.has_faced_uncursed_boss):
                self.won = True
                self.run_won = True
                res.won = True
                return
            self.won = True
            res.won = True
            if any(b.cursed for b in self.bosses) and run.ascension > 0:
                run.cursed_bosses_defeated.append(run.stage - 1)
            if run.challenge_is("Embargo") and not run.is_final_stage() and run.node == Node.BOSS:
                refund = 0
                for it in player.all_items(for_comparison=True):
                    refund += sum(it.money_invested)
                    run.embargoed.add(it.game_class)
                player.stickers = [None] * 5
                player.stamps = [None] * 5
                player.change_money(refund)
            dnpg = run.challenge_is("DoNotPassGo")
            unused = self.remaining_grids
            boss = run.node == Node.BOSS
            interest = 0
            dragons = player.unpacked_of("Dragon")
            if dragons:
                basis = player.money + (0 if dnpg else 10 + unused * 2 + (5 if boss else 0))
                interest = len(dragons) * int(float(basis) * 0.1)
            before = player.money
            if not dnpg:
                player.change_money(10 + unused * 2)
                if boss:
                    player.change_money(5)
                if interest > 0:
                    player.change_money(interest)
            meg = self.boss("CretaceousMegBoss")
            if boss and meg is not None:
                restore_meg_inventory(meg, player, self.rng)
            self.payout = player.money - before
            res.payout = self.payout
            return
        if self.remaining_grids <= 0:
            self.lost = True
            self.lost_reason = "out_of_grids"
            res.lost = True
            return
        self.build_grid()
        if self.lost:
            res.lost = True

    def _setup_next_michael_phase(self) -> None:
        # Same EncounterController between phases: _previousWords carry over.
        self.setup()

    def _submit_finale(self, tiles: list[Tile], words: list[str], money_before: int) -> SubmitResult:
        """Michael's 25-tile puzzle grid: any valid all-tile word wins the run."""
        avail = self.grid.available()
        if len(tiles) < len(avail):
            raise ValueError("the finale needs every tile")
        self.won = True
        self.run_won = True
        return SubmitResult(0, words, -1, money_before, self.player.money, won=True)

    def finale_solution(self) -> tuple[list[tuple[int, int]], list[str]] | None:
        return getattr(self, "_finale_answer", None)


# ---------------------------------------------------------------------------- helpers


def _first_take(enc: Encounter, tiles: list[Tile]) -> Tile | None:
    """First chess take on the path (Jolly Roger copies the taken piece)."""
    for i in range(1, len(tiles)):
        prev, cur = tiles[i - 1], tiles[i]
        if prev.get_glyph() == C.G_CHESS and cur.get_glyph() == C.G_CHESS and (cur.white != prev.white or enc.player.unpacked_of("KingOfTheBridge")):
            return cur
    return None


def rollercoaster_check(player, rng: Rng) -> None:
    """``Rollercoaster.MakeRollercoasterCheck``: 1 in 10 upgrades a random upgradeable sticker."""
    if rng.range(0, 10) != 0:
        return
    cands = [s for s in player.stickers_list(for_comparison=True) if s.can_be_upgraded(player.max_upgrade_count(s))]
    if cands:
        pick = cands[rng.range(0, len(cands))]
        pick.upgrade(0, rng=rng, player=player)
        pick.times_upgraded += 1


def populate_michael_drafts(m: BossModifier, rng: Rng) -> None:
    """``MichaelBoss.PopulateModifierDrafts``."""
    from cursed_words_solver.sim.game.player import boss_rows

    pool = [BossModifier(b) for b in boss_rows() if b != "MichaelBoss"]
    pool = [b for b in pool if b.summonable]
    if rng.range(0, 2) == 0:
        pool = [b for b in pool if b.game_class != "MinWordLength"]
    else:
        pool = [b for b in pool if b.game_class != "MaxWordLength"]
    m.drafts = []
    for n in range(m.floor_mod):
        pair = []
        for _ in range(2):
            b = pool.pop(rng.range(0, len(pool)))
            b.set_floor(5 - n, False)
            pair.append(b)
        m.drafts.append(pair)


def microphone_tables(player) -> tuple[dict[str, str], dict[str, str]]:
    """``Microphone.GetAccumulatorWords`` / ``GetAccumulatorPairs``: names of un-owned pool
    items (stamps while a stamp slot is free, stickers while a sticker slot is free)."""
    from cursed_words_solver.sim.game.items import catalog_rows
    from cursed_words_solver.sim.game.pools import stamp_pool, sticker_pool

    rows = catalog_rows()
    owned = {i.game_class for i in player.all_items()}
    single: dict[str, str] = {}
    pairs: dict[str, str] = {}
    pools = []
    if len(player.stamps_list(for_comparison=True)) < 5:
        pools.append(stamp_pool())
    if len(player.stickers_list(for_comparison=True)) < 5:
        pools.append(sticker_pool())
    for pool in pools:
        for cls in pool:
            if cls in owned:
                continue
            name = str(rows[cls].get("name") or cls).lower()
            if " " not in name:
                single[name] = cls
            elif name.count(" ") == 1:
                pairs[name] = cls
    return single, pairs


def microphone_item(words: list[str], player=None) -> str | None:
    """``Microphone.ApplyWordBonus``: submitting an item's name adds it."""
    if player is None:
        return None
    single, pairs = microphone_tables(player)
    if len(words) == 1:
        return single.get(words[0])
    if len(words) == 2:
        return pairs.get(" ".join(words))
    return None
