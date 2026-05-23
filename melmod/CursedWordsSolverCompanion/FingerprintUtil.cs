using System.Collections.Generic;
using System.Text;

namespace CursedWordsSolverCompanion
{
    public static class FingerprintUtil
    {
        public static string ComputeLoadoutFingerprint(Player player)
        {
            if (player == null)
                return "";

            var sb = new StringBuilder();
            sb.Append(RunStateExporter.GetCharacterName(player.MyCharacter));
            sb.Append('|');
            sb.Append(player.Money);
            sb.Append('|');
            RunStateExporter.AppendItemsFingerprint(sb, player.Stickers);
            sb.Append('|');
            RunStateExporter.AppendItemsFingerprint(sb, player.Stamps);
            sb.Append('|');
            RunStateExporter.AppendBossFingerprint(sb, BossResolver.Resolve(player));
            sb.Append('|');
            RunStateExporter.AppendPinFingerprint(sb, player.MyCharacter);
            return sb.ToString();
        }

        public static string ComputeBoardFingerprint(Player player)
        {
            return RunStateExporter.ComputeBoardFingerprint(player);
        }
    }
}
