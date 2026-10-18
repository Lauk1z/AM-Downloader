using System.Text.Json;
using AMDownloader.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI.Views;

internal sealed partial class LoginView
{
    internal static async Task<List<string>> VerifyBehaviorAsync(Accounts accounts, Window owner)
    {
        var checks = new List<string>(); var commands = new List<JsonElement>(); var successful = false;
        ToolWindow? dialog = null;
        var view = new LoginView(accounts, command => commands.Add(JsonSerializer.SerializeToElement(command)), () => { successful = true; dialog!.Close(); });
        dialog = new ToolWindow(owner, "隔离账号流程测试", view, 490, 680, "取消"); dialog.Activate();
        var shown = dialog.Completion; await Task.Delay(100);
        void Check(bool value, string name) { if (!value) throw new InvalidOperationException(name); checks.Add(name); }
        JsonElement Event(string kind, bool ok = false, string challenge = "") => JsonSerializer.SerializeToElement(new { @event = kind, request_id = view.requestId, challenge_id = challenge, ok, error = "测试错误" });
        try
        {
            accounts.Success("winui-test@example.invalid", "temporary-test-secret", true, true);
            Check(accounts.Password("winui-test@example.invalid") == "temporary-test-secret", "DPAPI roundtrip");
            view.password.Password = "temporary-test-secret"; view.SelectHistory("winui-test@example.invalid");
            Check(view.password.Password.Length == 0, "history selection fills only username");
            view.password.Password = "incorrect-test-secret"; view.Start(); view.Receive(Event("login"));
            Check(!successful && view.submit.IsEnabled && view.status.Text.Length > 0, "incorrect password keeps login open");
            view.password.Password = "temporary-test-secret"; view.Start(); view.Receive(Event("twofa", challenge: "first-challenge"));
            Check(view.verification.Visibility == Visibility.Visible && view.code.IsEnabled, "first login exposes verification entry");
            view.code.Text = "123456"; await Task.Delay(50); view.Verify(); var expiredRequest = view.requestId;
            Check(!successful && commands[^1].GetProperty("action").GetString() == "twofa", "submitting code does not close dialog");
            view.Receive(Event("login"));
            Check(!successful && view.verification.Visibility == Visibility.Visible && view.verify.IsEnabled && view.retry, "incorrect code keeps verification open");
            view.Verify(); Check(view.requestId != expiredRequest, "verification retry creates new request");
            view.Receive(JsonSerializer.SerializeToElement(new { @event = "login", request_id = expiredRequest, ok = true }));
            Check(!successful, "stale successful replies are ignored");
            view.Receive(Event("twofa", challenge: "second-challenge")); view.code.Text = "654321"; await Task.Delay(50); view.Verify(); view.Receive(Event("login", true));
            Check(successful, "only confirmed success closes login");
            await shown;
        }
        finally { view.Cancel(); if (!dialog.Completion.IsCompleted) dialog.Close(); }
        return checks;
    }
}
