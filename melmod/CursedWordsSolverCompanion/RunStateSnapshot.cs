using System.Collections.Generic;

namespace CursedWordsSolverCompanion
{
    public sealed class RunStateSnapshot
    {
        public string character = "";
        public string pin_branch = "";
        public int money;
        public List<RunStateItem> stickers = new List<RunStateItem>();
        public List<RunStateItem> stamps = new List<RunStateItem>();
        public string boss_id = "";
        public string boss_name = "";
        public string boss_effect = "";
        public Dictionary<string, string> extras = new Dictionary<string, string>();
        public BoardSnapshot board;
    }

    public sealed class RunStateItem
    {
        public string id = "";
        public string name = "";
        public int level = 1;
    }
}
