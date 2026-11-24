using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;
using VideoLinkDownloader;

class WindowSmoke
{
    static MainForm current;
    static void Assert(bool condition, string message)
    {
        if (!condition) throw new Exception(message);
    }

    static T ControlOf<T>(Form form, string name) where T : Control
    {
        return (T)form.Controls.Find(name, true)[0];
    }

    static void Until(Func<bool> condition, string message)
    {
        var timer = Stopwatch.StartNew();
        while (!condition() && timer.ElapsedMilliseconds < 15000)
        {
            Application.DoEvents();
            Thread.Sleep(25);
        }
        if (!condition() && current != null && !current.IsDisposed) {
            Console.Error.WriteLine("Status: " + ControlOf<Label>(current, "StatusLabel").Text);
            Console.Error.WriteLine("Busy: " + current.IsBusy + " Start enabled: " + ControlOf<Button>(current, "StartButton").Enabled);
            Console.Error.WriteLine(ControlOf<TextBox>(current, "LogOutput").Text);
        }
        Assert(condition(), message);
        Application.DoEvents();
    }

    static bool ChildAlive(string root)
    {
        try { return !Process.GetProcessById(Int32.Parse(File.ReadAllText(Path.Combine(root, "child.pid")))).HasExited; }
        catch (ArgumentException) { return false; }
    }

    [STAThread]
    static int Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        try
        {
            Application.EnableVisualStyles();
            Control.CheckForIllegalCrossThreadCalls = true;
            int result = 1;
            using (var form = new MainForm(args[0]))
            {
                current = form;
                form.Shown += delegate {
                    form.BeginInvoke((Action)delegate {
                        try {
                Assert(SynchronizationContext.Current is WindowsFormsSynchronizationContext, "UI test must run inside the actual message loop");
                var input = ControlOf<TextBox>(form, "LinkInput");
                var output = ControlOf<TextBox>(form, "OutputInput");
                var start = ControlOf<Button>(form, "StartButton");
                var status = ControlOf<Label>(form, "StatusLabel");
                start.PerformClick();
                Assert(!form.IsBusy && status.Text.Contains("粘贴"), "Empty input must give a helpful message before installation");
                input.Text = "分享文字含换行\r\nhttps://www.douyin.com/video/123?x=1&y=2\r\n另一条分享 https://b23.tv/demo/";
                output.Text = Path.Combine(args[0], "下载 目录&一");
                start.PerformClick();
                Assert(form.IsBusy && !input.Enabled, "The UI must prevent concurrent jobs");
                Until(() => !form.IsBusy, "Download never completed");
                Assert(status.Text.Contains("完成"), "Success must be shown in the window");
                Assert(ControlOf<TextBox>(form, "LogOutput").Text.Contains("中文测试任务"), "UTF-8 output must remain readable");
                input.Text = "https://v.douyin.com/fail/";
                start.PerformClick();
                Until(() => !form.IsBusy, "Failure never completed");
                Assert(status.Text.Contains("失败"), "Backend errors must not be reported as success");
                input.Text = "https://v.douyin.com/slow/";
                start.PerformClick();
                Until(() => File.Exists(Path.Combine(args[0], "child.pid")), "Slow worker not started");
                start.PerformClick();
                Until(() => !form.IsBusy, "Stop did not finish");
                Assert(!ChildAlive(args[0]), "Stop left an owned child process behind");
                Assert(status.Text.Contains("停止"), "Cancellation must be distinct from success");
                File.Delete(Path.Combine(args[0], "child.pid"));
                start.Select();
                Application.DoEvents();
                Console.WriteLine("Retry: input=" + input.Text + "; visible=" + start.Visible + "; canSelect=" + start.CanSelect + "; formVisible=" + form.Visible);
                start.PerformClick();
                Assert(form.IsBusy, "A stopped job must allow another click; status=" + status.Text);
                Until(() => File.Exists(Path.Combine(args[0], "child.pid")), "Second slow worker not started");
                form.Close();
                Until(() => form.IsDisposed, "Closing a busy window did not finish");
                Assert(!ChildAlive(args[0]), "Closing left an owned child process behind");
                result = 0;
                        }
                        catch (Exception error) { Console.Error.WriteLine(error); }
                        finally { if (!form.IsDisposed) form.Close(); }
                    });
                };
                // 保留真正的消息循环，让 await 续体与产品一样返回 UI 线程。
                Application.Run(form);
            }
            if (result == 0) Console.WriteLine("UI: blank input, Unicode batch, failure, stop and closing passed");
            return result;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }
}
