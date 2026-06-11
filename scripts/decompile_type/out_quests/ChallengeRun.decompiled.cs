using System;
using System.Collections.Generic;
using System.Linq;

public class ChallengeRun
{
	public string ChallengeName;

	public string Description;

	public bool EliteQuest;

	public List<(string text, Emotions emotion)> StartOfChallengeDialogue = new List<(string, Emotions)>();

	public Dictionary<int, List<Type>> BannedBossModifiers = new Dictionary<int, List<Type>>();

	public virtual Character GetCharacter()
	{
		return null;
	}

	public virtual List<Type> GetStartingItems()
	{
		return null;
	}

	public virtual List<int> GetItemUpgrades()
	{
		return null;
	}

	public virtual List<Tile> GetChallengeRunStartingConsumableTiles()
	{
		return new List<Tile>();
	}

	public List<Type> GetRemainingStartingItems()
	{
		List<Type> startingItems = GetStartingItems();
		if (startingItems == null)
		{
			return new List<Type>();
		}
		return startingItems.Where((Type itemType) => !SaveManager.IsItemUnlocked(itemType)).ToList();
	}
}
