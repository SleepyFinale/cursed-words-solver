using System.Collections.Generic;
using UnityEngine;

public class WordTrie
{
	private class Node
	{
		public Dictionary<char, Node> Children = new Dictionary<char, Node>();

		public bool IsWord;
	}

	private Node _root = new Node();

	public void Insert(string word)
	{
		Node node = _root;
		foreach (char key in word)
		{
			if (!node.Children.TryGetValue(key, out var value))
			{
				value = new Node();
				node.Children[key] = value;
			}
			node = value;
		}
		node.IsWord = true;
	}

	public string TryMatchTiles(List<Tile> tiles, List<bool> wildcards, List<string> tileStrings, InventoryCache inventoryCache)
	{
		return MatchRecursive(_root, tiles, wildcards, tileStrings, 0, "", inventoryCache);
	}

	private string MatchRecursive(Node node, List<Tile> tiles, List<bool> wildcards, List<string> tileStrings, int tileIndex, string builtWord, InventoryCache inventoryCache)
	{
		if (tileIndex == tiles.Count)
		{
			if (!node.IsWord)
			{
				return null;
			}
			return builtWord;
		}
		Tile tile = tiles[tileIndex];
		bool isWildcard = wildcards[tileIndex];
		string text = tileStrings[tileIndex];
		Node node2 = node;
		int num = 0;
		Node value;
		while (num < text.Length && node2.Children.TryGetValue(text[num], out value))
		{
			num++;
			node2 = value;
		}
		if (num == text.Length)
		{
			string text2 = MatchRecursive(node2, tiles, wildcards, tileStrings, tileIndex + 1, builtWord + text, inventoryCache);
			if (text2 != null)
			{
				return text2;
			}
		}
		List<(char, Node)> list = new List<(char, Node)>();
		foreach (KeyValuePair<char, Node> child in node.Children)
		{
			if (child.Value != node2)
			{
				char key = child.Key;
				if (IsTileMatchingChar(inventoryCache, tile, isWildcard, text, key, tileIndex))
				{
					list.Add((key, child.Value));
				}
			}
		}
		for (int num2 = list.Count - 1; num2 > 0; num2--)
		{
			int index = Random.Range(0, num2 + 1);
			(char, Node) value2 = list[num2];
			list[num2] = list[index];
			list[index] = value2;
		}
		foreach (var item3 in list)
		{
			char item = item3.Item1;
			Node item2 = item3.Item2;
			string text3 = MatchRecursive(item2, tiles, wildcards, tileStrings, tileIndex + 1, builtWord + item, inventoryCache);
			if (text3 != null)
			{
				return text3;
			}
		}
		return null;
	}

	private static bool IsTileMatchingChar(InventoryCache inventoryCache, Tile tile, bool isWildcard, string tileStr, char c, int tileIndex)
	{
		if (isWildcard)
		{
			return true;
		}
		if (tileStr.Length == 1 && tileStr[0] == c)
		{
			return true;
		}
		if (inventoryCache.HasRedEnvelope && inventoryCache.RedEnvelopeTileTypes.Exists((TileType tt) => tile.IsTileType(tt)) && c == 'e')
		{
			return true;
		}
		if (inventoryCache.HasSpicyPepper && inventoryCache.SpicyPepperTileTypes.Exists((TileType tt) => tile.IsTileType(tt)) && c == 's')
		{
			return true;
		}
		if (inventoryCache.HasAutomobile && tile.GetGlyphType() == GlyphType.Letter && inventoryCache.AutomobileTileTypes.Exists((TileType tt) => tile.IsTileType(tt)) && Mathf.Abs(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(c.ToString()) - Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(tileStr.ToString())) < 2)
		{
			return true;
		}
		if (inventoryCache.HasSluggishZombie && tileStr == "z" && c == 's')
		{
			return true;
		}
		if (inventoryCache.HasJellyfish && tileStr == "j" && (c == 'y' || c == 'h'))
		{
			return true;
		}
		if (inventoryCache.HasCardShark && tile.CardSuit == Suit.Clubs && c == 'c')
		{
			return true;
		}
		if (inventoryCache.HasCardShark && tile.CardSuit == Suit.Spades && c == 's')
		{
			return true;
		}
		if (inventoryCache.HasCardShark && tile.CardSuit == Suit.Diamonds && c == 'd')
		{
			return true;
		}
		if (inventoryCache.HasCardShark && tile.CardSuit == Suit.Hearts && c == 'h')
		{
			return true;
		}
		if (tile.GetGlyphType() == GlyphType.Currency && tile.GetStringRepresentation(forWordValidity: true) == Currency.GetCurrencyFromLetter(c.ToString()))
		{
			return true;
		}
		if (inventoryCache.HasBunchOfGrapes && tile.GetGlyphType() == GlyphType.Number && tile.Number == 1 && c == 'i')
		{
			return true;
		}
		if (inventoryCache.HasBunchOfGrapes && tile.GetGlyphType() == GlyphType.Number && tile.Number == 5 && c == 'v')
		{
			return true;
		}
		if (inventoryCache.HasBunchOfGrapes && tile.GetGlyphType() == GlyphType.Number && tile.Number == 10 && c == 'x')
		{
			return true;
		}
		return false;
	}

	public bool Contains(string word)
	{
		Node value = _root;
		foreach (char key in word)
		{
			if (!value.Children.TryGetValue(key, out value))
			{
				return false;
			}
		}
		return value.IsWord;
	}

	public List<string> GetAllWords()
	{
		List<string> list = new List<string>();
		CollectWordsRecursive(_root, "", list);
		return list;
	}

	private void CollectWordsRecursive(Node node, string currentWord, List<string> words)
	{
		if (node.IsWord)
		{
			words.Add(currentWord);
		}
		foreach (KeyValuePair<char, Node> child in node.Children)
		{
			CollectWordsRecursive(child.Value, currentWord + child.Key, words);
		}
	}
}
