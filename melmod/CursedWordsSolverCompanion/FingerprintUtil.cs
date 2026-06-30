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
            RunStateExporter.AppendBossFingerprint(sb, BossResolver.ResolveLiveForExport(player));
            sb.Append('|');
            var beforePin = sb.Length;
            RunStateExporter.AppendPinFingerprint(sb, player.MyCharacter);
            if (sb.Length == beforePin)
            {
                sb.Append(':');
                sb.Append(RunStateExporter.GetPinBranch(player.MyCharacter));
            }
            return sb.ToString();
        }

        public static string ComputeBoardFingerprint(Player player)
        {
            return RunStateExporter.ComputeBoardFingerprint(player);
        }
    }
}
