public class SpeedrunChallenge : ChallengeRun
{
	public static int TimeLimitInSeconds = 900;

	public static (string text, Emotions emotion) GameOverQuip = (text: "I'm afraid you're out of time!", emotion: Emotions.ShopkeeperConfused);

	public SpeedrunChallenge()
	{
		ChallengeName = "We're Finally Landing";
		Description = "The quest to beat 15 minutes.";
	}
}
