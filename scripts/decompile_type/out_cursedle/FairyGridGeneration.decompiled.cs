using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class FairyGridGeneration
{
	private static int _puzzleGridDimension = 6;

	public static FairyGrid GenerateRandomFairyGrid(System.Random seed)
	{
		string randomFairyGridWord = Vocabulary.GetRandomFairyGridWord(seed);
		List<Tile> list = new List<Tile>();
		for (int i = 0; i < randomFairyGridWord.Length; i++)
		{
			string letter = randomFairyGridWord.Substring(i, 1);
			Tile tile = new Tile();
			tile.SetLetter(letter);
			list.Add(tile);
		}
		return seed.Next(0, 7) switch
		{
			0 => GenerateTestTubeNumbersPuzzle(list, randomFairyGridWord, seed), 
			1 => GenerateNumberGoUpNumbersPuzzle(list, randomFairyGridWord, seed), 
			2 => GenerateQueeniePuzzle(list, randomFairyGridWord, seed), 
			3 => GenerateCardSharkPuzzle(list, randomFairyGridWord, seed), 
			4 => GenerateZombiePuzzle(list, randomFairyGridWord, seed), 
			5 => GenerateJellyfishPuzzle(list, randomFairyGridWord, seed), 
			6 => GenerateHungrySnakePuzzle(list, randomFairyGridWord, seed), 
			_ => GenerateTestTubeNumbersPuzzle(list, randomFairyGridWord, seed), 
		};
	}

	public static FairyGrid GenerateHungrySnakePuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool num = seed.Next(0, 3) == 0;
		int num2 = seed.Next(0, 4);
		int num3 = seed.Next(0, 3);
		bool flag = seed.Next(0, 3) == 0;
		int num4 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>(wordAsTiles);
		List<ChessPiece> list3 = new List<ChessPiece>
		{
			ChessPiece.Knight,
			ChessPiece.Bishop,
			ChessPiece.Rook,
			ChessPiece.Queen
		};
		if (num)
		{
			list2[seed.Next(0, list2.Count)].SetScatteredItem(new HungrySnake());
		}
		else
		{
			Tile tile2 = new Tile();
			tile2.SetScatteredItem(new HungrySnake());
			list.Add(tile2);
		}
		for (int i = 0; i < num2; i++)
		{
			List<Tile> list4 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			Tile tile3 = list4[seed.Next(0, list4.Count)];
			ChessPiece piece = list3[seed.Next(0, list3.Count)];
			tile3.SetChessPiece(piece, isWhite: true);
		}
		Tile tile4 = list2.Find((Tile tile) => tile.GetGlyphType() == GlyphType.Chess);
		if (tile4 != null)
		{
			tile4.IsWhitePiece = seed.Next(0, 2) == 0;
		}
		for (int j = 1; j < list2.Count; j++)
		{
			if (list2[j - 1].GetGlyphType() == GlyphType.Chess && list2[j].GetGlyphType() == GlyphType.Chess)
			{
				list2[j].IsWhitePiece = !list2[j - 1].IsWhitePiece;
			}
			else
			{
				list2[j].IsWhitePiece = seed.Next(0, 2) == 0;
			}
		}
		for (int k = 0; k < num3; k++)
		{
			Tile tile5 = new Tile();
			ChessPiece piece2 = list3[seed.Next(0, list3.Count)];
			tile5.SetChessPiece(piece2, seed.Next(0, 2) == 0);
			list.Add(tile5);
		}
		if (flag)
		{
			List<Tile> list5 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			if (list5.Count > 0)
			{
				int num5 = seed.Next(0, 3);
				Tile tile6 = list5[seed.Next(0, list5.Count)];
				switch (num5)
				{
				case 0:
					tile6.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
				{
					int num6 = list2.IndexOf(tile6) + 1;
					if (seed.Next(0, 4) == 0)
					{
						string fractionWithValue = Alphabet.GetFractionWithValue(num6, seed);
						tile6.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
					}
					else
					{
						tile6.SetNumber(num6);
					}
					break;
				}
				default:
					tile6.SetGlyphType(GlyphType.BespokeCard);
					tile6.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int l = 0; l < num4; l++)
		{
			Tile tile7 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile7.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				if (seed.Next(0, 4) == 0)
				{
					tile7.SetFractionNumbers(Alphabet.GetFractionNumbers(Alphabet.GetFractionWithValue(seed.Next(1, 7), seed)));
				}
				else
				{
					tile7.SetNumber(seed.Next(1, 7));
				}
				break;
			default:
				tile7.SetGlyphType(GlyphType.BespokeCard);
				tile7.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile7);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateCardSharkPuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool flag = seed.Next(0, 3) == 0;
		int num = seed.Next(0, 4);
		int num2 = seed.Next(1, 4);
		bool flag2 = seed.Next(0, 3) == 0;
		int num3 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>(wordAsTiles);
		List<Suit> list3 = new List<Suit>
		{
			Suit.Clubs,
			Suit.Diamonds,
			Suit.Hearts,
			Suit.Spades
		};
		if (flag && num > 0)
		{
			int num4 = seed.Next(0, num + 1);
			solutionWord = Vocabulary.GetFairyGridWordContainingSuitLetters(num4, seed);
			List<Tile> list4 = new List<Tile>();
			for (int i = 0; i < solutionWord.Length; i++)
			{
				string letter = solutionWord.Substring(i, 1);
				Tile tile2 = new Tile();
				tile2.SetLetter(letter);
				list4.Add(tile2);
			}
			List<string> suitLetters = new List<string> { "c", "s", "d", "h" };
			Dictionary<string, Suit> dictionary = new Dictionary<string, Suit>
			{
				{
					"c",
					Suit.Clubs
				},
				{
					"d",
					Suit.Diamonds
				},
				{
					"h",
					Suit.Hearts
				},
				{
					"s",
					Suit.Spades
				}
			};
			for (int j = 0; j < num4; j++)
			{
				List<Tile> list5 = list4.Where((Tile tile) => tile.GetSuit() == Suit.None && suitLetters.Contains(tile.GetStringRepresentation())).ToList();
				Tile tile3 = list5[seed.Next(0, list5.Count)];
				tile3.SetSuit(dictionary[tile3.GetStringRepresentation()]);
				tile3.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterWeighted(seed));
			}
			List<Tile> list6 = list4.Where((Tile tile) => tile.GetSuit() == Suit.None).ToList();
			list6[seed.Next(0, list6.Count)].SetScatteredItem(new CardShark());
			for (int k = 0; k < num - num4; k++)
			{
				List<Tile> list7 = list2.Where((Tile tile) => tile.GetSuit() == Suit.None).ToList();
				list7[seed.Next(0, list7.Count)].SetSuit(list3[seed.Next(0, list3.Count)]);
			}
			list2 = new List<Tile>(list4);
		}
		else if (flag)
		{
			list2[seed.Next(0, list2.Count)].SetScatteredItem(new CardShark());
		}
		else if (num > 0)
		{
			for (int l = 0; l < num; l++)
			{
				List<Tile> list8 = list2.Where((Tile tile) => tile.GetSuit() == Suit.None).ToList();
				list8[seed.Next(0, list8.Count)].SetSuit(list3[seed.Next(0, list3.Count)]);
			}
		}
		if (!flag)
		{
			Tile tile4 = new Tile();
			tile4.SetScatteredItem(new CardShark());
			list.Add(tile4);
		}
		for (int m = 0; m < num2; m++)
		{
			Tile tile5 = new Tile();
			tile5.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterWeighted(seed));
			tile5.SetSuit(list3[seed.Next(0, list3.Count)]);
			list.Add(tile5);
		}
		if (flag2)
		{
			List<Tile> list9 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetSuit() == Suit.None).ToList();
			if (list9.Count > 0)
			{
				int num5 = seed.Next(0, 4);
				Tile tile6 = list9[seed.Next(0, list9.Count)];
				switch (num5)
				{
				case 0:
					tile6.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				case 2:
				{
					int num6 = list2.IndexOf(tile6) + 1;
					if (seed.Next(0, 4) == 0)
					{
						string fractionWithValue = Alphabet.GetFractionWithValue(num6, seed);
						tile6.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
					}
					else
					{
						tile6.SetNumber(num6);
					}
					break;
				}
				default:
					tile6.SetGlyphType(GlyphType.BespokeCard);
					tile6.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int n = 0; n < num3; n++)
		{
			Tile tile7 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile7.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile7.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile7.SetGlyphType(GlyphType.BespokeCard);
				tile7.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile7);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateJellyfishPuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool flag = seed.Next(0, 3) == 0;
		int num = seed.Next(0, 3);
		int num2 = seed.Next(0, 5);
		bool flag2 = seed.Next(0, 3) == 0;
		int num3 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>();
		if (flag && num > 0)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingJellyfishLetters(num, seed);
			for (int i = 0; i < solutionWord.Length; i++)
			{
				string text = solutionWord.Substring(i, 1);
				if (text == "h" && seed.Next(0, 2) == 0)
				{
					text = "j";
				}
				if (text == "y" && seed.Next(0, 2) == 0)
				{
					text = "j";
				}
				Tile tile2 = new Tile();
				tile2.SetLetter(text);
				list2.Add(tile2);
			}
		}
		else if (num > 0)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingJellyfishLetters(num, seed);
			for (int j = 0; j < solutionWord.Length; j++)
			{
				string letter = solutionWord.Substring(j, 1);
				Tile tile3 = new Tile();
				tile3.SetLetter(letter);
				list2.Add(tile3);
			}
		}
		else
		{
			list2 = new List<Tile>(wordAsTiles);
		}
		if (flag)
		{
			List<Tile> list3 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "j" && tile.GetStringRepresentation() != "h" && tile.GetStringRepresentation() != "y").ToList();
			list2[seed.Next(0, list3.Count)].SetScatteredItem(new Jellyfish());
		}
		else
		{
			Tile tile4 = new Tile();
			tile4.SetScatteredItem(new Jellyfish());
			list.Add(tile4);
		}
		for (int k = 0; k < num2; k++)
		{
			List<string> list4 = new List<string> { "j", "h", "y" };
			Tile tile5 = new Tile();
			tile5.SetLetter(list4[seed.Next(0, list4.Count)]);
			list.Add(tile5);
		}
		if (flag2)
		{
			List<Tile> list5 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "h" && tile.GetStringRepresentation() != "y" && tile.GetStringRepresentation() != "j").ToList();
			if (list5.Count > 0)
			{
				int num4 = seed.Next(0, 4);
				Tile tile6 = list5[seed.Next(0, list5.Count)];
				switch (num4)
				{
				case 0:
					tile6.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				case 2:
				{
					int num5 = list2.IndexOf(tile6) + 1;
					if (seed.Next(0, 4) == 0)
					{
						string fractionWithValue = Alphabet.GetFractionWithValue(num5, seed);
						tile6.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
					}
					else
					{
						tile6.SetNumber(num5);
					}
					break;
				}
				default:
					tile6.SetGlyphType(GlyphType.BespokeCard);
					tile6.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int l = 0; l < num3; l++)
		{
			Tile tile7 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile7.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile7.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile7.SetGlyphType(GlyphType.BespokeCard);
				tile7.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile7);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateZombiePuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool flag = seed.Next(0, 3) == 0;
		int num = seed.Next(0, 3);
		int num2 = seed.Next(0, 3);
		bool flag2 = seed.Next(0, 3) == 0;
		int num3 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>();
		if (flag && num > 0)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingS(num, seed);
			for (int i = 0; i < solutionWord.Length; i++)
			{
				string text = solutionWord.Substring(i, 1);
				if (text == "s" && seed.Next(0, 2) == 0)
				{
					text = "z";
				}
				Tile tile2 = new Tile();
				tile2.SetLetter(text);
				list2.Add(tile2);
			}
		}
		else if (num > 0)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingS(num, seed);
			for (int j = 0; j < solutionWord.Length; j++)
			{
				string letter = solutionWord.Substring(j, 1);
				Tile tile3 = new Tile();
				tile3.SetLetter(letter);
				list2.Add(tile3);
			}
		}
		else
		{
			list2 = new List<Tile>(wordAsTiles);
		}
		if (flag)
		{
			List<Tile> list3 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "z" && tile.GetStringRepresentation() != "s").ToList();
			list2[seed.Next(0, list3.Count)].SetScatteredItem(new SluggishZombie());
		}
		else
		{
			Tile tile4 = new Tile();
			tile4.SetScatteredItem(new SluggishZombie());
			list.Add(tile4);
		}
		for (int k = 0; k < num2; k++)
		{
			Tile tile5 = new Tile();
			tile5.SetLetter("z");
			list.Add(tile5);
		}
		if (flag2)
		{
			List<Tile> list4 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "z" && tile.GetStringRepresentation() != "s").ToList();
			if (list4.Count > 0)
			{
				int num4 = seed.Next(0, 4);
				Tile tile6 = list4[seed.Next(0, list4.Count)];
				switch (num4)
				{
				case 0:
					tile6.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				case 2:
				{
					int num5 = list2.IndexOf(tile6) + 1;
					if (seed.Next(0, 4) == 0)
					{
						string fractionWithValue = Alphabet.GetFractionWithValue(num5, seed);
						tile6.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
					}
					else
					{
						tile6.SetNumber(num5);
					}
					break;
				}
				default:
					tile6.SetGlyphType(GlyphType.BespokeCard);
					tile6.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int l = 0; l < num3; l++)
		{
			Tile tile7 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile7.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile7.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile7.SetGlyphType(GlyphType.BespokeCard);
				tile7.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile7);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateQueeniePuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool flag = seed.Next(0, 3) == 0;
		bool flag2 = seed.Next(0, 3) == 0;
		int num = seed.Next(0, 3);
		bool flag3 = seed.Next(0, 3) == 0;
		int num2 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>();
		if (flag && flag2)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingQ(seed);
			for (int i = 0; i < solutionWord.Length; i++)
			{
				string text = solutionWord.Substring(i, 1);
				if (i <= 1 || !(solutionWord.Substring(i - 1, 1) == "q") || !(text == "u") || seed.Next(0, 3) >= 2)
				{
					Tile tile2 = new Tile();
					tile2.SetLetter(text);
					list2.Add(tile2);
				}
			}
		}
		else if (flag2)
		{
			solutionWord = Vocabulary.GetFairyGridWordContainingQ(seed);
			for (int j = 0; j < solutionWord.Length; j++)
			{
				string letter = solutionWord.Substring(j, 1);
				Tile tile3 = new Tile();
				tile3.SetLetter(letter);
				list2.Add(tile3);
			}
		}
		else
		{
			list2 = new List<Tile>(wordAsTiles);
		}
		if (flag)
		{
			List<Tile> list3 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "q").ToList();
			list2[seed.Next(0, list3.Count)].SetScatteredItem(new Queen());
		}
		else
		{
			Tile tile4 = new Tile();
			tile4.SetScatteredItem(new Queen());
			list.Add(tile4);
		}
		for (int k = 0; k < num; k++)
		{
			Tile tile5 = new Tile();
			tile5.SetLetter("q");
			list.Add(tile5);
		}
		if (flag3)
		{
			List<Tile> list4 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetStringRepresentation() != "q").ToList();
			if (list4.Count > 0)
			{
				int num3 = seed.Next(0, 4);
				Tile tile6 = list4[seed.Next(0, list4.Count)];
				switch (num3)
				{
				case 0:
					tile6.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				case 2:
				{
					int num4 = list2.IndexOf(tile6) + 1;
					if (seed.Next(0, 4) == 0)
					{
						string fractionWithValue = Alphabet.GetFractionWithValue(num4, seed);
						tile6.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
					}
					else
					{
						tile6.SetNumber(num4);
					}
					break;
				}
				default:
					tile6.SetGlyphType(GlyphType.BespokeCard);
					tile6.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int l = 0; l < num2; l++)
		{
			Tile tile7 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile7.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile7.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile7.SetGlyphType(GlyphType.BespokeCard);
				tile7.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile7);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateNumberGoUpNumbersPuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool num = seed.Next(0, 3) == 0;
		int num2 = seed.Next(0, 4);
		int num3 = seed.Next(0, 3);
		bool flag = seed.Next(0, 4) == 0;
		int num4 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>(wordAsTiles);
		if (num)
		{
			list2[seed.Next(0, list2.Count)].SetScatteredItem(new NumberGoUp());
		}
		else
		{
			Tile tile2 = new Tile();
			tile2.SetScatteredItem(new NumberGoUp());
			list.Add(tile2);
		}
		if (num)
		{
			List<int> list3 = new List<int>();
			List<int> list4 = new List<int>();
			for (int i = 1; i < 26; i++)
			{
				list3.Add(i);
			}
			for (int j = 0; j < num2; j++)
			{
				int item = list3[seed.Next(0, list3.Count)];
				list4.Add(item);
				list3.Remove(item);
			}
			list4.Sort();
			List<Tile> list5 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			List<Tile> list6 = new List<Tile>();
			for (int k = 0; k < num2; k++)
			{
				Tile item2 = list5[seed.Next(0, list5.Count)];
				list6.Add(item2);
				list5.Remove(item2);
			}
			foreach (Tile item3 in list2)
			{
				if (list6.Contains(item3))
				{
					item3.SetNumber(list4[0]);
					list4.RemoveAt(0);
				}
			}
		}
		else
		{
			for (int l = 0; l < num2; l++)
			{
				List<Tile> list7 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
				Tile tile3 = list7[seed.Next(0, list7.Count)];
				int number = list2.IndexOf(tile3) + 1;
				tile3.SetNumber(number);
			}
		}
		for (int m = 0; m < num3; m++)
		{
			Tile tile4 = new Tile();
			tile4.SetNumber(seed.Next(1, 26));
			list.Add(tile4);
		}
		if (flag)
		{
			List<Tile> list8 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			if (list8.Count > 0)
			{
				int num5 = seed.Next(0, 3);
				Tile tile5 = list8[seed.Next(0, list8.Count)];
				switch (num5)
				{
				case 0:
					tile5.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile5.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				default:
					tile5.SetGlyphType(GlyphType.BespokeCard);
					tile5.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int n = 0; n < num4; n++)
		{
			Tile tile6 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile6.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile6.SetGlyphType(GlyphType.BespokeCard);
				tile6.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile6);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item4 in list2)
		{
			Debug.Log($"{list2.IndexOf(item4)} - {item4.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static FairyGrid GenerateTestTubeNumbersPuzzle(List<Tile> wordAsTiles, string solutionWord, System.Random seed)
	{
		bool flag = seed.Next(0, 3) == 0;
		int num = seed.Next(0, 4);
		int num2 = seed.Next(0, 3);
		bool flag2 = seed.Next(0, 4) == 0;
		int num3 = seed.Next(0, 3);
		List<Tile> list = new List<Tile>();
		List<Tile> list2 = new List<Tile>(wordAsTiles);
		if (flag)
		{
			list2[seed.Next(0, list2.Count)].SetScatteredItem(new TestTube());
		}
		else
		{
			Tile tile2 = new Tile();
			tile2.SetScatteredItem(new TestTube());
			list.Add(tile2);
		}
		for (int i = 0; i < num; i++)
		{
			List<Tile> list3 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			bool num4 = seed.Next(0, 4) == 0;
			Tile tile3 = list3[seed.Next(0, list3.Count)];
			int num5 = list2.IndexOf(tile3) + 1;
			if (flag)
			{
				int num6 = seed.Next(0, 3);
				if (num6 == 0)
				{
					num5++;
				}
				if (num6 == 1 && num5 > 1)
				{
					num5--;
				}
			}
			if (num4)
			{
				string fractionWithValue = Alphabet.GetFractionWithValue(num5, seed);
				tile3.SetFractionNumbers(Alphabet.GetFractionNumbers(fractionWithValue));
			}
			else
			{
				tile3.SetNumber(num5);
			}
		}
		for (int j = 0; j < num2; j++)
		{
			bool num7 = seed.Next(0, 4) == 0;
			Tile tile4 = new Tile();
			if (num7)
			{
				tile4.SetFractionNumbers(Alphabet.GetFractionNumbers(Alphabet.GetRandomFraction(seed)));
			}
			else
			{
				tile4.SetNumber(seed.Next(1, 8));
			}
			list.Add(tile4);
		}
		if (flag2)
		{
			List<Tile> list4 = list2.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			if (list4.Count > 0)
			{
				int num8 = seed.Next(0, 3);
				Tile tile5 = list4[seed.Next(0, list4.Count)];
				switch (num8)
				{
				case 0:
					tile5.SetGlyphType(GlyphType.Blank);
					break;
				case 1:
					tile5.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
					break;
				default:
					tile5.SetGlyphType(GlyphType.BespokeCard);
					tile5.SetSuit(Suit.Joker);
					break;
				}
			}
		}
		for (int k = 0; k < num3; k++)
		{
			Tile tile6 = new Tile();
			switch (seed.Next(0, 3))
			{
			case 0:
				tile6.SetGlyphType(GlyphType.Blank);
				break;
			case 1:
				tile6.SetChessPiece(ChessPieces.GetRandomChessPiece(seed));
				break;
			default:
				tile6.SetGlyphType(GlyphType.BespokeCard);
				tile6.SetSuit(Suit.Joker);
				break;
			}
			list.Add(tile6);
		}
		GridData grid = GenerateGridDataFromTiles(list2, list, seed);
		Debug.Log("TILES IN WORD: ");
		foreach (Tile item in list2)
		{
			Debug.Log($"{list2.IndexOf(item)} - {item.GetStringRepresentation()}");
		}
		return new FairyGrid(grid, list2, solutionWord);
	}

	public static GridData GenerateGridDataFromTiles(List<Tile> tilesInWord, List<Tile> tilesNotInWord, System.Random seed)
	{
		GridData gridData = PlaceTilesOnGrid(tilesInWord, seed);
		PlaceOtherTilesOnGrid(gridData, tilesInWord, tilesNotInWord, seed);
		FillInRemainderOfGrid(gridData, tilesInWord, tilesNotInWord, seed);
		return gridData;
	}

	public static GridData PlaceTilesOnGrid(List<Tile> tilesInWord, System.Random seed)
	{
		GridData gridData = new GridData();
		gridData.SetDimensions(new Vector2Int(_puzzleGridDimension, _puzzleGridDimension));
		gridData.GridTiles = new Tile[_puzzleGridDimension * _puzzleGridDimension];
		gridData.GridNumber = 1;
		for (int j = 0; j < gridData.GridTiles.Length; j++)
		{
			Vector2Int coordinates = new Vector2Int(j % _puzzleGridDimension, j / _puzzleGridDimension);
			Tile tile = new Tile();
			gridData.GridTiles[j] = tile;
			tile.SetCoordinates(coordinates);
			tile.SetGlyphType(GlyphType.Blank);
		}
		List<TileSelection> tileSelections = new List<TileSelection>();
		int num = 0;
		while (tileSelections.Count < tilesInWord.Count && num < 100000)
		{
			TryGetNextTileSelection(gridData, tileSelections, tilesInWord, seed);
			num++;
			if (tileSelections.Count != tilesInWord.Count)
			{
				continue;
			}
			List<TileSelection> list = new List<TileSelection>(tileSelections);
			List<TileSelection> list2 = new List<TileSelection>();
			bool flag = false;
			int i;
			for (i = 0; i < list.Count - 1; i++)
			{
				list2.Add(tileSelections[i]);
				if (!GridUtility.Singleton.GetValidNextTiles(gridData, list2.Select((TileSelection ts) => ts.SelectedTile).ToList(), null, noInventory: true).Exists((TileSelection ts) => ts.SelectedTile == tileSelections[i + 1].SelectedTile))
				{
					flag = true;
				}
			}
			if (flag)
			{
				tileSelections.Clear();
			}
		}
		if (num == 100000)
		{
			Debug.Log("While loop ran 100000 times");
		}
		return gridData;
	}

	public static void TryGetNextTileSelection(GridData gridData, List<TileSelection> tileSelections, List<Tile> tilesInWord, System.Random seed)
	{
		if (tileSelections.Count == 0)
		{
			Tile[] gridTiles = gridData.GridTiles;
			for (int i = 0; i < gridTiles.Length; i++)
			{
				gridTiles[i].SetGlyphType(GlyphType.Blank);
			}
			int num = seed.Next(0, gridData.GridTiles.Length);
			Vector2Int coordinates = gridData.GridTiles[num].Coordinates;
			gridData.GridTiles[num] = tilesInWord[0];
			tilesInWord[0].Coordinates = coordinates;
			tileSelections.Add(new TileSelection(tilesInWord[0], TileSelectionMethod.Initial, isWobbly: false));
			return;
		}
		List<TileSelection> validNextTiles = GridUtility.Singleton.GetValidNextTiles(gridData, tileSelections.Select((TileSelection s) => s.SelectedTile).ToList(), null, noInventory: true);
		if (validNextTiles.Count == 0)
		{
			for (int j = 0; j < gridData.GridTiles.Length; j++)
			{
				gridData.GridTiles[j] = new Tile();
				gridData.GridTiles[j].SetCoordinates(new Vector2Int(j % _puzzleGridDimension, j / _puzzleGridDimension));
				gridData.GridTiles[j].SetGlyphType(GlyphType.Blank);
			}
			tileSelections.Clear();
		}
		else
		{
			Tile tile = tilesInWord[tileSelections.Count];
			TileSelection tileSelection = validNextTiles[seed.Next(0, validNextTiles.Count)];
			int num2 = Array.IndexOf(gridData.GridTiles, tileSelection.SelectedTile);
			gridData.GridTiles[num2] = tile;
			tile.Coordinates = new Vector2Int(num2 % _puzzleGridDimension, num2 / _puzzleGridDimension);
			tileSelection.SelectedTile = tile;
			tileSelections.Add(tileSelection);
		}
	}

	public static GridData PlaceOtherTilesOnGrid(GridData gridData, List<Tile> tilesInWord, List<Tile> otherTiles, System.Random seed)
	{
		foreach (Tile otherTile in otherTiles)
		{
			List<Tile> list = gridData.GridTiles.Where((Tile gt) => !tilesInWord.Contains(gt) && !otherTiles.Contains(gt)).ToList();
			Tile value = list[seed.Next(0, list.Count)];
			int num = Array.IndexOf(gridData.GridTiles, value);
			gridData.GridTiles[num] = otherTile;
			otherTile.Coordinates = new Vector2Int(num % _puzzleGridDimension, num / _puzzleGridDimension);
		}
		return gridData;
	}

	public static GridData FillInRemainderOfGrid(GridData gridData, List<Tile> tilesInWord, List<Tile> otherTiles, System.Random seed)
	{
		Tile[] gridTiles = gridData.GridTiles;
		foreach (Tile tile in gridTiles)
		{
			if (!tilesInWord.Contains(tile) && !otherTiles.Contains(tile))
			{
				tile.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterWeighted(seed));
			}
		}
		return gridData;
	}
}
