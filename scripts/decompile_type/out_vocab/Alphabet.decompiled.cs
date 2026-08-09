using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class Alphabet
{
	public List<string> AllLetters;

	public List<string> Consonants;

	public List<string> Vowels;

	public Dictionary<string, int> LetterValues;

	public Dictionary<string, int> AscensionLetterValues;

	public Dictionary<string, int> LetterFrequencies;

	public Dictionary<string, int> AscensionLetterFrequencies;

	public static List<int> SingleDigitNumbers = new List<int> { 1, 2, 3, 4, 5, 6, 7, 8, 9 };

	public static Dictionary<string, List<int>> FractionNumbers = new Dictionary<string, List<int>>
	{
		{
			"⅐",
			new List<int> { 1, 7 }
		},
		{
			"⅑",
			new List<int> { 1, 9 }
		},
		{
			"⅒",
			new List<int> { 1, 10 }
		},
		{
			"½",
			new List<int> { 1, 2 }
		},
		{
			"⅓",
			new List<int> { 1, 3 }
		},
		{
			"⅔",
			new List<int> { 2, 3 }
		},
		{
			"¼",
			new List<int> { 1, 4 }
		},
		{
			"¾",
			new List<int> { 3, 4 }
		},
		{
			"⅕",
			new List<int> { 1, 5 }
		},
		{
			"⅖",
			new List<int> { 2, 5 }
		},
		{
			"⅗",
			new List<int> { 3, 5 }
		},
		{
			"⅘",
			new List<int> { 4, 5 }
		},
		{
			"⅙",
			new List<int> { 1, 6 }
		},
		{
			"⅚",
			new List<int> { 5, 6 }
		},
		{
			"⅛",
			new List<int> { 1, 8 }
		},
		{
			"⅜",
			new List<int> { 3, 8 }
		},
		{
			"⅝",
			new List<int> { 5, 8 }
		},
		{
			"⅞",
			new List<int> { 7, 8 }
		}
	};

	public static Dictionary<int, List<string>> FractionsByValue = new Dictionary<int, List<string>>
	{
		{
			1,
			new List<string> { "⅐", "⅑", "⅒", "⅓", "¼", "⅕", "⅙", "⅛", "½" }
		},
		{
			2,
			new List<string> { "½", "⅔", "⅖" }
		},
		{
			3,
			new List<string> { "⅓", "⅔", "¾", "⅗", "⅜" }
		},
		{
			4,
			new List<string> { "¼", "¾", "⅘" }
		},
		{
			5,
			new List<string> { "⅕", "⅖", "⅗", "⅘", "⅝" }
		},
		{
			6,
			new List<string> { "⅙", "⅚" }
		},
		{
			7,
			new List<string> { "⅐", "⅞" }
		},
		{
			8,
			new List<string> { "⅛", "⅜", "⅝", "⅞" }
		},
		{
			9,
			new List<string> { "⅑" }
		},
		{
			10,
			new List<string> { "⅒" }
		}
	};

	public static Dictionary<ChessPiece, int> ChessValues = new Dictionary<ChessPiece, int>
	{
		{
			ChessPiece.None,
			0
		},
		{
			ChessPiece.Pawn,
			1
		},
		{
			ChessPiece.Knight,
			3
		},
		{
			ChessPiece.Bishop,
			3
		},
		{
			ChessPiece.Rook,
			5
		},
		{
			ChessPiece.Queen,
			9
		},
		{
			ChessPiece.King,
			15
		}
	};

	public int TotalWeighting;

	public int TotalAscensionWeighting;

	public int TotalConsonantWeighting;

	public int TotalVowelWeighting;

	public void GetTotalFrequency()
	{
		TotalWeighting = 0;
		TotalAscensionWeighting = 0;
		TotalConsonantWeighting = 0;
		TotalVowelWeighting = 0;
		foreach (KeyValuePair<string, int> letterFrequency in LetterFrequencies)
		{
			TotalWeighting += letterFrequency.Value;
			if (Consonants.Contains(letterFrequency.Key))
			{
				TotalConsonantWeighting += letterFrequency.Value;
			}
			if (Vowels.Contains(letterFrequency.Key))
			{
				TotalVowelWeighting += letterFrequency.Value;
			}
		}
		foreach (KeyValuePair<string, int> ascensionLetterFrequency in AscensionLetterFrequencies)
		{
			TotalAscensionWeighting += ascensionLetterFrequency.Value;
		}
	}

	public int GetLetterValue(string letter)
	{
		if (GameStatics.GetPlayer().CurrentRunProgress == null)
		{
			return LetterValues[letter];
		}
		if (!GameStatics.GetPlayer().CurrentRunProgress.IsAscensionModifierActive(AscensionLevel.LowerTileScores))
		{
			return LetterValues[letter];
		}
		return AscensionLetterValues[letter];
	}

	public int GetUnchangedLetterValue(string letter)
	{
		return LetterValues[letter];
	}

	public static int GetChessValue(ChessPiece piece)
	{
		return ChessValues[piece];
	}

	public static string GetRandomFraction()
	{
		List<string> list = FractionNumbers.Keys.ToList();
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public static string GetRandomFraction(System.Random seed)
	{
		List<string> list = FractionNumbers.Keys.ToList();
		return list[seed.Next(0, list.Count)];
	}

	public static string GetFractionWithValue(int value, System.Random seed)
	{
		return FractionsByValue[value][seed.Next(0, FractionsByValue[value].Count)];
	}

	public static List<int> GetFractionNumbers(string fraction)
	{
		if (FractionNumbers.ContainsKey(fraction))
		{
			return FractionNumbers[fraction];
		}
		throw new Exception("Fraction " + fraction + " not found in FractionNumbers dictionary.");
	}

	public static string GetFractionSymbol(int numerator, int denominator, bool isFontTagged)
	{
		string key = FractionNumbers.ToList().Find((KeyValuePair<string, List<int>> kvp) => kvp.Value.Contains(numerator) && kvp.Value.Contains(denominator)).Key;
		if (!isFontTagged)
		{
			return key;
		}
		return "<font=TTNormsPro-Bold SDF>" + key + "</font>";
	}

	public static string GetFractionFromNumbers(List<int> fractionNumbers)
	{
		foreach (KeyValuePair<string, List<int>> fractionNumber in FractionNumbers)
		{
			if (fractionNumber.Value.Contains(fractionNumbers[0]) && fractionNumber.Value.Contains(fractionNumbers[1]))
			{
				return fractionNumber.Key;
			}
		}
		return "";
	}

	public static Dictionary<string, float> GetFractionNumbersAsFloats()
	{
		Dictionary<string, float> dictionary = new Dictionary<string, float>();
		foreach (KeyValuePair<string, List<int>> fractionNumber in FractionNumbers)
		{
			dictionary.Add(fractionNumber.Key, (float)fractionNumber.Value[0] / (float)fractionNumber.Value[1]);
		}
		return dictionary;
	}

	public string GetRandomLetterWeighted()
	{
		int num = UnityEngine.Random.Range(0, TotalWeighting);
		foreach (KeyValuePair<string, int> letterFrequency in LetterFrequencies)
		{
			if (num < letterFrequency.Value)
			{
				return letterFrequency.Key;
			}
			num -= letterFrequency.Value;
		}
		throw new Exception("This should not be able to happen. Is the value of _totalWeighting wrong?");
	}

	public string GetRandomLetterWeighted(System.Random seed)
	{
		int num = seed.Next(0, TotalWeighting);
		foreach (KeyValuePair<string, int> letterFrequency in LetterFrequencies)
		{
			if (num < letterFrequency.Value)
			{
				return letterFrequency.Key;
			}
			num -= letterFrequency.Value;
		}
		throw new Exception("This should not be able to happen. Is the value of _totalWeighting wrong?");
	}

	public string GetRandomLetterAscensionWeighted()
	{
		int num = UnityEngine.Random.Range(0, TotalAscensionWeighting);
		foreach (KeyValuePair<string, int> ascensionLetterFrequency in AscensionLetterFrequencies)
		{
			if (num < ascensionLetterFrequency.Value)
			{
				return ascensionLetterFrequency.Key;
			}
			num -= ascensionLetterFrequency.Value;
		}
		throw new Exception("This should not be able to happen. Is the value of _totalAscensionWeighting wrong?");
	}

	public static int GetRandomSingleDigitNumberWeighted()
	{
		return SingleDigitNumbers[UnityEngine.Random.Range(0, SingleDigitNumbers.Count)];
	}

	public static int GetRandomOddNumber()
	{
		List<int> list = new List<int> { 1, 3, 5, 7, 9 };
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public static int GetRandomEvenNumber()
	{
		List<int> list = new List<int> { 2, 4, 6, 8 };
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public string GetRandomConsonantWeighted()
	{
		int num = UnityEngine.Random.Range(0, TotalConsonantWeighting);
		foreach (KeyValuePair<string, int> letterFrequency in LetterFrequencies)
		{
			if (Consonants.Contains(letterFrequency.Key))
			{
				if (num < letterFrequency.Value)
				{
					return letterFrequency.Key;
				}
				num -= letterFrequency.Value;
			}
		}
		throw new Exception("This should not be able to happen. Is the value of _totalWeighting wrong?");
	}

	public string GetRandomVowelWeighted()
	{
		int num = UnityEngine.Random.Range(0, TotalVowelWeighting);
		foreach (KeyValuePair<string, int> letterFrequency in LetterFrequencies)
		{
			if (Vowels.Contains(letterFrequency.Key))
			{
				if (num < letterFrequency.Value)
				{
					return letterFrequency.Key;
				}
				num -= letterFrequency.Value;
			}
		}
		throw new Exception("This should not be able to happen. Is the value of _totalWeighting wrong?");
	}

	public bool IsVowel(string letter)
	{
		return Vowels.Contains(letter);
	}

	public bool IsConsonant(string letter)
	{
		return Consonants.Contains(letter);
	}

	public bool IsLaterLetter(Tile tile, Tile comparisonTile)
	{
		if (tile.GetGlyphType() != GlyphType.Letter || comparisonTile.GetGlyphType() != GlyphType.Letter)
		{
			return false;
		}
		return AllLetters.IndexOf(tile.GetStringRepresentation()) > AllLetters.IndexOf(comparisonTile.GetStringRepresentation());
	}

	public bool IsNextLetter(Tile tile, Tile comparisonTile)
	{
		if (tile.GetGlyphType() != GlyphType.Letter || comparisonTile.GetGlyphType() != GlyphType.Letter)
		{
			return false;
		}
		return AllLetters.IndexOf(tile.GetStringRepresentation()) - AllLetters.IndexOf(comparisonTile.GetStringRepresentation()) == 1;
	}

	public bool IsLaterGlyph(Tile tile, Tile comparisonTile)
	{
		if (tile.GetGlyphType() == GlyphType.Blank || comparisonTile.GetGlyphType() == GlyphType.Blank)
		{
			return false;
		}
		if (tile.IsNumber() && comparisonTile.IsNumber())
		{
			int num = ((tile.GetGlyphType() == GlyphType.Fraction) ? Mathf.Max(tile.GetFractionNumbers()[0], tile.GetFractionNumbers()[1]) : tile.GetNumber());
			int num2 = ((tile.GetGlyphType() == GlyphType.Fraction) ? Mathf.Min(tile.GetFractionNumbers()[0], tile.GetFractionNumbers()[1]) : tile.GetNumber());
			return num > num2;
		}
		if (tile.GetGlyphType() != comparisonTile.GetGlyphType())
		{
			return false;
		}
		if (tile.GetGlyphType() == GlyphType.Letter)
		{
			return AllLetters.IndexOf(tile.GetStringRepresentation()) > AllLetters.IndexOf(comparisonTile.GetStringRepresentation());
		}
		return false;
	}

	public bool IsNextGlyph(Tile tile, Tile comparisonTile)
	{
		if (tile.GetGlyphType() == GlyphType.Blank || comparisonTile.GetGlyphType() == GlyphType.Blank)
		{
			return false;
		}
		if (tile.IsNumber() && comparisonTile.IsNumber())
		{
			List<int> obj = ((tile.GetGlyphType() == GlyphType.Fraction) ? tile.GetFractionNumbers() : new List<int> { tile.GetNumber() });
			List<int> list = ((comparisonTile.GetGlyphType() == GlyphType.Fraction) ? comparisonTile.GetFractionNumbers() : new List<int> { comparisonTile.GetNumber() });
			foreach (int item in obj)
			{
				foreach (int item2 in list)
				{
					if (item == item2 + 1)
					{
						return true;
					}
				}
			}
			return false;
		}
		if (tile.GetGlyphType() != comparisonTile.GetGlyphType())
		{
			return false;
		}
		if (tile.GetGlyphType() == GlyphType.Letter)
		{
			return AllLetters.IndexOf(tile.GetStringRepresentation()) > AllLetters.IndexOf(comparisonTile.GetStringRepresentation());
		}
		return false;
	}
}
