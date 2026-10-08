using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Threading;
using MelonLoader;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Starts the bundled solver when the game launches and stops it on quit.
    /// A dev DLL with no exe beside UserData leaves the usual cursed-solver process alone.
    /// </summary>
    internal static class SolverHost
    {
        private const string ExeFileName = "CursedWordsSolver.exe";
        private const string BundleFileName = "CursedWordsSolver.bundle.zip";
        private const string StampFileName = "CursedWordsSolver.bundle.stamp";
        private const string ProcessName = "CursedWordsSolver";
        private const uint JobObjectInfoClassExtendedLimit = 9;
        private const uint JobObjectLimitKillOnJobClose = 0x2000;

        private static Process _process;
        private static IntPtr _job = IntPtr.Zero;
        private static StreamWriter _log;
        private static int _stopping;
        private static int _unexpectedExit;
        private static bool _missingLogged;

        public static string SolverLogPath =>
            Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".cursed_words_solver",
                "solver.log"
            );

        public static void Start()
        {
            try
            {
                EnsureBundleExtracted();
                var exe = FindSolverExe();
                if (exe == null)
                {
                    if (!_missingLogged)
                    {
                        _missingLogged = true;
                        MelonLogger.Msg(
                            "No bundled solver found. Dev build: start cursed-solver yourself. "
                                + "Players: install the package so "
                                + ExeFileName
                                + " is under UserData."
                        );
                    }
                    return;
                }

                if (IsSolverRunning())
                {
                    MelonLogger.Msg("Bundled solver already running (" + exe + ")");
                    return;
                }

                var logPath = SolverLogPath;
                Directory.CreateDirectory(Path.GetDirectoryName(logPath));
                _log = new StreamWriter(
                    new FileStream(
                        logPath,
                        FileMode.Append,
                        FileAccess.Write,
                        FileShare.ReadWrite
                    )
                )
                {
                    AutoFlush = true,
                };
                _log.WriteLine();
                _log.WriteLine(
                    "---- solver start " + DateTime.UtcNow.ToString("o") + " ----"
                );
                _log.WriteLine("exe: " + exe);

                var psi = new ProcessStartInfo
                {
                    FileName = exe,
                    WorkingDirectory = Path.GetDirectoryName(exe),
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
                proc.OutputDataReceived += (_, e) => AppendLog(e.Data);
                proc.ErrorDataReceived += (_, e) => AppendLog(e.Data);
                proc.Exited += (_, __) =>
                {
                    if (Interlocked.CompareExchange(ref _stopping, 0, 0) == 0)
                        Interlocked.Exchange(ref _unexpectedExit, 1);
                };
                if (!proc.Start())
                {
                    MelonLogger.Error("Failed to start solver: " + exe);
                    return;
                }
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
                TryAssignKillOnJobClose(proc);
                _process = proc;
                MelonLogger.Msg("Started bundled solver: " + exe);
                MelonLogger.Msg("Solver log: " + logPath);
            }
            catch (Exception ex)
            {
                MelonLogger.Error("Solver start failed: " + ex);
            }
        }

        public static void Poll()
        {
            if (Interlocked.Exchange(ref _unexpectedExit, 0) != 1)
                return;
            var code = -1;
            try
            {
                if (_process != null && _process.HasExited)
                    code = _process.ExitCode;
            }
            catch (Exception)
            {
                // Exit code is optional context for the log line.
            }
            MelonLogger.Error(
                "Bundled solver exited (code " + code + "). See " + SolverLogPath
            );
        }

        public static void Stop()
        {
            if (Interlocked.Exchange(ref _stopping, 1) == 1)
                return;
            var proc = _process;
            _process = null;
            try
            {
                if (_job != IntPtr.Zero)
                {
                    CloseHandle(_job);
                    _job = IntPtr.Zero;
                }
                else if (proc != null && !proc.HasExited)
                {
                    KillProcessTree(proc);
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("Solver stop failed: " + ex.Message);
            }
            finally
            {
                try
                {
                    proc?.Dispose();
                }
                catch (Exception)
                {
                    // Already gone.
                }
                try
                {
                    _log?.Dispose();
                    _log = null;
                }
                catch (Exception)
                {
                    _log = null;
                }
            }
        }

        private static bool IsSolverRunning()
        {
            try
            {
                return Process.GetProcessesByName(ProcessName).Length > 0;
            }
            catch (Exception)
            {
                return false;
            }
        }

        private static void EnsureBundleExtracted()
        {
            foreach (var dir in SolverDirectories())
            {
                var bundle = Path.Combine(dir, BundleFileName);
                if (!File.Exists(bundle))
                    continue;
                var stamp = BundleStamp(bundle);
                var stampPath = Path.Combine(dir, StampFileName);
                var exePath = Path.Combine(dir, ExeFileName);
                if (File.Exists(exePath) && File.Exists(stampPath))
                {
                    var existing = File.ReadAllText(stampPath).Trim();
                    if (existing == stamp)
                        return;
                }

                MelonLogger.Msg("Unpacking bundled solver (first launch or update)...");
                if (Directory.Exists(dir))
                {
                    foreach (var entry in Directory.GetFileSystemEntries(dir))
                    {
                        var name = Path.GetFileName(entry);
                        if (
                            name.Equals(BundleFileName, StringComparison.OrdinalIgnoreCase)
                            || name.Equals(StampFileName, StringComparison.OrdinalIgnoreCase)
                        )
                            continue;
                        if (Directory.Exists(entry))
                            Directory.Delete(entry, true);
                        else
                            File.Delete(entry);
                    }
                }
                else
                {
                    Directory.CreateDirectory(dir);
                }

                ZipFile.ExtractToDirectory(bundle, dir);
                File.WriteAllText(stampPath, stamp);
                MelonLogger.Msg("Unpacked solver to " + dir);
                return;
            }
        }

        private static string BundleStamp(string bundlePath)
        {
            var info = new FileInfo(bundlePath);
            return info.Length + ":" + info.LastWriteTimeUtc.Ticks;
        }

        private static IEnumerable<string> SolverDirectories()
        {
            var dllDir = Path.GetDirectoryName(typeof(SolverHost).Assembly.Location);
            if (string.IsNullOrEmpty(dllDir))
                yield break;
            var root = FindInstallRoot(dllDir);
            if (root == null)
                yield break;

            var packageFolder = new DirectoryInfo(dllDir).Name;
            if (!packageFolder.Equals("Mods", StringComparison.OrdinalIgnoreCase))
            {
                yield return Path.Combine(root, "UserData", packageFolder, "solver");
            }

            yield return Path.Combine(root, "UserData", "CursedWordsSolver");
        }

        private static string FindSolverExe()
        {
            foreach (var dir in SolverDirectories())
            {
                var exe = Path.Combine(dir, ExeFileName);
                if (File.Exists(exe))
                    return exe;
            }
            return null;
        }

        private static string FindInstallRoot(string startDir)
        {
            var dir = new DirectoryInfo(startDir);
            while (dir != null)
            {
                var mods = Path.Combine(dir.FullName, "Mods");
                if (Directory.Exists(mods))
                {
                    var userData = Path.Combine(dir.FullName, "UserData");
                    var melon = Path.Combine(dir.FullName, "MelonLoader");
                    if (Directory.Exists(userData) || Directory.Exists(melon))
                        return dir.FullName;
                }
                dir = dir.Parent;
            }
            return null;
        }

        private static void AppendLog(string line)
        {
            if (line == null)
                return;
            try
            {
                var log = _log;
                if (log == null)
                    return;
                lock (log)
                {
                    log.WriteLine(line);
                }
            }
            catch (Exception)
            {
                // Logging must not take down the game.
            }
        }

        private static void KillProcessTree(Process proc)
        {
            try
            {
                var killer = Process.Start(
                    new ProcessStartInfo
                    {
                        FileName = "taskkill.exe",
                        Arguments = "/PID " + proc.Id + " /T /F",
                        CreateNoWindow = true,
                        UseShellExecute = false,
                    }
                );
                killer?.WaitForExit(5000);
            }
            catch (Exception)
            {
                try
                {
                    if (!proc.HasExited)
                        proc.Kill();
                }
                catch (Exception)
                {
                    // Process already exited.
                }
            }
        }

        private static void TryAssignKillOnJobClose(Process proc)
        {
            var job = IntPtr.Zero;
            try
            {
                job = CreateJobObject(IntPtr.Zero, null);
                if (job == IntPtr.Zero)
                    return;
                var info = new JobObjectExtendedLimitInformation();
                info.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;
                var length = Marshal.SizeOf(typeof(JobObjectExtendedLimitInformation));
                var ptr = Marshal.AllocHGlobal(length);
                try
                {
                    Marshal.StructureToPtr(info, ptr, false);
                    if (!SetInformationJobObject(
                            job,
                            JobObjectInfoClassExtendedLimit,
                            ptr,
                            (uint)length
                        ))
                    {
                        CloseHandle(job);
                        return;
                    }
                }
                finally
                {
                    Marshal.FreeHGlobal(ptr);
                }
                if (!AssignProcessToJobObject(job, proc.Handle))
                {
                    CloseHandle(job);
                    return;
                }
                _job = job;
                job = IntPtr.Zero;
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("Solver job object skipped: " + ex.Message);
                if (job != IntPtr.Zero)
                    CloseHandle(job);
            }
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr hJob,
            uint jobObjectInfoClass,
            IntPtr lpJobObjectInfo,
            uint cbJobObjectInfoLength
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        [StructLayout(LayoutKind.Sequential)]
        private struct JobObjectBasicLimitInformation
        {
            public long PerProcessUserTimeLimit;
            public long PerJobUserTimeLimit;
            public uint LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public uint ActiveProcessLimit;
            public UIntPtr Affinity;
            public uint PriorityClass;
            public uint SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IoCounters
        {
            public ulong ReadOperationCount;
            public ulong WriteOperationCount;
            public ulong OtherOperationCount;
            public ulong ReadTransferCount;
            public ulong WriteTransferCount;
            public ulong OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JobObjectExtendedLimitInformation
        {
            public JobObjectBasicLimitInformation BasicLimitInformation;
            public IoCounters IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }
    }
}
