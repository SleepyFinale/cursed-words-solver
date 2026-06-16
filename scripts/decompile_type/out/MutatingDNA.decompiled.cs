// Decompiled from Assembly-CSharp.dll (Cursed Words v0.2.0) via ilspycmd -t MutatingDNA
using System.Collections.Generic;

public class MutatingDNA : Item
{
    public Dictionary<string, int> LetterUseCounts = new Dictionary<string, int>();

    public MutatingDNA()
    {
        Name = "Mutating DNA";
        SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "MutatingDNA"));
        Rarity = ItemRarity.Legendary;
        Cost = 25;
        ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericAdditive };
    }

    public override string GetDescription()
    {
        return "Each time you use a letter,  tiles with that letter get +1 TILE SCORE whilst you have this item";
    }

    public override void ApplyTileBonus(
        ScoreCalcVizInfo step,
        int index,
        List<Tile> tiles,
        List<TileSelection> selections,
        List<HistoricWord> previousWords,
        GridData gridData)
    {
        if (tiles.Count != 0)
        {
            string key = tiles[index].GetStringRepresentation();
            if (LetterUseCounts.ContainsKey(key))
            {
                step.TileScores[index] += LetterUseCounts[key];
                LetterUseCounts[key]++;
            }
            else
            {
                LetterUseCounts[key] = 1;
            }
        }
    }
}
