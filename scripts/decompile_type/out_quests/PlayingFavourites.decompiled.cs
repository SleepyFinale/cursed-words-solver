public class PlayingFavourites : ChallengeRun
{
	public PlayingFavourites()
	{
		ChallengeName = "Playing Favourites";
		Description = "Only your favourite stamps and stickers work";
		EliteQuest = true;
	}

	public override Character GetCharacter()
	{
		return new SockHead();
	}
}
