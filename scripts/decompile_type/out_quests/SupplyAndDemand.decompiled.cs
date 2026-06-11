using System;
using System.Collections.Generic;

public class SupplyAndDemand : ChallengeRun
{
	public SupplyAndDemand()
	{
		ChallengeName = "On Cooldown";
		Description = "You may not use any tiles with letters matching your previous word's tiles.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("Think carefully before submitting a word - all the letters you use will be banned from the next word!", Emotions.ShopkeeperExplaining),
			("Make sure you leave yourself some useful letters every time!", Emotions.ShopkeeperIdea)
		};
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type>();
	}
}
