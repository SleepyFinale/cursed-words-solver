using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class PokerHands
{
	public static Dictionary<PokerHand, int> PokerHandPointValues = new Dictionary<PokerHand, int>
	{
		{
			PokerHand.GodFlush,
			3000
		},
		{
			PokerHand.MonsterFlush,
			2750
		},
		{
			PokerHand.WickedFlush,
			2500
		},
		{
			PokerHand.UnrealFlush,
			2250
		},
		{
			PokerHand.LudicrousFlush,
			2000
		},
		{
			PokerHand.UltraFlush,
			1800
		},
		{
			PokerHand.MegaFlush,
			1600
		},
		{
			PokerHand.ImpressiveFlush,
			1400
		},
		{
			PokerHand.FlushSpree,
			1200
		},
		{
			PokerHand.RoyalFlush,
			1000
		},
		{
			PokerHand.StraightFlush,
			800
		},
		{
			PokerHand.FourOfAKind,
			420
		},
		{
			PokerHand.FullHouse,
			160
		},
		{
			PokerHand.Flush,
			140
		},
		{
			PokerHand.Straight,
			120
		},
		{
			PokerHand.ThreeOfAKind,
			90
		},
		{
			PokerHand.TwoPair,
			40
		},
		{
			PokerHand.Pair,
			20
		},
		{
			PokerHand.HighCard,
			5
		}
	};

	public static Dictionary<PokerHand, string> PokerHandDisplayNames = new Dictionary<PokerHand, string>
	{
		{
			PokerHand.GodFlush,
			"GOD FLUSH"
		},
		{
			PokerHand.MonsterFlush,
			"MONSTER FLUSH"
		},
		{
			PokerHand.WickedFlush,
			"WICKED FLUSH"
		},
		{
			PokerHand.UnrealFlush,
			"UNREAL FLUSH"
		},
		{
			PokerHand.LudicrousFlush,
			"LUDICROUS FLUSH"
		},
		{
			PokerHand.UltraFlush,
			"ULTRA FLUSH"
		},
		{
			PokerHand.MegaFlush,
			"MEGA FLUSH"
		},
		{
			PokerHand.ImpressiveFlush,
			"IMPRESSIVE FLUSH"
		},
		{
			PokerHand.FlushSpree,
			"FLUSH SPREE"
		},
		{
			PokerHand.RoyalFlush,
			"ROYAL FLUSH"
		},
		{
			PokerHand.StraightFlush,
			"STRAIGHT FLUSH"
		},
		{
			PokerHand.FourOfAKind,
			"FOUR OF A KIND"
		},
		{
			PokerHand.FullHouse,
			"FULL HOUSE"
		},
		{
			PokerHand.Flush,
			"FLUSH"
		},
		{
			PokerHand.Straight,
			"STRAIGHT"
		},
		{
			PokerHand.ThreeOfAKind,
			"THREE OF A KIND"
		},
		{
			PokerHand.TwoPair,
			"TWO PAIR"
		},
		{
			PokerHand.Pair,
			"PAIR"
		},
		{
			PokerHand.HighCard,
			"HIGH CARD"
		}
	};

	public static List<PokerHand> PokerHandsInDescendingOrder = new List<PokerHand>
	{
		PokerHand.GodFlush,
		PokerHand.MonsterFlush,
		PokerHand.WickedFlush,
		PokerHand.UnrealFlush,
		PokerHand.LudicrousFlush,
		PokerHand.UltraFlush,
		PokerHand.MegaFlush,
		PokerHand.ImpressiveFlush,
		PokerHand.FlushSpree,
		PokerHand.RoyalFlush,
		PokerHand.StraightFlush,
		PokerHand.FourOfAKind,
		PokerHand.FullHouse,
		PokerHand.Flush,
		PokerHand.Straight,
		PokerHand.ThreeOfAKind,
		PokerHand.TwoPair,
		PokerHand.Pair,
		PokerHand.HighCard
	};

	public static List<Tile> GetPokerHandFromTiles(List<Tile> tiles, out PokerHand pokerHand)
	{
		List<Tile> list = tiles.Where((Tile tile) => tile.GetSuit() != 0 && tile.GetSuit() != Suit.Joker).ToList();
		List<Tile> list2 = Player.Shuffle(tiles.Where((Tile tile) => tile.GetSuit() == Suit.Joker).ToList()).ToList();
		int num = (GameStatics.GetPlayer().GetAllItems().Exists((Item item) => item is Martini) ? 3 : 5);
		if (list.Count + list2.Count == 0)
		{
			pokerHand = PokerHand.None;
			return null;
		}
		if (list.Count + list2.Count == 1)
		{
			pokerHand = PokerHand.HighCard;
			if (list.Count <= 0)
			{
				return new List<Tile> { list2[0] };
			}
			return new List<Tile> { list[0] };
		}
		if (list2.Count >= num)
		{
			pokerHand = PokerHand.StraightFlush;
			List<Tile> list3 = new List<Tile>();
			for (int i = 0; i < num; i++)
			{
				list3.Add(list2[i]);
			}
			return list3;
		}
		List<Tile> cards = (from tile in list
			where tile.GetGlyphType() == GlyphType.Letter
			orderby tile.GetStringRepresentation() descending
			select tile).ToList();
		List<Tile> cards2 = (from tile in list
			where tile.GetGlyphType() == GlyphType.Number
			orderby tile.GetNumber() descending
			select tile).ToList();
		PokerHand pokerHand2;
		List<Tile> cards3 = TryGetStraightOrStraightFlush(cards, list2.Count, out pokerHand2, num);
		if (pokerHand2 == PokerHand.StraightFlush)
		{
			pokerHand = PokerHand.StraightFlush;
			return GetFullHandComplement(cards3, list2);
		}
		PokerHand pokerHand3;
		List<Tile> cards4 = TryGetStraightOrStraightFlush(cards2, list2.Count, out pokerHand3, num);
		if (pokerHand3 == PokerHand.StraightFlush)
		{
			pokerHand = PokerHand.StraightFlush;
			return GetFullHandComplement(cards4, list2);
		}
		PokerHand pokerHand4;
		List<Tile> bestOfAKind = GetBestOfAKind(list, list2.Count, out pokerHand4);
		switch (pokerHand4)
		{
		case PokerHand.FourOfAKind:
			pokerHand = PokerHand.FourOfAKind;
			return GetFullHandComplement(bestOfAKind, list2);
		case PokerHand.FullHouse:
			pokerHand = PokerHand.FullHouse;
			return GetFullHandComplement(bestOfAKind, list2);
		default:
		{
			List<Tile> list4 = TryGetFlush(list, list2.Count, num);
			if (list4 != null)
			{
				pokerHand = PokerHand.Flush;
				return GetFullHandComplement(list4, list2);
			}
			if (pokerHand2 == PokerHand.Straight)
			{
				pokerHand = PokerHand.Straight;
				return GetFullHandComplement(cards3, list2);
			}
			if (pokerHand3 == PokerHand.Straight)
			{
				pokerHand = PokerHand.Straight;
				return GetFullHandComplement(cards4, list2);
			}
			pokerHand = pokerHand4;
			return GetFullHandComplement(bestOfAKind, list2);
		}
		}
	}

	public static List<Tile> GetFlush(List<Tile> tiles)
	{
		List<Item> unpackedItemsOfType = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Martini));
		foreach (Tile tile in tiles)
		{
			if (tile.GetGlyphType() == GlyphType.ScatteredItem)
			{
				unpackedItemsOfType.Add(tile.ScatteredItem);
			}
		}
		List<Tile> cards = tiles.Where((Tile tile) => tile.GetSuit() != 0 && tile.GetSuit() != Suit.Joker).ToList();
		List<Tile> list = Player.Shuffle(tiles.Where((Tile tile) => tile.GetSuit() == Suit.Joker).ToList()).ToList();
		List<Tile> list2 = TryGetFlush(requiredCardsForHand: unpackedItemsOfType.Exists((Item item) => item is Martini) ? 3 : 5, cards: cards, jokerCount: list.Count);
		if (list2 == null)
		{
			return null;
		}
		foreach (Tile item in new List<Tile>(list2))
		{
			if (item == null)
			{
				list2.Remove(item);
				list2.Add(list[0]);
				list.RemoveAt(0);
			}
		}
		return list2;
	}

	public static List<Tile> GetStraight(List<Tile> tiles)
	{
		List<Tile> list = tiles.Where((Tile tile) => tile.GetSuit() != 0 && tile.GetSuit() != Suit.Joker).ToList();
		List<Tile> list2 = Player.Shuffle(tiles.Where((Tile tile) => tile.GetSuit() == Suit.Joker).ToList()).ToList();
		int num = (GameStatics.GetPlayer().GetAllItems().Exists((Item item) => item is Martini) ? 3 : 5);
		if (list.Count + list2.Count == 0)
		{
			return null;
		}
		if (list.Count + list2.Count == 1)
		{
			return null;
		}
		if (list2.Count >= num)
		{
			List<Tile> list3 = new List<Tile>();
			for (int i = 0; i < num; i++)
			{
				list3.Add(list2[i]);
			}
			return list3;
		}
		List<Tile> cards = (from tile in list
			where tile.GetGlyphType() == GlyphType.Letter
			orderby tile.GetStringRepresentation() descending
			select tile).ToList();
		List<Tile> cards2 = (from tile in list
			where tile.GetGlyphType() == GlyphType.Number
			orderby tile.GetNumber() descending
			select tile).ToList();
		PokerHand pokerHand;
		List<Tile> cards3 = TryGetStraightOrStraightFlush(cards, list2.Count, out pokerHand, num);
		if (pokerHand == PokerHand.StraightFlush || pokerHand == PokerHand.Straight)
		{
			return GetFullHandComplement(cards3, list2);
		}
		PokerHand pokerHand2;
		List<Tile> cards4 = TryGetStraightOrStraightFlush(cards2, list2.Count, out pokerHand2, num);
		if (pokerHand2 == PokerHand.StraightFlush || pokerHand2 == PokerHand.Straight)
		{
			return GetFullHandComplement(cards4, list2);
		}
		return null;
	}

	public static List<Tile> GetXOfAKind(int xOfAKind, List<Tile> tiles)
	{
		List<Tile> list = tiles.Where((Tile tile) => tile.GetSuit() != 0 && tile.GetSuit() != Suit.Joker).ToList();
		List<Tile> list2 = Player.Shuffle(tiles.Where((Tile tile) => tile.GetSuit() == Suit.Joker).ToList()).ToList();
		Dictionary<string, List<Tile>> dictionary = new Dictionary<string, List<Tile>>();
		if (list2.Count >= xOfAKind)
		{
			return list2.Where((Tile joker, int i) => i < xOfAKind).ToList();
		}
		foreach (Tile item in list)
		{
			string stringRepresentation = item.GetStringRepresentation();
			if (dictionary.ContainsKey(stringRepresentation))
			{
				dictionary[stringRepresentation].Add(item);
				if (dictionary[stringRepresentation].Count + list2.Count == xOfAKind)
				{
					while (dictionary[stringRepresentation].Count < xOfAKind)
					{
						dictionary[stringRepresentation].Add(list2[0]);
						list2.RemoveAt(0);
					}
					return dictionary[stringRepresentation];
				}
				continue;
			}
			dictionary[stringRepresentation] = new List<Tile> { item };
			if (dictionary[stringRepresentation].Count + list2.Count == xOfAKind)
			{
				while (dictionary[stringRepresentation].Count < xOfAKind)
				{
					dictionary[stringRepresentation].Add(list2[0]);
					list2.RemoveAt(0);
				}
				return dictionary[stringRepresentation];
			}
		}
		return null;
	}

	private static List<Tile> TryGetStraight(List<Tile> cards, List<Tile> jokers, int requiredCardsForHand = 5)
	{
		if (cards.Count + jokers.Count < requiredCardsForHand)
		{
			return null;
		}
		if (jokers.Count >= requiredCardsForHand && cards.Count > 0)
		{
			List<Tile> list = new List<Tile>();
			for (int i = 0; i < requiredCardsForHand; i++)
			{
				list.Add(jokers[i]);
			}
			return list;
		}
		bool isNumberType = cards[0].IsNumber();
		List<Tile> list2 = null;
		for (int j = 0; j < cards.Count; j++)
		{
			List<Tile> list3 = new List<Tile> { cards[j] };
			List<Tile> list4 = new List<Tile> { cards[j] };
			Suit currentSuit = cards[j].GetSuit();
			int num = (isNumberType ? cards[j].GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(cards[j].GetStringRepresentation()));
			for (int k = 1; k < requiredCardsForHand; k++)
			{
				int requiredValue = num - k;
				Tile tile2 = cards.Find((Tile tile) => tile.GetSuit() == currentSuit && (isNumberType ? tile.GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(tile.GetStringRepresentation())) == requiredValue);
				if (tile2 != null)
				{
					if (list2 == null)
					{
						list3.Add(tile2);
					}
					list4.Add(tile2);
					continue;
				}
				list4.Add(null);
				if (list2 == null)
				{
					Tile item = cards.Find((Tile tile) => (isNumberType ? tile.GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(tile.GetStringRepresentation())) == requiredValue);
					list3.Add(item);
				}
			}
			if (list4.Count((Tile card) => card == null) <= jokers.Count)
			{
				return list4;
			}
			if (list2 == null && list3.Count((Tile card) => card == null) <= jokers.Count)
			{
				list2 = list3;
			}
		}
		if (list2 == null)
		{
			return null;
		}
		return list2;
	}

	private static List<Tile> TryGetStraightOrStraightFlush(List<Tile> cards, int jokerCount, out PokerHand pokerHand, int requiredCardsForHand = 5)
	{
		if (cards.Count + jokerCount < requiredCardsForHand)
		{
			pokerHand = PokerHand.None;
			return null;
		}
		if (jokerCount >= requiredCardsForHand && cards.Count > 0)
		{
			pokerHand = PokerHand.StraightFlush;
			return new List<Tile>
			{
				cards[0],
				null,
				null,
				null,
				null
			};
		}
		bool isNumberType = cards[0].IsNumber();
		List<Tile> list = null;
		for (int i = 0; i < cards.Count; i++)
		{
			List<Tile> list2 = new List<Tile> { cards[i] };
			List<Tile> list3 = new List<Tile> { cards[i] };
			Suit currentSuit = cards[i].GetSuit();
			int num = (isNumberType ? cards[i].GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(cards[i].GetStringRepresentation()));
			for (int j = 1; j < requiredCardsForHand; j++)
			{
				int requiredValue = num - j;
				Tile tile2 = cards.Find((Tile tile) => tile.GetSuit() == currentSuit && (isNumberType ? tile.GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(tile.GetStringRepresentation())) == requiredValue);
				if (tile2 != null)
				{
					if (list == null)
					{
						list2.Add(tile2);
					}
					list3.Add(tile2);
					continue;
				}
				list3.Add(null);
				if (list == null)
				{
					Tile item = cards.Find((Tile tile) => (isNumberType ? tile.GetNumber() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.AllLetters.IndexOf(tile.GetStringRepresentation())) == requiredValue);
					list2.Add(item);
				}
			}
			if (list3.Count((Tile card) => card == null) <= jokerCount)
			{
				pokerHand = PokerHand.StraightFlush;
				return list3;
			}
			if (list == null && list2.Count((Tile card) => card == null) <= jokerCount)
			{
				list = list2;
			}
		}
		if (list == null)
		{
			pokerHand = PokerHand.None;
			return null;
		}
		pokerHand = PokerHand.Straight;
		return list;
	}

	private static List<Tile> GetBestOfAKind(List<Tile> cards, int jokerCount, out PokerHand pokerHand)
	{
		if (jokerCount >= 4)
		{
			pokerHand = PokerHand.FourOfAKind;
			return new List<Tile> { null, null, null, null };
		}
		switch (jokerCount)
		{
		case 3:
			if (cards.Count > 0)
			{
				pokerHand = PokerHand.FourOfAKind;
				return new List<Tile>
				{
					cards[0],
					null,
					null,
					null
				};
			}
			pokerHand = PokerHand.ThreeOfAKind;
			return new List<Tile> { null, null, null };
		case 2:
			if (cards.Count == 0)
			{
				pokerHand = PokerHand.Pair;
				return new List<Tile> { null, null };
			}
			break;
		}
		Dictionary<string, List<Tile>> dictionary = new Dictionary<string, List<Tile>>();
		foreach (Tile card in cards)
		{
			string stringRepresentation = card.GetStringRepresentation();
			if (dictionary.ContainsKey(stringRepresentation))
			{
				dictionary[stringRepresentation].Add(card);
				if (dictionary[stringRepresentation].Count + jokerCount == 4)
				{
					while (dictionary[stringRepresentation].Count < 4)
					{
						dictionary[stringRepresentation].Add(null);
					}
					pokerHand = PokerHand.FourOfAKind;
					return dictionary[stringRepresentation];
				}
			}
			else
			{
				dictionary[stringRepresentation] = new List<Tile> { card };
			}
		}
		List<Tile> list = null;
		List<Tile> list2 = null;
		List<Tile> list3 = null;
		foreach (List<Tile> value in dictionary.Values)
		{
			if (value.Count == 3)
			{
				if (list == null)
				{
					list = value;
				}
			}
			else
			{
				if (value.Count != 2)
				{
					continue;
				}
				if (list2 == null)
				{
					list2 = value;
					if (list != null)
					{
						pokerHand = PokerHand.FullHouse;
						List<Tile> list4 = new List<Tile>(list);
						list4.AddRange(list2);
						return list4;
					}
				}
				else if (list3 == null)
				{
					list3 = value;
				}
			}
		}
		if (list != null)
		{
			if (jokerCount > 0)
			{
				pokerHand = PokerHand.FourOfAKind;
				return new List<Tile>
				{
					list[0],
					list[1],
					list[2],
					null
				};
			}
			if (list2 != null)
			{
				pokerHand = PokerHand.FullHouse;
				return new List<Tile>
				{
					list[0],
					list[1],
					list[2],
					list2[0],
					list2[1]
				};
			}
			pokerHand = PokerHand.ThreeOfAKind;
			return list;
		}
		if (list2 != null)
		{
			if (jokerCount == 1)
			{
				if (list3 == null)
				{
					pokerHand = PokerHand.ThreeOfAKind;
					return new List<Tile>
					{
						list2[0],
						list2[1],
						null
					};
				}
				pokerHand = PokerHand.FullHouse;
				return new List<Tile>
				{
					list2[0],
					list2[1],
					null,
					list3[0],
					list3[1]
				};
			}
			if (list3 == null)
			{
				pokerHand = PokerHand.Pair;
				return new List<Tile>
				{
					list2[0],
					list2[1]
				};
			}
			pokerHand = PokerHand.TwoPair;
			return new List<Tile>
			{
				list2[0],
				list2[1],
				list3[0],
				list3[1]
			};
		}
		switch (jokerCount)
		{
		case 2:
			pokerHand = PokerHand.ThreeOfAKind;
			return new List<Tile>
			{
				cards[0],
				null,
				null
			};
		case 1:
			pokerHand = PokerHand.Pair;
			return new List<Tile>
			{
				cards[0],
				null
			};
		default:
			pokerHand = PokerHand.HighCard;
			return new List<Tile> { cards[0] };
		}
	}

	private static List<Tile> TryGetFlush(List<Tile> cards, int jokerCount, int requiredCardsForHand = 5)
	{
		if (cards.Count + jokerCount < requiredCardsForHand)
		{
			return null;
		}
		if (jokerCount >= requiredCardsForHand)
		{
			List<Tile> list = new List<Tile>();
			for (int i = 0; i < requiredCardsForHand; i++)
			{
				list.Add(null);
			}
			return list;
		}
		Dictionary<Suit, List<Tile>> dictionary = new Dictionary<Suit, List<Tile>>();
		foreach (Tile card in cards)
		{
			Suit suit = card.GetSuit();
			if (dictionary.ContainsKey(suit))
			{
				dictionary[suit].Add(card);
				if (dictionary[suit].Count + jokerCount >= requiredCardsForHand)
				{
					while (dictionary[suit].Count < requiredCardsForHand)
					{
						dictionary[suit].Add(null);
					}
					return dictionary[suit];
				}
				continue;
			}
			dictionary[suit] = new List<Tile> { card };
			if (dictionary[suit].Count + jokerCount >= requiredCardsForHand)
			{
				while (dictionary[suit].Count < requiredCardsForHand)
				{
					dictionary[suit].Add(null);
				}
				return dictionary[suit];
			}
		}
		Debug.Log("Flush not found");
		return null;
	}

	private static List<Tile> GetFullHandComplement(List<Tile> cards, List<Tile> jokers)
	{
		List<Tile> list = new List<Tile>();
		int num = 0;
		for (int i = 0; i < cards.Count; i++)
		{
			if (cards[i] == null)
			{
				list.Add(jokers[num]);
				num++;
			}
			else
			{
				list.Add(cards[i]);
			}
		}
		return list;
	}
}
