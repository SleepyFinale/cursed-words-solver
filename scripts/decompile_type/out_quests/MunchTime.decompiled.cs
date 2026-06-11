using System;
using System.Collections.Generic;
using UnityEngine;

public class MunchTime : ChallengeRun
{
	public List<Vector2Int> PathThroughGrid = new List<Vector2Int>();

	public List<Vector2Int> MunchedCoordinates = new List<Vector2Int>();

	public static (string text, Emotions emotion) GameOverQuip = (text: "You don't have enough tiles left to finish the remaining encounters... Unfortunately that's game over.", emotion: Emotions.ShopkeeperConfused);

	public MunchTime()
	{
		ChallengeName = "Munch Time";
		Description = "When a grid is generated, a tile gets eaten.";
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
					typeof(MinWordLength)
				}
			},
			{
				2,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(ExtraVoids),
					typeof(ExtraQs),
					typeof(MinWordLength),
					typeof(DiscolourTiles),
					typeof(AddNumbers)
				}
			},
			{
				3,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(ExtraVoids),
					typeof(ExtraQs),
					typeof(MinWordLength),
					typeof(DiscolourTiles),
					typeof(AddNumbers)
				}
			},
			{
				4,
				new List<Type>
				{
					typeof(SmallGrid),
					typeof(DestroyGrid),
					typeof(ExtraVoids),
					typeof(ExtraQs),
					typeof(MinWordLength),
					typeof(DiscolourTiles),
					typeof(AddNumbers)
				}
			}
		};
		StartOfChallengeDialogue = new List<(string, Emotions)>
		{
			("Watch out! Every time a new grid is generated, another tile will get eaten!", Emotions.ShopkeeperExplaining),
			("Don't use too many grids, or you'll never make it to the end!", Emotions.ShopkeeperSerious)
		};
	}
}
