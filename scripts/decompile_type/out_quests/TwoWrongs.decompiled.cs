using System;
using System.Collections.Generic;

public class TwoWrongs : ChallengeRun
{
	public TwoWrongs()
	{
		ChallengeName = "Two Wrongs";
		Description = "Target scores are negative.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("Wait, the target is -12?", Emotions.ShopkeeperConfused),
			("Then I guess we'll have to RAISE it to zero!", Emotions.ShopkeeperIdea)
		};
	}

	public override Character GetCharacter()
	{
		return new NinaNix();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(DangerousSummit) };
	}
}
