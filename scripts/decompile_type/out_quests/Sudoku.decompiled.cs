using System.Collections.Generic;

public class Sudoku : ChallengeRun
{
	public Sudoku()
	{
		ChallengeName = "Advent Calendar";
		Description = "Grids naturally generate the numbers 1 - 25.";
	}

	public override List<Tile> GetChallengeRunStartingConsumableTiles()
	{
		List<Tile> list = new List<Tile>();
		for (int i = 1; i < 6; i++)
		{
			Tile tile = new Tile();
			tile.SetNumber(i);
			tile.SetTileToBeConsumable();
			list.Add(tile);
		}
		return list;
	}
}
