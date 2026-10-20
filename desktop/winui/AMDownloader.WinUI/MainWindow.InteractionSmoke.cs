using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyInteractionUiAsync(string folder)
    {
        var failures = new List<string>(); var tables = new List<object>(); var menus = new List<object>();
        Check(root.KeyboardAcceleratorPlacementMode == KeyboardAcceleratorPlacementMode.Hidden, "全窗口快捷键提示仍然可见");
        Check(root.KeyboardAccelerators.Any(x => x.Key == Windows.System.VirtualKey.L && x.Modifiers == Windows.System.VirtualKeyModifiers.Control && x.IsEnabled), "Ctrl+L 快捷键丢失");
        var targets = new List<string> { "songs", "recent", "favourites", "search" };
        if (tracks.Count > 0) targets.Add("album:" + tracks[0].AlbumKey);
        if (playlists.Count > 0) targets.Add(playlists[0].Id);
        foreach (var target in targets)
        {
            Navigate(target); await Task.Delay(180); root.UpdateLayout();
            var list = Descendants<ListView>(pageHost).FirstOrDefault(x => x.Items.FirstOrDefault() is TrackRow);
            if (list?.ContainerFromIndex(0) is not ListViewItem item) continue;
            var content = (Grid)item.ContentTemplateRoot; var presenter = Descendants<ListViewItemPresenter>(item).Single();
            var origin = content.TransformToVisual(presenter).TransformPoint(new());
            Check(presenter.CornerRadius == new CornerRadius(7) && Math.Abs(origin.X) < .1 && Math.Abs(origin.Y) < .1 && Math.Abs(content.ActualWidth - presenter.ActualWidth) < .1 && Math.Abs(content.ActualHeight - presenter.ActualHeight) < .1, "歌曲背景与高亮的尺寸不一致：" + target);
            foreach (var row in list.Items.Cast<TrackRow>())
            {
                if (list.ContainerFromItem(row) is not ListViewItem realized) continue;
                var face = Descendants<ListViewItemPresenter>(realized).Single();
                Check(face.PointerOverBackground is SolidColorBrush hover && hover.Color.A == 0 && face.SelectedBackground is SolidColorBrush selected && selected.Color.A == 0 && face.PressedBackground is SolidColorBrush pressed && pressed.Color.A == 0, "系统容器仍绘制第二层高亮：" + target);
                Check(((Grid)realized.ContentTemplateRoot).Background is SolidColorBrush background && background.Color == ((SolidColorBrush)row.Background).Color && realized.Tag is TrackRowHighlight, "歌曲隔行底色丢失或回收后串行：" + target);
            }
            if (target == "songs")
            {
                foreach (var selected in new[] { false, true })
                {
                    item.IsSelected = selected; await Task.Delay(100);
                    await CaptureAsync("song-row-" + (selected ? "selected" : "normal"));
                }
                item.IsSelected = false; ((TrackRowHighlight)item.Tag).SetPointerOver(true); await Task.Delay(100);
                Check(((SolidColorBrush)content.Background).Color == Ui.Brush(24, 255, 255, 255).Color, "歌曲悬停没有使用同一圆角背景");
                await CaptureAsync("song-row-hover"); ((TrackRowHighlight)item.Tag).SetPointerOver(false);
                list.SelectedItems.Clear();
                list.SelectedItems.Add(list.Items[0]); if (list.Items.Count > 1) list.SelectedItems.Add(list.Items[1]);
                Check(list.SelectedItems.Count == Math.Min(2, list.Items.Count), "歌曲表格失去多选能力");
                list.SelectedItems.Clear(); await Task.Delay(100);
                await CaptureAsync("songs-interaction");
            }
            tables.Add(new { page = target, corner = presenter.CornerRadius.TopLeft, contentX = origin.X, contentY = origin.Y, widthDifference = content.ActualWidth - presenter.ActualWidth, heightDifference = content.ActualHeight - presenter.ActualHeight, list.CanDragItems, list.CanReorderItems });
            await VerifyMenuAsync("专辑操作"); await VerifyMenuAsync("歌单操作");
        }
        if (tracks.Count > 0)
        {
            pageHost.Content = TrackTable(Enumerable.Range(0, 160).Select(i => tracks[i % tracks.Count]).ToList()); await Task.Delay(120); root.UpdateLayout();
            var list = Descendants<ListView>(pageHost).Single(); var scroll = Descendants<ScrollViewer>(list).First();
            foreach (var offset in new[] { scroll.ScrollableHeight, 0d })
            {
                scroll.ChangeView(null, offset, null, true); await Task.Delay(150); root.UpdateLayout();
                foreach (var row in list.Items.Cast<TrackRow>())
                    if (list.ContainerFromItem(row) is ListViewItem item && item.ContentTemplateRoot is Grid surface)
                    {
                        var y = item.TransformToVisual(scroll).TransformPoint(new()).Y;
                        if (item.ActualHeight <= 0 || y + item.ActualHeight <= 0 || y >= scroll.ViewportHeight) continue;
                        Check(surface.Background is SolidColorBrush background && background.Color == ((SolidColorBrush)row.Background).Color, $"可见歌曲回收后留下旧高亮或错误隔行底色：{row.OriginalIndex}, actual={(surface.Background as SolidColorBrush)?.Color}, expected={((SolidColorBrush)row.Background).Color}, selected={item.IsSelected}");
                    }
            }
            await CaptureAsync("songs-recycled");
        }
        Navigate("artists"); await Task.Delay(250); root.UpdateLayout(); await VerifyMenuAsync("歌曲操作");
        var result = new { interaction = "global-shortcut-tooltip,row-bounds-and-states,menu-button-anchors", tables, menus, failures, ok = failures.Count == 0 };
        await File.WriteAllTextAsync(Path.Combine(folder, "interaction-checks.json"), JsonSerializer.Serialize(result, StateStore.Json));
        if (failures.Count > 0) throw new InvalidOperationException(string.Join("\n", failures));
        return result;
        void Check(bool value, string message) { if (!value) failures.Add(message); }
        async Task VerifyMenuAsync(string name)
        {
            var button = Descendants<Button>(pageHost).FirstOrDefault(x => AutomationProperties.GetName(x) == name);
            if (button is null) return;
            ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke(); await Task.Delay(150); root.UpdateLayout();
            var menu = FlyoutBase.GetAttachedFlyout(button);
            Check(menu is { IsOpen: true } && ReferenceEquals(menu.Target, button), "操作菜单未定位在点击的按钮：" + name);
            var popup = VisualTreeHelper.GetOpenPopupsForXamlRoot(root.XamlRoot).FirstOrDefault(x => x.Child is MenuFlyoutPresenter);
            if (popup?.Child is FrameworkElement face)
            {
                var position = face.TransformToVisual(root).TransformPoint(new()); var anchor = button.TransformToVisual(root).TransformPoint(new());
                Check(position.X + face.ActualWidth > anchor.X && position.X < anchor.X + button.ActualWidth, "操作菜单出现在按钮以外的栏目：" + name);
                menus.Add(new { name, x = position.X, width = face.ActualWidth, buttonX = anchor.X, anchored = ReferenceEquals(menu?.Target, button) });
                var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(face); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png"));
                popup.IsOpen = false;
            }
            menu?.Hide();
        }
        async Task CaptureAsync(string name) { var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); }
    }
}
