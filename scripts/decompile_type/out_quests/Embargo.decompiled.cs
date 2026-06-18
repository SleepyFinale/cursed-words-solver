using System;
using System.Collections.Generic;

public class Embargo : ChallengeRun
{
	public Embargo()
	{
		ChallengeName = "Embargo";
		Description = "After each boss, all of your items are removed from your inventory and the shop pool. Items cannot be sold.";
		BannedBossModifiers = new Dictionary<int, List<Type>>
		{
			{
				0,
				new List<Type> { typeof(ForcedSell) }
			},
			{
				1,
				new List<Type> { typeof(ForcedSell) }
			},
			{
				2,
				new List<Type> { typeof(ForcedSell) }
			},
			{
				3,
				new List<Type> { typeof(ForcedSell) }
			},
			{
				4,
				new List<Type> { typeof(ForcedSell) }
			}
		};
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("After each boss, you're going to lose all of your items, and the shop will never stock them again...", Emotions.ShopkeeperConfused),
			("Don't worry, you'll get your money back for anything you bought!", Emotions.ShopkeeperIdea),
			("And before I go, choose your purchases carefully - items can't be sold.", Emotions.ShopkeeperExplaining)
		};
	}

	public override Character GetCharacter()
	{
		return new Spike();
	}
}
