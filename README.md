# pikpak-llc-workflow

这是一个由 Project Agent 驱动的自动化脚本项目。

## 用户工作流

1. PikPak → 获取并下载 480p 低清代理版本。
2. 使用 LosslessCut v3.69.0 浏览代理视频并选择片段，保存 `.llc` 文件。
3. Project Agent 读取 `.llc`，解析时间片段。
4. 验证原画的 Range/Seek 能力，确保存取安全。
5. 只下载指定的原画片段，不下载完整原片。

## Workspace output contract

一次 PikPak Share 调用创建一个 Job：

```text
workspace/jobs/<job-id>/
  proxies/
  projects/
  segments/
    <source-stem>/
  reports/
  temp/
```

`workspace/LATEST.txt` 指向当前 Job。用户只需使用程序最终报告的两个绝对路径：

- `PROXY_DIR`：LosslessCut 使用的代理文件目录。
- `SEGMENTS_DIR`：完成验证的原画片段目录。

用户完成 LosslessCut 后，把一个或多个 `.llc` 放入当前 Job 的 `projects/`；Agent 会从 LATEST Job 稳定发现全部项目。每个 source 的输出进入 `segments/<source-stem>/`，避免不同 LLC 的 `segment_001.mp4` 冲突。`workspace/` 全目录不进入 Git。

Job 内部会保留原 Share invocation 以继续 Origin 阶段；该字段属于内部状态，不进入 report、log 或 Git。

## 日常 authenticated Origin 流程

secure profile 缺失或失效时，Agent 只启动一次可见 setup：

```powershell
python -m pikpak_llc.profile_setup
```

setup 完成后，日常由 Agent 运行：

```powershell
python -m pikpak_llc.authenticated_workflow
```

该入口自动使用 `workspace/LATEST.txt` 定位 LLC 与输出目录，自动从源文件大小、源时长和所选片段时长计算 hard fuse；日常运行不要求用户提供 rclone config、加密密码、file ID、Range、路径或 `--max-origin-bytes`。只有 secure profile 缺失/失效，或估算预算接近完整 Origin 时才会明确停止并要求一次 setup/确认。

Windows 的 portable rclone、DPAPI profile、临时明文 config 与内部日志位于 `%LOCALAPPDATA%\PikPakLLC\`，不进入 Git。服务只监听 `127.0.0.1`，强制 `--pikpak-no-media-link`；临时明文 config 在每次运行结束时删除。
