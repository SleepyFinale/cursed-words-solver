using System.Collections.Generic;

public class Lexographer : ChallengeRun
{
	public (string text, Emotions emotion) GameOverQuip = (text: "Unfortunately [SUBMITTED WORD] isn't a valid word - that's game over.", emotion: Emotions.ShopkeeperConfused);

	public Lexographer()
	{
		ChallengeName = "Lexographer";
		Description = "Are you <i>sure</i> that's a valid word?";
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("You can submit any combination of tiles in this challenge, but if it's not a valid word then that's game over!", Emotions.ShopkeeperIdea),
			("It's up to you to make sure you've dotted the Is, crossed the Ts, put numbers in the correct position, obeyed boss instructions...", Emotions.ShopkeeperExplaining),
			("Oh, and watch out - cursed tiles always get a TILE SCORE of zero!", Emotions.ShopkeeperSerious)
		};
	}

	public override Character GetCharacter()
	{
		return new Octacles();
	}
}
