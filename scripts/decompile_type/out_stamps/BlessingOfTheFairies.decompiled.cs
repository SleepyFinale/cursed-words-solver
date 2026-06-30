using System.Collections.Generic;

public class BlessingOfTheFairies : Item
{
	public int ConsumableTilesUsed;

	public BlessingOfTheFairies()
	{
		Name = "Blessing of the Fairies";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "BlessingOfTheFairies"));
		Rarity = ItemRarity.Rare;
		Cost = 20;
		Tags = new List<ItemTag>();
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericMultiplier };
	}

	public override string GetDescription()
	{
		Player player = GameStatics.GetPlayer();
		if (player != null && player.CurrentRunProgress != null)
		{
			int count = player.CurrentRunProgress.CursedBossesDefeated.Count;
			return $"Get x{(float)(100 + 50 * count) / 100f} WORD SCORE (0.5 extra for each fairy)";
		}
		return "Get x1 WORD SCORE (0.5 extra for each fairy)";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		int count = GameStatics.GetPlayer().CurrentRunProgress.CursedBossesDefeated.Count;
		step.WordBonus = new WordBonusToken(100 + 50 * count, isMultiplicative: true);
	}
}
