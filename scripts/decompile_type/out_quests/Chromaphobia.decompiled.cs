using System;
using System.Collections.Generic;

public class Chromaphobia : ChallengeRun
{
	public Chromaphobia()
	{
		ChallengeName = "Chromaphobia";
		Description = "You cannot submit words containing coloured tiles.";
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(GamePad) };
	}

	public override List<int> GetItemUpgrades()
	{
		return new List<int> { 2 };
	}

	public override Character GetCharacter()
	{
		return new WetDennis();
	}
}
