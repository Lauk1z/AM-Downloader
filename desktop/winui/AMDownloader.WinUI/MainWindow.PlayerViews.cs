using AMDownloader.WinUI.Views;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private enum PlayerViewMode { Library, Mini, Fullscreen }
    private PlayerWindow? playerWindow;
    private bool LyricsVisible => openPanel == "lyrics" && body.IsPaneOpen;
    private void CycleRepeat()
    {
        if (repeatOne) { repeatOne = false; repeat = true; }
        else if (repeat) repeat = false;
        else repeatOne = true;
        UpdatePlayer();
    }
    private void UpdateRepeatButton(Button button)
    {
        Ui.SetGlyph(button, repeatOne ? "repeat-one" : "repeat", 20);
        button.Foreground = repeat || repeatOne ? Ui.Accent : Ui.Muted;
        var label = "循环：" + (repeatOne ? "单曲循环" : repeat ? "列表循环" : "关闭") + "（点击切换）";
        ToolTipService.SetToolTip(button, label); AutomationProperties.SetName(button, label);
    }
    private void SetPlayerView(PlayerViewMode mode)
    {
        if (mode == PlayerViewMode.Library) { playerWindow?.Close(); return; }
        HideVolume();
        if (playerWindow is null)
        {
            var window = new PlayerWindow(this); playerWindow = window;
            window.Closed += (_, _) =>
            {
                if (ReferenceEquals(playerWindow, window)) playerWindow = null;
                if (!quitting) Restore();
            };
        }
        playerWindow.ShowMode(mode == PlayerViewMode.Fullscreen);
        (AppWindow.Presenter as OverlappedPresenter)?.Minimize();
        playerWindow.Activate();
    }
}
