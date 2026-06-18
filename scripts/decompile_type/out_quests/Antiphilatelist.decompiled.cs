using System.Collections.Generic;

public class Antiphilatelist : ChallengeRun
{
	public Antiphilatelist()
	{
		ChallengeName = "Antiphilatelist";
		Description = "You hate Stamps.";
		StartOfChallengeDialogue = new List<(string, Emotions)> { ("No Stamps allowed in this challenge!", Emotions.ShopkeeperSerious) };
	}
}
