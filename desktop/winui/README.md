# AM Dowloader · WinUI 3

这是从现有 AM Dowloader 迁移的 Windows 原生桌面版本，使用 C#、WinUI 3 和
Windows Composition。窗口、页面、歌词、播放控制、队列、账户界面、设置、托盘及
单实例逻辑已重新实现；应用不加载 Qt、PySide6 或 Qt Multimedia。

保留现有 AppleMusicDecrypt 下载进程和 C++ 音频输出引擎。标签读取、封面处理、
CUE／SACD 准备由独立、无 Qt 的 Python 工具进程处理。

## 运行

可使用 Release 的 `*-Setup.exe` 安装版，或完整解压便携 ZIP 后打开
`AM Downloader WinUI.exe`。安装版默认安装到当前用户的
`%LOCALAPPDATA%\Programs\AM Downloader`，支持选择目录、开始菜单快捷方式、
可选桌面快捷方式及卸载；卸载保留 `%LOCALAPPDATA%\MusicDesk` 中的个人数据。
升级前请在托盘菜单正常退出正在运行的旧版。需要 Windows 10 2004（19041）或更新的
x64 系统；包内包含 .NET 和 Windows App SDK 运行时，无需另装 Python 或 .NET SDK。
首次启动下载后端会将公开的初始镜像解压到个人数据目录，之后复用用户镜像与登录状态。

默认沿用 `%LOCALAPPDATA%\MusicDesk` 数据格式，包括资料库路径、喜爱歌曲、歌单、
播放队列、最后选择的歌曲及同一 Windows 用户的 DPAPI 账户信息。首次写入前会备份
原偏好文件。使用真实资料库前先退出旧版，避免两个版本同时写入同一个配置文件。

本包是 **WinUI 迁移预览版**，保留旧版安装，不自动覆盖现有程序或发布 GitHub Release。
原生 DAC／ASIO／DoP 输出和 Apple 在线账户流程仍需要实际设备与账户验收。
精确验证范围见源码中的 `winui/MIGRATION.md`。

使用独立数据目录试运行：

```powershell
& '.\AM Downloader WinUI.exe' --data-dir 'D:\AM-WinUI-Test'
```

## 功能与播放规格

- 原有深色／玫瑰红布局、专辑背景模糊、主页精选、艺人双栏、专辑详情、歌曲筛选与搜索。
- 递归导入文件夹、本地多选导入、标签与封面批量编辑、原文件备份、重复与版本识别。
- 自定义歌单、拖放与顺序调整、M3U 导入／导出、独立播放队列、本轮不重复的伪随机播放。
- 自然结束后暂停两秒；手动切歌立即响应。恢复上次歌曲时不自动播放。
- 加粗歌词、上下渐隐、逐字高亮与轻微浮起、LRC 同时刻翻译合并、原生平滑滚动与点击定位；歌词和队列从右侧展开。
- 后端自动启动、下载进度、暂停／重试／移除、可用最高规格确认、日志导出。
- 登录历史、DPAPI 记住密码、自动登录、错误密码和验证码保持窗口、单实例唤回、托盘与关闭选择。

| 类型 | 支持范围 |
| --- | --- |
| 有损与常见容器 | AAC、M4A／M4B、MP3、MP2、Ogg Vorbis、Opus、Speex、WMA、Musepack、AC-3、E-AC-3 |
| PCM 与无损 | ALAC、FLAC、WAV、AIFF／AIFC、APE、WavPack、TAK、TTA |
| DSD 与整轨 | DSF、DFF／DSDIFF、CUE 整轨、SACD ISO；DST 等格式通过兼容解码路径播放 |
| 系统共享输出 | FFmpeg 解码为 PCM，经 Windows 共享混音；支持软件音量。DSD 在此路径解码为 PCM |
| 独占输出 | WASAPI／ASIO PCM；DSF 与未压缩 DFF 可使用 ASIO 原生 DSD 或 DoP，不自动改采样率 |
| DSD 档位 | 数据读取与封装覆盖 DSD64、128、256、512；实际直通档位由驱动、DAC 和传输能力决定 |

不能将“格式可识别”视为所有变体均已验证。已有自动测试生成并解码 18 种音频样本；
DSD／DoP 的字节与定位测试覆盖 DSD64 至 DSD512。APE、TAK、Musepack 及真实
DST 镜像仍需额外样本验收。输出链路窗口显示源规格、解码步骤、实际驱动确认和状态。

## 从源码构建

需要 .NET 10 SDK、Visual Studio C++ x64 Build Tools、Windows SDK，以及可运行
构建脚本的 Python。NuGet 依赖固定在项目文件，源为 nuget.org。官方框架参考：
[WinUI](https://github.com/microsoft/microsoft-ui-xaml)、
[Windows App SDK](https://learn.microsoft.com/windows/apps/windows-app-sdk/)。

```powershell
python winui/build_native.py
dotnet run --project winui/AMDownloader.Tests/AMDownloader.Tests.csproj
dotnet build winui/AMDownloader.WinUI/AMDownloader.WinUI.csproj
python winui/build_package.py --output 'winui/artifacts/my-winui-build'
python winui/tests/check_package.py 'winui/artifacts/my-winui-build.zip' --report-dir 'qa/winui-package-check'
```

打包脚本只接受新的输出路径，不删除旧包。首次会验证并从固定的公开上游产物准备后端。
也可通过 `--backend` 复用经过校验的精简公开后端，禁止使用个人登录镜像。分发目录包含
对应源码、许可证、SACD 源码归档及逐文件 SHA-256 清单。

`check_package.py` 校验压缩包及逐文件哈希，将其解压到仓库外的临时目录，以包内
Python 生成静音样本，再运行真正的 Release EXE；它不传入开发资源路径，也不使用
个人资料库。通过后保留报告与界面截图，并清理此次临时解压目录。

逐字时间优先使用增强 LRC 的 `<mm:ss.xx>` 标记；普通 LRC 只有整句时间时，
句内进度按时间估算，不能代表精确的演唱对齐。暂停、跳转和换行会同步重置动画。

生成安装版需要 [Inno Setup 7](https://jrsoftware.org/isinfo.php)，先验证便携包，再运行：

```powershell
python winui/build_installer.py 'winui/artifacts/my-winui-build' --iscc 'C:/Tools/Inno Setup 7/ISCC.exe' --version '2.0.0-preview.3' --output-dir 'winui/artifacts/installers'
```

安装器逐文件校验输入目录后编译，不自动关闭运行中的播放器，不卸载旧 Qt 版，
不写入或删除个人资料库、音乐文件和账号信息。安装版与便携版包含同一套运行文件。

在源码目录使用现有组件调试，可通过 `--resources` 指定包含 `musicdesk_worker.py` 和
`vendor/backend/bundle.json` 的源码根目录。自动界面验收必须同时指定隔离数据目录和
`--no-backend`，只使用生成的静音样本，不操作个人账户。

## 许可与使用

应用源码遵循 GNU AGPL-3.0-or-later。第三方组件保留各自许可证，参见
`THIRD_PARTY_NOTICES.md`、`licenses` 和后端目录。Apple Music 名称与封面属于其权利人；
本项目与 Apple 没有隶属关系。请仅处理自己拥有权利或取得许可的内容，并遵守适用法律
与服务条款。软件按现状提供，不对账户可用性、第三方服务或特定设备兼容性作保证。
