"""从明确的文件清单生成无账号数据的 Windows x64 便携分享包。"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION = "3.13.16"
PYTHON_URL = f"https://www.python.org/ftp/python/{VERSION}/python-{VERSION}-embed-amd64.zip"
PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
FILES = {
    "grab.py": "grab.py",
    "grab.ps1": "grab.ps1",
    "tests/test_grab.py": "tests/test_grab.py",
    "share/先读我.txt": "先读我.txt",
    "share/THIRD_PARTY.txt": "THIRD_PARTY.txt",
    "ui/DownloadApp.cs": "ui/DownloadApp.cs",
    "ui/app.manifest": "ui/app.manifest",
}


def build_ui(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work = ROOT / ".work"
    work.mkdir(exist_ok=True)
    compiler = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    command = [compiler, "/nologo", "/utf8output", "/target:winexe", "/optimize+", "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/win32manifest:" + str(ROOT / "ui" / "app.manifest"), "/out:" + str(output), ROOT / "ui" / "DownloadApp.cs"]
    result = subprocess.run([str(x) for x in command], cwd=ROOT, env=dict(os.environ, TEMP=str(work), TMP=str(work)), capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace"))
    if not output.is_file():
        raise RuntimeError("未生成窗口程序")
    return output


def launcher(arguments):
    text = rf'''@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 exit /b 2
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "TEMP=%~dp0.work"
set "TMP=%~dp0.work"
if not exist ".work" mkdir ".work"
echo 正在检查运行组件，首次运行需要联网下载，请稍候……
".runtime\python.exe" -B grab.py --setup
if errorlevel 1 goto setup_failed
".runtime\python.exe" -B grab.py {arguments}
set "grab_exit=%errorlevel%"
goto finished
:setup_failed
echo 组件准备失败。请阅读“先读我.txt”中的常见问题，再重试。
set "grab_exit=2"
:finished
pause
popd
exit /b %grab_exit%
'''
    return text.replace("\n", "\r\n").encode("utf-8")


def build(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"不会覆盖已有分享包：{destination}")
    cache = ROOT / ".work" / "share-build"
    cache.mkdir(parents=True, exist_ok=True)
    runtime_zip = cache / f"python-{VERSION}-embed-amd64.zip"
    if not runtime_zip.exists():
        with tempfile.TemporaryDirectory(dir=cache) as temp:
            downloaded = Path(temp) / "python.zip"
            print("下载官方 Python 便携运行环境…", flush=True)
            with urlopen(PYTHON_URL, timeout=60) as source, downloaded.open("xb") as target:
                shutil.copyfileobj(source, target)
            if hashlib.sha256(downloaded.read_bytes()).hexdigest() != PYTHON_SHA256:
                raise ValueError("Python 下载校验失败，未使用该文件")
            downloaded.rename(runtime_zip)
    if hashlib.sha256(runtime_zip.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise ValueError("缓存的 Python 文件校验失败，请先检查缓存文件")

    # 只打包白名单源码和经校验的官方运行环境，不递归复制项目目录。
    entries = {name: (ROOT / source).read_bytes() for source, name in FILES.items()}
    with tempfile.TemporaryDirectory(prefix="gui-build-", dir=cache) as temp:
        entries["视频下载工具.exe"] = build_ui(Path(temp) / "视频下载工具.exe").read_bytes()
    with zipfile.ZipFile(runtime_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError("Python 压缩包损坏")
        for member in archive.infolist():
            if member.is_dir():
                continue
            if ".." in Path(member.filename).parts or member.filename.startswith(("/", "\\")):
                raise ValueError("Python 压缩包中出现不安全路径")
            entries[".runtime/" + member.filename] = archive.read(member)
    entries[".runtime/python313._pth"] = b"python313.zip\n.\n..\n"
    entries["开始下载.cmd"] = '@echo off\r\nchcp 65001 >nul\r\nstart "" "%~dp0视频下载工具.exe"\r\n'.encode("utf-8")
    entries["登录抖音.cmd"] = launcher("--login douyin")
    entries["登录B站.cmd"] = launcher("--login bilibili")
    entries["文件校验.json"] = json.dumps({
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "platform": "Windows x64",
        "python": VERSION,
        "files": [{"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in sorted(entries.items())],
    }, ensure_ascii=False, indent=2).encode("utf-8")
    assert ".runtime/python.exe" in entries and ".runtime/LICENSE.txt" in entries
    assert all(not set(Path(name).parts) & {".session", ".work", ".tools", ".git", "下载内容"} for name in entries)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="share-", dir=destination.parent) as temp:
        output = Path(temp) / "package.zip"
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr("视频链接下载工具/" + name, data)
        with zipfile.ZipFile(output) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(entries)
        output.rename(destination)
    with destination.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    print(f"已生成：{destination}\n大小：{destination.stat().st_size:,} 字节\nSHA256：{digest}")
    return destination


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "分享包" / f"视频链接下载工具-窗口版-{datetime.now():%Y%m%d-%H%M%S}.zip"
    build(output)
