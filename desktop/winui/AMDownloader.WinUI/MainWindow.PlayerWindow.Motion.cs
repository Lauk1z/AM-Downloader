using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.UI.Composition;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Hosting;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.Foundation;
using Windows.Graphics;

namespace AMDownloader.WinUI;

public sealed partial class MainWindow
{
    private sealed partial class PlayerWindow
    {
        private readonly nint hwnd;
        private readonly PlayerSubclass nativeProcedure;
        private Stopwatch? boundsClock;
        private RectInt32 boundsFrom, boundsTo;
        private double boundsDuration;
        private Action? boundsCompleted;
        private bool resizingMode;
        private double frozenLyricsWidth;
        private int panelSerial;
        private uint? dragPointer;
        private PlayerPoint dragCursor;
        private PointInt32 dragPosition;
        internal bool IsAnimating => boundsClock is not null;
        internal int MotionFrames { get; private set; }
        internal bool HadIntermediateBounds { get; private set; }
        private RectInt32 CurrentRect => new(AppWindow.Position.X, AppWindow.Position.Y, AppWindow.Size.Width, AppWindow.Size.Height);
        private void ApplyChrome()
        {
            var style = GetWindowLongPtr(hwnd, -16).ToInt64() & ~0xC40000L;
            var extended = GetWindowLongPtr(hwnd, -20).ToInt64() & ~0x20300L;
            SetWindowLongPtr(hwnd, -16, (nint)style); SetWindowLongPtr(hwnd, -20, (nint)extended);
            var dark = 1; var corners = IsFullscreen ? 1 : 2; var border = unchecked((int)0xFFFFFFFE);
            DwmSetWindowAttribute(hwnd, 20, ref dark, sizeof(int)); DwmSetWindowAttribute(hwnd, 33, ref corners, sizeof(int)); DwmSetWindowAttribute(hwnd, 34, ref border, sizeof(int));
            SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37);
        }
        internal bool HasNativeFrame => (GetWindowLongPtr(hwnd, -16).ToInt64() & 0xC40000) != 0 || (GetWindowLongPtr(hwnd, -20).ToInt64() & 0x20300) != 0;
        internal string NativeFrameDetails => $"style={GetWindowLongPtr(hwnd, -16).ToInt64():X}, exstyle={GetWindowLongPtr(hwnd, -20).ToInt64():X}";
        internal bool CanDragAt(Point point)
        {
            if (IsClosed || IsFullscreen || IsAnimating || Surface.XamlRoot is null || point.X < 0 || point.Y < 0 || point.X >= Surface.ActualWidth || point.Y >= Surface.ActualHeight) return false;
            foreach (var hit in VisualTreeHelper.FindElementsInHostCoordinates(point, Surface))
                for (DependencyObject? node = hit; node is not null && node != Surface; node = VisualTreeHelper.GetParent(node))
                    if (node is ButtonBase or Slider or ListViewItem || node is ScrollViewer scroll && scroll.ScrollableHeight > 0) return false;
            return true;
        }
        private void BeginWindowDrag(PointerRoutedEventArgs e)
        {
            var point = e.GetCurrentPoint(Surface);
            if (!point.Properties.IsLeftButtonPressed || !CanDragAt(point.Position)) return;
            for (var node = e.OriginalSource as DependencyObject; node is not null && node != Surface; node = VisualTreeHelper.GetParent(node))
                if (node is UIElement element) element.ReleasePointerCapture(e.Pointer);
            var origin = new PlayerPoint(); ClientToScreen(hwnd, ref origin);
            dragCursor = new() { X = origin.X + (int)Math.Round(point.Position.X * Scale), Y = origin.Y + (int)Math.Round(point.Position.Y * Scale) };
            if (!Surface.CapturePointer(e.Pointer)) return;
            dragPosition = AppWindow.Position; dragPointer = e.Pointer.PointerId; e.Handled = true;
        }
        private void MoveWindowDrag(PointerRoutedEventArgs e)
        {
            if (dragPointer != e.Pointer.PointerId || IsClosed || !GetCursorPos(out var point)) return;
            AppWindow.Move(new(dragPosition.X + point.X - dragCursor.X, dragPosition.Y + point.Y - dragCursor.Y)); e.Handled = true;
        }
        private void EndWindowDrag(PointerRoutedEventArgs e)
        { if (dragPointer == e.Pointer.PointerId) { dragPointer = null; Surface.ReleasePointerCapture(e.Pointer); e.Handled = true; } }
        private nint NativeMessage(nint window, uint message, nuint wParam, nint lParam, nuint id, nuint reference)
        {
            if (message == 0x7C)
            {
                // WinUI can reintroduce a fixed dialog frame after presenter/activation changes.
                var result = DefSubclassProc(window, message, wParam, lParam);
                var styles = Marshal.PtrToStructure<PlayerStyles>(lParam);
                if (unchecked((int)wParam) == -16) styles.Next &= ~0xC40000u;
                if (unchecked((int)wParam) == -20) styles.Next &= ~0x20300u;
                Marshal.StructureToPtr(styles, lParam, false); return result;
            }
            if (message == 0x83)
            {
                // Preserve WinUI's input bookkeeping, then extend the client to the outer bounds.
                var client = Marshal.PtrToStructure<PlayerRect>(lParam);
                DefSubclassProc(window, message, wParam, lParam);
                Marshal.StructureToPtr(client, lParam, false); return 0;
            }
            return DefSubclassProc(window, message, wParam, lParam);
        }
        private void StopMotion()
        { CompositionTarget.Rendering -= MotionFrame; boundsClock = null; boundsCompleted = null; }
        private void AnimateBounds(RectInt32 target, int milliseconds, Action? completed = null)
        {
            StopMotion(); boundsFrom = CurrentRect; boundsTo = target; MotionFrames = 0; HadIntermediateBounds = false;
            if (boundsFrom.Equals(boundsTo)) { completed?.Invoke(); return; }
            boundsDuration = milliseconds; boundsCompleted = completed; boundsClock = Stopwatch.StartNew(); CompositionTarget.Rendering += MotionFrame;
        }
        private void MotionFrame(object? sender, object args)
        {
            if (boundsClock is null || IsClosed) { StopMotion(); return; }
            var t = Math.Clamp(boundsClock.Elapsed.TotalMilliseconds / boundsDuration, 0, 1);
            var eased = 1 - Math.Pow(1 - t, 3);
            int Lerp(int a, int b) => (int)Math.Round(a + (b - a) * eased);
            var next = new RectInt32(Lerp(boundsFrom.X, boundsTo.X), Lerp(boundsFrom.Y, boundsTo.Y), Lerp(boundsFrom.Width, boundsTo.Width), Lerp(boundsFrom.Height, boundsTo.Height));
            AppWindow.MoveAndResize(next); MotionFrames++;
            HadIntermediateBounds |= !CurrentRect.Equals(boundsFrom) && !CurrentRect.Equals(boundsTo);
            if (t < 1) return;
            var completed = boundsCompleted; StopMotion(); completed?.Invoke();
            DispatcherQueue.TryEnqueue(() => { if (!IsClosed) { Surface.UpdateLayout(); UpdateLyrics(true); } });
        }
        private void Fade(UIElement element, bool show, int duration = 190, Action? completed = null)
        {
            var serial = panelSerial; var visual = ElementCompositionPreview.GetElementVisual(element);
            var animation = visual.Compositor.CreateScalarKeyFrameAnimation(); animation.InsertKeyFrame(0, show ? 0 : 1); animation.InsertKeyFrame(1, show ? 1 : 0); animation.Duration = TimeSpan.FromMilliseconds(duration);
            var batch = visual.Compositor.CreateScopedBatch(CompositionBatchTypes.Animation);
            visual.StartAnimation("Opacity", animation);
            batch.Completed += (_, _) => { batch.Dispose(); if (!IsClosed && serial == panelSerial) completed?.Invoke(); }; batch.End();
        }
        private delegate nint PlayerSubclass(nint window, uint message, nuint wParam, nint lParam, nuint id, nuint reference);
        [StructLayout(LayoutKind.Sequential)] private struct PlayerPoint { public int X, Y; }
        [StructLayout(LayoutKind.Sequential)] private struct PlayerStyles { public uint Previous, Next; }
        [StructLayout(LayoutKind.Sequential)] private struct PlayerRect { public int Left, Top, Right, Bottom; }
        [DllImport("comctl32.dll")] private static extern bool SetWindowSubclass(nint window, PlayerSubclass procedure, nuint id, nuint reference);
        [DllImport("comctl32.dll")] private static extern bool RemoveWindowSubclass(nint window, PlayerSubclass procedure, nuint id);
        [DllImport("comctl32.dll")] private static extern nint DefSubclassProc(nint window, uint message, nuint wParam, nint lParam);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern nint GetWindowLongPtr(nint window, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern nint SetWindowLongPtr(nint window, int index, nint value);
        [DllImport("user32.dll")] private static extern bool SetWindowPos(nint window, nint after, int x, int y, int width, int height, uint flags);
        [DllImport("user32.dll")] private static extern bool GetCursorPos(out PlayerPoint point);
        [DllImport("user32.dll")] private static extern bool ClientToScreen(nint window, ref PlayerPoint point);
    }
}
