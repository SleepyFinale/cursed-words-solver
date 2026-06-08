using System.Collections.Generic;

public class BuildData
{
	public ItemTag BuildTag;

	public List<Item> RelevantItems;

	public Dictionary<ItemFunction, int> FunctionTagCounts;

	public BuildData(ItemTag buildTag, List<Item> relevantItems, Dictionary<ItemFunction, int> functionTagCounts)
	{
		BuildTag = buildTag;
		RelevantItems = relevantItems;
		FunctionTagCounts = functionTagCounts;
	}
}
