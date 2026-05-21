using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using MelonLoader;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public static class DictionaryExporter
    {
        private static readonly string OutputDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver"
        );

        private static readonly string WordsPath = Path.Combine(OutputDir, "game_words.txt");
        private static readonly string MetaPath = Path.Combine(OutputDir, "game_words_meta.json");

        private static string _lastFingerprint = "";

        public static string WordsFilePath
        {
            get { return WordsPath; }
        }

        public static bool TryExport(bool logSuccess)
        {
            try
            {
                var words = CollectWords();
                if (words == null || words.Count == 0)
                    return false;

                var language = GetActiveLanguageName();
                var fingerprint = language + "|" + words.Count;
                if (fingerprint == _lastFingerprint && File.Exists(WordsPath))
                    return true;

                WriteWords(words);
                WriteMeta(words.Count, language);
                _lastFingerprint = fingerprint;

                if (logSuccess)
                    MelonLogger.Msg(
                        "Exported " + words.Count + " game words (" + language + ") to " + WordsPath
                    );
                return true;
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("Dictionary export failed: " + ex.Message);
                return false;
            }
        }

        private static HashSet<string> CollectWords()
        {
            EnsureActiveVocabulary();
            var vocab = Vocabulary.ActiveLanguageVocabulary;
            if (vocab == null || !vocab.IsInitialized)
                return null;

            var words = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            if (vocab.TriesByLength != null)
            {
                foreach (var trie in vocab.TriesByLength.Values)
                {
                    if (trie == null)
                        continue;
                    var list = trie.GetAllWords();
                    if (list == null)
                        continue;
                    foreach (var w in list)
                        AddWord(words, w);
                }
            }

            AddList(words, vocab.FourLetterCuratedWords);
            AddList(words, vocab.FiveLetterCuratedWords);
            AddList(words, vocab.SixLetterCuratedWords);
            AddList(words, vocab.TwentyFiveLetterWords);

            return words;
        }

        private static void EnsureActiveVocabulary()
        {
            var vocab = Vocabulary.ActiveLanguageVocabulary;
            if (vocab != null && vocab.IsInitialized)
                return;

            try
            {
                Vocabulary.SetActiveLanguageVocabulary(DictionaryLanguage.EnglishDefault);
            }
            catch
            {
                // already set or unavailable until a run starts
            }

            vocab = Vocabulary.ActiveLanguageVocabulary;
            if (vocab != null && !vocab.IsInitialized)
                vocab.TryInitializeVocabulary();
        }

        private static void AddWord(HashSet<string> words, string w)
        {
            if (string.IsNullOrWhiteSpace(w))
                return;

            w = w.Trim().ToLowerInvariant();
            if (w.Length < 2)
                return;

            for (var i = 0; i < w.Length; i++)
            {
                if (!char.IsLetter(w[i]))
                    return;
            }

            words.Add(w);
        }

        private static void AddList(HashSet<string> words, List<string> list)
        {
            if (list == null)
                return;

            foreach (var w in list)
                AddWord(words, w);
        }

        private static string GetActiveLanguageName()
        {
            var vocab = Vocabulary.ActiveLanguageVocabulary;
            if (vocab == null)
                return "unknown";
            return vocab.Language.ToString();
        }

        private static void WriteWords(HashSet<string> words)
        {
            Directory.CreateDirectory(OutputDir);
            var sorted = words.ToList();
            sorted.Sort(StringComparer.Ordinal);
            File.WriteAllLines(WordsPath, sorted, new UTF8Encoding(false));
        }

        private static void WriteMeta(int count, string language)
        {
            var meta = new DictionaryExportMeta
            {
                count = count,
                language = language,
                exported_at = DateTime.UtcNow.ToString("o"),
            };
            var json = JsonConvert.SerializeObject(meta, Formatting.Indented);
            File.WriteAllText(MetaPath, json, new UTF8Encoding(false));
        }
    }

    public class DictionaryExportMeta
    {
        public int count;
        public string language;
        public string exported_at;
    }
}
