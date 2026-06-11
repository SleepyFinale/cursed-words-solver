using System.Collections.Generic;

public class Bullseye : ChallengeRun
{
	public Bullseye()
	{
		ChallengeName = "Bullseye";
		Description = "Score targets must be reached precisely.";
		EliteQuest = true;
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("This one is about precision - you must bring the target scores down to exactly zero.", Emotions.ShopkeeperExplaining),
			("If you overshoot the target score, the extra will get added back on!", Emotions.ShopkeeperSerious)
		};
	}

	public override Character GetCharacter()
	{
		return new HayleyBayles();
	}
}
