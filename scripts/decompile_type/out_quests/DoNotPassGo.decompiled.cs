using System;
using System.Collections.Generic;

public class DoNotPassGo : ChallengeRun
{
	public DoNotPassGo()
	{
		ChallengeName = "Do Not Pass Go";
		Description = "No money is earned from wins or remaining grids.";
	}

	public override Character GetCharacter()
	{
		return new Spike();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(KokeshiDolls) };
	}
}
