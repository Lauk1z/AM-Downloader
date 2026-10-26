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
        var saved = lyricLines; var savedPanel = openPanel; var savedOpen = body.IsPaneOpen; var savedPage = page; var savedMode = LyricsMode; var savedFloating = Store.Get("lyrics_floating", true);
        var legacyModeMigration = Store.Get<string?>("lyrics_mode", null) is null;
        try
        {
            if (legacyModeMigration)
            {
                Store.Set("lyrics_floating", false); Check(LyricsMode == "word", "旧版普通模式没有保留为逐字高亮");
                Store.Set("lyrics_floating", true); Check(LyricsMode == "floating", "旧版浮动模式没有保留");
            }
            Store.Set("lyrics_mode", "floating");
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
            Navigate("settings"); await Task.Delay(200); root.UpdateLayout();
            var mode = FindElement<ComboBox>(pageHost, "LyricsMode") ?? throw new InvalidOperationException("歌词显示模式设置缺失");
            Check(Ui.Selected<string>(mode) == "floating", "已有用户的歌词模式没有默认保留浮动");
            view.SetClock(4000, false, true); var scrollOffset = lyricScroll.VerticalOffset;
            mode.SelectedIndex = 1; await Capture("lyrics-normal-mode");
            Check(pieces.All(x => x.Translation.Y == 0) && pieces.Take(6).All(x => x.Opacity == 1) && pieces.Skip(6).All(x => Math.Abs(x.Opacity - .35) < .001), "普通模式未移除浮动或丢失逐字高亮");
            Check(lyricScroll.VerticalOffset == scrollOffset && ReferenceEquals(view, lyricViews[0]), "切换歌词模式重建了侧栏或改变了滚动位置");
            mode.SelectedIndex = 0;
            Check(pieces.Take(6).All(x => x.Translation.Y == -3 && x.Opacity == 1) && pieces.Skip(6).All(x => x.Translation.Y == 0), "切回浮动模式没有保留句内进度");
            view.SetClock(2000, true, true); await Task.Delay(150); mode.SelectedIndex = 1;
            await Task.Delay(150); view.SetClock(2300, false, true);
            Check(pieces.All(x => x.Translation.Y == 0) && pieces.Take(3).All(x => x.Opacity == 1), "播放时切换普通模式后仍在浮动或进度被重置");
            Check(new StateStore(Store.DirectoryPath).Get("lyrics_mode", "") == "word", "逐字高亮模式没有保存到磁盘");
            mode.SelectedIndex = 2;
            Check(view.IsActive && view.GlyphBounds.Count == 0 && view.Children[0].Opacity == 1 && view.Translation.Y == 0, "整句高亮没有使用完整明亮且不浮动的文字");
            Check(Math.Abs(lyricViews[1].Children[0].Opacity - .35) < .001 && ReferenceEquals(view, lyricViews[0]) && lyricScroll.VerticalOffset == scrollOffset, $"整句高亮影响了其他句、重建了侧栏或改变了滚动位置：opacity={lyricViews[1].Children[0].Opacity}, scroll={lyricScroll.VerticalOffset}/{scrollOffset}");
            view.SetClock(0, false, true); var lineStart = await CaptureLine(view, "lyrics-whole-line-start");
            view.SetClock(4000, false, true); var lineMiddle = await CaptureLine(view, "lyrics-whole-line-middle");
            view.SetClock(8000, false, true); var lineEnd = await CaptureLine(view, "lyrics-whole-line-end");
            Check(lineStart.SequenceEqual(lineMiddle) && lineMiddle.SequenceEqual(lineEnd), "整句高亮仍随句内进度变化");
            view.SetClock(4000, false, true); mode.SelectedIndex = 1;
            pieces = Descendants<Grid>(view).Where(x => x.Clip is not null).ToList();
            Check(pieces.Count == timing.Count && pieces.Take(6).All(x => x.Opacity == 1) && pieces.Skip(6).All(x => Math.Abs(x.Opacity - .35) < .001) && pieces.All(x => x.Translation.Y == 0), "从整句切回逐字高亮后没有恢复句内进度");
            mode.SelectedIndex = 2; view.SetClock(2000, true, true); await Task.Delay(150); mode.SelectedIndex = 0;
            pieces = Descendants<Grid>(view).Where(x => x.Clip is not null).ToList();
            Check(pieces.Count == timing.Count && pieces.Take(3).All(x => x.Opacity == 1 && x.Translation.Y == -3), "播放中从整句切回浮动模式丢失进度");
            view.SetClock(2300, false, true); mode.SelectedIndex = 2;
            Check(new StateStore(Store.DirectoryPath).Get("lyrics_mode", "") == "line", "整句高亮模式没有保存到磁盘");
            Navigate("home"); Navigate("settings"); await Task.Delay(200); root.UpdateLayout();
            mode = FindElement<ComboBox>(pageHost, "LyricsMode")!; Check(Ui.Selected<string>(mode) == "line", "重新进入设置没有恢复整句高亮模式");
            RefreshPanel(); await Task.Delay(200); root.UpdateLayout();
            viewport = Descendants<FadingLyricsViewport>((DependencyObject)body.Pane).Single();
            var normal = lyricViews[0]; normal.Activate(timing, 8000); normal.SetClock(4000, false, true);
            Check(normal.IsActive && normal.GlyphBounds.Count == 0 && normal.Children[0].Opacity == 1, "重新打开歌词后没有使用已保存的整句高亮模式");
            normal.Deactivate(); Check(Math.Abs(normal.Children[0].Opacity - .35) < .001, "整句结束后文字没有恢复暗色");
            var next = lyricViews[1]; next.Activate(Lyrics.Timing(lyricLines[1], 12000), 12000); next.SetClock(8000, false, true);
            Check(next.Children[0].Opacity == 1 && Math.Abs(normal.Children[0].Opacity - .35) < .001, "换句时没有只高亮当前整句");
            next.Deactivate(); mode.SelectedIndex = 0;
            var wrapped = lyricViews[2]; wrapped.Activate(Lyrics.Timing(lyricLines[2], 20000), 20000); wrapped.SetClock(16000, false, true);
            Check(wrapped.GlyphBounds.Select(x => x.Y).Distinct().Count() > 1, "长歌词没有换行或逐字位置丢失");
            lyricScroll!.ChangeView(null, lyricScroll.ScrollableHeight, null, true); await Task.Delay(150); await Capture("lyrics-wrapped-bottom");
            view.Deactivate(); Check(!view.IsActive && view.GlyphBounds.Count == 0, "离开当前句后没有释放逐字动画");
            var result = new { lyrics = "alpha-fade,enhanced-and-line-timing,graphemes,lift,wrap,pause,seek,three-mode-live-switch,whole-line-stable-render,line-change,persisted-mode", legacyModeMigration, glyphCount = timing.Count, wrappedGlyphCount = wrapped.GlyphBounds.Count, viewport.MaskConnected, renderTargetBitmap = "XAML glyphs captured; composition alpha mask verified by live brush connection", ok = true };
            await File.WriteAllTextAsync(Path.Combine(folder, "lyrics-checks.json"), JsonSerializer.Serialize(result, StateStore.Json));
            return result;
        }
        finally { Store.Set("lyrics_floating", savedFloating); Store.Set("lyrics_mode", savedMode); lyricLines = saved; Navigate(savedPage); openPanel = savedPanel; body.IsPaneOpen = savedOpen; if (savedPanel.Length > 0) RefreshPanel(); }
        static void Check(bool value, string message) { if (!value) throw new InvalidOperationException(message); }
        async Task<byte[]> Capture(string name) { await Task.Delay(100); var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(root); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); return (await bitmap.GetPixelsAsync()).ToArray(); }
        async Task<byte[]> CaptureLine(LyricLineView line, string name) { await Task.Delay(100); var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(line); await SaveScreenshotAsync(bitmap, Path.Combine(folder, name + ".png")); return (await bitmap.GetPixelsAsync()).ToArray(); }
    }
}
