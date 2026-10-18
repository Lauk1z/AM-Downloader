namespace AMDownloader.WinUI.Services;

public sealed class RuntimePaths
{
    public string Resources { get; }
    public string Bundle { get; }
    public string Python { get; }
    public string AudioHost { get; }
    public string Ffmpeg => Path.Combine(Bundle, "deps", "ffmpeg.exe");
    public string Utility { get; }
    public RuntimePaths(string? resources)
    {
        var candidates = resources is not null ? new[] { resources } : Ancestors(AppContext.BaseDirectory).Concat(new[] { Environment.CurrentDirectory });
        Resources = candidates.FirstOrDefault(x => File.Exists(Path.Combine(x, "musicdesk_worker.py")))
            ?? throw new DirectoryNotFoundException("下载组件缺失，请使用完整的 WinUI 包，或通过 --resources 指定现有源码目录。");
        Bundle = new[] { Path.Combine(Resources, "backend"), Path.Combine(Resources, "vendor", "backend") }
            .FirstOrDefault(x => File.Exists(Path.Combine(x, "bundle.json"))) ?? throw new DirectoryNotFoundException("内置后端 bundle.json 缺失。");
        Python = new[] { Path.Combine(Bundle, ".venv", "python.exe"), Path.Combine(Bundle, ".venv", "Scripts", "python.exe") }.FirstOrDefault(File.Exists)
            ?? throw new FileNotFoundException("内置 Python 运行环境缺失。");
        AudioHost = new[] { Path.Combine(AppContext.BaseDirectory, "native", "am_audio.exe"), Path.Combine(Resources, "native", "bin", "am_audio.exe") }.FirstOrDefault(File.Exists)
            ?? throw new FileNotFoundException("原生音频组件缺失。");
        Utility = new[] { Path.Combine(Resources, "winui", "engine", "library_worker.py"), Path.Combine(Resources, "engine", "library_worker.py") }.FirstOrDefault(File.Exists)
            ?? throw new FileNotFoundException("WinUI 元数据组件缺失。");
    }
    private static IEnumerable<string> Ancestors(string path)
    { for (DirectoryInfo? current = new(path); current is not null; current = current.Parent) yield return current.FullName; }
}
