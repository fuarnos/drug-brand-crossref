"""手机通道：队列库 + agent CLI + 服务端端点测试。

每个用例都把 MOBILE_INBOX 指到 tempfile 临时目录，**绝不写真实 inbox/**。

运行（仓库根目录）：

    & $py -m unittest tests.test_mobile_inbox -v

覆盖：
    - 追加指令 → load_state 出现且 status=pending；
    - 回帖推导状态（最后一条为准）、doing 中间态；
    - 并发：8 线程 × 10 条、8 进程 × 10 条，正好 80 行、全部可解析、id 不重复；
    - 坏行跳过并告警，其余条目照常返回；
    - 校验：空文本 / 超 2000 字 / 非法 status / 不存在的 cmd_id；
    - CLI 子进程冒烟：pending / list / done / blocked / 错误码；
    - 端点（mobile/server.py 就绪后自动启用）：401 / 302+cookie / 200 / 201 / 429。
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import http.client
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mobile import inbox as inbox_cli  # noqa: E402
from mobile import queue  # noqa: E402

PY = sys.executable
INBOX_SCRIPT = ROOT / "mobile" / "inbox.py"
TOKEN = "test-token-0123456789"

# 工位 A 并行写 mobile/server.py：此刻还没有就跳过端点测试，别让整份测试红。
try:  # pragma: no cover - 取决于别的工位
    from mobile.server import make_server as _make_server
except Exception as _exc:  # noqa: BLE001
    _make_server = None
    _SERVER_IMPORT_ERROR = _exc
else:
    _SERVER_IMPORT_ERROR = ""


def _child_env(inbox: Path) -> dict[str, str]:
    """给子进程用的环境：临时队列目录 + 强制 UTF-8 输出。"""
    env = dict(os.environ)
    env["MOBILE_INBOX"] = str(inbox)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(ROOT)
    return env


class TempInboxDir:
    """一次性临时目录（name 为路径，cleanup() 删除）。

    没有直接用 tempfile.TemporaryDirectory()：它用 mode=0o700 建根目录，而本机
    DSH Windows 沙箱会把这类目录变成「连自己都写不进」（WinError 5，事后也删不掉）。
    改用 tempfile 的基准目录 + 默认模式建目录，隔离效果相同，还能干净删掉。
    """

    def __init__(self) -> None:
        base = Path(tempfile.gettempdir())
        for _ in range(50):
            candidate = base / f"mobile-inbox-test-{os.getpid()}-{secrets.token_hex(4)}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            self.name = str(candidate)
            return
        raise RuntimeError(f"临时目录建不出来：{base}")

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)


class InboxTestCase(unittest.TestCase):
    """基类：每个用例一个临时 inbox 目录。"""

    def setUp(self) -> None:
        self._tmpdir = TempInboxDir()
        self.addCleanup(self._tmpdir.cleanup)
        self.inbox = Path(self._tmpdir.name) / "inbox"
        patcher = mock.patch.dict(os.environ, {"MOBILE_INBOX": str(self.inbox)})
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- 小工具 ---------------------------------------------------------
    def _lines(self, name: str = "commands.jsonl") -> list[str]:
        path = self.inbox / name
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _ids(self, name: str = "commands.jsonl") -> list[str]:
        return [json.loads(line)["id"] for line in self._lines(name)]

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PY, str(INBOX_SCRIPT), *args],
            cwd=str(ROOT),
            env=_child_env(self.inbox),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )


class QueueTest(InboxTestCase):
    """queue.py：追加、状态推导、坏行、校验。"""

    def test_uses_temp_inbox(self) -> None:
        self.assertEqual(queue.inbox_dir(), self.inbox)
        self.assertNotEqual(queue.inbox_dir(), ROOT / "inbox")

    def test_append_command_is_pending(self) -> None:
        rec = queue.append_command("把墨西哥浓度复核补完", ua="iPhone Safari")
        self.assertRegex(rec["id"], r"^c-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
        self.assertEqual(rec["source"], "phone")

        state = queue.load_state()
        self.assertEqual(state["counts"], {"total": 1, "pending": 1, "doing": 0, "done": 0, "blocked": 0})
        cmd = state["commands"][0]
        self.assertEqual(cmd["id"], rec["id"])
        self.assertEqual(cmd["status"], "pending")
        self.assertEqual(cmd["text"], "把墨西哥浓度复核补完")
        self.assertEqual(cmd["ua"], "iPhone Safari")
        self.assertEqual(cmd["replies"], [])

        lines = self._lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["id"], rec["id"])
        self.assertFalse((self.inbox / ".lock").exists(), "正常写完后不应留锁文件")

    def test_text_stripped(self) -> None:
        rec = queue.append_command("  前后有空白  \n")
        self.assertEqual(rec["text"], "前后有空白")

    def test_reply_last_status_wins(self) -> None:
        cmd = queue.append_command("任务 A")
        queue.append_reply(cmd["id"], "doing", "开始处理")
        self.assertEqual(queue.load_state()["commands"][0]["status"], "doing")
        queue.append_reply(cmd["id"], "done", "已改完，见 reports/x.md")

        state = queue.load_state()
        got = state["commands"][0]
        self.assertEqual(got["status"], "done")
        self.assertEqual([r["status"] for r in got["replies"]], ["doing", "done"])
        self.assertEqual(got["replies"][-1]["text"], "已改完，见 reports/x.md")
        self.assertEqual(state["counts"], {"total": 1, "pending": 0, "doing": 0, "done": 1, "blocked": 0})

        replies = self._lines("replies.jsonl")
        self.assertEqual(len(replies), 2)
        self.assertRegex(json.loads(replies[0])["id"], r"^r-\d{8}-\d{6}-[0-9a-f]{4}$")
        self.assertEqual(json.loads(replies[0])["cmd"], cmd["id"])

    def test_ids_unique_in_same_second(self) -> None:
        ids = [queue.append_command(f"同秒任务 {i}")["id"] for i in range(50)]
        self.assertEqual(len(set(ids)), 50)

    def test_commands_sorted_by_ts(self) -> None:
        # 手工写三条乱序记录：同一天不同时区，按真实时间升序排出 c-early/c-mid/c-late。
        records = [
            {"id": "c-mid", "ts": "2026-10-26T20:00:00+08:00", "text": "中", "source": "phone", "ua": ""},
            {"id": "c-late", "ts": "2026-10-26T18:00:00-07:00", "text": "晚", "source": "phone", "ua": ""},
            {"id": "c-early", "ts": "2026-10-26T01:00:00-07:00", "text": "早", "source": "phone", "ua": ""},
        ]
        self.inbox.mkdir(parents=True, exist_ok=True)
        with (self.inbox / "commands.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        got = [c["id"] for c in queue.load_state()["commands"]]
        self.assertEqual(got, ["c-early", "c-mid", "c-late"])

    def test_bad_line_skipped(self) -> None:
        keep = queue.append_command("好行")
        path = self.inbox / "commands.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write('{"id":"c-half","ts":"2026-10-26T19:00:00-07:00","text":"半行没关上"\n')
            fh.write("{坏\n")
            fh.write("[1, 2]\n")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            state = queue.load_state()
        self.assertEqual([c["id"] for c in state["commands"]], [keep["id"]])
        self.assertEqual(state["counts"]["total"], 1)
        warnings = [ln for ln in err.getvalue().splitlines() if ln.startswith("警告：")]
        self.assertEqual(len(warnings), 3, err.getvalue())
        for line in warnings:
            self.assertIn("commands.jsonl", line)

    def test_bad_reply_line_skipped(self) -> None:
        cmd = queue.append_command("有坏回帖的指令")
        with (self.inbox / "replies.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
            fh.write('{"id":"r-x","cmd":"%s","ts":"2026-10-26T20:00:00-07:00",'
                     '"status":"finished","text":"非法状态","source":"agent"}\n' % cmd["id"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            state = queue.load_state()
        self.assertEqual(state["commands"][0]["status"], "pending")
        self.assertIn("警告", err.getvalue())

    def test_validation(self) -> None:
        with self.assertRaises(ValueError):
            queue.append_command("")
        with self.assertRaises(ValueError):
            queue.append_command("  \n\t ")
        with self.assertRaises(ValueError):
            queue.append_command("字" * (queue.MAX_TEXT + 1))
        with self.assertRaises(ValueError):
            queue.append_command(None)  # type: ignore[arg-type]

        edge = queue.append_command("字" * queue.MAX_TEXT)  # 边界：正好 2000 字可以
        self.assertEqual(len(edge["text"]), queue.MAX_TEXT)

        with self.assertRaises(ValueError):
            queue.append_reply(edge["id"], "finished", "非法状态")
        with self.assertRaises(ValueError):
            queue.append_reply(edge["id"], "done", "")
        with self.assertRaises(ValueError):
            queue.append_reply("c-19700101-000000-0000", "done", "指令不存在")

        self.assertEqual(len(self._lines()), 1, "校验失败不能落行")
        self.assertEqual(self._lines("replies.jsonl"), [])

    def test_load_state_without_files(self) -> None:
        state = queue.load_state()
        self.assertEqual(state["commands"], [])
        self.assertEqual(state["counts"], {"total": 0, "pending": 0, "doing": 0, "done": 0, "blocked": 0})
        self.assertFalse(self.inbox.exists(), "只读 load_state 不应创建目录")

    def test_lock_timeout(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        lock = self.inbox / ".lock"
        lock.write_text("别人持有", encoding="utf-8")
        self.addCleanup(lambda: lock.unlink(missing_ok=True))
        with mock.patch.object(queue, "LOCK_TIMEOUT", 0.2):
            with self.assertRaises(TimeoutError):
                queue.append_command("等不到的锁")
        lock.unlink()
        rec = queue.append_command("锁放开后能写")
        self.assertEqual(rec["text"], "锁放开后能写")

    def test_stale_lock_reclaimed(self) -> None:
        self.inbox.mkdir(parents=True, exist_ok=True)
        lock = self.inbox / ".lock"
        lock.write_text("死进程留下的锁", encoding="utf-8")
        long_ago = time.time() - 120
        os.utime(lock, (long_ago, long_ago))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rec = queue.append_command("死锁也能写")
        self.assertEqual(rec["text"], "死锁也能写")
        self.assertIn("超时锁", err.getvalue())
        self.assertFalse(lock.exists())


class ConcurrencyTest(InboxTestCase):
    """并发追加：多线程 + 多进程都不能丢行、不能出现半行 JSON。"""

    PER_WORKER = 10
    WORKERS = 8

    def _assert_all_appended(self, prefix: str) -> None:
        lines = self._lines()
        self.assertEqual(len(lines), self.WORKERS * self.PER_WORKER)
        records = [json.loads(line) for line in lines]  # 有任何半行 JSON 这里就会炸
        self.assertEqual(len({rec["id"] for rec in records}), len(records))
        self.assertTrue(all(rec["text"].startswith(prefix) for rec in records))
        state = queue.load_state()
        self.assertEqual(state["counts"]["total"], len(records))
        self.assertEqual(state["counts"]["pending"], len(records))
        self.assertFalse((self.inbox / ".lock").exists(), "并发结束后不应留锁文件")

    def test_concurrent_threads(self) -> None:
        def worker(n: int) -> None:
            for i in range(self.PER_WORKER):
                queue.append_command(f"线程{n}-{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.WORKERS) as pool:
            list(pool.map(worker, range(self.WORKERS)))
        self._assert_all_appended("线程")

    def test_concurrent_processes(self) -> None:
        code = (
            "import sys\n"
            "from mobile import queue\n"
            "n = int(sys.argv[1])\n"
            "for i in range(10):\n"
            "    queue.append_command('进程' + str(n) + '-' + str(i))\n"
        )
        env = _child_env(self.inbox)
        procs = [
            subprocess.Popen(
                [PY, "-c", code, str(n)],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            for n in range(self.WORKERS)
        ]
        for proc in procs:
            out, err = proc.communicate(timeout=180)
            self.assertEqual(proc.returncode, 0, f"子进程失败：{err or out}")
        self._assert_all_appended("进程")


class CliTest(InboxTestCase):
    """inbox.py 子进程冒烟：中文输出、状态徽章、宽度、退出码。"""

    def _check_width(self, text: str) -> None:
        for line in text.splitlines():
            self.assertLessEqual(inbox_cli._width(line), inbox_cli.WIDTH, f"超宽：{line!r}")

    def test_pending_empty(self) -> None:
        result = self._run_cli("pending")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("没有待办指令", result.stdout)

    def test_default_action_is_pending(self) -> None:
        queue.append_command("默认动作的任务")
        result = self._run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("默认动作的任务", result.stdout)

    def test_pending_shows_badge_and_id(self) -> None:
        cmd = queue.append_command("把墨西哥浓度复核补完")
        result = self._run_cli("pending")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[待办]", result.stdout)
        self.assertIn(cmd["id"], result.stdout)
        self.assertIn("把墨西哥浓度复核补完", result.stdout)
        self.assertIn("待办 1 条", result.stdout)
        self._check_width(result.stdout)

    def test_done_then_pending_empty_and_list(self) -> None:
        cmd = queue.append_command("把墨西哥浓度复核补完")
        result = self._run_cli("done", cmd["id"], "已重跑 MX 入库，见 reports/mx-20261026.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"已回帖：{cmd['id']} → done", result.stdout)
        self.assertEqual(queue.load_state()["commands"][0]["status"], "done")

        result = self._run_cli("pending")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("没有待办指令", result.stdout)

        result = self._run_cli("list", "--all")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[完成]", result.stdout)
        self.assertIn("已重跑 MX 入库", result.stdout)
        self._check_width(result.stdout)

    def test_reply_default_status_is_done(self) -> None:
        cmd = queue.append_command("任务 B")
        result = self._run_cli("reply", cmd["id"], "做完了")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("→ done", result.stdout)
        self.assertEqual(queue.load_state()["commands"][0]["status"], "done")

    def test_reply_with_status_doing(self) -> None:
        cmd = queue.append_command("任务 C")
        result = self._run_cli("reply", cmd["id"], "正在跑", "--status", "doing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("→ doing", result.stdout)
        state = queue.load_state()
        self.assertEqual(state["commands"][0]["status"], "doing")
        self.assertEqual(state["counts"]["doing"], 1)

    def test_blocked(self) -> None:
        cmd = queue.append_command("任务 D")
        result = self._run_cli("blocked", cmd["id"], "缺数据源许可，等人确认")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("→ blocked", result.stdout)
        self.assertEqual(queue.load_state()["commands"][0]["status"], "blocked")

    def test_reply_unknown_id_exit2(self) -> None:
        result = self._run_cli("done", "c-19700101-000000-0000", "不存在的指令")
        self.assertEqual(result.returncode, 2)
        self.assertIn("错误", result.stderr)
        self.assertIn("不存在", result.stderr)

    def test_list_limit(self) -> None:
        for i in range(5):
            queue.append_command(f"任务 {i}")
        result = self._run_cli("list", "--limit", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("任务 4", result.stdout)
        self.assertIn("任务 3", result.stdout)
        self.assertNotIn("任务 0", result.stdout)
        self._check_width(result.stdout)

    def test_long_text_wraps(self) -> None:
        queue.append_command("长文本折行测试：" + "甲" * 120)
        result = self._run_cli("pending")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("长文本折行测试", result.stdout)
        self._check_width(result.stdout)


@unittest.skipUnless(_make_server is not None, f"mobile/server.py 尚未就绪：{_SERVER_IMPORT_ERROR}")
class ServerEndpointTest(InboxTestCase):
    """mobile/server.py 端点契约（设计 §4.3）：token、cookie、201、429。"""

    def setUp(self) -> None:
        super().setUp()
        self.httpd = _make_server("127.0.0.1", 0, TOKEN)  # type: ignore[misc]
        self.addCleanup(self.httpd.server_close)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_thread)

    def _stop_thread(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=10)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def test_no_token_401(self) -> None:
        status, _headers, body = self._request("GET", "/")
        self.assertEqual(status, 401)
        self.assertNotIn(b"c-", body)

    def test_token_redirect_sets_cookie(self) -> None:
        status, headers, _body = self._request("GET", f"/?k={TOKEN}")
        self.assertEqual(status, 302)
        cookie = headers.get("Set-Cookie", "")
        self.assertIn("mb_token=" + TOKEN, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_state_with_cookie(self) -> None:
        status, _headers, body = self._request(
            "GET", "/api/state", headers={"Cookie": f"mb_token={TOKEN}"}
        )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload.get("ok"))
        self.assertIn("queue", payload)
        self.assertEqual(payload["queue"]["counts"]["total"], 0)

    def test_post_command_visible_in_state(self) -> None:
        body = json.dumps({"text": "手机发来的指令"}, ensure_ascii=False).encode("utf-8")
        status, _headers, data = self._request(
            "POST",
            "/api/command",
            body=body,
            headers={"Cookie": f"mb_token={TOKEN}", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 201, data)
        payload = json.loads(data)
        self.assertTrue(payload.get("ok"))
        cmd_id = payload["id"]
        self.assertTrue(cmd_id.startswith("c-"))

        state = queue.load_state()
        self.assertEqual([c["id"] for c in state["commands"]], [cmd_id])
        self.assertEqual(state["commands"][0]["status"], "pending")

    def test_post_rate_limit_429(self) -> None:
        headers = {"Cookie": f"mb_token={TOKEN}", "Content-Type": "application/json"}
        body = json.dumps({"text": "限流测试"}, ensure_ascii=False).encode("utf-8")
        codes = [self._request("POST", "/api/command", body=body, headers=headers)[0] for _ in range(21)]
        self.assertEqual(codes[:20], [201] * 20, codes)
        self.assertEqual(codes[20], 429, codes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
