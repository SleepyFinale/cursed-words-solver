using System.Collections.Generic;

public class FairyGrid
{
	public GridData Grid;

	public List<Tile> Solution;

	public string SolutionWord;

	public FairyGrid(GridData grid, List<Tile> word, string solutionWord)
	{
		Grid = grid;
		Solution = word;
		SolutionWord = solutionWord;
	}
}
