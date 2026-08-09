using System;
using System.Collections.Generic;
using UnityEngine;

public class LanguageVocabulary
{
	public DictionaryLanguage Language;

	public Dictionary<int, WordTrie> TriesByLength = new Dictionary<int, WordTrie>();

	public List<string> TwentyFiveLetterWords = new List<string>();

	public List<string> FourLetterCuratedWords = new List<string>();

	public List<string> FiveLetterCuratedWords = new List<string>();

	public List<string> SixLetterCuratedWords = new List<string>();

	public Alphabet LanguageAlphabet;

	public bool IsInitialized;

	public void TryInitializeVocabulary()
	{
		if (!IsInitialized)
		{
			GetAllWordsFromFiles();
			LanguageAlphabet = Vocabulary.LanguageAlphabets[Language];
			IsInitialized = true;
		}
	}

	private void GetAllWordsFromFiles()
	{
		HashSet<string> hashSet = new HashSet<string>();
		foreach (string item2 in Vocabulary.BannedWordFiles[Language])
		{
			TextAsset textAsset = Resources.Load<TextAsset>(item2);
			if (textAsset != null)
			{
				string[] array = textAsset.text.Split(new char[2] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
				for (int i = 0; i < array.Length; i++)
				{
					string item = array[i].Trim().ToLower();
					hashSet.Add(item);
				}
				continue;
			}
			throw new Exception(item2 + " not found!");
		}
		foreach (string item3 in Vocabulary.WordFiles[Language])
		{
			TextAsset textAsset2 = Resources.Load<TextAsset>(item3);
			if (textAsset2 != null)
			{
				string[] array = textAsset2.text.Split(new char[2] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
				for (int i = 0; i < array.Length; i++)
				{
					string text = array[i].Trim().ToLower();
					int length = text.Length;
					if (hashSet.Contains(text))
					{
						continue;
					}
					if (Language != 0)
					{
						if (length == 4)
						{
							FourLetterCuratedWords.Add(text);
						}
						if (length == 5)
						{
							FiveLetterCuratedWords.Add(text);
						}
						if (length == 6)
						{
							SixLetterCuratedWords.Add(text);
						}
					}
					if (!TriesByLength.TryGetValue(length, out var value))
					{
						value = new WordTrie();
						TriesByLength[length] = value;
					}
					value.Insert(text);
				}
				continue;
			}
			throw new Exception(item3 + " not found!");
		}
		TwentyFiveLetterWords = new List<string>
		{
			"alkenylidenecyclopropanes", "amygdalohippocampectomies", "antidisestablishmentarian", "antimetanitrobenzaldoxime", "ballistocardiographically", "cholinephosphotransferase", "demethylchlortetracycline", "dichlorotetrafluoroethane", "diphenylhydroxyethylamine", "electroencephalographical",
			"formaldehydesulphoxylates", "hypobetalipoproteinaemias", "immunoelectrophoretically", "intracerebroventricularly", "microcrystallographically", "microspectrophotometrical", "monohydroxycorticosterone", "octillionduotrigintillion", "pancreaticoduodenectomies", "phosphatidylethanolamines",
			"quinquagintatrecentillion", "quinquaquadragintillionth", "scaphotrapeziotrapezoidal", "tetraiodophenolphthaleins", "undecillionsedecilliardth", "uvulopalatopharyngoplasty"
		};
		if (Language == DictionaryLanguage.EnglishDefault)
		{
			foreach (string englishCuratedWordFile in Vocabulary.EnglishCuratedWordFiles)
			{
				TextAsset textAsset3 = Resources.Load<TextAsset>(englishCuratedWordFile);
				if (!(textAsset3 != null))
				{
					continue;
				}
				string[] array = textAsset3.text.Split(new char[2] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
				for (int i = 0; i < array.Length; i++)
				{
					string text2 = array[i].Trim().ToLower();
					int length2 = text2.Length;
					if (!hashSet.Contains(text2))
					{
						if (length2 == 4)
						{
							FourLetterCuratedWords.Add(text2);
						}
						if (length2 == 5)
						{
							FiveLetterCuratedWords.Add(text2);
						}
						if (length2 == 6)
						{
							SixLetterCuratedWords.Add(text2);
						}
					}
				}
			}
		}
		Debug.Log($"Curated words loaded. Loaded: {FourLetterCuratedWords.Count} 4 letter words, {FiveLetterCuratedWords.Count} 5 letter words and {SixLetterCuratedWords.Count} 6 letter words.");
	}
}
