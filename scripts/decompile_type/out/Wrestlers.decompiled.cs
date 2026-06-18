using System.Collections.Generic;
using UnityEngine;

public class Wrestlers : Item
{
	public Wrestlers()
	{
		Name = "Wrestlers";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Wrestlers"));
		Rarity = ItemRarity.Common;
		Cost = 10;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 50, 150)
		};
		Tags = new List<ItemTag> { ItemTag.CardsBuild };
		DependencyTags = new List<ItemTag> { ItemTag.CardsGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificMultiplier };
	}

	public override string GetDescription()
	{
		return $"If your word starts and ends on different suits, get {GameStatics.ZeroWidthCharacter}×{(float)UpgradeableComponents[0].VariableValue / 100f}{GameStatics.ZeroWidthCharacter} WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (step == null)
		{
			Debug.LogError("Error: 'step' is null in ApplyWordBonus.");
		}
		else if (UpgradeableComponents == null || UpgradeableComponents.Count == 0 || UpgradeableComponents[0] == null)
		{
			Debug.LogError("Error: 'UpgradeableComponents' is null, empty, or its first element is null.");
		}
		else if (tiles != null && tiles.Count != 0 && tiles[0] != null && tiles[tiles.Count - 1] != null)
		{
			Tile tile = tiles[0];
			Tile tile2 = tiles[tiles.Count - 1];
			if (tile.CardSuit != 0 && tile2.CardSuit != 0 && (tile.CardSuit != tile2.CardSuit || tile.CardSuit == Suit.Joker))
			{
				step.WordBonus = new WordBonusToken(UpgradeableComponents[0].VariableValue, isMultiplicative: true);
				step.LettersInWordToPulse.AddRange(new List<Tile> { tile, tile2 });
			}
		}
	}
}
