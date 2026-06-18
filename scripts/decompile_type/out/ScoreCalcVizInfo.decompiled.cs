using System;
using System.Collections.Generic;

public class ScoreCalcVizInfo
{
	public List<ScorePacket> TileScores = new List<ScorePacket>();

	public List<int?> TileScoreMultipliers = new List<int?>();

	public List<float?> TileScoreMultiplierFloats = new List<float?>();

	public bool IsUsingFloatMultipliers;

	public WordBonusToken WordBonus;

	public Item RelevantItem;

	public List<Tile> LettersInWordToPulse = new List<Tile>();

	public List<Tile> LettersOnGridToPulse = new List<Tile>();

	public Tile[] PlayerConsumableTiles = new Tile[10];

	public Dictionary<string, int> EarningsBreakdown = new Dictionary<string, int>();

	public int Money;

	public bool IsPulsingWholeWord;

	public bool IsPulsingMoney;

	public Type BossModifierToPulse;

	public bool IsPulsingGridNumber;

	public bool IsPulsingConsumableTiles;

	public int GridNumberChange;

	public List<Tile> PokerHandTiles;

	public PokerHand PokerHand;

	public bool IsShowingTakes;

	public bool IsSettlingGlitchTiles;

	public List<Tile> TilesToRepopulate;

	public List<TileSelection> WordTileSelections;

	public Type ItemTypeToAddToInventory;

	public void SetWordBonus(WordBonusToken bonus)
	{
		WordBonus = bonus;
	}

	public ScoreCalcVizInfo GetMatchingStep()
	{
		ScoreCalcVizInfo scoreCalcVizInfo = new ScoreCalcVizInfo();
		scoreCalcVizInfo.TileScores = new List<ScorePacket>(TileScores);
		scoreCalcVizInfo.Money = Money;
		scoreCalcVizInfo.PlayerConsumableTiles = new Tile[10];
		Array.Copy(PlayerConsumableTiles, scoreCalcVizInfo.PlayerConsumableTiles, 10);
		for (int i = 0; i < TileScores.Count; i++)
		{
			scoreCalcVizInfo.TileScoreMultipliers.Add(null);
			scoreCalcVizInfo.TileScoreMultiplierFloats.Add(null);
		}
		return scoreCalcVizInfo;
	}
}
