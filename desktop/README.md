# AM Downloader Windows 桌面端

当前版本 **1.5.2**，可执行文件沿用 `AM Dowloader.exe` 名称。

软件用途、完整格式列表、音频输出规格、数据说明和免责声明见仓库根目录的 [README](../README.md)。已打包程序从 [Releases](https://github.com/Lauk1z/AM-Downloader/releases) 下载。

## 构建

在本目录执行，需要 Windows x64、Python 3.12、Visual Studio C++ x64 工具和 Windows SDK。7z 打包另需 7-Zip。

```powershell
py -3.12 -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe build.py
.\.build-venv\Scripts\python.exe package_release.py --7z
```

`build.py` 会构建原生音频进程、校验 SACD 组件、冻结桌面程序，并暂存固定版本的后端运行包。输出位于 `dist\AM Dowloader`，发布附件位于 `release`。首次构建需联网；原上游运行包的固定镜像保存在本仓库 1.5.2 Release，构建时仍校验其原始 SHA-256。

本目录的依赖与仓库根目录的上游 v3 依赖分开。桌面版固定使用 AppleMusicDecrypt v2 提交 `d1a9a10079a72a454ce013589a5a47d5c17c8aee`；集成修改在 `backend_patches.py`，原生音频源码在 `native`。

## 验证与来源

界面及单元测试位于 `tests`，版本验收记录见 [TEST_REPORT.md](TEST_REPORT.md)，历史更新见 [CHANGELOG.md](CHANGELOG.md)。部分整合测试需要已经暂存的后端、媒体工具或 Windows 图形环境；DAC 硬件验收另行进行。`qa` 中的本机运行记录不随源码上传。

[LICENSE.txt](LICENSE.txt) 提供项目许可，[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 `licenses` 保留第三方来源与声明。禁止将个人账号镜像、偏好配置、音乐、凭据或诊断导出混入发布目录。
