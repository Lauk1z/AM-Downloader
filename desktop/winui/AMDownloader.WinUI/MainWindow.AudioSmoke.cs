using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyAudioSettingsUiAsync()
    {
        var previousPage = page;
        try
        {
            Navigate("settings"); await Task.Delay(250);
            var mode = Descendants<ComboBox>(pageHost).Single(x => x.Items.OfType<ComboBoxItem>().Any(i => Equals(i.Tag, "shared")));
            var devices = Descendants<ComboBox>(pageHost).Single(x => x.PlaceholderText == "请选择 DAC 对应的输出设备");
            mode.SelectedItem = mode.Items.OfType<ComboBoxItem>().Single(x => Equals(x.Tag, "asio"));
            await Until(() => devices.Items.Count > 0, 3000);
            if (Audio.Config.Mode != "asio" && devices.SelectedItem is not null) throw new InvalidOperationException("切换 ASIO 时仍默认选择首个驱动");
            var selected = (string)((ComboBoxItem)devices.Items[^1]).Tag; devices.SelectedIndex = devices.Items.Count - 1;
            var refresh = Descendants<Button>(pageHost).Single(x => Equals(x.Content, "刷新设备"));
            ((IInvokeProvider)new ButtonAutomationPeer(refresh).GetPattern(PatternInterface.Invoke)).Invoke(); await Task.Delay(300);
            if (devices.SelectedItem is not ComboBoxItem refreshed || !Equals(refreshed.Tag, selected)) throw new InvalidOperationException("刷新设备丢失选择");
            mode.SelectedItem = mode.Items.OfType<ComboBoxItem>().Single(x => Equals(x.Tag, "shared"));
            mode.SelectedItem = mode.Items.OfType<ComboBoxItem>().Single(x => Equals(x.Tag, "asio"));
            if (devices.SelectedItem is not ComboBoxItem restored || !Equals(restored.Tag, selected)) throw new InvalidOperationException("切换输出模式丢失 DAC 选择");
            return new { audioSettings = "explicit-driver-selection,preserve-on-refresh,preserve-on-mode-switch", ok = true };
        }
        finally { Navigate(previousPage); }
    }
    private async Task<long> VerifyPausedProbeUiAsync()
    {
        var previousPage = page;
        try
        {
            Navigate("settings"); await Task.Delay(250);
            var mode = Descendants<ComboBox>(pageHost).Single(x => x.Items.OfType<ComboBoxItem>().Any(i => Equals(i.Tag, "shared")));
            mode.SelectedItem = mode.Items.OfType<ComboBoxItem>().Single(x => Equals(x.Tag, "asio"));
            var devices = Descendants<ComboBox>(pageHost).Single(x => x.PlaceholderText == "请选择 DAC 对应的输出设备");
            var missing = new ComboBoxItem { Content = "未注册测试驱动", Tag = "{00000000-0000-0000-0000-000000000000}" }; devices.Items.Add(missing); devices.SelectedItem = missing;
            var probe = Descendants<Button>(pageHost).Single(x => Equals(x.Content, "检测 DSD 能力"));
            var position = Audio.Position;
            ((IInvokeProvider)new ButtonAutomationPeer(probe).GetPattern(PatternInterface.Invoke)).Invoke();
            await Until(() => probe.IsEnabled && Descendants<TextBlock>(pageHost).Any(x => x.Text.Contains("检测 未注册测试驱动 失败：") && x.Text.Contains("Load ASIO driver")), 5000);
            return position;
        }
        finally { Navigate(previousPage); }
    }
}
