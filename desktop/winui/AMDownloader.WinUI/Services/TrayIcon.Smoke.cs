using System.Runtime.InteropServices;
using System.Runtime.InteropServices.WindowsRuntime;
using AMDownloader.WinUI.Views;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics;
using Windows.Graphics.Imaging;
using Windows.Storage;
using Windows.System;

namespace AMDownloader.WinUI.Services;

internal sealed partial class TrayIcon
{
    internal async Task<object> VerifyMenuAsync(string folder)
    {
        var saved = (playing, canPlay, canSkip); var owner = AppWindow.GetFromWindowId(Win32Interop.GetWindowIdFromWindow(window));
        var visible = owner.IsVisible; TrayMenuWindow? sample = null;
        try
        {
            playing = canPlay = canSkip = false; owner.Hide(); SendMessage(window, Callback, 0, 0x205); await Task.Delay(180);
            var opened = menu ?? throw new InvalidOperationException("托盘消息没有打开 WinUI 菜单");
            Check(!owner.IsVisible && opened.AppWindow.IsVisible && !opened.AppWindow.IsShownInSwitchers, "托盘菜单唤起主窗口或出现额外任务栏窗口");
            Check(opened.Commands.Count == 8 && opened.Commands.Where(x => !x.IsEnabled).Select(x => x.Tag).SequenceEqual(new object[] { "play", "previous", "next" }), "无歌曲时播放操作未禁用");
            Check(opened.Surface.Background is SolidColorBrush background && background.Color == Windows.UI.Color.FromArgb(255, 43, 43, 43) && opened.Surface.CornerRadius.TopLeft == 8, "托盘菜单未采用深灰圆角外观");
            Check(opened.AppWindow.Presenter is OverlappedPresenter presenter && !presenter.HasTitleBar && !presenter.IsResizable, "托盘菜单显示了标题栏或可调整大小");
            var width = opened.Surface.ActualWidth; var height = opened.Surface.ActualHeight;
            Check(width is >= 238 and <= 242 && height is > 300 and < 380, "托盘菜单未形成收窄后的紧凑布局");
            await CaptureAsync(opened, "tray-menu-modern");
            var show = opened.Commands[0];
            Check(FindFace(show)?.BackgroundTransition is null || FindFace(show)!.BackgroundTransition.Duration.TotalMilliseconds == 0, "托盘按钮带有背景渐退，快速悬停会留下多行高光拖尾");
            Check(new ButtonAutomationPeer(show).GetName() == "显示主窗口", "托盘菜单缺少无障碍名称");
            Check(opened.MoveFocus(VirtualKey.Down) && opened.Commands[4].FocusState != FocusState.Unfocused, "键盘导航没有跳过禁用的播放操作");
            Check(opened.MoveFocus(VirtualKey.End) && opened.Commands[^1].FocusState != FocusState.Unfocused, "键盘不能到达退出操作");
            await Task.Delay(150);
            foreach (var (state, red) in new[] { ("PointerOver", (byte)61), ("Pressed", (byte)72) })
            {
                Check(VisualStateManager.GoToState(show, state, false), "托盘按钮状态缺失"); await Task.Delay(250);
                var face = FindFace(show);
                await CaptureAsync(opened, "tray-menu-" + state);
                var current = VisualStateManager.GetVisualStateGroups((FrameworkElement)VisualTreeHelper.GetChild(show, 0)).Select(x => x.CurrentState?.Name);
                Check(face?.Background is SolidColorBrush brush && brush.Color.R == red && face.CornerRadius.TopLeft == 4, $"托盘悬停背景或高光圆角错误：{state}, {((face?.Background as SolidColorBrush)?.Color)}, {face?.CornerRadius.TopLeft}, {string.Join(',', current)}");
            }
            VisualStateManager.GoToState(show, "Normal", false);
            var hoverCommands = opened.Commands.Where(x => x.IsEnabled).ToList();
            foreach (var target in hoverCommands)
            {
                foreach (var button in hoverCommands) VisualStateManager.GoToState(button, ReferenceEquals(button, target) ? "PointerOver" : "Normal", true);
                await Task.Delay(20);
                var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(opened.Surface); var pixels = (await bitmap.GetPixelsAsync()).ToArray();
                foreach (var button in hoverCommands)
                {
                    var point = button.TransformToVisual(opened.Surface).TransformPoint(new(button.ActualWidth - 20, button.ActualHeight / 2));
                    var x = Math.Clamp((int)(point.X * bitmap.PixelWidth / opened.Surface.ActualWidth), 0, bitmap.PixelWidth - 1);
                    var y = Math.Clamp((int)(point.Y * bitmap.PixelHeight / opened.Surface.ActualHeight), 0, bitmap.PixelHeight - 1);
                    var red = pixels[(y * bitmap.PixelWidth + x) * 4 + 2];
                    Check(Math.Abs(red - (ReferenceEquals(button, target) ? 61 : 43)) <= 3, "快速移动后旧菜单行仍有高光拖尾");
                }
            }
            foreach (var button in hoverCommands) VisualStateManager.GoToState(button, "Normal", false);
            var work = DisplayArea.GetFromWindowId(opened.AppWindow.Id, DisplayAreaFallback.Nearest).WorkArea;
            foreach (var anchor in new[] { new PointInt32(work.X, work.Y), new(work.X + work.Width - 1, work.Y + work.Height - 1) })
            {
                opened.ShowAt(anchor); await Task.Delay(80);
                var bounds = opened.AppWindow;
                Check(bounds.Position.X >= work.X && bounds.Position.Y >= work.Y && bounds.Position.X + bounds.Size.Width <= work.X + work.Width + 1 && bounds.Position.Y + bounds.Size.Height <= work.Y + work.Height + 1, "托盘菜单超出显示器工作区");
            }
            opened.MoveFocus(VirtualKey.Escape); await Task.Delay(50); Check(menu is null, "Escape 未关闭托盘菜单");
            SendMessage(window, Callback, 0, 0x205); await Task.Delay(80); var previous = menu;
            SendMessage(window, Callback, 0, 0x205); await Task.Delay(80); Check(menu is not null && menu != previous, "重复右击没有替换旧菜单");
            owner.Show(); SetForegroundWindow(window); await Task.Delay(180); Check(menu is null, "点击其他窗口后托盘菜单未关闭");
            owner.Hide();
            foreach (var outside in new[] { new PointInt32(work.X - 20, work.Y), new(work.X, work.Y - 20), new(work.X + work.Width + 20, work.Y), new(work.X, work.Y + work.Height + 1) })
            {
                var closes = 0;
                sample = new TrayMenuWindow("外部点击验收", false, true, true, _ => throw new InvalidOperationException("点击空白处不应触发菜单操作"));
                sample.Closed += (_, _) => closes++;
                sample.ShowAt(new(work.X + work.Width, work.Y + work.Height)); await Task.Delay(100);
                Check(sample.WatchingOutsideClicks && !owner.IsVisible, "没有在菜单显示时监听外部点击，或主窗口被唤起");
                var bounds = sample.AppWindow;
                sample.DismissIfOutside(new(bounds.Position.X + bounds.Size.Width / 2, bounds.Position.Y + bounds.Size.Height / 2));
                await Task.Delay(60); Check(closes == 0, "菜单内部按下时提前关闭，影响按钮点击");
                var foreground = GetForegroundWindow();
                // Deliver the hook's screen coordinates without activating another window or generating desktop input.
                sample.DismissIfOutside(outside); sample.DismissIfOutside(outside);
                Check(GetForegroundWindow() == foreground && closes == 0, "外部点击检查不应强制切换窗口或在输入回调中同步关闭");
                await Task.Delay(100);
                Check(closes == 1 && !sample.WatchingOutsideClicks && !owner.IsVisible, "没有失焦事件时外部点击未关闭菜单，或关闭后仍监听输入");
                sample.Close(); sample = null;
            }
            owner.Show(); SetForegroundWindow(window);
            var called = new List<string>();
            foreach (var command in new[] { "show", "play", "previous", "next", "queue", "output", "tray", "quit" })
            {
                sample = new TrayMenuWindow("The Other Side of Paradise · Glass Animals", true, true, true, called.Add);
                sample.ShowAt(new(work.X + work.Width, work.Y + work.Height)); await Task.Delay(60);
                Check((string)sample.Commands[1].Content == "暂停", "播放时菜单未显示暂停");
                if (command == "show") await CaptureAsync(sample, "tray-menu-playing");
                var button = sample.Commands.Single(x => Equals(x.Tag, command));
                ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke();
                await Task.Delay(40); Check(called.LastOrDefault() == command, "菜单操作未正确分发：" + command); sample = null;
            }
            return new { tray = "winui-dark-rounded-menu,240dip-width,no-hover-trails,hover,pressed,disabled,keyboard,escape,deactivation-dismiss,nonactivating-outside-press,inside-press-preserved,observer-cleanup,idempotent-close,hidden-owner,work-area,all-commands,accessible-labels", outside_input = "registered native hook; screen-coordinate callbacks without desktop input injection", width, height, ok = true };
        }
        finally { sample?.Close(); menu?.Close(); (playing, canPlay, canSkip) = saved; if (visible) { owner.Show(); SetForegroundWindow(window); } }
        static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        static ContentPresenter? FindFace(DependencyObject parent)
        {
            if (parent is ContentPresenter presenter) return presenter;
            for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++) if (FindFace(VisualTreeHelper.GetChild(parent, i)) is { } found) return found;
            return null;
        }
        async Task CaptureAsync(TrayMenuWindow target, string name)
        {
            var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(target.Surface); var pixels = (await bitmap.GetPixelsAsync()).ToArray();
            var directory = await StorageFolder.GetFolderFromPathAsync(folder); var file = await directory.CreateFileAsync(name + ".png", CreationCollisionOption.ReplaceExisting);
            using var stream = await file.OpenAsync(FileAccessMode.ReadWrite); var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
            encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied, (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96, 96, pixels); await encoder.FlushAsync();
        }
    }
    [DllImport("user32.dll", EntryPoint = "SendMessageW")] private static extern nint SendMessage(nint window, uint message, nuint wParam, nint lParam);
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
}
