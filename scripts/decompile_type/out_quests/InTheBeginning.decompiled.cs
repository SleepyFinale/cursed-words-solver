using System;
using System.Collections.Generic;

public class InTheBeginning : ChallengeRun
{
	public InTheBeginning()
	{
		ChallengeName = "In The Beginning";
		Description = "...Was The Word.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("New trade restrictions just came in, I'm not allowed to sell Stickers or Stamps any more.", Emotions.ShopkeeperExplaining),
			("I'm not sure how you're going to make it through this one.", Emotions.ShopkeeperConfused)
		};
	}

	public override Character GetCharacter()
	{
		return new NathaServo();
	}

	public override List<Type> GetStartingItems()
	{
		return new List<Type> { typeof(Microphone) };
	}
}
