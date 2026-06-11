using System;
using System.Collections.Generic;

public class CallOfTheVoid : ChallengeRun
{
	public CallOfTheVoid()
	{
		ChallengeName = "Call Of The Void";
		Description = "Live on the edge.";
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type>
		{
			typeof(FullMoon),
			typeof(HungrySnake),
			typeof(TwinkleToes)
		};
	}
}
