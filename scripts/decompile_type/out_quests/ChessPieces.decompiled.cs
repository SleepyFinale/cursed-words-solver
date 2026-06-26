using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class ChessPieces
{
	private static List<ChessPiece> AllChessPieces = new List<ChessPiece>
	{
		ChessPiece.Pawn,
		ChessPiece.Knight,
		ChessPiece.Bishop,
		ChessPiece.Rook,
		ChessPiece.Queen,
		ChessPiece.King
	};

	public static Dictionary<ChessPiece, string> ChessFontLettersBlack = new Dictionary<ChessPiece, string>
	{
		{
			ChessPiece.None,
			""
		},
		{
			ChessPiece.Pawn,
			"o"
		},
		{
			ChessPiece.Knight,
			"j"
		},
		{
			ChessPiece.Bishop,
			"n"
		},
		{
			ChessPiece.Rook,
			"t"
		},
		{
			ChessPiece.Queen,
			"w"
		},
		{
			ChessPiece.King,
			"l"
		}
	};

	public static Dictionary<ChessPiece, string> ChessFontLettersWhite = new Dictionary<ChessPiece, string>
	{
		{
			ChessPiece.None,
			""
		},
		{
			ChessPiece.Pawn,
			"p"
		},
		{
			ChessPiece.Knight,
			"h"
		},
		{
			ChessPiece.Bishop,
			"b"
		},
		{
			ChessPiece.Rook,
			"r"
		},
		{
			ChessPiece.Queen,
			"q"
		},
		{
			ChessPiece.King,
			"k"
		}
	};

	public static Dictionary<ChessPiece, string> ChessComparisonLetters = new Dictionary<ChessPiece, string>
	{
		{
			ChessPiece.Queen,
			"q"
		},
		{
			ChessPiece.King,
			"k"
		}
	};

	public static (ChessPiece piece, bool isWhite) GetRandomChessPiece()
	{
		return (piece: AllChessPieces[UnityEngine.Random.Range(0, AllChessPieces.Count)], isWhite: UnityEngine.Random.Range(0, 2) == 0);
	}

	public static (ChessPiece piece, bool isWhite) GetRandomChessPiece(System.Random seed)
	{
		return (piece: AllChessPieces[seed.Next(0, AllChessPieces.Count)], isWhite: seed.Next(0, 2) == 0);
	}

	public static string GetFontTaggedChessIcon(ChessPiece piece, bool isBlack = false)
	{
		if (isBlack)
		{
			return "<font=ChessPiece SDF>" + ChessFontLettersBlack[piece] + "</font>";
		}
		return "<font=ChessPiece SDF>" + ChessFontLettersWhite[piece] + "</font>";
	}

	public static List<TileSelection> GetValidChessMoves(GridData gridData, List<Item> inventory, Tile tile, TileSelectionManager tileSelectionManager = null, bool isCheckingAgainstKing = false)
	{
		bool hasHungrySnake = inventory.Exists((Item item) => item is HungrySnake);
		bool allowFriendlyCapture = inventory.Exists((Item item) => item is KingOfTheBridge);
		if (tile.PieceType == ChessPiece.Pawn)
		{
			return GetPawnMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
		}
		if (tile.PieceType == ChessPiece.Knight)
		{
			return GetKnightMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
		}
		if (tile.PieceType == ChessPiece.Bishop)
		{
			return GetBishopMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
		}
		if (tile.PieceType == ChessPiece.Rook)
		{
			return GetRookMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
		}
		if (tile.PieceType == ChessPiece.Queen)
		{
			List<TileSelection> bishopMoves = GetBishopMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
			List<Tile> bishopTiles = bishopMoves.Select((TileSelection tile) => tile.SelectedTile).ToList();
			bishopMoves.AddRange(from tile in GetRookMoves(gridData, tileSelectionManager, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture)
				where !bishopTiles.Contains(tile.SelectedTile)
				select tile);
			return bishopMoves;
		}
		if (tile.PieceType == ChessPiece.King)
		{
			return GetKingMoves(gridData, tileSelectionManager, inventory, tile, isCheckingAgainstKing, hasHungrySnake, allowFriendlyCapture);
		}
		return new List<TileSelection>();
	}

	private static List<TileSelection> GetPawnMoves(GridData gridData, TileSelectionManager tileSelectionManager, Tile tile, bool isCheckingAgainstKing, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		List<TileSelection> validTiles = new List<TileSelection>();
		Vector2Int coordinates = tile.Coordinates;
		Vector2Int dimensions = gridData.GetDimensions();
		bool flag = (tile.IsWhitePiece && coordinates.y == 1) || (!tile.IsWhitePiece && coordinates.y == dimensions.y - 2);
		bool flag2 = (tile.IsWhitePiece && coordinates.y == dimensions.y - 4) || (!tile.IsWhitePiece && coordinates.y == 3);
		List<Vector2Int> obj = new List<Vector2Int>
		{
			new Vector2Int(1, 1),
			new Vector2Int(-1, 1)
		};
		Vector2Int vector2Int = (tile.IsWhitePiece ? (coordinates + new Vector2Int(0, 1)) : (coordinates - new Vector2Int(0, 1)));
		Tile tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
		if (gridData.IsValidCoordinate(vector2Int) && tileAtCoordinates.GetGlyphType() != GlyphType.Chess && !isCheckingAgainstKing)
		{
			validTiles.Add(new TileSelection(tileAtCoordinates, TileSelectionMethod.ChessMove, tileAtCoordinates.IsDisplayingAsVariableLetter(tileSelectionManager)));
			if (flag)
			{
				vector2Int = (tile.IsWhitePiece ? (vector2Int + new Vector2Int(0, 1)) : (vector2Int - new Vector2Int(0, 1)));
				tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
				if (gridData.IsValidCoordinate(vector2Int) && tileAtCoordinates.GetGlyphType() != GlyphType.Chess)
				{
					validTiles.Add(new TileSelection(tileAtCoordinates, TileSelectionMethod.ChessMove, tileAtCoordinates.IsDisplayingAsVariableLetter(tileSelectionManager)));
				}
			}
		}
		foreach (Vector2Int item in obj)
		{
			vector2Int = (tile.IsWhitePiece ? (coordinates + item) : (coordinates - item));
			if (hasHungrySnake)
			{
				vector2Int = new Vector2Int((vector2Int.x + dimensions.x) % dimensions.x, vector2Int.y);
			}
			if (gridData.IsValidCoordinate(vector2Int))
			{
				tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
				Tile tileAtCoordinates2 = gridData.GetTileAtCoordinates(tile.IsWhitePiece ? (vector2Int - new Vector2Int(0, 1)) : (vector2Int + new Vector2Int(0, 1)));
				bool num = tileAtCoordinates.GetGlyphType() == GlyphType.Chess && (tileAtCoordinates.IsWhitePiece != tile.IsWhitePiece || allowFriendlyCapture);
				bool flag3 = flag2 && tileAtCoordinates2.GetGlyphType() == GlyphType.Chess && tileAtCoordinates2.PieceType == ChessPiece.Pawn && tileAtCoordinates2.IsWhitePiece != tile.IsWhitePiece && tileAtCoordinates.GetGlyphType() != GlyphType.Chess && !isCheckingAgainstKing;
				TileSelectionMethod selectionMethod = (flag3 ? TileSelectionMethod.EnPassant : TileSelectionMethod.ChessTake);
				Tile enPassantedTile = (flag3 ? tileAtCoordinates2 : null);
				if (num || flag3 || isCheckingAgainstKing)
				{
					validTiles.Add(new TileSelection(tileAtCoordinates, selectionMethod, tileAtCoordinates.IsDisplayingAsVariableLetter(tileSelectionManager), enPassantedTile));
				}
			}
		}
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Television)).Count > 0)
		{
			List<TileSelection> collection = (from tile in gridData.GetAvailableTiles()
				where tile.GetGlyphType() == GlyphType.ScatteredItem && !validTiles.Exists((TileSelection validTile) => validTile.SelectedTile == tile)
				select new TileSelection(tile, TileSelectionMethod.Television, isWobbly: false)).ToList();
			validTiles.AddRange(collection);
		}
		return validTiles;
	}

	private static List<TileSelection> GetRookMoves(GridData gridData, TileSelectionManager tileSelectionManager, Tile tile, bool isCheckingAgainstKing, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		List<TileSelection> list = new List<TileSelection>();
		Vector2Int dimensions = gridData.GetDimensions();
		foreach (Vector2Int item in new List<Vector2Int>
		{
			new Vector2Int(0, 1),
			new Vector2Int(1, 0),
			new Vector2Int(0, -1),
			new Vector2Int(-1, 0)
		})
		{
			int num = 0;
			Vector2Int vector2Int = tile.Coordinates;
			while (num < 100)
			{
				num++;
				vector2Int += item;
				if (hasHungrySnake)
				{
					vector2Int = new Vector2Int((vector2Int.x + dimensions.x) % dimensions.x, vector2Int.y);
				}
				if (!gridData.IsValidCoordinate(vector2Int) || vector2Int.Equals(tile.Coordinates))
				{
					break;
				}
				Tile tileToCheck = gridData.GetTileAtCoordinates(vector2Int);
				TileSelection tileSelection = null;
				if (tileToCheck.GetGlyphType() == GlyphType.Chess)
				{
					if (tileToCheck.IsWhitePiece != tile.IsWhitePiece || allowFriendlyCapture || isCheckingAgainstKing)
					{
						tileSelection = list.Find((TileSelection selection) => selection.SelectedTile == tileToCheck);
						if (tileSelection != null)
						{
							tileSelection.MoveDistance = Mathf.Max(num, tileSelection.MoveDistance);
						}
						else
						{
							list.Add(new TileSelection(tileToCheck, TileSelectionMethod.ChessTake, tileToCheck.IsDisplayingAsVariableLetter(tileSelectionManager), null, num));
						}
					}
					break;
				}
				tileSelection = list.Find((TileSelection selection) => selection.SelectedTile == tileToCheck);
				if (tileSelection != null)
				{
					tileSelection.MoveDistance = Mathf.Max(num, tileSelection.MoveDistance);
				}
				else
				{
					list.Add(new TileSelection(tileToCheck, TileSelectionMethod.ChessMove, tileToCheck.IsDisplayingAsVariableLetter(tileSelectionManager), null, num));
				}
			}
		}
		return list;
	}

	public static List<TileSelection> GetKnightMoves(GridData gridData, TileSelectionManager tileSelectionManager, Tile tile, bool isCheckingAgainstKing, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		List<TileSelection> list = new List<TileSelection>();
		Vector2Int coordinates = tile.Coordinates;
		Vector2Int dimensions = gridData.GetDimensions();
		foreach (Vector2Int item in new List<Vector2Int>
		{
			new Vector2Int(1, 2),
			new Vector2Int(-1, 2),
			new Vector2Int(1, -2),
			new Vector2Int(-1, -2),
			new Vector2Int(2, 1),
			new Vector2Int(-2, 1),
			new Vector2Int(2, -1),
			new Vector2Int(-2, -1)
		})
		{
			Vector2Int vector2Int = coordinates + item;
			if (hasHungrySnake)
			{
				vector2Int = new Vector2Int((vector2Int.x + dimensions.x) % dimensions.x, vector2Int.y);
			}
			if (gridData.IsValidCoordinate(vector2Int))
			{
				Tile tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
				bool flag = tileAtCoordinates.GetGlyphType() == GlyphType.Chess;
				if (!flag || tile.GetGlyphType() != GlyphType.Chess || tileAtCoordinates.IsWhitePiece != tile.IsWhitePiece || allowFriendlyCapture || isCheckingAgainstKing)
				{
					list.Add(new TileSelection(tileAtCoordinates, flag ? TileSelectionMethod.ChessTake : TileSelectionMethod.ChessMove, tileAtCoordinates.IsDisplayingAsVariableLetter(tileSelectionManager)));
				}
			}
		}
		return list;
	}

	private static List<TileSelection> GetBishopMoves(GridData gridData, TileSelectionManager tileSelectionManager, Tile tile, bool isCheckingAgainstKing, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		List<TileSelection> list = new List<TileSelection>();
		Vector2Int dimensions = gridData.GetDimensions();
		foreach (Vector2Int item in new List<Vector2Int>
		{
			new Vector2Int(1, 1),
			new Vector2Int(-1, 1),
			new Vector2Int(1, -1),
			new Vector2Int(-1, -1)
		})
		{
			int num = 0;
			Vector2Int vector2Int = tile.Coordinates;
			while (num < 100)
			{
				num++;
				vector2Int += item;
				if (hasHungrySnake)
				{
					vector2Int = new Vector2Int((vector2Int.x + dimensions.x) % dimensions.x, vector2Int.y);
				}
				if (!gridData.IsValidCoordinate(vector2Int) || vector2Int.Equals(tile.Coordinates))
				{
					break;
				}
				Tile tileToCheck = gridData.GetTileAtCoordinates(vector2Int);
				TileSelection tileSelection = null;
				if (tileToCheck.GetGlyphType() == GlyphType.Chess)
				{
					if (tileToCheck.IsWhitePiece != tile.IsWhitePiece || allowFriendlyCapture || isCheckingAgainstKing)
					{
						tileSelection = list.Find((TileSelection selection) => selection.SelectedTile == tileToCheck);
						if (tileSelection != null)
						{
							tileSelection.MoveDistance = Mathf.Max(num, tileSelection.MoveDistance);
						}
						else
						{
							list.Add(new TileSelection(tileToCheck, TileSelectionMethod.ChessTake, tileToCheck.IsDisplayingAsVariableLetter(tileSelectionManager), null, num));
						}
					}
					break;
				}
				tileSelection = list.Find((TileSelection selection) => selection.SelectedTile == tileToCheck);
				if (tileSelection != null)
				{
					tileSelection.MoveDistance = Mathf.Max(num, tileSelection.MoveDistance);
				}
				else
				{
					list.Add(new TileSelection(tileToCheck, TileSelectionMethod.ChessMove, tileToCheck.IsDisplayingAsVariableLetter(tileSelectionManager), null, num));
				}
			}
		}
		return list;
	}

	private static List<TileSelection> GetKingMoves(GridData gridData, TileSelectionManager tileSelectionManager, List<Item> inventory, Tile tile, bool isCheckingAgainstKing, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		GameStatics.GetPlayer().GetAllItems();
		bool flag = inventory.Exists((Item item) => item is Television);
		bool flag2 = inventory.Exists((Item item) => item is KingOfTheBridge);
		List<TileSelection> list = (from tile in GridUtility.Singleton.GetTilesAdjacentToCoordinates(gridData, tile.Coordinates, hasHungrySnake)
			select new TileSelection(tile, (tile.GetGlyphType() == GlyphType.Chess) ? TileSelectionMethod.ChessTake : TileSelectionMethod.ChessMove, tile.IsDisplayingAsVariableLetter(tileSelectionManager))).ToList();
		if (isCheckingAgainstKing)
		{
			if (flag)
			{
				HashSet<Tile> selectedTiles2 = new HashSet<Tile>(list.Select((TileSelection vt) => vt.SelectedTile));
				List<TileSelection> collection = (from tile in gridData.GetAvailableTiles()
					where tile.GetGlyphType() == GlyphType.ScatteredItem && !selectedTiles2.Contains(tile)
					select new TileSelection(tile, TileSelectionMethod.Television, tile.IsDisplayingAsVariableLetter(tileSelectionManager))).ToList();
				list.AddRange(collection);
			}
			return list;
		}
		HashSet<Tile> checkmatePositions = new HashSet<Tile>(GetCheckmatePositions(gridData, tileSelectionManager, inventory, tile));
		list = (from validTile in list
			where validTile.SelectedTile.GetGlyphType() != GlyphType.Chess || validTile.SelectedTile.IsWhitePiece != tile.IsWhitePiece || allowFriendlyCapture
			where !checkmatePositions.Contains(validTile.SelectedTile)
			select validTile).ToList();
		if (flag2)
		{
			HashSet<Tile> friendlyThreats = new HashSet<Tile>(GetCheckmatePositions(gridData, tileSelectionManager, inventory, tile, includeFriendly: true));
			list = list.Where((TileSelection v) => !friendlyThreats.Contains(v.SelectedTile)).ToList();
		}
		if (flag)
		{
			HashSet<Tile> selectedTiles = new HashSet<Tile>(list.Select((TileSelection vt) => vt.SelectedTile));
			List<TileSelection> collection2 = (from tile in gridData.GetAvailableTiles()
				where tile.GetGlyphType() == GlyphType.ScatteredItem && !selectedTiles.Contains(tile)
				select new TileSelection(tile, TileSelectionMethod.Television, tile.IsDisplayingAsVariableLetter(tileSelectionManager))).ToList();
			list.AddRange(collection2);
		}
		return list;
	}

	public static List<Tile> GetCheckmatePositions(GridData gridData, TileSelectionManager tileSelectionManager, List<Item> inventory, Tile tile, bool includeFriendly = false)
	{
		List<Tile> list = new List<Tile>();
		foreach (Tile item in from t in gridData.GetTiles()
			where t.GetGlyphType() == GlyphType.Chess && (includeFriendly ? (t.IsWhitePiece == tile.IsWhitePiece) : (t.IsWhitePiece != tile.IsWhitePiece)) && t != tile
			select t)
		{
			GridData gridData2 = new GridData();
			gridData2.SetDimensions(gridData.GetDimensions());
			gridData2.GridTiles = (Tile[])gridData.GridTiles.Clone();
			Tile tile2 = new Tile();
			tile2.SetGlyphType(GlyphType.Blank);
			tile2.SetCoordinates(tile.Coordinates);
			gridData2.GridTiles[Array.IndexOf(gridData2.GridTiles, tile)] = tile2;
			Debug.Log($"Checking checkmate positions for {item.PieceType} at {item.GetCoordinates()}");
			foreach (Tile item2 in from move in GetValidChessMoves(gridData2, inventory, item, tileSelectionManager, isCheckingAgainstKing: true)
				select move.SelectedTile)
			{
				Debug.Log($"It is protecting the {item2.GetStringRepresentation()} tile at {item2.GetCoordinates()}");
			}
			list.AddRange(from move in GetValidChessMoves(gridData2, inventory, item, tileSelectionManager, isCheckingAgainstKing: true)
				select move.SelectedTile);
		}
		return list;
	}
}
