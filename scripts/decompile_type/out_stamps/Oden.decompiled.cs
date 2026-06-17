using System.Collections.Generic;

public class Oden : Item
{
	public Oden()
	{
		Name = "Oden";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Oden"));
		Rarity = ItemRarity.Rare;
		Cost = 18;
		IsFood = true;
		Tags = new List<ItemTag> { ItemTag.CurseBuild };
		DependencyTags = new List<ItemTag> { ItemTag.CurseGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificMultiplier };
	}

	public override string GetDescription()
	{
		return "Get WORD SCORE × number of unique curse types";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		List<Tile> list = new List<Tile>();
		List<CurseType> list2 = new List<CurseType>();
		foreach (TileSelection selection in selections)
		{
			foreach (CurseType curseType in selection.GetCurseTypes())
			{
				if (!list2.Contains(curseType) && curseType != CurseType.None)
				{
					list.Add(selection.SelectedTile);
					list2.Add(curseType);
				}
			}
		}
		if (list2.Count != 1)
		{
			step.WordBonus = new WordBonusToken(100 * list2.Count, isMultiplicative: true);
			if (list.Count > 0)
			{
				step.LettersInWordToPulse.AddRange(list);
				step.LettersOnGridToPulse.AddRange(list);
			}
		}
	}
}
