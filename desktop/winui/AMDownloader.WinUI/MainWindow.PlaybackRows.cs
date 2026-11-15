using AMDownloader.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Markup;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private readonly List<TrackRow> pageTrackRows = [];
    private (string Path, string Status) rowPlayback;
    private const string TrackMarkerMarkup = """
        <Grid xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" VerticalAlignment="Center" ToolTipService.ToolTip="{Binding PlaybackTip}">
          <TextBlock Text="{Binding IndexText}" VerticalAlignment="Center" Foreground="{Binding MarkerBrush}"/>
          <Viewbox Width="14" Height="14" HorizontalAlignment="Left" VerticalAlignment="Center" Visibility="{Binding MarkerVisibility}">
            <Canvas Width="24" Height="24"><Path Data="{Binding MarkerData}" Fill="{Binding MarkerBrush}"/></Canvas>
          </Viewbox>
        </Grid>
        """;
    private (string Path, string Status) CurrentRowPlayback()
    {
        var status = Audio.Preparing && Audio.PrepareAutoplay ? "正在准备" : Audio.State switch
        {
            "starting" => "正在加载", "playing" => "正在播放", "paused" => "已暂停",
            _ => gapWaiting ? trackGap.Running ? "等待下一首" : "已暂停" : ""
        };
        return (status.Length > 0 && Audio.Current is { } track ? Core.Paths.Key(track.Path) : "", status);
    }
    private TrackRow CreateTrackRow(Track track, int index, PlaylistEntry? entry = null)
    {
        var row = new TrackRow(track, index, favourites.Contains(track.Path), entry);
        var state = CurrentRowPlayback(); row.SetPlayback(state.Path, state.Status); pageTrackRows.Add(row); return row;
    }
    private void UpdatePlaybackRows()
    {
        var state = CurrentRowPlayback(); if (rowPlayback == state) return; rowPlayback = state;
        foreach (var row in pageTrackRows) row.SetPlayback(state.Path, state.Status);
    }
    private static FrameworkElement TrackMarker(TrackRow row)
    {
        var marker = (FrameworkElement)XamlReader.Load(TrackMarkerMarkup); marker.DataContext = row; return marker;
    }
}
