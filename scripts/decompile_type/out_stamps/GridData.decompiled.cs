using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

[Serializable]
public class GridData
{
	public Tile[] GridTiles;

	public Vector2Int Dimensions;

	public bool HasLostChallenge;

	public int GridNumber;

	public Tile[] GetTiles()
	{
		return GridTiles;
	}

	public List<Tile> GetAvailableTiles()
	{
		return (from tile in GridTiles.ToList()
			where !tile.IsInTheVoid && !tile.HasBeenDestroyed
			select tile).ToList();
	}

	public Tile GetTileAtCoordinates(int x, int y)
	{
		return Array.Find(GridTiles, (Tile tile) => tile.GetCoordinates().x == x && tile.GetCoordinates().y == y);
	}

	public Tile GetTileAtCoordinates(Vector2Int coordinates)
	{
		return Array.Find(GridTiles, (Tile tile) => tile.GetCoordinates().x == coordinates.x && tile.GetCoordinates().y == coordinates.y);
	}

	public Tile GetAvailableTileAtCoordinates(int x, int y)
	{
		Tile tileAtCoordinates = GetTileAtCoordinates(x, y);
		if (tileAtCoordinates != null && !tileAtCoordinates.IsInTheVoid && !tileAtCoordinates.HasBeenDestroyed)
		{
			return tileAtCoordinates;
		}
		return null;
	}

	public Vector2Int GetDimensions()
	{
		return Dimensions;
	}

	public void SetDimensions(Vector2Int dimensions)
	{
		Dimensions = dimensions;
	}

	public bool IsValidCoordinate(Vector2Int coord)
	{
		return IsValidCoordinate(coord.x, coord.y);
	}

	public bool IsValidCoordinate(int x, int y)
	{
		if (x >= 0 && x < Dimensions.x && y >= 0)
		{
			return y < Dimensions.y;
		}
		return false;
	}
}
