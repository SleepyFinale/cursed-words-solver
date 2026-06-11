using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

[Serializable]
public class Tile
{
	public GlyphType MyGlyphType = GlyphType.Letter;

	public string Letter;

	public int Number = -1000;

	public List<int> FractionNumbers = new List<int>();

	public Suit CardSuit;

	public ChessPiece PieceType;

	public bool IsWhitePiece;

	public Item ScatteredItem;

	public TileType MyTileType;

	public ScorePacket ValueModifier = new ScorePacket(0L);

	public ScorePacket CactusGrowth = new ScorePacket(0L);

	public bool IsEmptyTile;

	public Vector2Int Coordinates;

	public bool WasConsumable;

	public bool HasBeenDestroyed;

	public bool IsCrossedOut;

	public bool IsInTheVoid;

	public bool Gone;

	public bool IsInverted;

	public bool IsSellingPrevented;

	public bool IsNumberGoUpMiddleTile;

	public bool SafeFromDestruction;

	public bool WasGlitchTile;

	public bool AlreadyOnTileRack;

	public bool IsSandyBossTile;

	public static Dictionary<TileType, string> TileTypeToString = new Dictionary<TileType, string>
	{
		{
			TileType.Normal,
			"COLOURLESS"
		},
		{
			TileType.Red,
			"RED"
		},
		{
			TileType.Blue,
			"BLUE"
		},
		{
			TileType.Shiny,
			"SHINY"
		},
		{
			TileType.Void,
			"VOID"
		},
		{
			TileType.Cactus,
			"CACTUS"
		},
		{
			TileType.Pink,
			"PINK"
		},
		{
			TileType.Gold,
			"GOLD"
		},
		{
			TileType.Green,
			"GREEN"
		},
		{
			TileType.Purple,
			"PURPLE"
		},
		{
			TileType.White,
			"WHITE"
		},
		{
			TileType.Glitch,
			"GLITCH"
		}
	};

	public Tile(string letter, TileType tileType)
	{
		Letter = letter;
		MyTileType = tileType;
		Coordinates = new Vector2Int(-100, -100);
	}

	public Tile()
	{
	}

	public Tile GetCopy(bool isConsumable)
	{
		Tile tile = new Tile();
		tile.SetLetter(Letter);
		tile.SetNumber(Number);
		tile.SetFractionNumbers(FractionNumbers);
		tile.SetTileType(GetTileType());
		tile.SetCoordinates(new Vector2Int(Coordinates.x, Coordinates.y));
		tile.SetChessPiece(PieceType, IsWhitePiece);
		if (ScatteredItem != null)
		{
			Item item = Activator.CreateInstance(ScatteredItem.GetType()) as Item;
			if (ScatteredItem.UpgradeableComponents.Count > 0 && ScatteredItem.UpgradeableComponents[0].Level > 1)
			{
				for (int i = 0; i < ScatteredItem.UpgradeableComponents[0].Level - 1; i++)
				{
					item.Upgrade(0);
				}
			}
			tile.SetScatteredItem(item);
		}
		tile.SetGlyphType(MyGlyphType);
		tile.SetSuit(GetSuit());
		tile.ValueModifier = ValueModifier;
		tile.CactusGrowth = CactusGrowth;
		tile.WasConsumable = isConsumable;
		tile.AlreadyOnTileRack = AlreadyOnTileRack;
		tile.IsSandyBossTile = IsSandyBossTile;
		return tile;
	}

	public void SetAsCopy(Tile tileToCopy, bool changeCoords)
	{
		Letter = tileToCopy.Letter;
		Number = tileToCopy.Number;
		FractionNumbers = new List<int>(tileToCopy.FractionNumbers);
		PieceType = tileToCopy.PieceType;
		IsWhitePiece = tileToCopy.IsWhitePiece;
		MyTileType = tileToCopy.GetTileType();
		IsEmptyTile = tileToCopy.IsEmpty();
		if (tileToCopy.ScatteredItem != null)
		{
			Item item = Activator.CreateInstance(tileToCopy.ScatteredItem.GetType()) as Item;
			if (tileToCopy.ScatteredItem.UpgradeableComponents.Count > 0 && tileToCopy.ScatteredItem.UpgradeableComponents[0].Level > 1)
			{
				for (int i = 0; i < tileToCopy.ScatteredItem.UpgradeableComponents[0].Level - 1; i++)
				{
					item.Upgrade(0);
				}
			}
			ScatteredItem = item;
		}
		MyGlyphType = tileToCopy.GetGlyphType();
		if (changeCoords)
		{
			Coordinates = new Vector2Int(tileToCopy.Coordinates.x, tileToCopy.Coordinates.y);
		}
		SetSuit(tileToCopy.GetSuit());
		CactusGrowth = tileToCopy.CactusGrowth;
		ValueModifier = tileToCopy.ValueModifier;
		AlreadyOnTileRack = tileToCopy.AlreadyOnTileRack;
		IsSandyBossTile = tileToCopy.IsSandyBossTile;
	}

	public bool IsCopy(Tile tile)
	{
		if (MyGlyphType == tile.GetGlyphType() && GetStringRepresentation() == tile.GetStringRepresentation() && MyTileType == tile.GetTileType())
		{
			return CardSuit == tile.GetSuit();
		}
		return false;
	}

	public GlyphType GetGlyphType()
	{
		if (IsInTheVoid || Gone || HasBeenDestroyed)
		{
			return GlyphType.Letter;
		}
		return MyGlyphType;
	}

	public bool IsNumber()
	{
		if (MyGlyphType != GlyphType.Number)
		{
			return MyGlyphType == GlyphType.Fraction;
		}
		return true;
	}

	public bool IsChessPiece()
	{
		return MyGlyphType == GlyphType.Chess;
	}

	public void SetGlyphType(GlyphType glyphType)
	{
		MyGlyphType = glyphType;
		ValueModifier = new ScorePacket(0L);
		if (CardSuit == Suit.Joker)
		{
			CardSuit = Suit.None;
		}
	}

	public void SetSafeFromDestruction()
	{
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(PieceOfCake)).Count > 0 && UnityEngine.Random.Range(0, 2) == 0)
		{
			Debug.Log("SAFE FROM DESTRUCTION ACTIVATED ON TILE!");
			SafeFromDestruction = true;
		}
		else
		{
			SafeFromDestruction = false;
		}
	}

	public bool IsNumericWildcard(int index, InventoryCache inventoryCache)
	{
		List<int> list = new List<int> { index + 1 };
		if (inventoryCache.HasTestTube)
		{
			list.Add(index);
			list.Add(index + 2);
		}
		if (MyGlyphType == GlyphType.Number && list.Contains(Number))
		{
			return true;
		}
		if (MyGlyphType == GlyphType.Fraction && (list.Contains(FractionNumbers[0]) || list.Contains(FractionNumbers[1])))
		{
			return true;
		}
		if (inventoryCache.HasFlamingo && IsTileType(inventoryCache.FlamingoTileTypes[0]) && index == 0)
		{
			return true;
		}
		if (inventoryCache.HasMicroscope && new ScorePacket(index + 1) == GetValue())
		{
			return true;
		}
		return false;
	}

	public int GetNumber()
	{
		if (MyGlyphType == GlyphType.Number)
		{
			return Number;
		}
		throw new InvalidOperationException("Tile is not a number tile.");
	}

	public void SetNumber(int number)
	{
		SetGlyphType(GlyphType.Number);
		Number = number;
	}

	public void SetFractionNumbers(List<int> fractionNumbers)
	{
		SetGlyphType(GlyphType.Fraction);
		FractionNumbers = fractionNumbers;
	}

	public List<int> GetFractionNumbers()
	{
		if (MyGlyphType == GlyphType.Fraction)
		{
			return new List<int>(FractionNumbers);
		}
		throw new InvalidOperationException("Tile is not a fraction tile.");
	}

	public float GetFractionFloat()
	{
		if (MyGlyphType == GlyphType.Fraction)
		{
			return (float)FractionNumbers[0] / (float)FractionNumbers[1];
		}
		throw new InvalidOperationException("Tile is not a fraction tile.");
	}

	public float GetNumberFloat()
	{
		if (MyGlyphType == GlyphType.Number)
		{
			return Number;
		}
		return GetFractionFloat();
	}

	public void SetSuit(Suit suit)
	{
		if (GetGlyphType() != GlyphType.BespokeCard || suit == Suit.Joker)
		{
			CardSuit = suit;
		}
	}

	public Suit GetSuit()
	{
		return CardSuit;
	}

	public void SetChessPiece((ChessPiece piece, bool isWhite) pieceInfo)
	{
		SetChessPiece(pieceInfo.piece, pieceInfo.isWhite);
	}

	public void SetChessPiece(ChessPiece piece, bool isWhite)
	{
		if (piece != 0)
		{
			SetGlyphType(GlyphType.Chess);
			PieceType = piece;
			IsWhitePiece = isWhite;
		}
	}

	public void InvertChessPiece()
	{
		IsInverted = true;
	}

	public void SetCurrency(string currency)
	{
		SetGlyphType(GlyphType.Currency);
		Letter = currency;
	}

	public void SetScatteredItem(Item item)
	{
		SetGlyphType(GlyphType.ScatteredItem);
		ScatteredItem = item;
		_ = ScatteredItem.UpgradeableComponents.Count;
	}

	public bool IsBlank()
	{
		return MyGlyphType == GlyphType.Blank;
	}

	public bool IsWildcard(int index, List<Tile> tiles, InventoryCache inventoryCache)
	{
		if (MyGlyphType == GlyphType.Blank || MyGlyphType == GlyphType.Chess || MyGlyphType == GlyphType.Arrow || CardSuit == Suit.Joker || MyGlyphType == GlyphType.ScatteredItem)
		{
			return true;
		}
		if (inventoryCache.HasNumberGoUp && tiles[index].IsNumber())
		{
			bool flag = true;
			List<float> list = new List<float>();
			foreach (Tile tile in tiles)
			{
				if (tile.IsNumber())
				{
					if (tile.MyGlyphType == GlyphType.Number)
					{
						list.Add(tile.GetNumber());
					}
					else if (tile.MyGlyphType == GlyphType.Fraction)
					{
						list.Add((float)tile.GetFractionNumbers()[0] / (float)tile.GetFractionNumbers()[1]);
					}
				}
			}
			for (int i = 1; i < list.Count; i++)
			{
				if (list[i] <= list[i - 1])
				{
					flag = false;
					break;
				}
			}
			if (flag)
			{
				return true;
			}
		}
		return IsNumericWildcard(index, inventoryCache);
	}

	public bool IsEmpty()
	{
		return IsEmptyTile;
	}

	public void SetLetter(string letter)
	{
		SetGlyphType(GlyphType.Letter);
		Letter = letter;
		_ = GameStatics.GetPlayer().CurrentRunProgress;
	}

	public string GetStringRepresentation(bool forWordValidity = false)
	{
		if (MyGlyphType == GlyphType.BespokeCard && CardSuit == Suit.Joker)
		{
			if (!forWordValidity)
			{
				return "<font=NotoEmoji-Regular SDF>\ud83c\udccf\ufe0e</font>";
			}
			return "!";
		}
		if (MyGlyphType == GlyphType.Letter)
		{
			return Letter.ToLower();
		}
		if (MyGlyphType == GlyphType.Currency)
		{
			if (!forWordValidity)
			{
				return "<font=InterBold SDF>" + Letter + "</font>";
			}
			return Letter.ToLower();
		}
		if (MyGlyphType == GlyphType.Arrow)
		{
			if (!forWordValidity)
			{
				return "<font=Borel SDF>" + Letter + "</font>";
			}
			return Letter.ToLower();
		}
		if (MyGlyphType == GlyphType.Fraction)
		{
			if (forWordValidity)
			{
				return "!";
			}
			return Alphabet.GetFractionSymbol(FractionNumbers[0], FractionNumbers[1], isFontTagged: true) ?? "";
		}
		if (MyGlyphType == GlyphType.Number)
		{
			if (forWordValidity)
			{
				return "!";
			}
			return Number.ToString();
		}
		if (MyGlyphType == GlyphType.Chess)
		{
			if (forWordValidity)
			{
				return "!";
			}
			string text = (IsWhitePiece ? ChessPieces.ChessFontLettersWhite[PieceType] : ChessPieces.ChessFontLettersBlack[PieceType]);
			string text2 = "";
			string text3 = "";
			if (IsInverted)
			{
				text2 = "<rotate=180>";
				text3 = "</rotate>";
			}
			return text2 + "<font=ChessPiece SDF>" + text + "</font>" + text3;
		}
		if (MyGlyphType == GlyphType.Blank)
		{
			return "?";
		}
		if (MyGlyphType == GlyphType.ScatteredItem)
		{
			if (!forWordValidity)
			{
				return "<font=TwemojiMozillaAll>" + ScatteredItemPools.ScatteredItemEmojis[ScatteredItem.GetType()] + "</font>";
			}
			return "!";
		}
		if (MyGlyphType == GlyphType.None)
		{
			return "";
		}
		if (Letter != null)
		{
			return Letter.ToLower();
		}
		return Letter;
	}

	public void SetCrossedOut(bool isCrossedOut)
	{
		IsCrossedOut = isCrossedOut;
	}

	public ScorePacket GetValue()
	{
		if (GameStatics.GetPlayer() != null && GameStatics.GetPlayer().CurrentRunProgress != null && GameStatics.GetPlayer().CurrentRunProgress.Challenge is TheBonesRound)
		{
			return new ScorePacket(0L);
		}
		if (Gone || IsInTheVoid || HasBeenDestroyed)
		{
			return new ScorePacket(0L);
		}
		if (MyGlyphType == GlyphType.ScatteredItem)
		{
			return new ScorePacket(0L);
		}
		if (MyTileType == TileType.Shiny)
		{
			return new ScorePacket(50L);
		}
		foreach (Item item in GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Shield)))
		{
			if (IsTileType(item.RelevantColours[0]))
			{
				return new ScorePacket(item.UpgradeableComponents[0].VariableValue);
			}
		}
		if (MyTileType == TileType.Gold)
		{
			return new ScorePacket(GameStatics.GetPlayer().Money);
		}
		ScorePacket result = new ScorePacket(0L);
		if (MyGlyphType == GlyphType.Number)
		{
			result = new ScorePacket(Number);
		}
		else if (MyGlyphType == GlyphType.Fraction)
		{
			result = new ScorePacket(FractionNumbers.Sum());
		}
		else if (MyGlyphType == GlyphType.Letter)
		{
			result = new ScorePacket(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetLetterValue(GetStringRepresentation()));
		}
		else if (MyGlyphType == GlyphType.Chess)
		{
			result = new ScorePacket(Alphabet.GetChessValue(PieceType));
		}
		else if (MyGlyphType == GlyphType.Blank)
		{
			result = new ScorePacket(0L);
		}
		else if (MyGlyphType == GlyphType.Currency)
		{
			result = new ScorePacket(0L);
		}
		if (MyTileType == TileType.Red || MyTileType == TileType.Blue)
		{
			result += 1L;
		}
		else if (MyTileType == TileType.Purple)
		{
			result += 2L;
		}
		else if (MyTileType == TileType.Cactus)
		{
			result += CactusGrowth;
		}
		result += ValueModifier;
		if (MyTileType == TileType.Void)
		{
			result *= -1L;
		}
		return result;
	}

	public string GetSuitForDisplay()
	{
		if (CardSuit != 0 && CardSuit != Suit.Joker)
		{
			return "<font=ShipporiMinchoB1-Bold SDF>" + PlayingCardUtility.GetCharacterFromSuit(CardSuit) + "</font>";
		}
		return "";
	}

	public string GetValueForDisplay()
	{
		return GetValue().ToString();
	}

	public void SetCoordinates(Vector2Int coordinates)
	{
		Coordinates = coordinates;
	}

	public Vector2Int GetCoordinates()
	{
		return Coordinates;
	}

	public TileType GetTileType()
	{
		return MyTileType;
	}

	public bool IsTileType(TileType tileType)
	{
		if (MyTileType == TileType.Purple && (tileType == TileType.Red || tileType == TileType.Blue))
		{
			return true;
		}
		return MyTileType == tileType;
	}

	public void SetTileType(TileType tileType)
	{
		MyTileType = tileType;
	}

	public void SetIsEmpty(bool isEmpty)
	{
		if (isEmpty)
		{
			Letter = "";
		}
		IsEmptyTile = isEmpty;
	}

	public void SetTileToBeConsumable()
	{
		WasConsumable = true;
	}

	public void ChangeValueModifier(ScorePacket change)
	{
		ValueModifier += change;
	}

	public void MultiplyTileValue(int multiplier)
	{
		GetValue();
		if (MyTileType == TileType.Void)
		{
			ValueModifier -= GetValue() * (multiplier - 1);
		}
		else
		{
			ValueModifier += GetValue() * (multiplier - 1);
		}
	}

	public bool IsDisplayingAsVariableLetter(TileSelectionManager tileSelectionManager = null)
	{
		if (MyGlyphType == GlyphType.Blank || MyGlyphType == GlyphType.Chess || CardSuit == Suit.Joker || MyGlyphType == GlyphType.Arrow || MyGlyphType == GlyphType.ScatteredItem)
		{
			return false;
		}
		List<Item> allItems = GameStatics.GetPlayer().GetAllItems();
		if (tileSelectionManager == null)
		{
			UnityEngine.Object.FindFirstObjectByType<TileSelectionManager>();
		}
		if (tileSelectionManager != null)
		{
			foreach (Tile tilesFromSelectedTile in tileSelectionManager.GetTilesFromSelectedTiles())
			{
				if (tilesFromSelectedTile.GetGlyphType() == GlyphType.ScatteredItem)
				{
					allItems.Add(tilesFromSelectedTile.ScatteredItem);
				}
			}
		}
		Item item2 = allItems.Find((Item item) => item is RandomAccessMemory);
		Item item3 = allItems.Find((Item item) => item is Snapshot);
		List<Item> list = allItems.Where((Item item) => item is Frankenstein).ToList();
		if (item2 != null)
		{
			RandomAccessMemory randomAccessMemory = item2 as RandomAccessMemory;
			allItems.AddRange(randomAccessMemory.ItemsInMemory);
		}
		if (item3 != null)
		{
			Snapshot snapshot = item3 as Snapshot;
			if (snapshot.SnapshottedItem != null)
			{
				allItems.Add(snapshot.SnapshottedItem);
			}
		}
		List<TileType> list2 = new List<TileType>();
		List<TileType> list3 = new List<TileType>();
		List<TileType> list4 = new List<TileType>();
		List<TileType> list5 = new List<TileType>();
		foreach (Item item4 in allItems)
		{
			if (item4 is Flamingo)
			{
				list2.AddRange(item4.RelevantColours);
			}
			if (item4 is RedEnvelope)
			{
				list3.AddRange(item4.RelevantColours);
			}
			if (item4 is SpicyPepper)
			{
				list4.AddRange(item4.RelevantColours);
			}
			if (item4 is Automobile)
			{
				list5.AddRange(item4.RelevantColours);
			}
		}
		foreach (Item item5 in list)
		{
			Frankenstein frankenstein = item5 as Frankenstein;
			allItems.AddRange(frankenstein.StitchedItems);
		}
		string stringRepresentation = GetStringRepresentation();
		if (allItems.Exists((Item item) => item is RedEnvelope) && list3.Exists((TileType tt) => IsTileType(tt)) && (MyGlyphType != GlyphType.Letter || stringRepresentation != "e") && (MyGlyphType != GlyphType.Currency || Letter != "€"))
		{
			return true;
		}
		if (allItems.Exists((Item item) => item is SpicyPepper) && list4.Exists((TileType tt) => IsTileType(tt)) && (MyGlyphType != GlyphType.Letter || stringRepresentation != "s") && (MyGlyphType != GlyphType.Currency || Letter != "$"))
		{
			return true;
		}
		if (allItems.Exists((Item item) => item is Automobile) && list5.Exists((TileType tt) => IsTileType(tt)) && MyGlyphType == GlyphType.Letter)
		{
			return true;
		}
		if (allItems.Exists((Item item) => item is SluggishZombie) && MyGlyphType == GlyphType.Letter && stringRepresentation == "z")
		{
			return true;
		}
		if (allItems.Exists((Item item) => item is Jellyfish) && MyGlyphType == GlyphType.Letter && stringRepresentation == "j")
		{
			return true;
		}
		if (allItems.Exists((Item item) => item is CardShark))
		{
			if (CardSuit == Suit.Clubs && stringRepresentation != "c")
			{
				return true;
			}
			if (CardSuit == Suit.Diamonds && stringRepresentation != "d")
			{
				return true;
			}
			if (CardSuit == Suit.Hearts && stringRepresentation != "h")
			{
				return true;
			}
			if (CardSuit == Suit.Spades && stringRepresentation != "s" && Letter != "$")
			{
				return true;
			}
		}
		else
		{
			if (allItems.Exists((Item item) => item is Queen) && MyGlyphType == GlyphType.Letter && stringRepresentation == "q")
			{
				return true;
			}
			if (allItems.Exists((Item item) => item is Flamingo) && list2.Exists((TileType tt) => IsTileType(tt)))
			{
				if (MyGlyphType != GlyphType.Number && MyGlyphType != GlyphType.Fraction)
				{
					return true;
				}
				if (MyGlyphType == GlyphType.Number && GetNumber() != 1)
				{
					return true;
				}
				if (MyGlyphType == GlyphType.Fraction && !GetFractionNumbers().Contains(1))
				{
					return true;
				}
			}
			else
			{
				if (allItems.Exists((Item item) => item is TestTube) && IsNumber())
				{
					return true;
				}
				if (allItems.Exists((Item item) => item is Microscope) && GetValue() > new ScorePacket(0L))
				{
					if (MyGlyphType != GlyphType.Number && MyGlyphType != GlyphType.Fraction)
					{
						return true;
					}
					if (MyGlyphType == GlyphType.Number && new ScorePacket(GetNumber()) != GetValue())
					{
						return true;
					}
					if (MyGlyphType == GlyphType.Fraction && !GetFractionNumbers().Contains((int)GetValue().Score))
					{
						return true;
					}
				}
				else if (allItems.Exists((Item item) => item is NumbersBunchOfGrapes) && MyGlyphType == GlyphType.Number && (Number == 1 || Number == 5 || Number == 10))
				{
					return true;
				}
			}
		}
		return false;
	}

	public bool IsCursed()
	{
		if (MyGlyphType != GlyphType.Letter)
		{
			return true;
		}
		if (CardSuit != 0)
		{
			return true;
		}
		if (IsDisplayingAsVariableLetter())
		{
			return true;
		}
		return false;
	}

	public List<CurseType> GetCurseTypes()
	{
		List<CurseType> list = new List<CurseType>();
		if (CardSuit != 0 || MyGlyphType == GlyphType.BespokeCard)
		{
			list.Add(CurseType.Card);
		}
		if (MyGlyphType == GlyphType.Chess)
		{
			list.Add(CurseType.Chess);
		}
		else if (MyGlyphType == GlyphType.Currency)
		{
			list.Add(CurseType.Currency);
		}
		else if (MyGlyphType == GlyphType.Arrow)
		{
			list.Add(CurseType.Arrow);
		}
		else if (MyGlyphType == GlyphType.Number || MyGlyphType == GlyphType.Fraction)
		{
			list.Add(CurseType.Number);
		}
		else if (MyGlyphType == GlyphType.Blank)
		{
			list.Add(CurseType.Blank);
		}
		else if (MyGlyphType == GlyphType.ScatteredItem)
		{
			list.Add(CurseType.ScatteredItem);
		}
		if (IsDisplayingAsVariableLetter())
		{
			list.Add(CurseType.Wobbly);
		}
		return list;
	}

	public bool IsSuitedCard()
	{
		if (CardSuit != 0)
		{
			return CardSuit != Suit.Joker;
		}
		return false;
	}

	public static void RandomlyCurseTile(Tile tile, bool isAllowingScatteredItems)
	{
		bool flag = false;
		if (SaveManager.IsBulkUnlockUnlocked(typeof(CardsUnlock)) && UnityEngine.Random.Range(0, 10) == 0)
		{
			if (UnityEngine.Random.Range(0, 10) == 0)
			{
				tile.SetGlyphType(GlyphType.BespokeCard);
				tile.SetSuit(Suit.Joker);
				return;
			}
			flag = true;
		}
		List<GlyphType> list = new List<GlyphType>
		{
			GlyphType.Blank,
			GlyphType.Currency
		};
		if (SaveManager.IsBulkUnlockUnlocked(typeof(NumbersUnlock)))
		{
			list.Add(GlyphType.Number);
			list.Add(GlyphType.Fraction);
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(ChessUnlock)))
		{
			list.Add(GlyphType.Chess);
		}
		if (isAllowingScatteredItems && SaveManager.IsBulkUnlockUnlocked(typeof(ScatteredItemsUnlock)))
		{
			list.Add(GlyphType.ScatteredItem);
		}
		switch (list[UnityEngine.Random.Range(0, list.Count)])
		{
		case GlyphType.Blank:
			tile.SetGlyphType(GlyphType.Blank);
			break;
		case GlyphType.Number:
			tile.SetNumber(UnityEngine.Random.Range(1, 9));
			break;
		case GlyphType.Fraction:
		{
			string randomFraction = Alphabet.GetRandomFraction();
			tile.SetFractionNumbers(Alphabet.GetFractionNumbers(randomFraction));
			break;
		}
		case GlyphType.Chess:
			tile.SetChessPiece(ChessPieces.GetRandomChessPiece());
			break;
		case GlyphType.Currency:
			tile.SetLetter(Currency.GetRandomCurrency());
			tile.SetGlyphType(GlyphType.Currency);
			break;
		case GlyphType.ScatteredItem:
			tile.SetScatteredItem(ScatteredItemPools.GetRandomItem());
			break;
		}
		if (flag && tile.GetSuit() == Suit.None)
		{
			tile.SetSuit(PlayingCardUtility.GetRandomCardSuit());
		}
	}

	public void SetToRandomLetter()
	{
		SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters[UnityEngine.Random.Range(0, Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.Count)]);
	}

	public void SetToRandomCurrency()
	{
		SetCurrency(Currency.GetRandomCurrency());
	}

	public void SetToRandomFraction()
	{
		SetFractionNumbers(Alphabet.GetFractionNumbers(Alphabet.GetRandomFraction()));
	}

	public void SetToRandomNumber()
	{
		SetNumber(UnityEngine.Random.Range(1, 9));
	}

	public void SetToRandomChessPiece()
	{
		SetChessPiece(ChessPieces.GetRandomChessPiece());
	}

	public void SetToRandomItem()
	{
		SetScatteredItem(ScatteredItemPools.GetRandomItem());
	}

	public bool IsConsumableTileReplacementAllowed()
	{
		if (MyTileType == TileType.Cactus)
		{
			return false;
		}
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is UpAndUp && IsNumberGoUpMiddleTile)
		{
			return false;
		}
		return true;
	}

	public static string ChangeTileTypeToString(TileType tt)
	{
		return TileTypeToString[tt];
	}
}
