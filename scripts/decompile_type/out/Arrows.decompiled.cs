using System;
using System.Collections.Generic;
using UnityEngine;

public static class Arrows
{
	public static List<string> ArrowStrings = new List<string> { "↑", "→", "↓", "←", "↖", "↗", "↘", "↙" };

	public static Dictionary<string, Vector2Int> ArrowDirections = new Dictionary<string, Vector2Int>
	{
		{
			"↑",
			new Vector2Int(0, 1)
		},
		{
			"→",
			new Vector2Int(1, 0)
		},
		{
			"↓",
			new Vector2Int(0, -1)
		},
		{
			"←",
			new Vector2Int(-1, 0)
		},
		{
			"↖",
			new Vector2Int(-1, 1)
		},
		{
			"↗",
			new Vector2Int(1, 1)
		},
		{
			"↘",
			new Vector2Int(1, -1)
		},
		{
			"↙",
			new Vector2Int(-1, -1)
		}
	};

	public static List<string> GetPossibleArrows(Vector2Int coordinates, GridData grid)
	{
		List<string> list = new List<string>();
		foreach (KeyValuePair<string, Vector2Int> arrowDirection in ArrowDirections)
		{
			if (GetTilesPointedAt(arrowDirection.Key, coordinates, grid).Count >= 2)
			{
				list.Add(arrowDirection.Key);
			}
		}
		return list;
	}

	public static List<Tile> GetTilesPointedAt(string arrow, Vector2Int coordinates, GridData grid)
	{
		bool flag = GameStatics.GetPlayer().GetAllItems().Exists((Item item) => item is HungrySnake);
		Vector2Int dimensions = grid.GetDimensions();
		List<Tile> list = new List<Tile>();
		Vector2Int vector2Int = ArrowDirections[arrow];
		Vector2Int vector2Int2 = coordinates + vector2Int;
		for (int i = 0; i < Math.Max(dimensions.x, dimensions.y); i++)
		{
			Tile availableTileAtCoordinates = grid.GetAvailableTileAtCoordinates(vector2Int2.x, vector2Int2.y);
			if (availableTileAtCoordinates != null && availableTileAtCoordinates.GetCoordinates() != coordinates && !list.Contains(availableTileAtCoordinates))
			{
				list.Add(availableTileAtCoordinates);
			}
			if (flag && availableTileAtCoordinates == null)
			{
				vector2Int2 = new Vector2Int((vector2Int2.x + dimensions.x) % dimensions.x, vector2Int2.y);
				Tile availableTileAtCoordinates2 = grid.GetAvailableTileAtCoordinates(vector2Int2.x, vector2Int2.y);
				if (availableTileAtCoordinates2 != null && availableTileAtCoordinates2.GetCoordinates() != coordinates && !list.Contains(availableTileAtCoordinates2))
				{
					list.Add(availableTileAtCoordinates2);
				}
			}
			vector2Int2 += vector2Int;
		}
		return list;
	}
}
