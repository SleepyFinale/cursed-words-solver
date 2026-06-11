using System;
using System.Collections.Generic;

public class Cursophobia : ChallengeRun
{
	public Cursophobia()
	{
		ChallengeName = "Cursophobia";
		Description = "You cannot submit words containing cursed tiles.";
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(Amphora) };
	}

	public override List<int> GetItemUpgrades()
	{
		return new List<int> { 2 };
	}

	public override Character GetCharacter()
	{
		return new Octacles();
	}
}
