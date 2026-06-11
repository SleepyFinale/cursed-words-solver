using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class HistoricWord
{
	public List<TileSelection> TileSelections;

	public List<Tile> Tiles;

	public List<bool> Wobbly;

	public List<string> Words;

	public bool IsWordSkipped;

	public ScorePacket Score;

	public ScorePacket Remainder;

	public int SubmittedRound;

	public Vector2Int GridDimensions;

	public HistoricWord(List<TileSelection> tiles, List<string> words, bool isWordSkipped, ScorePacket score, ScorePacket remainder, int submittedRound, Vector2Int gridDimensions)
	{
		TileSelections = tiles;
		Tiles = tiles.Select((TileSelection tile) => tile.SelectedTile).ToList();
		Words = words;
		IsWordSkipped = isWordSkipped;
		Score = score;
		Remainder = remainder;
		SubmittedRound = submittedRound;
		GridDimensions = gridDimensions;
		Wobbly = new List<bool>();
		foreach (Tile tile in Tiles)
		{
			Wobbly.Add(tile.IsDisplayingAsVariableLetter());
		}
	}

	public HistoricWord(List<Tile> tiles, List<string> words, bool isWordSkipped)
	{
		TileSelections = tiles.Select((Tile tile) => new TileSelection(tile, TileSelectionMethod.None, isWobbly: false)).ToList();
		Tiles = tiles;
		Words = words;
		IsWordSkipped = isWordSkipped;
	}

	public CurseLevel GetCurseLevel()
	{
		int num = 0;
		for (int i = 0; i < Tiles.Count; i++)
		{
			if (Tiles[i].GetGlyphType() != GlyphType.Letter || Wobbly[i])
			{
				num++;
			}
		}
		if (num != 0)
		{
			if (num >= 3)
			{
				return CurseLevel.Major;
			}
			return CurseLevel.Minor;
		}
		return CurseLevel.Normal;
	}

	public string GetSubmittedWordString()
	{
		string text = "";
		foreach (Tile tile in Tiles)
		{
			text = ((tile.GetGlyphType() != GlyphType.Letter) ? (text + tile.GetStringRepresentation()) : (text + tile.GetStringRepresentation().ToUpper()));
		}
		return text;
	}
}
