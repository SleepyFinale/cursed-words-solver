using System;
using System.Collections.Generic;

public class ColourSwap : ChallengeRun
{
	public ColourSwap()
	{
		ChallengeName = "Chromatic Aberration";
		Description = "Colours are randomised.";
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type>();
	}

	public override List<int> GetItemUpgrades()
	{
		return new List<int>();
	}

	public override Character GetCharacter()
	{
		return new PrismaticBean();
	}
}
