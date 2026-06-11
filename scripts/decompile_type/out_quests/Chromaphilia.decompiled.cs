using System;
using System.Collections.Generic;

public class Chromaphilia : ChallengeRun
{
	public Chromaphilia()
	{
		ChallengeName = "Chromaphilia";
		Description = "You cannot submit words containing COLOURLESS tiles.";
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
