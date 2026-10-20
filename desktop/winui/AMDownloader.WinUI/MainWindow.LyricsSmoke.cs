using System.Text.Json;
using System.Runtime.InteropServices.WindowsRuntime;
using AMDownloader.Core;
using AMDownloader.WinUI.Views;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private async Task<object> VerifyLyricsUiAsync(string folder)
    {
        var saved = lyricLines; var savedPanel = openPanel; var savedOpen = body.IsPaneOpen;
        try
        {
            lyricLines = Lyrics.Parse("[00:00.00]让每一个字随音乐轻轻浮起\n[00:08.00]<00:08.00>逐字<00:10.00>高亮<00:12.00>\n[00:12.00]A long lyric that wraps naturally across several lines, with 音乐 and e\u0301 🎵\n[00:20.00]最后一行");
            openPanel = "lyrics"; RefreshPanel(); body.IsPaneOpen = true; await Task.Delay(250); root.UpdateLayout();
            var viewport = Descendants<FadingLyricsViewport>((DependencyObject)body.Pane).Single();
            Check(viewport.FadeFraction is > 0 and <= .2f && viewport.MaskConnected, "歌词上下渐隐没有连接到实际合成视口");
            lyricScroll!.ChangeView(null, 0, null, true); await Task.Delay(150);
            var view = lyricViews[0]; var timing = Lyrics.Timing(lyricLines[0], 8000);
            view.Activate(timing, 8000); view.SetClock(0, false, true); var startPixels = await Capture("lyrics-progress-start");
            Check(view.GlyphBounds.Count == timing.Count && view.GlyphBounds.All(x => x.Width > 0 && x.Height > 0 && x.X >= 0 && x.Right <= view.ActualWidth + 1), "逐字边界无效或超出歌词视口");
            view.SetClock(4000, false, true); var middlePixels = await Capture("lyrics-progress-middle");
            var pieces = Descendants<Grid>(view).Where(x => x.Clip is not null).ToList();
            Check(pieces.Take(6).All(x => x.Opacity == 1 && x.Translation.Y == -3) && pieces.Skip(6).All(x => Math.Abs(x.Opacity - .35) < .001 && x.Translation.Y == 0), "句内已唱和未唱部分没有分别高亮浮起与保持原位");
            view.SetClock(8000, false, true); var endPixels = await Capture("lyrics-progress-end");
            Check(!startPixels.SequenceEqual(middlePixels) && !middlePixels.SequenceEqual(endPixels), "逐字变化没有形成实际渲染结果");
            view.SetClock(2000, true, true); await Task.Delay(300); view.SetClock(2300, false, true); await Capture("lyrics-paused");
            view.SetClock(0, false, true); var rewindPixels = await Capture("lyrics-progress-seek-back");
            Check(startPixels.SequenceEqual(rewindPixels), "回退进度后文字位置或高亮没有完全复原");
            var wrapped = lyricViews[2]; wrapped.Activate(Lyrics.Timing(lyricLines[2], 20000), 20000); wrapped.SetClock(16000, false, true);
            Check(wrapped.GlyphBounds.Select(x => x.Y).Distinct().Count() > 1, "长歌词没有换行或逐字位置丢失");
            lyricScroll!.ChangeView(null, lyricScroll.ScrollableHeight, null, true); await Task.Delay(150); await Capture("lyrics-wrapped-bottom");
            view.Deactivate(); Check(!view.IsActive && view.GlyphBounds.Count == 0, "离开当前句后没有释放逐字动画");
            var result = new { lyrics = "alpha-fade,enhanced-and-line-timing,graphemes,lift,wrap,pause,seek", glyphCount = timing.Count, wrappedGlyphCount = wrapped.GlyphBounds.Count, viewport.MaskConnected, renderTargetBitmap = "XAML glyphs captured; composition alpha mask verified by live brush connection", ok = true };
            await File.WriteAllTextAsync(Path.Combine(folder, "lyrics-checks.json"), JsonSerializer.Serialize(result, StateStore.Json));
            return result;
        }
        finally { lyricLines = saved; openPanel = savedPanel; body.IsPaneOpen = savedOpen; if (savedPanel.Length > 0) RefreshPanel(); }
        static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        async Task<byte[]> Capture(string name) { await Task.Delay(100); var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); return (await bitmap.GetPixelsAsync()).ToArray(); }
    }
}
