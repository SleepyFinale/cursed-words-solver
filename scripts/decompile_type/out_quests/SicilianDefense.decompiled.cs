using System;
using System.Collections.Generic;

public class SicilianDefense : ChallengeRun
{
	public SicilianDefense()
	{
		ChallengeName = "Knight Time";
		Description = "Everything moves like a knight.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("I used to be a bit of a Kasparov myself.", Emotions.ShopkeeperExplaining),
			("Tip from one grandmaster to another: the knights move in a L shape. And in this challenge, everything else does too!", Emotions.ShopkeeperIdea)
		};
		BannedBossModifiers = new Dictionary<int, List<Type>>
		{
			{
				0,
				new List<Type> { typeof(SmallGrid) }
			},
			{
				1,
				new List<Type> { typeof(SmallGrid) }
			},
			{
				2,
				new List<Type> { typeof(SmallGrid) }
			},
			{
				3,
				new List<Type> { typeof(SmallGrid) }
			},
			{
				4,
				new List<Type> { typeof(SmallGrid) }
			}
		};
	}

	public override Character GetCharacter()
	{
		return new SamGambit();
	}
}
