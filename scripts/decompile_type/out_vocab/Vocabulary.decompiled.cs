using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class Vocabulary
{
	public static LanguageVocabulary ActiveLanguageVocabulary;

	private static List<LanguageVocabulary> _languageVocabularies = new List<LanguageVocabulary>();

	public static Dictionary<DictionaryLanguage, List<string>> WordFiles = new Dictionary<DictionaryLanguage, List<string>>
	{
		{
			DictionaryLanguage.EnglishDefault,
			new List<string> { "ReallyBigList", "BigList", "SmallList" }
		},
		{
			DictionaryLanguage.French,
			new List<string> { "FrenchWordList" }
		},
		{
			DictionaryLanguage.German,
			new List<string> { "GermanWordList" }
		},
		{
			DictionaryLanguage.Spanish,
			new List<string> { "SpanishWordList" }
		}
	};

	public static List<string> EnglishCuratedWordFiles = new List<string> { "FourLetterWordsGood", "FiveLetterWordsGood", "SixLetterWordsGood" };

	public static Dictionary<DictionaryLanguage, List<string>> BannedWordFiles = new Dictionary<DictionaryLanguage, List<string>>
	{
		{
			DictionaryLanguage.EnglishDefault,
			new List<string> { "BannedList" }
		},
		{
			DictionaryLanguage.French,
			new List<string> { "BannedList", "FrenchBannedList" }
		},
		{
			DictionaryLanguage.Spanish,
			new List<string> { "BannedList", "SpanishBannedList" }
		},
		{
			DictionaryLanguage.German,
			new List<string> { "BannedList", "GermanBannedList" }
		}
	};

	public static Dictionary<DictionaryLanguage, Alphabet> LanguageAlphabets = new Dictionary<DictionaryLanguage, Alphabet>
	{
		{
			DictionaryLanguage.EnglishDefault,
			new EnglishDefaultAlphabet()
		},
		{
			DictionaryLanguage.French,
			new FrenchEuropeanAlphabet()
		},
		{
			DictionaryLanguage.Spanish,
			new SpanishEuropeanAlphabet()
		},
		{
			DictionaryLanguage.German,
			new GermanAlphabet()
		}
	};

	[RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
	private static void CreateLanguageVocabularies()
	{
		foreach (DictionaryLanguage value in Enum.GetValues(typeof(DictionaryLanguage)))
		{
			LanguageVocabulary languageVocabulary = new LanguageVocabulary();
			languageVocabulary.Language = value;
			_languageVocabularies.Add(languageVocabulary);
		}
		ActiveLanguageVocabulary = _languageVocabularies[0];
	}

	public static void SetActiveLanguageVocabulary(DictionaryLanguage language)
	{
		ActiveLanguageVocabulary = _languageVocabularies.Find((LanguageVocabulary langVocab) => langVocab.Language == language);
		ActiveLanguageVocabulary.TryInitializeVocabulary();
	}

	public static string GetRandomFairyGridWord(System.Random seed)
	{
		return seed.Next(4, 7) switch
		{
			4 => ActiveLanguageVocabulary.FourLetterCuratedWords[seed.Next(0, ActiveLanguageVocabulary.FourLetterCuratedWords.Count)], 
			5 => ActiveLanguageVocabulary.FiveLetterCuratedWords[seed.Next(0, ActiveLanguageVocabulary.FiveLetterCuratedWords.Count)], 
			_ => ActiveLanguageVocabulary.SixLetterCuratedWords[seed.Next(0, ActiveLanguageVocabulary.SixLetterCuratedWords.Count)], 
		};
	}

	public static string GetFairyGridWordContainingQ(System.Random seed)
	{
		List<string> list = new List<string>();
		list.AddRange(ActiveLanguageVocabulary.FourLetterCuratedWords.Where((string word) => word.Contains("q")));
		list.AddRange(ActiveLanguageVocabulary.FiveLetterCuratedWords.Where((string word) => word.Contains("q")));
		list.AddRange(ActiveLanguageVocabulary.SixLetterCuratedWords.Where((string word) => word.Contains("q")));
		return list[seed.Next(0, list.Count)];
	}

	public static string GetFairyGridWordContainingS(int sCount, System.Random seed)
	{
		List<string> list = new List<string>();
		list.AddRange(ActiveLanguageVocabulary.FourLetterCuratedWords.Where((string word) => word.Count((char c) => c == 's') >= sCount));
		list.AddRange(ActiveLanguageVocabulary.FiveLetterCuratedWords.Where((string word) => word.Count((char c) => c == 's') >= sCount));
		list.AddRange(ActiveLanguageVocabulary.SixLetterCuratedWords.Where((string word) => word.Count((char c) => c == 's') >= sCount));
		return list[seed.Next(0, list.Count)];
	}

	public static string GetFairyGridWordContainingJellyfishLetters(int relevantLettersCount, System.Random seed)
	{
		List<char> suitLetters = new List<char> { 'j', 'h', 'y' };
		List<string> list = new List<string>();
		list.AddRange(ActiveLanguageVocabulary.FourLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= relevantLettersCount));
		list.AddRange(ActiveLanguageVocabulary.FiveLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= relevantLettersCount));
		list.AddRange(ActiveLanguageVocabulary.SixLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= relevantLettersCount));
		return list[seed.Next(0, list.Count)];
	}

	public static string GetFairyGridWordContainingSuitLetters(int numberOfSuitLetters, System.Random seed)
	{
		List<char> suitLetters = new List<char> { 'h', 'c', 'd', 's' };
		List<string> list = new List<string>();
		list.AddRange(ActiveLanguageVocabulary.FourLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= numberOfSuitLetters));
		list.AddRange(ActiveLanguageVocabulary.FiveLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= numberOfSuitLetters));
		list.AddRange(ActiveLanguageVocabulary.SixLetterCuratedWords.Where((string word) => word.Count((char c) => suitLetters.Contains(c)) >= numberOfSuitLetters));
		return list[seed.Next(0, list.Count)];
	}

	public static List<string> GetConcatenatedValidWordsFromTiles(IEnumerable<Tile> tiles, List<BossModifier> bossModifiers)
	{
		InventoryCache inventoryCache = new InventoryCache(tiles);
		inventoryCache.PertinentAccumulatorWords.Clear();
		List<string> list2 = inventoryCache.PertinentAccumulatorPairs.Select((List<string> list) => list[0]).ToList();
		List<string> list3 = inventoryCache.PertinentAccumulatorPairs.Select((List<string> list) => list[1]).ToList();
		foreach (string item in list2)
		{
			inventoryCache.PertinentAccumulatorWords.Clear();
			inventoryCache.PertinentAccumulatorWords.Add(item);
			string text = TryGetAccumulatorWordFromTiles(inventoryCache, tiles.Take(item.Length));
			if (text != null)
			{
				int index = list2.IndexOf(item);
				inventoryCache.PertinentAccumulatorWords.Clear();
				inventoryCache.PertinentAccumulatorWords.Add(list3[index]);
				string text2 = TryGetAccumulatorWordFromTiles(inventoryCache, tiles.Skip(item.Length));
				if (text2 != null)
				{
					return new List<string> { text, text2 };
				}
			}
		}
		InventoryCache inventoryCache2 = new InventoryCache(tiles);
		string validWordFromTiles = GetValidWordFromTiles(tiles, bossModifiers, inventoryCache2);
		if (validWordFromTiles != null)
		{
			return new List<string> { validWordFromTiles };
		}
		inventoryCache2.PertinentAccumulatorWords.Clear();
		for (int i = 1; i < tiles.Count(); i++)
		{
			string validWordFromTiles2 = GetValidWordFromTiles(tiles.Take(i), bossModifiers, inventoryCache2);
			if (validWordFromTiles2 != null)
			{
				string validWordFromTiles3 = GetValidWordFromTiles(tiles.Skip(i), bossModifiers, inventoryCache2);
				if (validWordFromTiles3 != null)
				{
					return new List<string> { validWordFromTiles2, validWordFromTiles3 };
				}
			}
		}
		return null;
	}

	public static string GetValidWordFromTiles(IEnumerable<Tile> tiles, List<BossModifier> bossModifiers, InventoryCache inventoryCache = null)
	{
		if (tiles == null)
		{
			return null;
		}
		if (!IsWordLengthValid(tiles.Count(), bossModifiers))
		{
			return null;
		}
		InventoryCache inventoryCache2 = ((inventoryCache == null) ? new InventoryCache(tiles) : inventoryCache);
		string text = TryGetAccumulatorWordFromTiles(inventoryCache2, tiles);
		if (text != null)
		{
			return text;
		}
		if (IsWordContainedInList(inventoryCache2, tiles.ToList(), out var matchedWord))
		{
			return matchedWord;
		}
		return null;
	}

	private static string TryGetAccumulatorWordFromTiles(InventoryCache inventoryCache, IEnumerable<Tile> tiles)
	{
		if (inventoryCache.PertinentAccumulatorWords.Count == 0)
		{
			return null;
		}
		List<string> list = new List<string>(inventoryCache.PertinentAccumulatorWords);
		while (list.Count > 0)
		{
			string text = list[UnityEngine.Random.Range(0, list.Count)];
			list.Remove(text);
			if (AreWordsFunctionallyEqual(tiles.ToList(), text, inventoryCache))
			{
				return text;
			}
		}
		return null;
	}

	public static WordValidity CheckInvalidityReason(IEnumerable<Tile> tiles, List<BossModifier> bossModifiers)
	{
		if (tiles == null)
		{
			return WordValidity.NoWord;
		}
		int num = tiles.Count();
		if (num == 0)
		{
			return WordValidity.NoWord;
		}
		if (IsWordTooShort(num, bossModifiers))
		{
			return WordValidity.TooShort;
		}
		if (IsWordTooLong(num, bossModifiers))
		{
			return WordValidity.TooLong;
		}
		return WordValidity.Invalid;
	}

	public static bool IsWordLengthValid(int wordLength, List<BossModifier> bossModifiers)
	{
		int num = 1;
		int num2 = 999;
		foreach (BossModifier bossModifier in bossModifiers)
		{
			if (bossModifier is MinWordLength)
			{
				num = bossModifier.FloorAdjustedModification;
			}
			else if (bossModifier is MaxWordLength)
			{
				num2 = bossModifier.FloorAdjustedModification;
			}
		}
		if (wordLength >= num)
		{
			return wordLength <= num2;
		}
		return false;
	}

	public static bool IsWordTooShort(int wordLength, List<BossModifier> bossModifiers)
	{
		int num = 1;
		foreach (BossModifier bossModifier in bossModifiers)
		{
			if (bossModifier is MinWordLength)
			{
				num = bossModifier.FloorAdjustedModification;
			}
		}
		return wordLength < num;
	}

	public static bool IsWordTooLong(int wordLength, List<BossModifier> bossModifiers)
	{
		int num = 100;
		foreach (BossModifier bossModifier in bossModifiers)
		{
			if (bossModifier is MaxWordLength)
			{
				num = bossModifier.FloorAdjustedModification;
			}
		}
		return wordLength > num;
	}

	public static bool IsValidWord(string word)
	{
		if (string.IsNullOrWhiteSpace(word))
		{
			return false;
		}
		string text = word.Trim().ToLower();
		if (ActiveLanguageVocabulary.TriesByLength.TryGetValue(text.Length, out var value))
		{
			return value.Contains(text);
		}
		return false;
	}

	public static string GetRandomWord(int length)
	{
		if (ActiveLanguageVocabulary == null)
		{
			return null;
		}
		if (!ActiveLanguageVocabulary.TriesByLength.TryGetValue(length, out var value))
		{
			return null;
		}
		List<string> allWords = value.GetAllWords();
		if (allWords.Count == 0)
		{
			return null;
		}
		return allWords[UnityEngine.Random.Range(0, allWords.Count)];
	}

	public static string GetRandomTwentyFiveLetterWord()
	{
		if (ActiveLanguageVocabulary == null)
		{
			return null;
		}
		return ActiveLanguageVocabulary.TwentyFiveLetterWords[UnityEngine.Random.Range(0, ActiveLanguageVocabulary.TwentyFiveLetterWords.Count)];
	}

	private static bool IsWordContainedInList(InventoryCache inventoryCache, List<Tile> tiles, out string matchedWord, WordTrie limitedTrie = null)
	{
		List<bool> wildcards = tiles.Select((Tile tile, int i) => tile.IsWildcard(i, tiles, inventoryCache)).ToList();
		foreach (List<string> wordPermutation in GetWordPermutations(tiles, inventoryCache))
		{
			int length = string.Join("", wordPermutation).Length;
			if (ActiveLanguageVocabulary.TriesByLength.ContainsKey(length))
			{
				string text = ((limitedTrie == null) ? ActiveLanguageVocabulary.TriesByLength[length] : limitedTrie).TryMatchTiles(tiles, wildcards, wordPermutation, inventoryCache);
				if (text != null)
				{
					matchedWord = text;
					return true;
				}
			}
		}
		matchedWord = null;
		return false;
	}

	private static List<List<string>> GetWordPermutations(List<Tile> tiles, InventoryCache inventoryCache)
	{
		List<List<string>> list = new List<List<string>>
		{
			new List<string>()
		};
		foreach (Tile tile in tiles)
		{
			List<List<string>> list2 = new List<List<string>>();
			string stringRepresentation = tile.GetStringRepresentation(forWordValidity: true);
			List<string> list3 = new List<string> { stringRepresentation };
			if (stringRepresentation == "q" && inventoryCache.HasQueen)
			{
				list3.Add("qu");
			}
			foreach (List<string> item2 in list)
			{
				foreach (string item3 in list3)
				{
					List<string> item = new List<string>(item2) { item3 };
					list2.Add(item);
				}
			}
			list = list2;
		}
		return list;
	}

	public static bool AreWordsFunctionallyEqual(List<Tile> tiles, string word, InventoryCache inventoryCache = null)
	{
		WordTrie wordTrie = new WordTrie();
		wordTrie.Insert(word);
		string matchedWord;
		return IsWordContainedInList((inventoryCache == null) ? new InventoryCache(tiles) : inventoryCache, tiles, out matchedWord, wordTrie);
	}
}
