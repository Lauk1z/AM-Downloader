using System.Diagnostics;
using System.Numerics;
using AMDownloader.Core;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;

namespace AMDownloader.WinUI.Views;

internal sealed class LyricLineView : Grid
{
    private readonly TextBlock text;
    private readonly Run run;
    private readonly Grid source = new();
    private readonly Grid ink = new() { IsHitTestVisible = false };
    private readonly CompositionPropertySet clock;
    private readonly Stopwatch elapsed = new();
    private readonly List<(Grid Piece, LyricGlyph Timing, ExpressionAnimation Opacity, ExpressionAnimation Lift)> pieces = [];
    private IReadOnlyList<LyricGlyph>? timing;
    private long position, end;
    private bool playing;
    internal List<Rect> GlyphBounds { get; } = [];
    internal bool IsActive => timing is not null;

    public LyricLineView(string content)
    {
        text = Ui.Text("", 23, true); text.VerticalAlignment = VerticalAlignment.Top;
        run = new Run { Text = content }; text.Inlines.Add(run);
        source.Children.Add(text); Children.Add(source); Children.Add(ink);
        source.Opacity = .35;
        clock = ElementCompositionPreview.GetElementVisual(this).Compositor.CreatePropertySet();
        clock.InsertScalar("Position", 0);
        SizeChanged += (_, _) => Rebuild();
        Unloaded += (_, _) => { clock.StopAnimation("Position"); playing = false; elapsed.Reset(); };
    }
    public void Activate(IReadOnlyList<LyricGlyph> glyphs, long lineEnd)
    { timing = glyphs; end = lineEnd; Rebuild(); }
    public void Deactivate()
    { timing = null; clock.StopAnimation("Position"); ClearInk(); source.Opacity = .35; }
    private void ClearInk()
    {
        foreach (var (piece, _, opacity, lift) in pieces) { piece.StopAnimation(opacity); piece.StopAnimation(lift); }
        ink.Children.Clear(); pieces.Clear(); GlyphBounds.Clear();
    }
    private void Rebuild()
    {
        if (timing is null || text.ActualWidth <= 0 || text.ActualHeight <= 0) return;
        ClearInk();
        foreach (var glyph in timing)
        {
            var pointer = run.ContentStart.GetPositionAtOffset(glyph.Index, LogicalDirection.Forward);
            var tail = run.ContentStart.GetPositionAtOffset(glyph.Index + glyph.Length, LogicalDirection.Backward);
            if (pointer is null || tail is null) continue;
            var head = pointer.GetCharacterRect(LogicalDirection.Forward); var last = tail.GetCharacterRect(LogicalDirection.Backward);
            var left = Math.Min(head.X, last.X); var right = Math.Max(head.Right, last.Right);
            if (right <= left) right = left + 1;
            var bounds = new Rect(left, head.Y, right - left, head.Height);
            GlyphBounds.Add(bounds);
            var piece = new Grid { Clip = new RectangleGeometry { Rect = bounds } };
            var glyphText = Ui.Text(run.Text, 23, true); glyphText.Foreground = Ui.Brush(255, 255, 255, 255); glyphText.VerticalAlignment = VerticalAlignment.Top;
            Microsoft.UI.Xaml.Automation.AutomationProperties.SetAccessibilityView(glyphText, Microsoft.UI.Xaml.Automation.Peers.AccessibilityView.Raw);
            piece.Children.Add(glyphText); ink.Children.Add(piece);
            var amount = "Clamp((clock.Position - start) / span, 0, 1)";
            var opacity = clock.Compositor.CreateExpressionAnimation("0.35 + 0.65 * " + amount); opacity.Target = "Opacity";
            var lift = clock.Compositor.CreateExpressionAnimation("Vector3(0, -3 * " + amount + ", 0)"); lift.Target = "Translation";
            foreach (var animation in new[] { opacity, lift })
            {
                animation.SetReferenceParameter("clock", clock); animation.SetScalarParameter("start", glyph.Start); animation.SetScalarParameter("span", Math.Max(1, glyph.End - glyph.Start));
            }
            pieces.Add((piece, glyph, opacity, lift));
        }
        source.Opacity = GlyphBounds.Count > 0 ? 0 : .35;
        SetClock(position + (playing ? elapsed.ElapsedMilliseconds : 0), playing, true);
    }
    public void SetClock(long value, bool running, bool force = false)
    {
        var predicted = position + (playing ? elapsed.ElapsedMilliseconds : 0);
        if (!force && running == playing && (running ? Math.Abs(value - predicted) < 160 : value == position)) return;
        position = value; playing = running; elapsed.Restart();
        clock.StopAnimation("Position"); clock.InsertScalar("Position", value);
        foreach (var (piece, glyph, opacity, lift) in pieces)
        {
            piece.StopAnimation(opacity); piece.StopAnimation(lift);
            var progress = Math.Clamp((value - glyph.Start) / (double)Math.Max(1, glyph.End - glyph.Start), 0, 1);
            piece.Opacity = .35 + .65 * progress; piece.Translation = new(0, (float)(-3 * progress), 0);
            if (running) { piece.StartAnimation(opacity); piece.StartAnimation(lift); }
        }
        if (!running || value >= end) return;
        var motion = clock.Compositor.CreateScalarKeyFrameAnimation();
        motion.InsertKeyFrame(1, end, clock.Compositor.CreateLinearEasingFunction());
        motion.Duration = TimeSpan.FromMilliseconds(end - value); clock.StartAnimation("Position", motion);
    }
}

internal sealed class LyricCompositionBrush(CompositionBrush brush) : XamlCompositionBrushBase
{
    internal bool IsConnected => CompositionBrush is not null;
    protected override void OnConnected() => CompositionBrush = brush;
    protected override void OnDisconnected() => CompositionBrush = null;
}

internal sealed class FadingLyricsViewport : Grid
{
    private readonly CompositionVisualSurface surface;
    private readonly CompositionLinearGradientBrush gradient;
    private readonly LyricCompositionBrush brush;
    internal float FadeFraction => gradient.ColorStops[1].Offset;
    internal bool MaskConnected => brush.IsConnected && surface.SourceVisual is not null && surface.SourceSize.X > 0 && surface.SourceSize.Y > 0;
    public FadingLyricsViewport(ScrollViewer scroll)
    {
        var source = new Grid(); source.Children.Add(scroll); Children.Add(source);
        // Keep the XAML source rendered while showing only its masked composition copy.
        ElementCompositionPreview.GetElementVisual(source).Opacity = 0;
        var compositor = ElementCompositionPreview.GetElementVisual(this).Compositor;
        surface = compositor.CreateVisualSurface(); surface.SourceVisual = ElementCompositionPreview.GetElementVisual(scroll);
        Loaded += (_, _) => surface.SourceVisual = ElementCompositionPreview.GetElementVisual(scroll);
        Unloaded += (_, _) => surface.SourceVisual = null;
        gradient = compositor.CreateLinearGradientBrush(); gradient.StartPoint = Vector2.Zero; gradient.EndPoint = new(0, 1);
        foreach (var (offset, color) in new[] { (0f, Microsoft.UI.Colors.Transparent), (.08f, Microsoft.UI.Colors.White), (.92f, Microsoft.UI.Colors.White), (1f, Microsoft.UI.Colors.Transparent) }) gradient.ColorStops.Add(compositor.CreateColorGradientStop(offset, color));
        var mask = compositor.CreateMaskBrush(); mask.Mask = gradient; mask.Source = compositor.CreateSurfaceBrush(surface);
        brush = new(mask); Children.Add(new Rectangle { Fill = brush, IsHitTestVisible = false });
        SizeChanged += (_, _) =>
        {
            surface.SourceSize = new((float)ActualWidth, (float)ActualHeight);
            var edge = (float)Math.Min(.2, 40 / Math.Max(1, ActualHeight));
            gradient.ColorStops[1].Offset = edge; gradient.ColorStops[2].Offset = 1 - edge;
        };
    }
}
