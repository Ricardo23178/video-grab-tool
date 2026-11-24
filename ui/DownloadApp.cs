using System;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace VideoLinkDownloader
{
    public sealed class MainForm : Form
    {
        readonly string root;
        readonly TextBox links = new TextBox();
        readonly TextBox output = new TextBox();
        readonly TextBox log = new TextBox();
        readonly Label status = new Label();
        readonly ActivityLine progress = new ActivityLine();
        readonly Button start = new SoftButton();
        readonly Label stateBadge = new Label();
        bool statusError;
        readonly Control[] idleControls;
        readonly object processLock = new object();
        Process activeProcess;
        Task stopTask = Task.FromResult(0);
        volatile bool cancelled;
        bool busy, closeAfterStop;
        public bool IsBusy { get { return busy; } }

        public MainForm(string projectRoot)
        {
            root = Path.GetFullPath(projectRoot);
            Text = "链接下载助手";
            Font = new Font("Microsoft YaHei UI", 9.5F);
            BackColor = Color.FromArgb(245, 246, 250);
            ForeColor = Color.FromArgb(34, 40, 58);
            AutoScaleDimensions = new SizeF(96, 96);
            AutoScaleMode = AutoScaleMode.Dpi;
            ClientSize = new Size(1000, 690);
            MinimumSize = new Size(940, 680);
            StartPosition = FormStartPosition.CenterScreen;

            var page = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Padding = new Padding(28, 20, 28, 14), Margin = Padding.Empty };
            page.RowStyles.Add(new RowStyle(SizeType.Absolute, 86));
            page.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.RowStyles.Add(new RowStyle(SizeType.Absolute, 56));
            Controls.Add(page);
            var header = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 1, Margin = Padding.Empty };
            header.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 62));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            header.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 164));
            var mark = new RoundedCard { Size = new Size(46, 46), BackColor = Theme.Accent, BorderColor = Theme.Accent, Margin = new Padding(0, 7, 0, 0), Radius = 14 };
            mark.Paint += delegate(object sender, PaintEventArgs e) {
                var saved = e.Graphics.Save();
                e.Graphics.ScaleTransform(mark.Width / 46F, mark.Height / 46F);
                e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                using (var pen = new Pen(Color.White, 2.5F)) {
                    pen.StartCap = pen.EndCap = LineCap.Round;
                    e.Graphics.DrawLine(pen, 23, 12, 23, 29);
                    e.Graphics.DrawLines(pen, new Point[] { new Point(16, 23), new Point(23, 30), new Point(30, 23) });
                    e.Graphics.DrawLines(pen, new Point[] { new Point(13, 32), new Point(13, 36), new Point(33, 36), new Point(33, 32) });
                }
                e.Graphics.Restore(saved);
            };
            header.Controls.Add(mark, 0, 0);
            var heading = new Panel { Dock = DockStyle.Fill, Margin = Padding.Empty };
            heading.Controls.Add(new Label { Text = "链接下载助手", Font = new Font(Font.FontFamily, 23, FontStyle.Bold), AutoSize = true, Location = new Point(0, 0) });
            heading.Controls.Add(new Label { Text = "粘贴链接，轻松保存视频与图文。", ForeColor = Theme.Muted, AutoSize = true, Location = new Point(2, 43) });
            header.Controls.Add(heading, 1, 0);
            var platforms = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft, WrapContents = false, Padding = new Padding(0, 15, 0, 0), Margin = Padding.Empty };
            platforms.Controls.Add(Pill("bilibili", Color.FromArgb(255, 237, 244), Color.FromArgb(204, 65, 116), 76));
            platforms.Controls.Add(Pill("抖音", Color.FromArgb(233, 236, 243), Color.FromArgb(66, 73, 92), 62));
            header.Controls.Add(platforms, 2, 0);
            page.Controls.Add(header, 0, 0);

            var columns = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            columns.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            columns.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 288));
            var main = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Margin = new Padding(0, 0, 18, 0) };
            main.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            main.RowStyles.Add(new RowStyle(SizeType.Absolute, 154));
            var linkCard = Card(new Padding(22), new Padding(0, 0, 0, 16));
            var linkLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Margin = Padding.Empty };
            linkLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 31));
            linkLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            linkLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            linkLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 16));
            linkLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));
            linkLayout.Controls.Add(Title("添加作品链接"), 0, 0);
            linkLayout.Controls.Add(Note("完整分享文字也可以，多条链接可一起粘贴。"), 0, 1);
            var inputBox = new RoundedCard { Dock = DockStyle.Fill, BackColor = Theme.Field, BorderColor = Theme.Border, Padding = new Padding(14), Margin = Padding.Empty, Radius = 12 };
            links.Name = "LinkInput";
            links.Multiline = true;
            links.ScrollBars = ScrollBars.Vertical;
            links.AcceptsReturn = true;
            links.Dock = DockStyle.Fill;
            links.BorderStyle = BorderStyle.None;
            links.BackColor = Theme.Field;
            links.Font = new Font(Font.FontFamily, 10.5F);
            links.Margin = Padding.Empty;
            links.MaxLength = 120000;
            var inputContent = new Panel { Dock = DockStyle.Fill, BackColor = Theme.Field, Margin = Padding.Empty };
            var placeholder = new Label { Text = "在这里粘贴抖音或 B 站链接…\n也可以直接粘贴整段分享文字", ForeColor = Color.FromArgb(150, 157, 176), BackColor = Theme.Field, Dock = DockStyle.Fill, Padding = new Padding(0, 3, 0, 0), Font = links.Font };
            inputContent.Controls.Add(links);
            inputContent.Controls.Add(placeholder);
            placeholder.BringToFront();
            placeholder.Click += delegate { links.Focus(); };
            links.Enter += delegate { inputBox.BorderColor = Theme.Accent; inputBox.Invalidate(); };
            links.Leave += delegate { placeholder.Visible = String.IsNullOrWhiteSpace(links.Text); inputBox.BorderColor = Theme.Border; inputBox.Invalidate(); };
            links.TextChanged += delegate { placeholder.Visible = String.IsNullOrWhiteSpace(links.Text); };
            inputBox.Controls.Add(inputContent);
            linkLayout.Controls.Add(inputBox, 0, 2);

            var paste = MakeButton("粘贴链接", "PasteButton");
            paste.BackColor = Theme.AccentSoft;
            paste.ForeColor = Theme.Accent;
            paste.Click += delegate {
                try {
                    if (!Clipboard.ContainsText()) { SetStatus("剪贴板中没有文字，请先复制作品链接。", true); return; }
                    string text = Clipboard.GetText().Trim();
                    links.AppendText((String.IsNullOrWhiteSpace(links.Text) ? "" : Environment.NewLine) + text);
                    links.Focus();
                } catch (Exception error) { SetStatus("暂时无法读取剪贴板：" + error.Message, true); }
            };
            var clear = MakeButton("清空", "ClearButton");
            clear.Click += delegate { links.Clear(); links.Focus(); };
            start.Name = "StartButton";
            start.Text = "开始下载";
            start.Dock = DockStyle.Fill;
            start.BackColor = Theme.Accent;
            start.ForeColor = Color.White;
            start.Font = new Font(Font.FontFamily, 10.5F, FontStyle.Bold);
            start.Margin = Padding.Empty;
            start.Cursor = Cursors.Hand;
            start.Click += async delegate { if (busy) Stop(); else await RunJob("download"); };
            var actions = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 1, Margin = Padding.Empty };
            actions.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 104));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 76));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 146));
            actions.Controls.Add(paste, 0, 0);
            actions.Controls.Add(clear, 1, 0);
            actions.Controls.Add(start, 3, 0);
            linkLayout.Controls.Add(actions, 0, 4);
            linkCard.Controls.Add(linkLayout);
            main.Controls.Add(linkCard, 0, 0);

            var folderCard = Card(new Padding(22, 16, 22, 12), Padding.Empty);
            var folderLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Margin = Padding.Empty };
            folderLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
            folderLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));
            folderLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            folderLayout.Controls.Add(Title("保存位置"), 0, 0);
            var folderRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            folderRow.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            folderRow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 94));
            var folderField = new RoundedCard { Dock = DockStyle.Fill, BackColor = Theme.Field, BorderColor = Theme.Field, Padding = new Padding(12, 11, 10, 7), Margin = new Padding(0, 0, 10, 0), Radius = 10 };
            output.Name = "OutputInput";
            output.ReadOnly = true;
            output.Text = Path.Combine(root, "下载内容");
            output.Dock = DockStyle.Fill;
            output.BorderStyle = BorderStyle.None;
            output.BackColor = Theme.Field;
            output.ForeColor = Color.FromArgb(83, 91, 113);
            folderField.Controls.Add(output);
            folderRow.Controls.Add(folderField, 0, 0);
            var browse = MakeButton("更改目录", "BrowseButton");
            browse.Dock = DockStyle.Fill;
            browse.Margin = Padding.Empty;
            browse.Click += delegate {
                using (var dialog = new FolderBrowserDialog { Description = "选择保存下载内容的文件夹", SelectedPath = output.Text })
                    if (dialog.ShowDialog(this) == DialogResult.OK) output.Text = dialog.SelectedPath;
            };
            folderRow.Controls.Add(browse, 1, 0);
            folderLayout.Controls.Add(folderRow, 0, 1);
            folderLayout.Controls.Add(Note("按平台与作品自动整理，下载完成后一键查看。"), 0, 2);
            folderCard.Controls.Add(folderLayout);
            main.Controls.Add(folderCard, 0, 1);
            columns.Controls.Add(main, 0, 0);

            var side = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Margin = Padding.Empty };
            side.RowStyles.Add(new RowStyle(SizeType.Absolute, 216));
            side.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            var statusCard = Card(new Padding(20), new Padding(0, 0, 0, 16));
            var statusLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, Margin = Padding.Empty };
            foreach (int height in new int[] { 30, 66, 5, 15, 38 })
                statusLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
            var statusHeading = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, RowCount = 1, Margin = Padding.Empty };
            statusHeading.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            statusHeading.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            statusHeading.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 76));
            statusHeading.Controls.Add(Caption("当前状态"), 0, 0);
            stateBadge.Dock = DockStyle.Fill;
            stateBadge.TextAlign = ContentAlignment.MiddleCenter;
            stateBadge.Font = new Font(Font.FontFamily, 8.5F);
            stateBadge.Margin = new Padding(0, 2, 0, 4);
            statusHeading.Controls.Add(stateBadge, 1, 0);
            statusLayout.Controls.Add(statusHeading, 0, 0);
            status.Name = "StatusLabel";
            status.Dock = DockStyle.Fill;
            status.TextAlign = ContentAlignment.MiddleLeft;
            status.Margin = Padding.Empty;
            statusLayout.Controls.Add(status, 0, 1);
            progress.Dock = DockStyle.Fill;
            progress.Margin = Padding.Empty;
            statusLayout.Controls.Add(progress, 0, 2);
            var open = MakeButton("打开下载目录", "OpenFolderButton");
            open.Dock = DockStyle.Fill;
            open.Margin = Padding.Empty;
            open.Click += delegate {
                try {
                    Directory.CreateDirectory(output.Text);
                    Process.Start(new ProcessStartInfo(output.Text) { UseShellExecute = true });
                } catch (Exception error) { SetStatus("无法打开文件夹：" + error.Message, true); }
            };
            statusLayout.Controls.Add(open, 0, 4);
            statusCard.Controls.Add(statusLayout);
            side.Controls.Add(statusCard, 0, 0);
            var logCard = Card(new Padding(20), Padding.Empty);
            var logLayout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2, Margin = Padding.Empty };
            logLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 28));
            logLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            logLayout.Controls.Add(Caption("处理记录"), 0, 0);
            var logBody = new Panel { Dock = DockStyle.Fill, BackColor = Color.White, Margin = Padding.Empty };
            log.Name = "LogOutput";
            log.Multiline = true;
            log.ReadOnly = true;
            log.ScrollBars = ScrollBars.Vertical;
            log.Dock = DockStyle.Fill;
            log.BackColor = Color.White;
            log.ForeColor = Theme.Muted;
            log.BorderStyle = BorderStyle.None;
            log.Font = new Font(Font.FontFamily, 9);
            var emptyLog = new Label { Text = "下载进度与保存结果\n会显示在这里", Dock = DockStyle.Fill, ForeColor = Color.FromArgb(160, 166, 184), TextAlign = ContentAlignment.MiddleCenter };
            logBody.Controls.Add(log);
            logBody.Controls.Add(emptyLog);
            emptyLog.BringToFront();
            log.TextChanged += delegate { emptyLog.Visible = log.TextLength == 0; };
            logLayout.Controls.Add(logBody, 0, 1);
            logCard.Controls.Add(logLayout);
            side.Controls.Add(logCard, 0, 1);
            columns.Controls.Add(side, 1, 0);
            page.Controls.Add(columns, 0, 1);

            var footer = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 1, Padding = new Padding(2, 10, 0, 0), Margin = Padding.Empty };
            footer.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 82));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 104));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
            footer.Controls.Add(Note("原视频 MP4  ·  图片与正文"), 0, 0);
            footer.Controls.Add(Note("账号"), 1, 0);
            var douyin = MakeButton("登录抖音", "DouyinLoginButton");
            var bilibili = MakeButton("登录 B 站", "BilibiliLoginButton");
            douyin.Click += async delegate { await RunJob("douyin"); };
            bilibili.Click += async delegate { await RunJob("bilibili"); };
            footer.Controls.Add(douyin, 2, 0);
            footer.Controls.Add(bilibili, 3, 0);
            page.Controls.Add(footer, 0, 2);
            idleControls = new Control[] { links, output, paste, clear, browse, douyin, bilibili };
            SetStatus("粘贴作品链接，点击“开始下载”即可保存到电脑。", false);
            FormClosing += delegate(object sender, FormClosingEventArgs e) {
                if (busy) { e.Cancel = true; closeAfterStop = true; Stop(); }
            };
        }

        static RoundedCard Card(Padding padding, Padding margin)
        {
            return new RoundedCard { Dock = DockStyle.Fill, BackColor = Color.White, BorderColor = Theme.Border, Padding = padding, Margin = margin };
        }

        static Label Caption(string text)
        {
            return new Label { Text = text, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true, Margin = Padding.Empty, Font = new Font("Microsoft YaHei UI", 10, FontStyle.Bold) };
        }

        static Label Title(string text)
        {
            var title = Caption(text);
            title.Font = new Font("Microsoft YaHei UI", 12, FontStyle.Bold);
            return title;
        }

        static Label Note(string text)
        {
            return new Label { Text = text, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, AutoEllipsis = true, Margin = Padding.Empty, ForeColor = Theme.Muted, Font = new Font("Microsoft YaHei UI", 9) };
        }

        static Control Pill(string text, Color back, Color fore, int width)
        {
            var pill = new RoundedCard { Size = new Size(width, 30), BackColor = back, BorderColor = back, Radius = 10, Margin = new Padding(8, 0, 0, 0) };
            pill.Controls.Add(new Label { Text = text, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, ForeColor = fore, BackColor = Color.Transparent });
            return pill;
        }

        static Button MakeButton(string text, string name)
        {
            return new SoftButton { Text = text, Name = name, Size = new Size(96, 38), BackColor = Color.White, ForeColor = Theme.Muted, Margin = new Padding(0, 0, 8, 0), Cursor = Cursors.Hand };
        }

        void SetStatus(string text, bool error)
        {
            status.Text = text;
            statusError = error;
            PaintStatus();
        }

        void PaintStatus()
        {
            bool complete = !busy && !statusError && status.Text.Contains("下载完成");
            Color tint = statusError ? Color.FromArgb(192, 65, 65) : complete ? Color.FromArgb(25, 137, 108) : Theme.Accent;
            status.ForeColor = statusError ? tint : Color.FromArgb(79, 88, 110);
            stateBadge.Text = statusError ? "需要处理" : busy ? "处理中" : complete ? "已完成" : status.Text.Contains("已停止") ? "已停止" : "准备就绪";
            stateBadge.ForeColor = tint;
            stateBadge.BackColor = statusError ? Color.FromArgb(255, 237, 237) : complete ? Color.FromArgb(230, 247, 240) : Theme.AccentSoft;
            progress.Tint = tint;
            progress.Complete = complete;
            progress.Invalidate();
        }

        void Post(Action action)
        {
            if (IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke((Action)delegate { if (!IsDisposed) action(); }); } catch (InvalidOperationException) { }
        }

        void AppendLog(string text)
        {
            if (String.IsNullOrWhiteSpace(text)) return;
            Post(delegate {
                if (log.TextLength > 100000) log.Clear();
                log.AppendText(text + Environment.NewLine);
                if (busy && !cancelled && text.Contains("处理链接")) SetStatus(text, false);
            });
        }

        void SetBusy(bool value)
        {
            busy = value;
            foreach (var control in idleControls) control.Enabled = !value;
            start.Enabled = true;
            start.Text = value ? "停止" : "开始下载";
            start.BackColor = value ? Color.FromArgb(253, 232, 235) : Theme.Accent;
            start.ForeColor = value ? Color.FromArgb(186, 55, 76) : Color.White;
            progress.Running = value;
            PaintStatus();
        }

        // 不经过 shell；正确引用 Windows 参数中的引号和尾部反斜杠。
        static string Quote(string value)
        {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char ch in value) {
                if (ch == '\\') { slashes++; continue; }
                result.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
                result.Append(ch);
                slashes = 0;
            }
            return result.Append('\\', slashes * 2).Append('"').ToString();
        }

        int RunPython(string[] arguments, bool loginWindow)
        {
            string portable = Path.Combine(root, ".runtime", "python.exe");
            var all = new string[] { "-B", "-u", Path.Combine(root, "grab.py") }.Concat(arguments);
            var info = new ProcessStartInfo {
                FileName = File.Exists(portable) ? portable : "python",
                Arguments = String.Join(" ", all.Select(Quote)),
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = !loginWindow,
                RedirectStandardOutput = !loginWindow,
                RedirectStandardError = !loginWindow
            };
            string work = Path.Combine(root, ".work");
            info.EnvironmentVariables["TEMP"] = work;
            info.EnvironmentVariables["TMP"] = work;
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            if (!loginWindow) {
                info.StandardOutputEncoding = Encoding.UTF8;
                info.StandardErrorEncoding = Encoding.UTF8;
            }
            using (var process = new Process { StartInfo = info }) {
                if (!loginWindow) {
                    process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { AppendLog(e.Data); };
                    process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { AppendLog(e.Data); };
                }
                lock (processLock) {
                    if (cancelled) return 130;
                    process.Start();
                    activeProcess = process;
                }
                try {
                    if (!loginWindow) { process.BeginOutputReadLine(); process.BeginErrorReadLine(); }
                    process.WaitForExit();
                    return process.ExitCode;
                }
                finally { lock (processLock) { activeProcess = null; } }
            }
        }

        void Stop()
        {
            if (cancelled) return;
            cancelled = true;
            start.Enabled = false;
            SetStatus("正在停止，请稍候…已完成的文件会保留。", false);
            Process stopping;
            lock (processLock) { stopping = activeProcess; }
            stopTask = Task.Run(delegate {
                lock (processLock) {
                    if (stopping == null || activeProcess != stopping || stopping.HasExited) return;
                    // 只终止本窗口启动的下载进程树，不按进程名称关闭浏览器。
                    var kill = new ProcessStartInfo {
                        FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "taskkill.exe"),
                        Arguments = "/PID " + stopping.Id + " /T /F",
                        UseShellExecute = false, CreateNoWindow = true,
                        RedirectStandardOutput = true, RedirectStandardError = true
                    };
                    try {
                        using (var task = Process.Start(kill)) {
                            task.BeginOutputReadLine();
                            task.BeginErrorReadLine();
                            if (!task.WaitForExit(10000)) { task.Kill(); AppendLog("停止请求超时，请等待当前操作结束后重试。"); }
                        }
                    }
                    catch (Exception error) { AppendLog("停止任务时出现问题：" + error.Message); }
                }
            });
        }

        async Task RunJob(string kind)
        {
            if (busy) return;
            string text = links.Text.Trim();
            if (kind == "download" && String.IsNullOrWhiteSpace(text)) {
                SetStatus("请先粘贴抖音或 B 站作品链接。", true);
                links.Focus();
                return;
            }
            string[] urls = Regex.Matches(text, @"https?://[^\s<>""“”]+").Cast<Match>().Select(match => match.Value).ToArray();
            if (kind == "download" && urls.Length == 0) {
                SetStatus("没有找到作品链接，请复制链接或完整分享文字后粘贴。", true);
                links.Focus();
                return;
            }
            string queue = null;
            cancelled = false;
            stopTask = Task.FromResult(0);
            SetBusy(true);
            log.Clear();
            SetStatus("正在准备下载组件，首次运行需要联网，请稍候…", false);
            try {
                Directory.CreateDirectory(Path.Combine(root, ".work"));
                string destination = Path.GetFullPath(output.Text);
                if (kind == "download") {
                    queue = Path.Combine(root, ".work", "ui-queue-" + Guid.NewGuid().ToString("N") + ".txt");
                    File.WriteAllLines(queue, urls, new UTF8Encoding(false));
                }
                string jobFile = queue;
                int code = await Task.Run(delegate {
                    int setup = RunPython(new string[] { "--setup" }, false);
                    if (setup != 0 || cancelled) return setup;
                    Post(delegate { SetStatus(kind == "download" ? "正在下载，请稍候…" : "请在打开的窗口中完成登录。", false); });
                    return kind == "download"
                        ? RunPython(new string[] { "--file", jobFile, "--output", destination }, false)
                        : RunPython(new string[] { "--login", kind }, kind == "bilibili");
                });
                if (cancelled) SetStatus("已停止。已完成的文件保留，可以重新下载未完成的链接。", false);
                else if (code != 0) SetStatus("操作失败或部分链接失败，请查看下方处理记录后重试。", true);
                else if (kind == "download") SetStatus("下载完成，点击“打开下载目录”查看文件。", false);
                else SetStatus(kind == "douyin" ? "请完成登录并关闭整个专用浏览器窗口，再开始下载。" : "登录窗口已结束，可以尝试下载。", false);
            }
            catch (Exception error) { SetStatus("无法完成操作：" + error.Message, true); AppendLog(error.Message); }
            try { await stopTask; }
            catch (Exception error) { SetStatus("停止操作未完成：" + error.Message, true); AppendLog(error.Message); }
            finally {
                if (queue != null) {
                    try { File.Delete(queue); } catch (IOException) { }
                }
                SetBusy(false);
                if (closeAfterStop) Close();
            }
        }
    }

    static class Theme
    {
        public static readonly Color Accent = Color.FromArgb(91, 82, 224);
        public static readonly Color AccentSoft = Color.FromArgb(239, 237, 255);
        public static readonly Color Muted = Color.FromArgb(112, 121, 143);
        public static readonly Color Border = Color.FromArgb(231, 234, 242);
        public static readonly Color Field = Color.FromArgb(247, 248, 252);

        public static GraphicsPath Rounded(RectangleF rectangle, float radius)
        {
            var path = new GraphicsPath();
            float diameter = Math.Min(radius * 2, Math.Min(rectangle.Width, rectangle.Height));
            path.AddArc(rectangle.Left, rectangle.Top, diameter, diameter, 180, 90);
            path.AddArc(rectangle.Right - diameter, rectangle.Top, diameter, diameter, 270, 90);
            path.AddArc(rectangle.Right - diameter, rectangle.Bottom - diameter, diameter, diameter, 0, 90);
            path.AddArc(rectangle.Left, rectangle.Bottom - diameter, diameter, diameter, 90, 90);
            path.CloseFigure();
            return path;
        }
    }

    sealed class RoundedCard : Panel
    {
        public Color BorderColor = Theme.Border;
        public int Radius = 16;

        public RoundedCard()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        }

        protected override void OnPaintBackground(PaintEventArgs e)
        {
            using (var background = new SolidBrush(Parent == null ? SystemColors.Control : Parent.BackColor))
                e.Graphics.FillRectangle(background, ClientRectangle);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (Width < 2 || Height < 2) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Theme.Rounded(new RectangleF(0.5F, 0.5F, Width - 1, Height - 1), Radius))
            using (var brush = new SolidBrush(BackColor))
            using (var pen = new Pen(BorderColor)) {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
            base.OnPaint(e);
        }
    }

    sealed class SoftButton : Button
    {
        bool hover, pressed;

        public SoftButton()
        {
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            UseVisualStyleBackColor = false;
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        }

        protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
        protected override void OnMouseLeave(EventArgs e) { hover = pressed = false; Invalidate(); base.OnMouseLeave(e); }
        protected override void OnMouseDown(MouseEventArgs e) { pressed = true; Invalidate(); base.OnMouseDown(e); }
        protected override void OnMouseUp(MouseEventArgs e) { pressed = false; Invalidate(); base.OnMouseUp(e); }
        protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            using (var background = new SolidBrush(Parent == null ? SystemColors.Control : Parent.BackColor))
                e.Graphics.FillRectangle(background, ClientRectangle);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (Width < 2 || Height < 2) return;
            Color fill = !Enabled ? Theme.Field : pressed ? ControlPaint.Dark(BackColor, 0.08F) : hover ? (BackColor == Color.White ? Theme.Field : ControlPaint.Light(BackColor, 0.08F)) : BackColor;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var path = Theme.Rounded(new RectangleF(0.5F, 0.5F, Width - 1, Height - 1), 10))
            using (var brush = new SolidBrush(fill))
            using (var pen = new Pen(BackColor == Color.White ? Theme.Border : fill)) {
                e.Graphics.FillPath(brush, path);
                e.Graphics.DrawPath(pen, path);
            }
            TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle, Enabled ? ForeColor : Color.FromArgb(164, 170, 185), TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.SingleLine);
            if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(ClientRectangle, -6, -6), ForeColor, fill);
        }
    }

    sealed class ActivityLine : Control
    {
        readonly Timer animation = new Timer { Interval = 30 };
        float position;
        public Color Tint = Theme.Accent;
        public bool Complete;
        public bool Running { set { animation.Enabled = value; position = 0; Invalidate(); } }

        public ActivityLine()
        {
            SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
            animation.Tick += delegate { position = (position + 0.018F) % 1.3F; Invalidate(); };
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            if (Width < 2 || Height < 2) return;
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (var background = new SolidBrush(Parent == null ? Color.White : Parent.BackColor))
                e.Graphics.FillRectangle(background, ClientRectangle);
            using (var track = Theme.Rounded(new RectangleF(0, 0, Width, Height), 3))
            using (var brush = new SolidBrush(Theme.Border)) e.Graphics.FillPath(brush, track);
            float segment = Width * 0.28F;
            float left = Math.Max(0, Width * position - segment);
            float right = Math.Min(Width, Width * position);
            if (Complete || (animation.Enabled && right > left)) {
                using (var bar = Theme.Rounded(new RectangleF(Complete ? 0 : left, 0, Complete ? Width : right - left, Height), 3))
                using (var brush = new SolidBrush(Tint)) e.Graphics.FillPath(brush, bar);
            }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) animation.Dispose();
            base.Dispose(disposing);
        }
    }

    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm(AppDomain.CurrentDomain.BaseDirectory));
        }
    }
}
