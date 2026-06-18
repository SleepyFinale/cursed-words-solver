using System;
using System.Collections.Generic;

public class RedLetterDay : ChallengeRun
{
	public RedLetterDay()
	{
		ChallengeName = "Red Letter Day";
		Description = "Grids do not naturally generate vowels.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("The grids in this challenge won't generate any vowels, you'll have to find them elsewhere or make do without!", Emotions.ShopkeeperExplaining),
			("Wh nds vwls nywy? Y gt ths kd!", Emotions.ShopkeeperSerious)
		};
	}

	public override Character GetCharacter()
	{
		return new SandySaguaro();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(RedEnvelope) };
	}
}
