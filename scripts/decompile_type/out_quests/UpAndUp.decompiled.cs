using System;
using System.Collections.Generic;

public class UpAndUp : ChallengeRun
{
	public UpAndUp()
	{
		ChallengeName = "Up and Up";
		Description = "The number at the center of the grid must be used. It goes up after each encounter.";
		EliteQuest = true;
		BannedBossModifiers = new Dictionary<int, List<Type>>
		{
			{
				0,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid)
				}
			},
			{
				1,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(MaxWordLength)
				}
			},
			{
				2,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(MaxWordLength)
				}
			},
			{
				3,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(MaxWordLength)
				}
			},
			{
				4,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(MaxWordLength)
				}
			}
		};
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("Each time you enter a new encounter, the number in the middle of the grid will go up!", Emotions.ShopkeeperExplaining),
			("It's up to you how you deal with the big numbers, but you won't be able to change them.", Emotions.ShopkeeperIdea),
			("And remember, you <i>have</i> to use the middle tile every time!", Emotions.ShopkeeperSerious)
		};
	}
}
