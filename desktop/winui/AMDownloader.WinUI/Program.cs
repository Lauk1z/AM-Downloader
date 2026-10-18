using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using AMDownloader.WinUI.Services;

namespace AMDownloader.WinUI;

internal static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        var options = LaunchOptions.Parse(args);
        using var instance = new SingleInstance(options.Profile);
        if (!instance.Acquire()) return;
        WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(parameters =>
        {
            SynchronizationContext.SetSynchronizationContext(new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread()));
            try { _ = new App(options, instance); }
            catch (Exception error) { Directory.CreateDirectory(options.Profile); File.AppendAllText(Path.Combine(options.Profile, "winui-errors.log"), error + Environment.NewLine); throw; }
        });
    }
}
public sealed record LaunchOptions(string Profile, string? Resources, bool NoBackend, string? Smoke)
{
    public static LaunchOptions Parse(string[] args)
    {
        string? Value(string key) { var index = Array.IndexOf(args, key); return index >= 0 && index + 1 < args.Length ? args[index + 1] : null; }
        if (Value("--smoke-test") is not null && (Value("--data-dir") is null || !args.Contains("--no-backend")))
            throw new ArgumentException("自动验收必须指定隔离的 --data-dir，并使用 --no-backend。");
        return new(Value("--data-dir") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MusicDesk"),
            Value("--resources"), args.Contains("--no-backend"), Value("--smoke-test"));
    }
}
public sealed partial class App : Application
{
    private readonly LaunchOptions options;
    private readonly SingleInstance instance;
    private MainWindow? window;
    public App(LaunchOptions options, SingleInstance instance)
    {
        this.options = options; this.instance = instance;
        UnhandledException += (_, e) =>
        {
            Directory.CreateDirectory(options.Profile);
            File.AppendAllText(Path.Combine(options.Profile, "winui-errors.log"), e.Exception.ToString() + Environment.NewLine);
        };
        RequestedTheme = ApplicationTheme.Dark;
        InitializeComponent();
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            window = new MainWindow(options);
            instance.Activated += () => window.DispatcherQueue.TryEnqueue(window.Restore);
            window.Activate(); _ = window.InitializeAsync();
        }
        catch (Exception error)
        {
            Directory.CreateDirectory(options.Profile);
            File.AppendAllText(Path.Combine(options.Profile, "winui-errors.log"), error + Environment.NewLine);
            Exit();
        }
    }
}
