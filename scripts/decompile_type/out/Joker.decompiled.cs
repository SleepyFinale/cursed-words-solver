using System.Collections.Generic;

public class Joker : Item
{
	public Joker()
	{
		Name = "Joker";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Joker"));
		Rarity = ItemRarity.Common;
		Cost = 12;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 1, 1)
		};
		Tags = new List<ItemTag>
		{
			ItemTag.CardsBuild,
			ItemTag.CardsGenerator
		};
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.Scatterer };
	}

	public override string GetDescription()
	{
		return $"START OF GRID: Scatters {GameStatics.ZeroWidthCharacter}{UpgradeableComponents[0].VariableValue}{GameStatics.ZeroWidthCharacter} <font=NotoEmoji-Regular SDF>\ud83c\udccf\ufe0e</font>";
	}

	public override GridData ApplyStartOfGridEffect(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps, bool isReroll)
	{
		List<Tile> list = new List<Tile>();
		for (int i = 0; i < UpgradeableComponents[0].VariableValue; i++)
		{
			Tile tileForItemScatter = GridUtility.Singleton.GetTileForItemScatter(gridData, TileType.Normal, GlyphType.BespokeCard, null, isSuited: true);
			if (tileForItemScatter != null)
			{
				tileForItemScatter.SetGlyphType(GlyphType.BespokeCard);
				tileForItemScatter.SetSuit(Suit.Joker);
				list.Add(tileForItemScatter);
			}
		}
		if (list.Count > 0)
		{
			vizSteps.Add(new BoardGenVizInfo(gridData, this, list, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles));
		}
		return gridData;
	}
}
