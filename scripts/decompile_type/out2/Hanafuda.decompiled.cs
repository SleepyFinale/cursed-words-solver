using System;
using System.Collections.Generic;
using System.Linq;

public class Hanafuda : Item
{
	public Hanafuda()
	{
		Name = "Hanafuda";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Hanafuda"));
		Rarity = ItemRarity.Common;
		Cost = 10;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 12, 12)
		};
		Tags = new List<ItemTag> { ItemTag.CardsBuild };
		DependencyTags = new List<ItemTag> { ItemTag.CardsGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificAdditive };
	}

	public override string GetDescription()
	{
		string text = ((UpgradeableComponents[0].Level == 1) ? "Pair" : ((UpgradeableComponents[0].Level == 2) ? "Three Of A Kind" : "Four Of A Kind"));
		return $"If you submit a {GameStatics.ZeroWidthCharacter}{text}{GameStatics.ZeroWidthCharacter} ({Math.Min(4, UpgradeableComponents[0].Level + 1)} matching letters with suits), get {GameStatics.ZeroWidthCharacter}+{UpgradeableComponents[0].VariableValue}{GameStatics.ZeroWidthCharacter} WORD SCORE for each unused card on the grid";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		List<Tile> list = ((UpgradeableComponents[0].Level == 1) ? PokerHands.GetXOfAKind(2, tiles) : ((UpgradeableComponents[0].Level == 2) ? PokerHands.GetXOfAKind(3, tiles) : PokerHands.GetXOfAKind(4, tiles)));
		if (list != null)
		{
			step.PokerHand = ((UpgradeableComponents[0].Level == 1) ? PokerHand.Pair : ((UpgradeableComponents[0].Level == 2) ? PokerHand.ThreeOfAKind : PokerHand.FourOfAKind));
			step.PokerHandTiles = list;
			step.LettersInWordToPulse.AddRange(list);
			List<Tile> list2 = (from tile in gridData.GetAvailableTiles()
				where tile.CardSuit != 0 && !tiles.Contains(tile)
				select tile).ToList();
			if (list2.Count > 0)
			{
				step.WordBonus = new WordBonusToken(list2.Count * UpgradeableComponents[0].VariableValue, isMultiplicative: false);
				step.LettersOnGridToPulse.AddRange(list2);
			}
		}
	}
}
