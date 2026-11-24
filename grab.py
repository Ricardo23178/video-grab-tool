"""Windows 本机链接下载入口；只保存原件，不分析视频内容。"""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT.parent / "视频资料"
WORK = ROOT / ".work"
TOOLS = ROOT / ".tools"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/155.0.0.0 Safari/537.36"
PAGE_DOMAINS = ("douyin.com", "iesdouyin.com", "bilibili.com", "b23.tv")
IMAGE_DOMAINS = ("douyinpic.com", "byteimg.com", "ibytedtos.com")


def domain_is(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def extract_url(text):
    urls = re.findall(r'https?://[^\s<>"\u201c\u201d]+', text)
    if len(urls) != 1:
        raise ValueError("每次需要一条链接；批量下载请使用 --file 链接.txt")
    url = urls[0].rstrip("。，、；;！!）)]}")
    p = urlsplit(url)
    if not domain_is(p.hostname or "", PAGE_DOMAINS) or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError("仅接受抖音或 B 站官方作品链接")
    return url


@dataclass(frozen=True)
class Target:
    platform: str
    key: str
    kind: str
    url: str
    page: int = 1


def identify(url):
    extract_url(url)
    p = urlsplit(url)
    if domain_is(p.hostname, ("douyin.com", "iesdouyin.com")):
        match = re.search(r"/(?:share/)?(video|note|slides)/(\d+)", p.path)
        if match:
            kind = "video" if match[1] == "video" else "note"
            return Target("douyin", match[2], kind, f"https://www.douyin.com/{kind}/{match[2]}")
    if domain_is(p.hostname, ("bilibili.com",)):
        match = re.search(r"/video/(BV[A-Za-z0-9]+|av\d+)", p.path)
        if match:
            page = max(1, int(parse_qs(p.query).get("p", ["1"])[0]))
            suffix = f"_p{page}" if page > 1 else ""
            return Target("bilibili", match[1] + suffix, "video", f"https://www.bilibili.com/video/{match[1]}/?p={page}", page)
        match = re.search(r"/(?:mobile/)?opus/(\d+)|/read/(cv\d+)", p.path)
        if match:
            return Target("bilibili", match[1] or match[2], "note", url)
    raise ValueError("未识别到作品编号，请提供具体作品链接，不要提供主页、直播间或收藏夹")


class PageRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        extract_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_url(text):
    url = extract_url(text)
    try:
        return identify(url)
    except ValueError:
        if urlsplit(url).hostname not in ("v.douyin.com", "b23.tv", "www.b23.tv"):
            raise
    agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
    with build_opener(PageRedirects()).open(Request(url, headers={"User-Agent": agent}), timeout=25) as response:
        return identify(response.url)


def find_browser():
    for base in (os.environ.get("PROGRAMFILES", "C:/Program Files"), os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")):
        for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            path = Path(base) / relative
            if path.is_file():
                return path
    raise FileNotFoundError("需要已安装的 Chrome 或 Edge 浏览器")


def find_tool(name):
    roots = (TOOLS, ROOT.parent / "tools")
    patterns = {"ffmpeg": ("ffmpeg.exe", "imageio-ffmpeg/imageio_ffmpeg/binaries/ffmpeg*.exe", "ffmpeg/imageio_ffmpeg/binaries/ffmpeg*.exe"), "bbdown": ("BBDown.exe", "BBDownNext-*.exe")}
    for root in roots:
        for pattern in patterns[name]:
            paths = sorted(root.glob(pattern), reverse=True)
            if paths:
                return paths[0]
    path = shutil.which("ffmpeg" if name == "ffmpeg" else "BBDown")
    if path:
        return Path(path)
    raise FileNotFoundError(f"缺少 {name}，请先运行 python -B grab.py --setup")


def process_env():
    WORK.mkdir(exist_ok=True)
    return dict(os.environ, TEMP=str(WORK), TMP=str(WORK), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")


def checked_run(args, timeout=120, cwd=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, env=process_env(), capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        message = (result.stderr or result.stdout).decode("utf-8", errors="replace")[-1000:]
        message = re.sub(r"https?://\S+", "[请求地址]", message)
        message = re.sub(r"(?i)(cookie|sessdata|access_token|refresh_token)\s*[:=]\s*[^\s]+", r"\1=[已隐藏]", message)
        raise RuntimeError(f"外部工具退出码 {result.returncode}：{message.strip()}")
    return result


def render_page(target, folder):
    profile = ROOT / ".session" / target.platform
    profile.mkdir(parents=True, exist_ok=True)
    netlog, dom = folder / "network.json", folder / "page.html"
    args = [str(find_browser()), "--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-sync", "--disable-component-update", "--disable-crash-reporter", f"--user-data-dir={profile}", f"--disk-cache-dir={profile / 'cache'}", f"--log-net-log={netlog}", "--timeout=25000", "--virtual-time-budget=15000", "--dump-dom", target.url]
    with dom.open("xb") as output:
        process = subprocess.Popen(args, stdout=output, stderr=subprocess.DEVNULL, env=process_env())
        try:
            code = process.wait(timeout=75)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            process.wait()
            raise TimeoutError("浏览器加载超时，请稍后重试") from None
    if code or dom.stat().st_size < 100 or not netlog.exists():
        raise RuntimeError("网页未加载成功。请关闭本工具专用的登录窗口后重试；平台验证码需本人处理。")
    return dom.read_text(encoding="utf-8", errors="replace"), json.loads(netlog.read_text(encoding="utf-8"))


def network_media(log):
    urls = []
    for event in log.get("events", []):
        url = event.get("params", {}).get("url", "")
        p = urlsplit(url)
        if p.scheme in ("https", "http") and domain_is(p.hostname or "", ("douyinvod.com",)) and "/video/tos/" in p.path and url not in urls:
            urls.append(url)
    videos = [u for u in urls if "media-audio" not in u]
    if not videos:
        raise ValueError("没有获取到原视频地址。请使用 --login douyin 在本机登录，关闭专用窗口后重试；也可能是作品不可访问或平台发生变化。")
    # 平台会预取推荐视频，只取目标页面最先播放的视频及音频。
    video = videos[0]
    next_video = next((i for i, u in enumerate(urls) if "media-audio" not in u and urlsplit(u).path != urlsplit(video).path), len(urls))
    audio = next((u for u in urls[:next_video] if "media-audio" in u), None)
    return video, audio


class PageInfo(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = []
        self.description = ""
        self.body, self.published, self.location, self.images = [], [], [], []
        self.player_text = []
        self.pending_published = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "description":
            self.description = attrs.get("content", "")
        marker = attrs.get("data-e2e", "")
        markers = [x[1] for x in self.stack] + [marker]
        if "dySwiperSlide" in attrs.get("class", "").split() and "note-detail" in markers and "player-container" in markers:
            marker = "photo-image"
        if tag == "img" and any(x in markers for x in ("photo-image", "feed-active-slide", "detail-photo", "note-content")) and not set(markers) & {"comment-item", "related-video", "aweme-relate"}:
            source = attrs.get("src") or attrs.get("data-src") or ""
            if source.startswith("//"):
                source = "https:" + source
            if domain_is(urlsplit(source).hostname or "", IMAGE_DOMAINS) and source not in self.images:
                self.images.append(source)
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"):
            self.stack.append((tag, marker))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        value = value.strip()
        if not value:
            return
        tags, markers = {x[0] for x in self.stack}, {x[1] for x in self.stack}
        if "title" in tags:
            self.title.append(value)
        if tags & {"script", "style"} or markers & {"comment-item", "related-video"}:
            return
        if "note-detail" in markers and "player-container" in markers:
            self.player_text.append(value)
        if markers & {"detail-video-info", "detail-photo-info", "note-content"}:
            self.body.append(value)
        if "detail-video-publish-time" in markers:
            self.published.append(value.removeprefix("发布时间："))
        if "note-detail" in markers:
            if self.pending_published and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?", value):
                self.published.append(value)
                self.pending_published = False
            if value == "发布时间：":
                self.pending_published = True
        if markers & {"poi-name", "video-location"}:
            self.location.append(value)


def page_info(source):
    parser = PageInfo()
    parser.feed(source)
    original_text = re.sub(r"\s+- .+?于\d{8}发布在抖音，.*$", "", parser.description)
    counter = re.search(r"\b\d+\s*/\s*(\d+)\b", " ".join(parser.player_text))
    return {"title": re.sub(r"\s*-\s*(抖音|哔哩哔哩.*)$", "", "".join(parser.title)), "description": parser.description, "body": "\n".join(parser.body) or original_text, "published_at": "".join(parser.published), "location": "".join(parser.location), "images": parser.images, "image_count": int(counter[1]) if counter else None}


def download_url(url, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"不会覆盖已有文件：{output}")
    for attempt in range(3):
        created = False
        try:
            req = Request(url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/", "Accept-Encoding": "identity"})
            with urlopen(req, timeout=40) as response:
                content_type = response.headers.get_content_type()
                if content_type.startswith("text/") or content_type == "application/json":
                    raise ValueError("服务器返回了网页或错误信息，没有下载成原件")
                expected = response.headers.get("Content-Length")
                total = 0
                with output.open("xb") as file:
                    created = True
                    while chunk := response.read(1024 * 1024):
                        file.write(chunk)
                        total += len(chunk)
                if not total or (expected and total != int(expected)):
                    raise OSError("文件下载不完整")
                return content_type
        except Exception as error:
            if created:
                output.unlink()
            retry = isinstance(error, (URLError, TimeoutError, OSError)) and not isinstance(error, FileExistsError)
            if isinstance(error, HTTPError) and error.code in (400, 401, 403, 404, 410, 412, 429):
                retry = False
            if not retry or attempt == 2:
                raise
            time.sleep(attempt + 1)


def verify_mp4(path):
    checked_run([find_tool("ffmpeg"), "-nostdin", "-v", "error", "-xerror", "-i", path, "-map", "0:v:0", "-map", "0:a?", "-c", "copy", "-f", "null", "-"], timeout=180)


def download_douyin(target, stage, work):
    print("  正在加载作品页面…", flush=True)
    source, network = render_page(target, work)
    info = page_info(source)
    gallery = target.kind == "note" or (info["images"] and 'data-e2e="note-detail"' in source)
    if not gallery:
        video_url, audio_url = network_media(network)
        if "media-video-" in video_url and not audio_url:
            raise ValueError("只获取到分离的视频轨，没有取得对应声音，未保存为完整视频。请重试或本人登录后再试。")
        video, audio = work / "video.mp4", work / "audio.mp4"
        print("  正在下载原始音视频…", flush=True)
        download_url(video_url, video)
        args = [find_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-n", "-i", video]
        if audio_url:
            download_url(audio_url, audio)
            args += ["-i", audio, "-map", "0:v:0", "-map", "1:a:0"]
        else:
            args += ["-map", "0:v:0", "-map", "0:a?"]
        output = stage / "原视频.mp4"
        checked_run(args + ["-c", "copy", "-movflags", "+faststart", output])
        verify_mp4(output)
    else:
        if not info["images"]:
            raise ValueError("未能识别此图集的原图，未标记为成功")
        if info["image_count"] and info["image_count"] != len(info["images"]):
            raise ValueError(f"图集共有 {info['image_count']} 张，只识别到 {len(info['images'])} 张，未标记为完整下载")
        images = stage / "图片"
        for index, url in enumerate(info["images"], 1):
            images.mkdir(exist_ok=True)
            path = images / f"{index:03}.bin"
            content_type = download_url(url, path)
            extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif", "image/heic": ".heic"}
            if not content_type.startswith("image/"):
                raise ValueError("图集地址没有返回图片")
            path.rename(path.with_suffix(extensions.get(content_type, ".bin")))
    return info


def download_bilibili(target, stage):
    print("  正在由 BBDownNext 下载…", flush=True)
    args = [find_tool("bbdown"), target.url, "--work-dir", stage, "--no-force-http", "--max-retry", "2"]
    if target.kind == "video":
        args += ["--get", "avm", "--pages", str(target.page), "--ffmpeg-path", find_tool("ffmpeg"), "--single-thread"]
    else:
        args += ["--get", "AiM"]
    checked_run(args, timeout=3600, cwd=stage)
    videos = list(stage.rglob("*.mp4"))
    documents = list(stage.rglob("*.md"))
    if target.kind == "video" and not videos:
        raise ValueError("未取得完整视频文件，请检查作品权限或登录状态")
    if target.kind == "note" and not documents:
        raise ValueError("未取得图文正文文件")
    for video in videos:
        verify_mp4(video)
    return {"title": (videos or documents)[0].stem, "description": "", "body": "", "published_at": "", "location": ""}


def file_records(folder):
    records = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path != folder / "信息.json":
            with path.open("rb") as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            records.append({"name": path.relative_to(folder).as_posix(), "size": path.stat().st_size, "sha256": digest})
    return records


def is_complete(folder):
    try:
        record = json.loads((folder / "信息.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("complete") is not True or not record.get("files"):
            return False
        for item in record["files"]:
            path = (folder / item["name"]).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file() or path.stat().st_size != item["size"]:
                return False
            with path.open("rb") as file:
                if hashlib.file_digest(file, "sha256").hexdigest() != item["sha256"]:
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def archive(text, output):
    target = resolve_url(text)
    folder = Path(output).resolve() / ("抖音" if target.platform == "douyin" else "B站") / target.key
    if is_complete(folder):
        return "skipped", folder
    if folder.exists():
        raise FileExistsError(f"已有目录未通过完整性检查，为避免覆盖，请换输出目录或先检查：{folder}")
    process_env()
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download-", dir=WORK, ignore_cleanup_errors=True) as name, tempfile.TemporaryDirectory(prefix=".grab-", dir=folder.parent, ignore_cleanup_errors=True) as result_name:
        work = Path(name).resolve()
        result_root = Path(result_name).resolve()
        if not work.is_relative_to(WORK.resolve()) or not result_root.is_relative_to(folder.parent.resolve()):
            raise ValueError("临时目录不在项目内部")
        stage = result_root / "result"
        stage.mkdir()
        info = download_douyin(target, stage, work) if target.platform == "douyin" else download_bilibili(target, stage)
        info.pop("images", None)
        info.update({"platform": target.platform, "id": target.key, "url": target.url, "original_url": extract_url(text), "saved_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")})
        note = f"# {info['title'] or target.key}\n\n原链接：{info['original_url']}\n\n发布时间：{info.get('published_at') or '未获取'}\n\n公开定位：{info.get('location') or '未获取'}\n\n{info.get('description', '')}\n\n{info.get('body', '')}\n"
        note_path = stage / ("归档信息.md" if (stage / "信息.md").exists() else "信息.md")
        with note_path.open("x", encoding="utf-8") as file:
            file.write(note)
        info.update({"complete": True, "files": file_records(stage)})
        (stage / "信息.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        stage.rename(folder)
    return "saved", folder


def setup_tools():
    find_browser()
    TOOLS.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    for name in ("ffmpeg", "bbdown"):
        try:
            print(f"已有 {name}：{find_tool(name)}")
            continue
        except FileNotFoundError:
            pass
        print(f"正在下载 {name}，请稍候…", flush=True)
        if name == "bbdown":
            url = "https://github.com/KaiHuaDou/BBDownNext/releases/download/v2.3.0/BBDown-win-x64.exe"
            with tempfile.TemporaryDirectory(dir=WORK) as temp_name:
                output = Path(temp_name) / "BBDown.exe"
                download_url(url, output)
                digest = hashlib.sha256(output.read_bytes()).hexdigest()
                if digest != "d9e75a7196ba28a77a7bcbca7408748e8efe42a52a81e5890bde5bbf7d952890":
                    raise ValueError("BBDownNext 校验失败，未安装该文件")
                output.rename(TOOLS / "BBDown.exe")
        else:
            with urlopen("https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json", timeout=30) as response:
                metadata = json.load(response)
            wheel = next(x for x in metadata["urls"] if x["filename"].endswith("win_amd64.whl"))
            with tempfile.TemporaryDirectory(dir=WORK) as temp_name:
                path = Path(temp_name) / "ffmpeg.whl"
                download_url(wheel["url"], path)
                if hashlib.sha256(path.read_bytes()).hexdigest() != wheel["digests"]["sha256"]:
                    raise ValueError("FFmpeg 下载校验失败")
                with zipfile.ZipFile(path) as archive:
                    member = next(x for x in archive.namelist() if x.endswith(".exe") and "/ffmpeg" in x)
                    extracted = Path(temp_name) / "ffmpeg.exe"
                    with archive.open(member) as source, extracted.open("xb") as output:
                        shutil.copyfileobj(source, output)
                extracted.rename(TOOLS / "ffmpeg.exe")
        print(f"已安装 {name}：{find_tool(name)}")


def login(platform):
    if platform == "bilibili":
        return subprocess.call([str(find_tool("bbdown")), "login"], env=process_env())
    profile = ROOT / ".session" / "douyin"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([str(find_browser()), f"--user-data-dir={profile}", f"--disk-cache-dir={profile / 'cache'}", "--no-first-run", "--no-default-browser-check", "--new-window", "https://www.douyin.com/"], env=process_env())
    print("请在专用浏览器窗口里登录抖音，登录后关闭整个专用窗口，再运行下载。")
    print(f"登录状态保存在本机 {profile}；不会导出或打印 Cookie，状态失效后需重新登录。")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="把抖音 / B 站链接的原视频、图片和原文保存到本机。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("link", nargs="?", help="链接，或包含一条链接的完整分享文字")
    mode.add_argument("--file", type=Path, help="UTF-8 链接清单，每行一条")
    mode.add_argument("--setup", action="store_true", help="检查并安装所需工具到 D 盘项目目录")
    mode.add_argument("--login", nargs="?", const="douyin", choices=("douyin", "bilibili"), help="由本人登录并在本机保留登录状态")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help=f"保存目录，默认 {DEFAULT_OUTPUT}")
    args = parser.parse_args(argv)
    try:
        if args.setup:
            setup_tools()
            return 0
        if args.login:
            return login(args.login)
        if args.file:
            lines = [x.strip() for x in args.file.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
            if not lines:
                raise ValueError("链接清单为空")
        elif args.link:
            lines = [args.link]
        else:
            print(f"粘贴链接或整段分享文字后回车；输入 q 退出。保存目录：{args.output}")
            while True:
                try:
                    text = input("链接> ").strip()
                except EOFError:
                    return 0
                if text.lower() in ("q", "quit", "exit"):
                    return 0
                if text:
                    main([text, "--output", str(args.output)])
        counts = {"saved": 0, "skipped": 0, "failed": 0}
        for i, text in enumerate(lines, 1):
            print(f"[{i}/{len(lines)}] 处理链接…", flush=True)
            try:
                state, path = archive(text, args.output)
                counts[state] += 1
                print(f"{'已保存' if state == 'saved' else '已完整下载，跳过'}：{path}", flush=True)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                counts["failed"] += 1
                print(f"失败：{error}", flush=True)
        print(f"完成：成功 {counts['saved']}，跳过 {counts['skipped']}，失败 {counts['failed']}")
        return 1 if counts["failed"] else 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"配置或输入错误：{error}")
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断；已完成的文件保留，不完整任务下次可重新下载。")
        sys.exit(130)
