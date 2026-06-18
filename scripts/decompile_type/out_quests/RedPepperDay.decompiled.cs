using System;
using System.Collections.Generic;

public class RedPepperDay : ChallengeRun
{
	public RedPepperDay()
	{
		ChallengeName = "Red Pepper Day";
		Description = "Grids do not naturally generate consonants.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("This challenge is strictly BYOC - Bring Your Own Consonants!", Emotions.ShopkeeperExplaining),
			("I'll give you a quick tip... I've been getting into medieval music recently and just learned the word EUOUAE, that's got to be on this grid somewhere!", Emotions.ShopkeeperIdea)
		};
	}

	public override Character GetCharacter()
	{
		return new SandySaguaro();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(SpicyPepper) };
	}
}
