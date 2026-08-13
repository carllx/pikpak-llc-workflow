# pikpak-llc-workflow

这是一个由 Project Agent 驱动的自动化脚本项目。

## 用户工作流

1. PikPak → 获取并下载 480p 低清代理版本。
2. 使用 LosslessCut v3.69.0 浏览代理视频并选择片段，保存 `.llc` 文件。
3. Project Agent 读取 `.llc`，解析时间片段。
4. 验证原画的 Range/Seek 能力，确保存取安全。
5. 只下载指定的原画片段，不下载完整原片。

## 导出原画片段

安装 Python 依赖并确保 `ffmpeg` 在 `PATH` 中，然后运行：

```powershell
python origin_segment_extractor.py <PikPak 分享 URL 或 token> <project.llc> <输出目录>
```

程序会先对 Origin URL 执行 64 KiB Range 预检。只有服务器返回与请求匹配的
`206 Partial Content` 和 `Content-Range` 时，才会使用 `ffmpeg -c copy` 生成
`segment_001.mp4` 等片段。如果服务器返回 `200 OK`，程序会在读取完整响应体前中止。
