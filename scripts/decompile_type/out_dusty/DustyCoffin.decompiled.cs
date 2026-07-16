using System.Collections.Generic;
using System.Linq;

public class DustyCoffin : Item
{
	public DustyCoffin()
	{
		Name = "Dusty Coffin";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "DustyCoffin"));
		Rarity = ItemRarity.Common;
		Cost = 12;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 8, 8)
		};
		Tags = new List<ItemTag> { ItemTag.VoidBuild };
		DependencyTags = new List<ItemTag> { ItemTag.VoidGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificAdditive };
		RelevantColours = new List<TileType> { TileType.Void };
	}

	public override string GetDescription()
	{
		return $"For each {Tile.ChangeTileTypeToString(RelevantColours[0])} tile on the grid whose letter does not appear in your word, get {GameStatics.ZeroWidthCharacter}+{UpgradeableComponents[0].VariableValue}{GameStatics.ZeroWidthCharacter} WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		List<Tile> list = (from tile in gridData.GetAvailableTiles()
			where tile.IsTileType(RelevantColours[0])
			select tile).ToList();
		List<Tile> list2 = new List<Tile>();
		List<string> list3 = tiles.Select((Tile tile) => tile.GetStringRepresentation()).ToList();
		foreach (Tile item in list)
		{
			if (!list3.Contains(item.GetStringRepresentation()))
			{
				list2.Add(item);
			}
		}
		if (list2.Count > 0)
		{
			step.SetWordBonus(new WordBonusToken(UpgradeableComponents[0].VariableValue * list2.Count, isMultiplicative: false));
			step.LettersOnGridToPulse.AddRange(list2);
		}
	}
}
