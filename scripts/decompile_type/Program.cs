using System.Text;
using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.TypeSystem;

var dll = args.Length > 0
    ? args[0]
    : @"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\Cursed Words_Data\Managed\Assembly-CSharp.dll";
var types = args.Length > 1 ? args[1..] : new[] { "Hanafuda", "PokerHands", "ScoreCalculation" };

if (!File.Exists(dll))
{
    Console.Error.WriteLine($"DLL not found: {dll}");
    return 1;
}

var settings = new DecompilerSettings(LanguageVersion.Latest) { ThrowOnAssemblyResolveErrors = false };
var decompiler = new CSharpDecompiler(dll, settings);

foreach (var typeName in types)
{
    var fullName = decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions
        .FirstOrDefault(t => t.Name == typeName)
        ?.FullName;
    if (fullName is null)
    {
        Console.WriteLine($"// Type not found: {typeName}");
        continue;
    }

    Console.WriteLine($"// ===== {fullName} =====");
    var typeRef = new TopLevelTypeName(fullName);
    Console.WriteLine(decompiler.DecompileTypeAsString(typeRef));
    Console.WriteLine();
}

return 0;
