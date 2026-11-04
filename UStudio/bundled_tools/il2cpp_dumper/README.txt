Il2CppDumper (patched fork) — used by UStudio to make "dummy" DLLs for IL2CPP games, so their
MonoBehaviour scripts can be read.

Original: Il2CppDumper by Perfare, https://github.com/Perfare/Il2CppDumper (MIT licence, see LICENSE.txt).

This build differs from the original in two ways:
  * Correct dummy DLLs for metadata v38/v39 games (Unity 6):
    custom attributes kept, enums marked as enums, nested types attached to the right outer type.
  * Also builds for .NET Framework 4.8 (part of Windows 10/11), so nothing has to be installed to run it.

Built from that source with `dotnet build -c Release` (bin\Release\net48). config.json here is
UStudio's own: only the dummy DLLs are generated, no struct/header files, no "press any key".
