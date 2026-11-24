import contextlib
import hashlib
import http.server
import importlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
try:
    grab = importlib.import_module("grab")
except ModuleNotFoundError:
    grab = None


class GrabTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(grab, "下载项目入口尚未实现")
        (ROOT / "tests" / ".temp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tests" / ".temp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_setup_installs_missing_tools_and_reuses_them(self):
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("imageio_ffmpeg/binaries/ffmpeg-test.exe", b"test ffmpeg")
        wheel_data = wheel.getvalue()
        metadata = {"urls": [{"filename": "test-win_amd64.whl", "url": "https://files.pythonhosted.org/test.whl", "digests": {"sha256": hashlib.sha256(wheel_data).hexdigest()}}]}
        original_sha256 = hashlib.sha256

        def downloaded(url, output):
            Path(output).write_bytes(b"test bbdown" if url.endswith(".exe") else wheel_data)

        def digest(data):
            if data == b"test bbdown":
                # 此测试验证首次安装及复用流程，不依赖在线下载正式的可执行文件。
                return mock.Mock(hexdigest=lambda: "d9e75a7196ba28a77a7bcbca7408748e8efe42a52a81e5890bde5bbf7d952890")
            return original_sha256(data)

        with mock.patch.multiple(grab, ROOT=self.root, TOOLS=self.root / ".tools", WORK=self.root / ".work"):
            with mock.patch.object(grab, "find_browser"), mock.patch.object(grab.shutil, "which", return_value=None):
                with mock.patch.object(grab, "urlopen", side_effect=lambda *a, **k: io.BytesIO(json.dumps(metadata).encode())) as request:
                    with mock.patch.object(grab, "download_url", side_effect=downloaded) as download, mock.patch.object(grab.hashlib, "sha256", side_effect=digest):
                        def interrupted(source, target):
                            target.write(b"partial")
                            raise OSError("模拟组件解压中断")
                        with mock.patch.object(grab.shutil, "copyfileobj", side_effect=interrupted):
                            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):
                                grab.setup_tools()
                        self.assertFalse((grab.TOOLS / "ffmpeg.exe").exists(), "解压中断不能留下可被误用的最终组件")
                        download.reset_mock()
                        request.reset_mock()
                        with contextlib.redirect_stdout(io.StringIO()):
                            grab.setup_tools()
                        self.assertEqual(grab.find_tool("ffmpeg").read_bytes(), b"test ffmpeg")
                        self.assertEqual(grab.find_tool("bbdown").read_bytes(), b"test bbdown")
                        self.assertEqual(download.call_count, 2)
                        request.reset_mock()
                        download.reset_mock()
                        with contextlib.redirect_stdout(io.StringIO()):
                            grab.setup_tools()
                        request.assert_not_called()
                        download.assert_not_called()

    def test_share_text_and_short_url(self):
        text = "复制打开抖音，看看作品 https://v.douyin.com/8_UurbIXX4g/ s@r.rR 08/24"
        self.assertEqual(grab.extract_url(text), "https://v.douyin.com/8_UurbIXX4g/")

    def test_reject_deceptive_domain_and_multiple_links(self):
        for text in ["https://douyin.com.example.org/video/12", "file:///D:/secret", "https://127.0.0.1/", "https://www.douyin.com/video/12 https://b23.tv/abc"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                grab.extract_url(text)

    def test_identify_video_note_and_bilibili_page(self):
        a = grab.identify("https://www.douyin.com/video/7696806671321959723?foo=bar")
        self.assertEqual((a.platform, a.key, a.kind), ("douyin", "7696806671321959723", "video"))
        self.assertEqual(grab.identify("https://www.douyin.com/note/12345678").kind, "note")
        b = grab.identify("https://www.bilibili.com/video/BV16h4y137YS/?p=2&foo=1")
        self.assertEqual((b.platform, b.key, b.page), ("bilibili", "BV16h4y137YS_p2", 2))

    def test_media_uses_primary_video_and_audio_not_recommendations(self):
        video = "https://v26-web.douyinvod.com/a/video/tos/first/media-video-avc1/?x=1"
        audio = "https://v26-web.douyinvod.com/b/video/tos/first/media-audio-und-mp4a/?x=1"
        log = {"events": [{"params": {"url": u}} for u in ["https://example.org/fake.mp4", video, video, audio, "https://v3.douyinvod.com/c/video/tos/recommendation/media-video-avc1/"]]}
        self.assertEqual(grab.network_media(log), (video, audio))
        with self.assertRaises(ValueError):
            grab.network_media({"events": []})

    def test_audio_requested_before_video_is_preserved(self):
        video = "https://v3.douyinvod.com/a/video/tos/first/media-video-avc1/?q=1"
        audio = "https://v3.douyinvod.com/b/video/tos/first/media-audio-und-mp4a/?q=1"
        log = {"events": [{"params": {"url": u}} for u in [audio, video, video + "&range=1"]]}
        self.assertEqual(grab.network_media(log), (video, audio))

    def test_result_staging_is_on_output_volume_and_existing_output_is_untouched(self):
        target = grab.identify("https://www.douyin.com/video/123456789")
        output = self.root / "中文 输出"

        def download(item, stage, work):
            self.assertEqual(stage.parent.parent, output / "抖音")
            (stage / "原视频.mp4").write_bytes(b"a verified fixture")
            return {"title": "测试作品", "body": "原文"}

        with mock.patch.object(grab, "resolve_url", return_value=target), mock.patch.object(grab, "download_douyin", side_effect=download):
            state, folder = grab.archive(target.url, output)
            self.assertEqual(state, "saved")
            state, _ = grab.archive(target.url, output)
            self.assertEqual(state, "skipped")
            (folder / "原视频.mp4").write_bytes(b"user changed this file")
            with self.assertRaises(FileExistsError):
                grab.archive(target.url, output)
            self.assertEqual((folder / "原视频.mp4").read_bytes(), b"user changed this file")

    def test_note_does_not_claim_success_when_gallery_images_are_missing(self):
        target = grab.identify("https://www.douyin.com/note/123456789")
        stage = self.root / "stage"
        stage.mkdir()
        with mock.patch.object(grab, "render_page", return_value=('<div data-e2e="note-content">图集文案</div>', {})):
            with self.assertRaises(ValueError):
                grab.download_douyin(target, stage, self.root)

    def test_missing_separate_audio_cannot_produce_silent_success(self):
        target = grab.identify("https://www.douyin.com/video/123456789")
        network = {"events": [{"params": {"url": "https://v3.douyinvod.com/a/video/tos/first/media-video-avc1/"}}]}
        with mock.patch.object(grab, "render_page", return_value=("<title>视频</title>", network)), mock.patch.object(grab, "download_url") as downloader:
            with self.assertRaises(ValueError):
                grab.download_douyin(target, self.root, self.root)
        downloader.assert_not_called()

    def test_real_note_slider_scope_and_split_publication_time(self):
        source = '''<title>图集标题 - 抖音</title><meta name="description" content="图集原文 - 作者于20260313发布在抖音，已经收获了8个喜欢">
        <main data-e2e="note-detail"><div data-e2e="player-container"><div class="hash dySwiperSlide selected"><img src="https://p3.douyinpic.com/tos-cn-i-0813c001/one.webp"><img src="https://p3.douyinpic.com/tos-cn-i-0813c001/one.webp"></div></div>
        <span>发布时间：</span><span>2026-03-13 00:00:19</span></main>'''
        info = grab.page_info(source)
        self.assertEqual(info["images"], ["https://p3.douyinpic.com/tos-cn-i-0813c001/one.webp"])
        self.assertEqual(info["published_at"], "2026-03-13 00:00:19")
        self.assertEqual(info["body"], "图集原文")

    def test_recommendation_photo_marker_is_not_an_original_image(self):
        source = '<div data-e2e="related-video"><div data-e2e="photo-image"><img src="https://p3.douyinpic.com/recommendation.jpg"></div></div>'
        self.assertEqual(grab.page_info(source)["images"], [])

    def test_page_information_excludes_comments_and_recommendation_images(self):
        source = '''<html><head><title>作品标题 - 抖音</title><meta name="description" content="原始文案"></head><body>
        <div data-e2e="feed-active-video"><div data-e2e="detail-video-info"><p>正文内容</p><span data-e2e="detail-video-publish-time">发布时间：2026-10-15 17:01</span></div>
        <div data-e2e="photo-image"><img src="https://p3.douyinpic.com/tos-cn-i-0813c001/photo.jpg"></div></div>
        <div data-e2e="comment-item">他人的评论<img src="https://p3.douyinpic.com/other.jpg"></div></body></html>'''
        info = grab.page_info(source)
        self.assertEqual(info["title"], "作品标题")
        self.assertIn("2026-10-15 17:01", info["published_at"])
        self.assertNotIn("他人的评论", info["body"])
        self.assertEqual(info["images"], ["https://p3.douyinpic.com/tos-cn-i-0813c001/photo.jpg"])

    def test_complete_record_requires_unchanged_files_and_contained_paths(self):
        folder = self.root / "中文 路径"
        folder.mkdir()
        p = folder / "原视频.mp4"
        p.write_bytes(b"original bytes")
        record = {"complete": True, "files": [{"name": p.name, "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}]}
        (folder / "信息.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertTrue(grab.is_complete(folder))
        p.write_bytes(b"modified bytes")
        self.assertFalse(grab.is_complete(folder))
        record["files"][0]["name"] = "../outside.mp4"
        (folder / "信息.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(grab.is_complete(folder))
        for invalid_record in ([], None, "unexpected", 42):
            (folder / "信息.json").write_text(json.dumps(invalid_record), encoding="utf-8")
            self.assertFalse(grab.is_complete(folder))

    def test_download_rejects_html_and_never_overwrites(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                data = b"<html>login</html>" if self.path == "/html" else b"\x00\x00\x00\x18ftypisom" + b"X" * 100
                self.send_response(200)
                self.send_header("Content-Type", "text/html" if self.path == "/html" else "video/mp4")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:" + str(server.server_port)
        output = self.root / "原视频.mp4"
        grab.download_url(base + "/ok", output)
        before = output.read_bytes()
        with self.assertRaises(FileExistsError):
            grab.download_url(base + "/ok", output)
        self.assertEqual(output.read_bytes(), before)
        with self.assertRaises(ValueError):
            grab.download_url(base + "/html", self.root / "bad.mp4")

    def test_batch_continues_and_reports_failure_exit_code(self):
        links = self.root / "链接.txt"
        links.write_text("https://v.douyin.com/ok/\n\nhttps://v.douyin.com/fail/\nhttps://v.douyin.com/ok2/\n", encoding="utf-8-sig")
        with mock.patch.object(grab, "archive", side_effect=[("saved", self.root), ValueError("作品不可访问"), ("skipped", self.root)]) as worker:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = grab.main(["--file", str(links), "--output", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual(worker.call_count, 3)
        self.assertIn("成功 1", output.getvalue())
        self.assertIn("失败 1", output.getvalue())
        self.assertIn("跳过 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
