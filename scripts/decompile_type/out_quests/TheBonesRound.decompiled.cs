using System.Collections.Generic;

public class TheBonesRound : ChallengeRun
{
	public TheBonesRound()
	{
		ChallengeName = "The Bones Round";
		Description = "Poker hands score but tiles don't.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("Tiles don't have base score in this challenge, but submitting a Poker Hand will earn you points.", Emotions.ShopkeeperExplaining),
			("Better hands are worth more points, just like Balatro!", Emotions.ShopkeeperIdea),
			("You've not played Balatro?! But... how?", Emotions.ShopkeeperConfused),
			("Here's a steam key so you can check it out: F348I-GFFVQ-84I52. Have fun!", Emotions.ShopkeeperIdea)
		};
	}

	public override Character GetCharacter()
	{
		return new BonesTheDog();
	}
}
