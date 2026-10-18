using System.Text.Json;
using AMDownloader.Core;
using AMDownloader.WinUI.Services;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace AMDownloader.WinUI.Views;

internal sealed partial class LoginView : UserControl
{
    private readonly Accounts accounts;
    private readonly Action<object> send;
    private readonly Action success;
    private readonly AutoSuggestBox username = new() { PlaceholderText = "Apple 账号邮箱或手机号码" };
    private readonly PasswordBox password = new() { PlaceholderText = "输入密码" };
    private readonly CheckBox remember = new() { Content = "记住密码" }, automatic = new() { Content = "自动登录" };
    private readonly TextBlock status = Ui.Text("", 13, color: Ui.Accent);
    private readonly Button submit;
    private readonly StackPanel verification = Ui.Stack(12);
    private readonly TextBox code = new() { PlaceholderText = "六位验证码", MaxLength = 6 };
    private readonly Button verify;
    private string requestId = "", challengeId = "", pendingUser = "", pendingPassword = "";
    private bool pending, retry, loading;
    public LoginView(Accounts accounts, Action<object> send, Action success)
    {
        this.accounts = accounts; this.send = send; this.success = success;
        var panel = Ui.Stack(12); panel.Width = 400; panel.Children.Add(Ui.Text("通过本机内置服务登录，支持双重认证。", color: Ui.Muted));
        panel.Children.Add(Ui.Text("账号", 13)); panel.Children.Add(username); panel.Children.Add(Ui.Text("密码", 13)); panel.Children.Add(password);
        var choices = Ui.Stack(18, Orientation.Horizontal); choices.Children.Add(remember); choices.Children.Add(automatic); panel.Children.Add(choices);
        panel.Children.Add(Ui.Text("密码由 Windows 加密保护。选择历史账号只填账号，不填密码。", 12, color: Ui.Muted)); panel.Children.Add(status);
        submit = Ui.Button("登录", Start, true); panel.Children.Add(submit);
        verification.Visibility = Visibility.Collapsed; verification.Children.Add(Ui.Text("双重认证", 20, true)); verification.Children.Add(Ui.Text("在受信任的 Apple 设备上允许登录，然后输入收到的六位验证码。", 13, color: Ui.Muted)); verification.Children.Add(code);
        verify = Ui.Button("验证", Verify, true); verification.Children.Add(verify); verification.Children.Add(Ui.Button("取消验证", CancelVerification)); panel.Children.Add(verification); Content = panel;
        username.GotFocus += (_, _) => { username.ItemsSource = accounts.History.Select(x => x.Username).ToList(); username.IsSuggestionListOpen = true; };
        username.AddHandler(UIElement.PointerPressedEvent, new Microsoft.UI.Xaml.Input.PointerEventHandler((_, _) => { username.ItemsSource = accounts.History.Select(x => x.Username).ToList(); username.IsSuggestionListOpen = true; }), true);
        username.SuggestionChosen += (_, e) => SelectHistory(e.SelectedItem.ToString()!);
        username.TextChanged += (_, e) => { if (e.Reason == AutoSuggestionBoxTextChangeReason.UserInput && !loading) { password.Password = ""; LoadOptions(); username.ItemsSource = accounts.History.Where(x => x.Username.Contains(username.Text, StringComparison.OrdinalIgnoreCase)).Select(x => x.Username).ToList(); } };
        remember.Unchecked += (_, _) => { if (!loading) { automatic.IsChecked = false; accounts.ForgetPassword(username.Text); } };
        automatic.Checked += (_, _) => remember.IsChecked = true;
        automatic.Unchecked += (_, _) => { if (!loading) accounts.DisableAutomatic(username.Text); };
        code.TextChanged += (_, _) => verify.IsEnabled = retry || challengeId.Length > 0 && code.Text.Length == 6 && code.Text.All(char.IsAsciiDigit);
        password.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) Start(); }; code.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) Verify(); };
        username.Text = accounts.History.FirstOrDefault()?.Username ?? ""; LoadOptions();
        try { password.Password = accounts.Password(username.Text); } catch { status.Text = "无法读取已保存的密码，请重新输入。"; }
    }
    private void SelectHistory(string value)
    { loading = true; username.Text = value; loading = false; password.Password = ""; LoadOptions(); password.Focus(FocusState.Programmatic); }
    private void LoadOptions()
    { loading = true; var entry = accounts.Entry(username.Text); remember.IsChecked = entry is null || entry.Secret.Length > 0; automatic.IsChecked = entry is null || entry.Automatic; loading = false; }
    private void Busy(bool active)
    { username.IsEnabled = password.IsEnabled = remember.IsEnabled = automatic.IsEnabled = submit.IsEnabled = !active; submit.Content = active ? "正在登录…" : "登录"; }
    private void Start()
    {
        if (pending) return;
        pendingUser = username.Text.Trim(); pendingPassword = password.Password;
        if (pendingUser.Length == 0 || pendingPassword.Length == 0) { status.Text = "请输入账号和密码。"; return; }
        pending = true; SendLogin();
    }
    private void SendLogin()
    { requestId = Guid.NewGuid().ToString("N"); retry = false; challengeId = ""; code.IsEnabled = verify.IsEnabled = false; Busy(true); status.Text = "正在登录，请稍候…"; send(new { action = "login", request_id = requestId, username = pendingUser, password = pendingPassword }); }
    public void StartAutomatic(AccountEntry entry)
    { username.Text = entry.Username; LoadOptions(); try { password.Password = accounts.Password(entry.Username); Start(); } catch { status.Text = "无法读取已保存的密码，请重新输入。"; } }
    private void Verify()
    {
        if (!verify.IsEnabled) return;
        if (retry) { SendLogin(); return; }
        if (requestId.Length == 0 || challengeId.Length == 0) return;
        var challenge = challengeId; challengeId = ""; code.IsEnabled = verify.IsEnabled = false; status.Text = "正在验证，请稍候…";
        send(new { action = "twofa", request_id = requestId, challenge_id = challenge, code = code.Text }); code.Text = "";
    }
    public void Receive(JsonElement value)
    {
        if (!pending || requestId.Length == 0 || J.S(value, "request_id") != requestId) return;
        if (J.S(value, "event") == "twofa")
        { verification.Visibility = Visibility.Visible; challengeId = J.S(value, "challenge_id"); retry = false; code.Text = ""; code.IsEnabled = true; verify.Content = "验证"; verify.IsEnabled = false; code.Focus(FocusState.Programmatic); status.Text = "等待双重认证…"; return; }
        requestId = "";
        if (J.B(value, "ok"))
        {
            try { accounts.Success(pendingUser, pendingPassword, remember.IsChecked == true, automatic.IsChecked == true); }
            catch (Exception error) { status.Text = "登录成功，但无法保存密码：" + error.Message; }
            pending = false; password.Password = pendingPassword = ""; success();
        }
        else
        {
            accounts.DisableAutomatic(pendingUser); status.Text = Text.Redact(J.S(value, "error")); if (status.Text.Length == 0) status.Text = "登录失败，请检查账号和密码后重试。";
            if (verification.Visibility == Visibility.Visible) { retry = true; code.IsEnabled = false; verify.Content = "重新验证"; verify.IsEnabled = true; return; }
            pending = false; pendingPassword = ""; Busy(false); password.Focus(FocusState.Programmatic);
        }
    }
    private void CancelVerification()
    { if (requestId.Length > 0) send(new { action = "cancel_login", request_id = requestId }); requestId = challengeId = ""; pending = retry = false; pendingPassword = ""; code.Text = ""; verification.Visibility = Visibility.Collapsed; Busy(false); status.Text = "已取消验证，可以重新登录。"; }
    public void BackendFailed(string message)
    { if (pending) Receive(JsonSerializer.SerializeToElement(new { @event = "login", request_id = requestId, ok = false, error = message })); }
    public void Cancel() { CancelVerification(); password.Password = ""; }
}
