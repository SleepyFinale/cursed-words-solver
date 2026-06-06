using ICSharpCode.Decompiler;
using ICSharpCode.Decompiler.CSharp;
using ICSharpCode.Decompiler.TypeSystem;

// Usage:
//   dotnet run --project scripts/decompile_type -- [--dll <path>] [--out <dir>]
//       [--subclasses-of <BaseType>]... [TypeName]...
// With --out, each type is written to <dir>/<TypeName>.decompiled.cs; otherwise
// all selected types are printed to stdout (legacy behaviour).

string dll = @"C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\Cursed Words_Data\Managed\Assembly-CSharp.dll";
string? outDir = null;
var typeNames = new List<string>();
var subclassesOf = new List<string>();

for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--dll":
            dll = args[++i];
            break;
        case "--out":
            outDir = args[++i];
            break;
        case "--subclasses-of":
            subclassesOf.Add(args[++i]);
            break;
        default:
            typeNames.Add(args[i]);
            break;
    }
}

if (typeNames.Count == 0 && subclassesOf.Count == 0)
{
    typeNames.AddRange(new[] { "Hanafuda", "PokerHands", "ScoreCalculation" });
}

if (!File.Exists(dll))
{
    Console.Error.WriteLine($"DLL not found: {dll}");
    return 1;
}

var settings = new DecompilerSettings(LanguageVersion.Latest) { ThrowOnAssemblyResolveErrors = false };
var decompiler = new CSharpDecompiler(dll, settings);

var allTypes = decompiler.TypeSystem.MainModule.TopLevelTypeDefinitions.ToList();

static bool IsDescendantOf(ITypeDefinition t, string baseName)
{
    foreach (var bt in t.GetAllBaseTypeDefinitions())
    {
        if (bt.Name == baseName && !ReferenceEquals(bt, t))
        {
            return true;
        }
    }
    return false;
}

var selected = new List<ITypeDefinition>();

foreach (var baseName in subclassesOf)
{
    selected.AddRange(allTypes.Where(t => IsDescendantOf(t, baseName)));
}

foreach (var name in typeNames)
{
    var t = allTypes.FirstOrDefault(x => x.Name == name);
    if (t is null)
    {
        Console.Error.WriteLine($"// Type not found: {name}");
        continue;
    }
    selected.Add(t);
}

selected = selected
    .GroupBy(t => t.FullName)
    .Select(g => g.First())
    .OrderBy(t => t.Name)
    .ToList();

if (outDir is not null)
{
    Directory.CreateDirectory(outDir);
}

int ok = 0;
foreach (var t in selected)
{
    string code;
    try
    {
        code = decompiler.DecompileTypeAsString(new TopLevelTypeName(t.FullName));
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"// Failed to decompile {t.FullName}: {ex.Message}");
        continue;
    }

    if (outDir is not null)
    {
        File.WriteAllText(Path.Combine(outDir, t.Name + ".decompiled.cs"), code);
    }
    else
    {
        Console.WriteLine($"// ===== {t.FullName} =====");
        Console.WriteLine(code);
        Console.WriteLine();
    }
    ok++;
}

Console.Error.WriteLine($"Decompiled {ok}/{selected.Count} types" + (outDir is not null ? $" -> {outDir}" : ""));
return 0;
