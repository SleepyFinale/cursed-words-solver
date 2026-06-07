using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEngine;

public class MichaelBoss : BossModifier
{
	public List<List<BossModifier>> ModifierDrafts = new List<List<BossModifier>>();

	public List<BossModifier> DraftedModifiers = new List<BossModifier>();

	public List<string> All25LetterWords = new List<string>();

	public List<DiscussionPacket> DraftQuips = new List<DiscussionPacket>
	{
		new DiscussionPacket((text: "Too easy for you? See how you like this!", emotion: Emotions.MichaelSnide), isLeftSided: true),
		new DiscussionPacket((text: "Now for the real challenge...", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
		new DiscussionPacket((text: "That was just the warm up!", emotion: Emotions.MichaelSnide), isLeftSided: true),
		new DiscussionPacket((text: "If you weren't such a coward you would throw away your items and fight me using real words!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
		new DiscussionPacket((text: "Might as well give up, you'll never beat me!", emotion: Emotions.MichaelSnide), isLeftSided: true)
	};

	public bool SummonedBossesDefeated;

	public bool AllFriendsAgain;

	public MichaelBoss()
	{
		Name = "MichaelBoss";
		PrefabFileName = "BossMichael";
		SpriteFileName = "Michael";
		AudioPrefix = "Michael";
		UIColor = new Color32(0, 58, 180, byte.MaxValue);
		DifficultyModifier = new List<int> { 0, 0, 0, 0, 0, 3, 4 };
		DifficultyIncrease = new List<int> { 0, 0, 0, 0, 0, 0, 1 };
		BannedFloorIndexes = new List<int> { 1, 2, 3, 4, 5 };
		CanBeSummonedByMichael = false;
		All25LetterWords = new List<string>(Vocabulary.ActiveLanguageVocabulary.TwentyFiveLetterWords);
	}

	public override string GetDescription()
	{
		if (DraftedModifiers.Count == 0)
		{
			return $"Summons {FloorAdjustedModification} bosses";
		}
		string text = "";
		for (int i = 0; i < DraftedModifiers.Count; i++)
		{
			text += $"Boss {i + 1}: {DraftedModifiers[i].GetDescription()}\n";
		}
		if (SummonedBossesDefeated)
		{
			text = "You must use every tile on the grid!";
		}
		return text;
	}

	public void PopulateModifierDrafts()
	{
		List<Type> list = (from t in Assembly.GetAssembly(typeof(BossModifier)).GetTypes()
			where t.IsClass && t.IsSubclassOf(typeof(BossModifier))
			select t).ToList();
		foreach (Type item in GameStatics.GetBossModifiersRequiringUnlock())
		{
			list.Remove(item);
		}
		List<BossModifier> list2 = (from bossType in list
			select Activator.CreateInstance(bossType) as BossModifier into bossMod
			where bossMod.CanBeSummonedByMichael
			select bossMod).ToList();
		Debug.Log($"Possible modifiers available for Michael drafts = {list2.Count}");
		if (UnityEngine.Random.Range(0, 2) == 0)
		{
			list2.RemoveAll((BossModifier boss) => boss is MinWordLength);
		}
		else
		{
			list2.RemoveAll((BossModifier boss) => boss is MaxWordLength);
		}
		Debug.Log($"Possible modifiers after removals = {list2.Count}");
		for (int i = 0; i < FloorAdjustedModification; i++)
		{
			List<BossModifier> list3 = new List<BossModifier>();
			for (int j = 0; j < 2; j++)
			{
				BossModifier bossModifier = list2[UnityEngine.Random.Range(0, list2.Count)];
				bossModifier.SetFloorAdjustedModification(5 - i, isAscensionModifierActive: false);
				list3.Add(bossModifier);
				list2.Remove(bossModifier);
			}
			ModifierDrafts.Add(list3);
		}
	}

	public bool HasPlayerSubmittedMultipleCursedWord()
	{
		if (GameStatics.GetPlayer().CurrentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count((HistoricWord word) => word.GetCurseLevel() != CurseLevel.Normal) >= 2)
		{
			return true;
		}
		return false;
	}

	public List<HistoricWord> GetCursedWordsFromRun()
	{
		List<HistoricWord> list = GameStatics.GetPlayer().CurrentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Where((HistoricWord word) => word.GetCurseLevel() == CurseLevel.Major).ToList();
		List<HistoricWord> list2 = GameStatics.GetPlayer().CurrentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Where((HistoricWord word) => word.GetCurseLevel() == CurseLevel.Minor).ToList();
		if (list2.Count() + list.Count() >= 2)
		{
			List<HistoricWord> list3 = new List<HistoricWord>();
			for (int i = 0; i < 2; i++)
			{
				if (list.Count() > 0)
				{
					HistoricWord item = list[UnityEngine.Random.Range(0, list.Count)];
					list.Remove(item);
					list3.Add(item);
				}
				else
				{
					HistoricWord item2 = list2[UnityEngine.Random.Range(0, list2.Count)];
					list2.Remove(item2);
					list3.Add(item2);
				}
			}
			return list3;
		}
		return new List<HistoricWord>();
	}

	public List<DiscussionPacket> MichaelIntroDiscussion()
	{
		Emotions playerEmotion = GetPlayerEmotion();
		if (HasPlayerSubmittedMultipleCursedWord())
		{
			List<string> list = (from word in GetCursedWordsFromRun()
				select DialogueUtility.FractionFriendlyString(word)).ToList();
			List<DiscussionPacket> list2 = new List<DiscussionPacket>();
			list2.Add(new DiscussionPacket((text: "That is IT! I've had it up to here with your nonsense!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true));
			list2.Add(new DiscussionPacket((text: "Michael...? What's wrong?", emotion: playerEmotion), isLeftSided: false));
			list2.Add(new DiscussionPacket((text: "My dictionary is ruined! I keep having to cross things out and fix your mistakes!", emotion: Emotions.MichaelWorried), isLeftSided: true));
			list2.Add(new DiscussionPacket((text: "I mean seriously... " + list[0] + " and " + list[1] + "? They're just a jumble of tiles! Words used to mean something you know?!", emotion: Emotions.MichaelConfused), isLeftSided: true));
			list2.Add(new DiscussionPacket((text: "It's time someone put a stop to you, once and for all!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true));
			return BossModifier.BonesifyDialogue(list2);
		}
		List<string> list3 = Player.Shuffle((from item in GameStatics.GetPlayer().GetAllItems()
			select item.Name).ToList()).ToList();
		return BossModifier.BonesifyDialogue(new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "That is IT! I've had it up to here with your nonsense!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "Michael...? What's wrong?", emotion: playerEmotion), isLeftSided: false),
			new DiscussionPacket((text: "What are you doing with all those items?!", emotion: Emotions.MichaelWorried), isLeftSided: true),
			new DiscussionPacket((text: "I mean seriously... " + list3[0] + "? How is that suppose to help with writing a dictionary?!", emotion: Emotions.MichaelConfused), isLeftSided: true),
			new DiscussionPacket((text: "It's time someone put a stop to you, once and for all!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true)
		});
	}

	public DiscussionPacket GetDraftQuip()
	{
		DiscussionPacket discussionPacket = DraftQuips[UnityEngine.Random.Range(0, DraftQuips.Count())];
		DraftQuips.Remove(discussionPacket);
		return discussionPacket;
	}

	public List<DiscussionPacket> MichaelLosesItDialogue()
	{
		Emotions playerEmotion = GetPlayerEmotion();
		return BossModifier.BonesifyDialogue(new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "Enough is enough! No more items!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "No more bosses!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "No more ridiculously high targets!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "We're going back to basics, just you and the grid.", emotion: Emotions.MichaelExplaining), isLeftSided: true),
			new DiscussionPacket((text: "But you have to use <b>all</b> the tiles!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "...", emotion: playerEmotion), isLeftSided: false),
			new DiscussionPacket((text: "WHAT?!", emotion: Emotions.MichaelConfused), isLeftSided: true),
			new DiscussionPacket((text: "Psst! This should help you out!", emotion: Emotions.ShopkeeperIdea), isLeftSided: false),
			new DiscussionPacket((text: "Edward?! What are you doing here LITTLE BROTHER??", emotion: Emotions.MichaelConfused), isLeftSided: true),
			new DiscussionPacket((text: "I go by E<font=ChessPiece SDF>j</font>?A56 now.", emotion: Emotions.ShopkeeperExplaining), isLeftSided: false),
			new DiscussionPacket((text: "Can I be honest, I always thought you two were the same person.", emotion: playerEmotion), isLeftSided: false)
		});
	}

	public string GetRandom25LetterWord()
	{
		string text = All25LetterWords[UnityEngine.Random.Range(0, All25LetterWords.Count)];
		All25LetterWords.Remove(text);
		return text;
	}

	private string MakeFirstLetterCapital(string input)
	{
		return input[0].ToString().ToUpper() + input.Substring(1);
	}

	public List<DiscussionPacket> EndOfFightDialogue()
	{
		Emotions playerEmotion = GetPlayerEmotion();
		List<DiscussionPacket> list = new List<DiscussionPacket>();
		list.Add(new DiscussionPacket((text: "Wahoooo! That was a long one!", emotion: Emotions.ShopkeeperExplaining), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "I wonder what word it was... I can't think of any words that are that long!", emotion: playerEmotion), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "Hmmm... I guess it could have been " + GetRandom25LetterWord() + "?", emotion: Emotions.MichaelThinking), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Or " + GetRandom25LetterWord() + "...", emotion: Emotions.MichaelExplaining), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Or even " + GetRandom25LetterWord() + "! This is actually kind of fun!", emotion: Emotions.MichaelHappy), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "I liked it just the way it was.", emotion: Emotions.ShopkeeperIdea), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "But then again, maybe it was " + GetRandom25LetterWord() + ", or " + GetRandom25LetterWord() + ", or " + GetRandom25LetterWord() + "?", emotion: Emotions.MichaelExplaining), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Or maybe " + GetRandom25LetterWord() + "? That's one of my favourites!", emotion: Emotions.MichaelHappy), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Ah... looks like we could be here a while....", emotion: Emotions.ShopkeeperIdea), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "Time to head back to the Clubhouse?", emotion: playerEmotion), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "Yep, time to go home. There's still lots of Secret Syntactic Society work to do!", emotion: Emotions.ShopkeeperExplaining), isLeftSided: false));
		list.Add(new DiscussionPacket((text: "Oh, and there's always " + GetRandom25LetterWord() + "!", emotion: Emotions.MichaelHappy), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Maybe it was " + GetRandom25LetterWord() + "?", emotion: Emotions.MichaelThinking), isLeftSided: true));
		list.Add(new DiscussionPacket((text: MakeFirstLetterCapital(GetRandom25LetterWord()) + " would also work!", emotion: Emotions.MichaelThinking), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Or it could have been " + GetRandom25LetterWord() + " - now there's a great word!", emotion: Emotions.MichaelHappy), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "What about " + GetRandom25LetterWord() + " - that works!", emotion: Emotions.MichaelExplaining), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Oh! Of course! I forgot about " + GetRandom25LetterWord() + "!", emotion: Emotions.MichaelHappy), isLeftSided: true));
		list.Add(new DiscussionPacket((text: "Oops sorry, am I in the way?", emotion: Emotions.MichaelWorried), isLeftSided: true));
		return BossModifier.BonesifyDialogue(list);
	}

	public DiscussionPacket ReturnDraftOneQuip()
	{
		List<DiscussionPacket> list = new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "Ready for a challenge?", emotion: Emotions.MichaelConfused), isLeftSided: true),
			new DiscussionPacket((text: "Think you've got what it takes?", emotion: Emotions.MichaelExplaining), isLeftSided: true),
			new DiscussionPacket((text: "Now for a true test of your skill...", emotion: Emotions.MichaelHappy), isLeftSided: true)
		};
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public DiscussionPacket ReturnDraftTwoQuip()
	{
		List<DiscussionPacket> list = new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "Let's up the ante!", emotion: Emotions.MichaelHappy), isLeftSided: true),
			new DiscussionPacket((text: "Choose wisely...", emotion: Emotions.MichaelExplaining), isLeftSided: true),
			new DiscussionPacket((text: "Let's make things a little more interesting...", emotion: Emotions.MichaelSnide), isLeftSided: true)
		};
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public DiscussionPacket ReturnDraftThreeQuip()
	{
		List<DiscussionPacket> list = new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "Think you can handle another one?", emotion: Emotions.MichaelConfused), isLeftSided: true),
			new DiscussionPacket((text: "Hmmm... Let's raise the stakes a <i>little</i> more!", emotion: Emotions.MichaelExplaining), isLeftSided: true),
			new DiscussionPacket((text: "Finding this easy? Let's add a bit more of a challenge!", emotion: Emotions.MichaelHappy), isLeftSided: true)
		};
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public List<DiscussionPacket> ReturnMichaelLoosesIt()
	{
		return BossModifier.BonesifyDialogue(new List<DiscussionPacket>
		{
			new DiscussionPacket((text: "That's it. No more items! No more bosses! No more nothing!", emotion: Emotions.MichaelAnnoyed), isLeftSided: true),
			new DiscussionPacket((text: "You have to use all the tiles!", emotion: Emotions.MichaelSnide), isLeftSided: true),
			new DiscussionPacket((text: "Pssst! This should make things easier!", emotion: Emotions.ShopkeeperIdea), isLeftSided: false)
		});
	}
}
