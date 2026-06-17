using System.Collections.Generic;

public class TileSelection
{
	public Tile SelectedTile;

	public TileSelectionMethod SelectionMethod;

	public Tile EnPassantedTile;

	public bool IsWobbly;

	public int MoveDistance;

	public TileSelection(Tile selectedTile, TileSelectionMethod selectionMethod, bool isWobbly, Tile enPassantedTile = null, int moveDistance = 0)
	{
		SelectedTile = selectedTile;
		SelectionMethod = selectionMethod;
		IsWobbly = isWobbly;
		EnPassantedTile = enPassantedTile;
		MoveDistance = moveDistance;
	}

	public bool IsCursed()
	{
		if (!IsWobbly)
		{
			return SelectedTile.IsCursed();
		}
		return true;
	}

	public List<CurseType> GetCurseTypes()
	{
		List<CurseType> curseTypes = SelectedTile.GetCurseTypes();
		if (IsWobbly && !curseTypes.Contains(CurseType.Wobbly))
		{
			curseTypes.Add(CurseType.Wobbly);
		}
		return curseTypes;
	}
}
