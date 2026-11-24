"""实际驱动 Windows 窗口，检查后台任务、失败与停止；不访问平台或账号。"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import package_share

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows 桌面窗口")
class WindowTests(unittest.TestCase):
    def test_window_download_failure_and_process_tree_cancellation(self):
        self.assertTrue((ROOT / "ui" / "DownloadApp.cs").is_file(), "图形界面尚未实现")
        (ROOT / "tests" / ".temp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="窗口 & 验收-", dir=ROOT / "tests" / ".temp") as name:
            folder = Path(name)
            app = package_share.build_ui(folder / "视频下载工具.exe")
            (folder / "grab.py").write_text('''import argparse, json, pathlib, subprocess, sys, time
p = argparse.ArgumentParser()
p.add_argument('--setup', action='store_true')
p.add_argument('--file', type=pathlib.Path)
p.add_argument('--output')
a = p.parse_args()
root = pathlib.Path(__file__).parent
if a.setup:
    print('组件准备完成', flush=True)
    sys.exit(0)
lines = a.file.read_text(encoding='utf-8-sig').splitlines()
if lines == ['https://v.douyin.com/fail/']:
    print('失败：测试作品不可访问', flush=True)
    sys.exit(1)
if lines == ['https://v.douyin.com/slow/']:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    (root / 'child.pid').write_text(str(child.pid))
    print('正在处理测试任务', flush=True)
    time.sleep(60)
    sys.exit(0)
(root / 'result.json').write_text(json.dumps({'lines': lines, 'output': a.output}, ensure_ascii=False), encoding='utf-8')
print('已保存：中文测试任务', flush=True)
''', encoding="utf-8")
            compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
            runner = folder / "ui-smoke.exe"
            env = dict(os.environ, TEMP=name, TMP=name, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            command = [str(compiler), "/nologo", "/target:exe", "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:" + str(app), "/out:" + str(runner), str(ROOT / "tests" / "ui_smoke.cs")]
            result = subprocess.run(command, env=env, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
            result = subprocess.run([str(runner), name], env=env, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8", errors="replace"))
            record = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(record["lines"], ['https://www.douyin.com/video/123?x=1&y=2', 'https://b23.tv/demo/'])
            self.assertEqual(record["output"], str(folder / "下载 目录&一"))
            self.assertFalse(list((folder / ".work").glob("ui-queue-*.txt")))
