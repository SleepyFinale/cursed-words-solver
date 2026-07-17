using System.Collections.Generic;

public class Egg : Item
{
	public Egg()
	{
		Name = "Egg";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Egg"));
		Rarity = ItemRarity.Common;
		Cost = 13;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 50, 150)
		};
		IsFood = true;
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericMultiplier };
	}

	public override string GetDescription()
	{
		return $"If your word starts with a vowel, get {GameStatics.ZeroWidthCharacter}×{(float)UpgradeableComponents[0].VariableValue / 100f}{GameStatics.ZeroWidthCharacter} WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (tiles.Count != 0 && Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.IsVowel(tiles[0].GetStringRepresentation()))
		{
			step.WordBonus = new WordBonusToken(UpgradeableComponents[0].VariableValue, isMultiplicative: true);
			Tile item = tiles[0];
			step.LettersInWordToPulse.Add(item);
			step.LettersOnGridToPulse.Add(item);
		}
	}
}
