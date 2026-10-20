using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;

namespace AMDownloader.WinUI.Views;

internal sealed class TrackRowHighlight
{
    private readonly ListViewItem item;
    private bool over, pressed;
    public TrackRowHighlight(ListViewItem item)
    {
        this.item = item;
        item.PointerEntered += (_, _) => SetPointerOver(true);
        item.PointerExited += (_, _) => SetPointerOver(false);
        item.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, _) => { pressed = true; Refresh(); }), true);
        item.AddHandler(UIElement.PointerReleasedEvent, new PointerEventHandler((_, _) => { pressed = false; Refresh(); }), true);
        item.PointerCanceled += (_, _) => { pressed = false; Refresh(); };
        item.PointerCaptureLost += (_, _) => { pressed = false; Refresh(); };
        item.RegisterPropertyChangedCallback(ListViewItem.IsSelectedProperty, (_, _) => Refresh());
        item.Loaded += (_, _) => Refresh();
    }
    internal void SetPointerOver(bool value) { over = value; if (!value) pressed = false; Refresh(); }
    internal void Refresh()
    {
        if (item.ContentTemplateRoot is not Grid surface || item.Content is not TrackRow row) return;
        surface.BackgroundTransition ??= new BrushTransition { Duration = TimeSpan.FromMilliseconds(83) };
        surface.Background = pressed ? Ui.Brush(20, 255, 255, 255) : item.IsSelected ? Ui.Brush(over ? (byte)40 : (byte)30, 255, 255, 255) : over ? Ui.Brush(24, 255, 255, 255) : row.Background;
    }
    internal static void Attach(ListViewBase sender, ContainerContentChangingEventArgs e)
    {
        if (e.InRecycleQueue) { if (e.ItemContainer.Tag is TrackRowHighlight recycled) recycled.SetPointerOver(false); return; }
        var highlight = e.ItemContainer.Tag as TrackRowHighlight;
        if (highlight is null) e.ItemContainer.Tag = highlight = new((ListViewItem)e.ItemContainer);
        highlight.Refresh();
        if (e.Phase == 0) e.RegisterUpdateCallback(Attach);
    }
}
