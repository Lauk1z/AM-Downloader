using System.Text.Json;
using System.Text.Json.Nodes;

namespace AMDownloader.Core;

public sealed class StateStore
{
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower, PropertyNameCaseInsensitive = true, WriteIndented = true };
    private readonly object gate = new();
    private readonly JsonObject data;
    private bool backedUp;
    public string DirectoryPath { get; }
    public string FilePath => Path.Combine(DirectoryPath, "preferences.json");
    public StateStore(string directory)
    {
        DirectoryPath = Path.GetFullPath(directory);
        Directory.CreateDirectory(DirectoryPath);
        data = File.Exists(FilePath) ? JsonNode.Parse(File.ReadAllText(FilePath))?.AsObject() ?? new() : new();
    }
    public T Get<T>(string key, T fallback)
    {
        lock (gate) return data[key] is { } value ? value.Deserialize<T>(Json) ?? fallback : fallback;
    }
    public void Set<T>(string key, T value)
    {
        lock (gate)
        {
            if (!backedUp && File.Exists(FilePath))
            {
                File.Copy(FilePath, FilePath + ".before-winui-" + DateTime.UtcNow.ToString("yyyyMMddHHmmssfff"), false);
                backedUp = true;
            }
            data[key] = JsonSerializer.SerializeToNode(value, Json);
            var temp = FilePath + ".winui.tmp";
            File.WriteAllText(temp, data.ToJsonString(Json), new System.Text.UTF8Encoding(false));
            File.Move(temp, FilePath, true);
        }
    }
}
