# pikpak-llc-workflow

这是一个由 Project Agent 驱动的自动化脚本项目。

## 用户工作流

1. PikPak → 获取并下载 480p 低清代理版本。
2. 使用 LosslessCut v3.69.0 浏览代理视频并选择片段，保存 `.llc` 文件。
3. Project Agent 读取 `.llc`，解析时间片段。
4. 验证原画的 Range/Seek 能力，确保存取安全。
5. 只下载指定的原画片段，不下载完整原片。
