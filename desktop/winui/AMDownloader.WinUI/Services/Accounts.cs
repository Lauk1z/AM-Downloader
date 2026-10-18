using System.Runtime.InteropServices;
using System.Text;
using AMDownloader.Core;

namespace AMDownloader.WinUI.Services;

public sealed class Accounts(StateStore store)
{
    public List<AccountEntry> History => store.Get("login_accounts", new List<AccountEntry>());
    public AccountEntry? Entry(string username) => History.FirstOrDefault(x => x.Username.Equals(username.Trim(), StringComparison.OrdinalIgnoreCase));
    public string Password(string username) => Entry(username) is { Secret.Length: > 0 } entry ? Encoding.UTF8.GetString(Protect(Convert.FromBase64String(entry.Secret), true)) : "";
    public void Success(string username, string password, bool remember, bool automatic)
    {
        var entry = new AccountEntry(username.Trim(), remember ? Convert.ToBase64String(Protect(Encoding.UTF8.GetBytes(password), false)) : "", remember && automatic);
        store.Set("login_accounts", new[] { entry }.Concat(History.Where(x => !x.Username.Equals(entry.Username, StringComparison.OrdinalIgnoreCase))).ToList());
    }
    public void DisableAutomatic(string username) => store.Set("login_accounts", History.Select(x => x.Username.Equals(username, StringComparison.OrdinalIgnoreCase) ? x with { Automatic = false } : x).ToList());
    public void ForgetPassword(string username) => store.Set("login_accounts", History.Select(x => x.Username.Equals(username, StringComparison.OrdinalIgnoreCase) ? x with { Automatic = false, Secret = "" } : x).ToList());
    [StructLayout(LayoutKind.Sequential)] private struct Blob { public int Size; public nint Data; }
    [DllImport("crypt32.dll", SetLastError = true, CharSet = CharSet.Unicode)] private static extern bool CryptProtectData(ref Blob input, string? description, nint entropy, nint reserved, nint prompt, uint flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)] private static extern bool CryptUnprotectData(ref Blob input, nint description, nint entropy, nint reserved, nint prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")] private static extern nint LocalFree(nint pointer);
    private static byte[] Protect(byte[] bytes, bool decrypt)
    {
        var incoming = new Blob { Size = bytes.Length, Data = Marshal.AllocHGlobal(bytes.Length) }; Blob outgoing = default;
        try
        {
            Marshal.Copy(bytes, 0, incoming.Data, bytes.Length);
            var ok = decrypt ? CryptUnprotectData(ref incoming, 0, 0, 0, 0, 1, out outgoing) : CryptProtectData(ref incoming, null, 0, 0, 0, 1, out outgoing);
            if (!ok) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            var result = new byte[outgoing.Size]; Marshal.Copy(outgoing.Data, result, 0, result.Length); return result;
        }
        finally
        {
            Array.Clear(bytes); for (var i = 0; i < incoming.Size; i++) Marshal.WriteByte(incoming.Data, i, 0); Marshal.FreeHGlobal(incoming.Data);
            if (outgoing.Data != 0) { for (var i = 0; i < outgoing.Size; i++) Marshal.WriteByte(outgoing.Data, i, 0); LocalFree(outgoing.Data); }
        }
    }
}
