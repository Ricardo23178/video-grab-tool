# 视频链接抓取与本地归档

把抖音或 B 站的作品链接交给这个工具，在本机保存原视频 MP4、原图和原文。只做链接解析与原件落盘 —— 不重新编码、不做内容分析、不上传任何东西。

**为什么不直接用现成下载器：** yt-dlp、BBDown 覆盖平台多、参数面也大，行为不完全可控。这个项目反过来，把「只在你指定的域名上取你指定的那一个作品」写死成约束：域名白名单、单链接入口、永不覆盖、失败不留垃圾 —— 全部由测试锁住。

## 核心能力

| 能力 | 实现方式 |
| --- | --- |
| 链接识别 | 抖音 / B 站作品链接，支持短链与整段分享文字 |
| 抖音取流 | headless Chrome 加载页面，从网络日志里取真实媒体请求 |
| 抖音落盘 | 分离的音视频轨由 FFmpeg 无损合并，`-c copy` 不重编码 |
| B 站取流 | 交给 BBDownNext，本项目只做参数编排与结果校验 |
| 完整性 | 每个文件记 SHA256 进 `信息.json`，二次运行逐项反校验 |
| 原子落定 | 先写临时目录，校验通过后一次 rename 到位 |
| 界面 | C# WinForms 单窗口，后台执行、可中断 |

## 六个技术决策

### 1. 域名白名单放在解析入口，而不是下载之前

`extract_url` 是整条链路的入口，`domain_is` 要求 host 精确等于白名单域名或为其子域，同时拒绝带 `username` / `password` 和非常规端口的 URL。仿冒域名 `https://douyin.com.example.org/video/12` 在入口就被拒绝，后面的下载、落盘、合并全都不必再防。

**重定向也要逐跳校验。** 短链 `v.douyin.com` 会 302 到真实作品页，`PageRedirects` 重写了 `redirect_request`，每一跳都过一遍白名单。否则白名单只挡住了入口，跳出去之后照样能落到任意站点。

### 2. 媒体地址取自浏览器网络日志，不取 DOM 文本

抖音的播放直链由 JS 在运行时生成，页面 HTML 里搜不到。`--log-net-log` 记录的是浏览器实际发出的请求，`network_media()` 从中筛 `douyinvod.com` 且路径含 `/video/tos/` 的条目。

这里有个坑：平台会预取推荐流的视频，日志里不止目标作品。所以取到第一条视频后，要找到下一条不同路径的视频作为边界，音频只在这个区间里找 —— 否则可能把下一条推荐视频的声音合进来。

### 3. 「下载完成」的定义是能完整解码，不是文件存在

`verify_mp4` 用 `ffmpeg -xerror -c copy -f null -` 把整个文件解一遍，容器损坏、码流截断都会让它非零退出。

抖音常把音视频分成两条轨下发。代码先把 `media-video-*` 与 `media-audio-*` 分别下载，再 `-c copy` 合并；**如果只拿到视频轨、没拿到音频，直接报错不落盘** —— 一个无声的 MP4 不算成功，比失败更糟，因为要等打开才发现。

### 4. 完整性靠清单反校验，二次运行幂等

`file_records` 对归档目录里每个文件算 SHA256，连大小一起写进 `信息.json`；`is_complete` 反过来逐项核对：文件在不在、大小对不对、哈希是否一致、路径有没有逃出目录（`is_relative_to`）。

于是重复执行同一链接是安全的：校验通过就跳过；目录存在但校验不过就报错并保留现场，**绝不静默覆盖**。文件被改过、被截断、混进别的东西，都能被发现。

### 5. 先写临时目录，最后一次 rename 落定

中间产物放在 `.work` 下的临时目录，最终结果写在目标目录的**同级**临时目录 —— 同一个卷，`os.rename` 才是原子的。等下载完、清单写完、校验通过，才 `stage.rename(folder)`。

下载中途断网、浏览器崩、按了 Ctrl-C，目标目录里都不会留下半个任务。`KeyboardInterrupt` 的处理也建立在这个前提上：已完成的保留，未完成的下次重下。

### 6. 错误信息脱敏，外部二进制验哈希

`checked_run` 对外部工具的 stderr 做两步替换：URL 变 `[请求地址]`，`cookie|sessdata|access_token|refresh_token` 变 `[已隐藏]`。错误信息要能贴出来给人看，但不能把登录态一起贴出去。

`--setup` 下载的 BBDownNext 硬编码 SHA256 校验，FFmpeg 取 PyPI 元数据里的 `digests.sha256`。这个项目的前提是不完全信任外部输入，那它自己拉的东西也得验。

## 已知边界

- 只支持抖音、B 站两个平台，不做通用下载器
- 抖音取流依赖 headless Chrome 与网络日志，平台前端改版会让它失效 —— 这是换取「不逆向私有接口」的代价
- B 站的解析能力来自 BBDownNext，本项目只负责编排与校验
- 不处理直播、收藏夹、合集批量、私密作品
- 不解析 HLS / DASH 分片，也不处理 DRM —— 取的是平台下发的完整文件
- 登录由本人操作，登录态只存在本机 `.session`，不导出、不打印

## 快速开始

需要 Windows、Python 3.11 以上、Chrome 或 Edge。

```powershell
# 检查并安装 FFmpeg / BBDownNext 到项目 .tools
.\grab.ps1 -Setup

# 下载一条链接（也可粘贴整段分享文字）
.\grab.ps1 'https://v.douyin.com/8_UurbIXX4g/'

# 指定保存目录
.\grab.ps1 'https://v.douyin.com/8_UurbIXX4g/' -OutDir 'D:\我的视频'

# 交互式：每次粘贴一条，q 退出
.\grab.ps1

# 批量：每行一条链接
.\grab.ps1 -InputFile '.\links.txt' -OutDir 'D:\我的视频'
```

不依赖 PowerShell 执行策略时，直接用 Python：

```powershell
python -B .\grab.py 'https://v.douyin.com/8_UurbIXX4g/' --output 'D:\我的视频'
python -B .\grab.py --file .\links.txt
python -B .\grab.py --login douyin
```

默认输出到 `视频资料/<平台>/<作品编号>/`，内含 `原视频.mp4` 或 `图片/`，加一份 `信息.md` 和 `信息.json`。标题、发布时间、公开定位属于能取到就附带的字段，取不到写「未获取」，不推测。

### 需要登录时

推荐用窗口里的登录按钮；也可以由本人在命令行执行 `.\grab.ps1 -Login douyin` 或 `-Login bilibili`。抖音使用独立浏览器目录 `.session\douyin`，在官方页面登录后关闭整个专用窗口再下载；B 站用 BBDownNext 自带的扫码登录。登录态只保存在本机，不导出、不打印 Cookie，过期后需重新登录。

### 窗口界面

`视频下载工具.exe` 是 C# WinForms 单窗口：粘贴链接、选保存位置、开始下载，状态与记录显示在窗口内，下载期间可停止，完成后直接打开文件夹。登录入口也在窗口里，均由本人操作。

### 分享给朋友

`python -B package_share.py` 在同级 `分享包` 目录生成 Windows x64 便携 ZIP：内置官方 Python 运行环境与窗口 EXE。构建按文件白名单打包，不包含 `.session`、`.tools`、`.work`、Git 历史与下载原件。

## 依赖

- Chrome 或 Edge（窗口与抖音取流使用）
- FFmpeg、BBDownNext（`--setup` 自动下载到项目 `.tools`，均校验 SHA256）
- 界面使用 Windows 自带的 .NET Framework，不需要额外安装大型框架

所有依赖都装在项目目录内，临时文件走 `.work`，不向 C 盘安装 Python 依赖，也不修改全局 Python 环境。

## 测试

```bash
python -m pytest tests/ -q
```

覆盖链接解析与域名白名单、重定向逐跳校验、路径逃逸防护、完整性判定、归档幂等与 UI 冒烟。不访问真实平台、不依赖外部素材。

## 许可

MIT。
