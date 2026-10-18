namespace AMDownloader.Core;

public sealed class ShuffleOrder
{
    private readonly Random random;
    private List<string> scope = [], pending = [], history = [];
    private readonly HashSet<string> visited = [];
    private int cursor = -1;
    public ShuffleOrder(Random? random = null) => this.random = random ?? Random.Shared;
    public void Reset() { scope = []; pending = []; history = []; visited.Clear(); cursor = -1; }
    private void Sync(IEnumerable<string> paths, string current)
    {
        var incoming = paths.Distinct().ToList();
        if (incoming.Count == 0) { scope = []; return; }
        if (cursor < 0 || history[cursor] != current)
        {
            scope = incoming;
            pending = scope.Where(x => x != current).ToList();
            random.Shuffle(System.Runtime.InteropServices.CollectionsMarshal.AsSpan(pending));
            visited.Clear(); if (scope.Contains(current)) visited.Add(current);
            history = scope.Contains(current) ? [current] : [];
            cursor = history.Count - 1;
        }
        else if (!scope.SequenceEqual(incoming))
        {
            pending = pending.Where(incoming.Contains).Concat(incoming.Where(x => !scope.Contains(x) && !visited.Contains(x))).ToList();
            var prefix = history.Take(cursor + 1).Where(incoming.Contains).ToList();
            history = prefix.Concat(history.Skip(cursor + 1).Where(incoming.Contains)).ToList();
            cursor = prefix.Count - 1; scope = incoming;
        }
    }
    public IReadOnlyList<string> Upcoming(IEnumerable<string> paths, string current)
    {
        Sync(paths, current);
        if (scope.Count == 0) return [];
        return history.Skip(cursor + 1).Concat(pending.AsEnumerable().Reverse()).ToList();
    }
    public string? Step(IEnumerable<string> paths, string current, int direction = 1)
    {
        Sync(paths, current);
        if (scope.Count == 0) return null;
        if (direction < 0) { cursor = Math.Max(0, cursor - 1); return history.Count > 0 ? history[cursor] : scope[0]; }
        if (cursor + 1 < history.Count) return history[++cursor];
        if (pending.Count == 0)
        {
            pending = [.. scope]; random.Shuffle(System.Runtime.InteropServices.CollectionsMarshal.AsSpan(pending)); visited.Clear();
            if (pending.Count > 1 && pending[^1] == current) (pending[0], pending[^1]) = (pending[^1], pending[0]);
        }
        var result = pending[^1]; pending.RemoveAt(pending.Count - 1); visited.Add(result); history.Add(result);
        if (history.Count > Math.Max(100, scope.Count * 2)) history.RemoveAt(0);
        cursor = history.Count - 1;
        return result;
    }
}

public sealed class InterTrackGap : IDisposable
{
    private readonly TimeSpan delay;
    private CancellationTokenSource timer = new();
    public bool Waiting { get; private set; }
    public bool Running { get; private set; }
    public event Action? Ready;
    public event Action? Changed;
    public InterTrackGap(TimeSpan? delay = null) => this.delay = delay ?? TimeSpan.FromSeconds(2);
    public void Start()
    {
        if (Running) return;
        timer.Dispose(); timer = new(); Waiting = Running = true; Changed?.Invoke(); _ = WaitAsync(timer.Token);
    }
    private async Task WaitAsync(CancellationToken token)
    {
        try { await Task.Delay(delay, token); if (!token.IsCancellationRequested) { Waiting = Running = false; Changed?.Invoke(); Ready?.Invoke(); } }
        catch (OperationCanceledException) { }
    }
    public void Pause() { timer.Cancel(); Running = false; Changed?.Invoke(); }
    public void Cancel() { timer.Cancel(); var changed = Waiting || Running; Waiting = Running = false; if (changed) Changed?.Invoke(); }
    public void Dispose() { Cancel(); timer.Dispose(); }
}

public static class OrderedEntries
{
    public static List<T> Move<T>(IReadOnlyList<T> items, IEnumerable<int> rows, int destination)
    {
        var selected = rows.Where(i => i >= 0 && i < items.Count).ToHashSet();
        destination = Math.Clamp(destination, 0, items.Count) - selected.Count(i => i < destination);
        var result = items.Where((_, i) => !selected.Contains(i)).ToList();
        result.InsertRange(destination, items.Where((_, i) => selected.Contains(i)));
        return result;
    }
}
