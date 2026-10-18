using System.Runtime.InteropServices;

namespace AMDownloader.WinUI.Services;

internal sealed class TrayIcon : IDisposable
{
    private const uint Callback = 0x8000 + 42;
    private readonly nint window, icon;
    private readonly Action<string> action;
    private readonly SubclassProc callback;
    private readonly uint taskbarCreated = RegisterWindowMessage("TaskbarCreated");
    private NotifyData data;
    private bool playing, canPlay, canSkip;
    public bool Available { get; private set; }
    public TrayIcon(nint window, string path, Action<string> action)
    {
        this.window = window; this.action = action; callback = WndProc;
        icon = LoadImage(0, path, 1, 0, 0, 0x10 | 0x40);
        data = new() { Size = (uint)Marshal.SizeOf<NotifyData>(), Window = window, Id = 1, Flags = 7, CallbackMessage = Callback, Icon = icon, Tip = "AM Dowloader", Info = "", InfoTitle = "" };
        SetWindowSubclass(window, callback, 42, 0); Available = ShellNotifyIcon(0, ref data);
    }
    public void Update(string title, bool playing, bool canPlay, bool canSkip)
    { this.playing = playing; this.canPlay = canPlay; this.canSkip = canSkip; var next = title.Length > 127 ? title[..127] : title; if (data.Tip == next) return; data.Tip = next; ShellNotifyIcon(1, ref data); }
    public static void Show(nint window) { ShowWindow(window, IsIconic(window) ? 9 : 5); SetForegroundWindow(window); }
    private nint WndProc(nint hwnd, uint message, nuint wParam, nint lParam, nuint id, nuint reference)
    {
        if (message == taskbarCreated) Available = ShellNotifyIcon(0, ref data);
        if (message == 0x24)
        {
            var result = DefSubclassProc(hwnd, message, wParam, lParam);
            var limits = Marshal.PtrToStructure<MinMaxInfo>(lParam); var scale = GetDpiForWindow(hwnd) / 96d;
            limits.MinTrackSize = new Point { X = (int)(1100 * scale), Y = (int)(720 * scale) }; Marshal.StructureToPtr(limits, lParam, false); return result;
        }
        if (message == Callback)
        {
            if ((uint)lParam is 0x202 or 0x203) action("show");
            else if ((uint)lParam == 0x205)
            {
                var menu = CreatePopupMenu();
                AppendMenu(menu, 0, 1, "显示主窗口"); AppendMenu(menu, 1, 10, data.Tip);
                AppendMenu(menu, canPlay ? 0u : 1u, 2, playing ? "暂停" : "播放"); AppendMenu(menu, canSkip ? 0u : 1u, 3, "上一首"); AppendMenu(menu, canSkip ? 0u : 1u, 4, "下一首");
                AppendMenu(menu, 0x800, 0, ""); AppendMenu(menu, 0, 6, "正在播放队列"); AppendMenu(menu, 0, 7, "音频输出链路"); AppendMenu(menu, 0, 8, "最小化到托盘");
                AppendMenu(menu, 0x800, 0, ""); AppendMenu(menu, 0, 5, "退出");
                GetCursorPos(out var point); SetForegroundWindow(window);
                var choice = TrackPopupMenu(menu, 0x100 | 2, point.X, point.Y, 0, window, 0); DestroyMenu(menu);
                if (choice > 0) action(choice switch { 1 => "show", 2 => "play", 3 => "previous", 4 => "next", 6 => "queue", 7 => "output", 8 => "tray", _ => "quit" });
            }
            return 0;
        }
        return DefSubclassProc(hwnd, message, wParam, lParam);
    }
    public void Dispose() { ShellNotifyIcon(2, ref data); RemoveWindowSubclass(window, callback, 42); if (icon != 0) DestroyIcon(icon); }
    private delegate nint SubclassProc(nint hwnd, uint message, nuint wParam, nint lParam, nuint id, nuint reference);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct NotifyData
    { public uint Size; public nint Window; public uint Id, Flags, CallbackMessage; public nint Icon; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Tip; public uint State, StateMask; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Info; public uint Version; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string InfoTitle; public uint InfoFlags; public Guid Guid; public nint BalloonIcon; }
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] private struct MinMaxInfo { public Point Reserved, MaxSize, MaxPosition, MinTrackSize, MaxTrackSize; }
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint window);
    [DllImport("shell32.dll", EntryPoint = "Shell_NotifyIconW")] private static extern bool ShellNotifyIcon(uint message, ref NotifyData data);
    [DllImport("comctl32.dll")] private static extern bool SetWindowSubclass(nint window, SubclassProc proc, nuint id, nuint reference);
    [DllImport("comctl32.dll")] private static extern bool RemoveWindowSubclass(nint window, SubclassProc proc, nuint id);
    [DllImport("comctl32.dll")] private static extern nint DefSubclassProc(nint window, uint message, nuint wParam, nint lParam);
    [DllImport("user32.dll", EntryPoint = "LoadImageW", CharSet = CharSet.Unicode)] private static extern nint LoadImage(nint instance, string name, uint type, int x, int y, uint flags);
    [DllImport("user32.dll")] private static extern bool DestroyIcon(nint icon);
    [DllImport("user32.dll")] private static extern bool ShowWindow(nint window, int mode);
    [DllImport("user32.dll")] private static extern bool IsIconic(nint window);
    [DllImport("user32.dll", EntryPoint = "RegisterWindowMessageW", CharSet = CharSet.Unicode)] private static extern uint RegisterWindowMessage(string name);
    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(nint window);
    [DllImport("user32.dll")] private static extern nint CreatePopupMenu();
    [DllImport("user32.dll", EntryPoint = "AppendMenuW", CharSet = CharSet.Unicode)] private static extern bool AppendMenu(nint menu, uint flags, nuint id, string text);
    [DllImport("user32.dll")] private static extern uint TrackPopupMenu(nint menu, uint flags, int x, int y, int reserved, nint window, nint rect);
    [DllImport("user32.dll")] private static extern bool DestroyMenu(nint menu);
    [DllImport("user32.dll")] private static extern bool GetCursorPos(out Point point);
}
