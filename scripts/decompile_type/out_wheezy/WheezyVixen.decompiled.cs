using System.Collections.Generic;

public class WheezyVixen : Item
{
	public WheezyVixen()
	{
		Name = "Wheezy Vixen";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "WheezyVixen"));
		Rarity = ItemRarity.Common;
		Cost = 12;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 1, 2)
		};
		IsAnimal = true;
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericMultiplier };
	}

	public override string GetDescription()
	{
		return $"If your word starts with a letter V, W, X, Y or Z, get {GameStatics.ZeroWidthCharacter}×{UpgradeableComponents[0].VariableValue}{GameStatics.ZeroWidthCharacter} WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (tiles.Count != 0 && new List<string> { "v", "w", "x", "y", "z" }.Contains(tiles[0].GetStringRepresentation()))
		{
			step.WordBonus = new WordBonusToken(UpgradeableComponents[0].VariableValue * 100, isMultiplicative: true);
			step.LettersInWordToPulse.Add(tiles[0]);
		}
	}
}
