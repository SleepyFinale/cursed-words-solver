using System;
using System.Collections.Generic;

public class EmptyGrid : ChallengeRun
{
	public EmptyGrid()
	{
		ChallengeName = " ";
		Description = " ";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("                                           <br>         ", Emotions.ShopkeeperExplaining),
			("                     ", Emotions.ShopkeeperConfused)
		};
	}

	public override Character GetCharacter()
	{
		return new SandySaguaro();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type>
		{
			typeof(SpoutingWhale),
			typeof(WeeklyShop)
		};
	}
}
