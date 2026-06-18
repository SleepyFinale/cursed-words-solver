public class WordBonusToken
{
	public ScorePacket Bonus;

	public bool IsMultiplicative;

	public bool IsPoison;

	public WordBonusToken(long bonus, bool isMultiplicative, bool isPoison = false)
	{
		Bonus = new ScorePacket(bonus);
		IsMultiplicative = isMultiplicative;
		IsPoison = isPoison;
	}

	public WordBonusToken(ScorePacket bonus, bool isMultiplicative, bool isPoison = false)
	{
		Bonus = bonus;
		IsMultiplicative = isMultiplicative;
		IsPoison = isPoison;
	}
}
