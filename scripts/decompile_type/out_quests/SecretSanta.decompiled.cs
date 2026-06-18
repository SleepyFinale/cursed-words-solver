using System.Collections.Generic;

public class SecretSanta : ChallengeRun
{
	public SecretSanta()
	{
		ChallengeName = "Secret Santa";
		Description = "Items in the shop are hidden.";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("I had to wrap up everything in the shop for the holidays.", Emotions.ShopkeeperExplaining),
			("I forgot to take the price tags off, but that's the only clue you're getting!", Emotions.ShopkeeperIdea)
		};
	}
}
