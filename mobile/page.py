"""手机看板页面：单页 HTML / 401 页。

契约见 docs/手机通道-设计.md §4.2：

    render_index(version, now) -> str   完整单页 HTML（内联 CSS+JS，零外链）
    render_denied() -> str              401 页

页面只做两件事：看进度、往 append-only 指令队列里写一句话。
不给用药建议、不做剂量换算、不判断两种药能否互换。
"""

from __future__ import annotations

import html

# 与 site/build.py 里站点的配色同一套来源（纸白 / 墨黑 / 深绿），
# 但本页是独立单页，不 import site 模块，也不改它。
_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0b6b53">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex">
<title>手机看板 · 药品商品名跨国定位站</title>
<link rel="icon" href="data:,">
<style>
:root{
  --bg:#fbfbf9;--fg:#1f2328;--muted:#646b73;--line:#e3e1da;--card:#fff;--soft:#f6f5f1;
  --accent:#0b6b53;--accent-fg:#fff;
  --sev:#a01b1b;--sevbg:#fdecec;--warnc:#b4471f;--warnbg:#fdf1ec;
  --pending:#8a4b00;--pendingbg:#fff6e8;
  --doing:#1f4f8a;--doingbg:#eef4fb;
  --done:#0b6b53;--donebg:#eef7f2;
  --blocked:#a01b1b;--blockedbg:#fdecec;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0f1214;--fg:#e7eaec;--muted:#98a2aa;--line:#2a3137;--card:#161a1e;--soft:#1c2227;
    --accent:#5cc9a7;--accent-fg:#0b1512;
    --sev:#f08a8a;--sevbg:#2f1b1b;--warnc:#e0a071;--warnbg:#2c2118;
    --pending:#e3b277;--pendingbg:#2c2418;
    --doing:#8db6e8;--doingbg:#1a2532;
    --done:#7fd0b1;--donebg:#152720;
    --blocked:#f08a8a;--blockedbg:#2f1b1b;
  }
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;overflow-x:hidden}
body{margin:0;background:var(--bg);color:var(--fg);overflow-x:hidden;
  font:15px/1.55 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
button,textarea{font-family:inherit}
button{cursor:pointer}
button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.top{position:sticky;top:0;z-index:10;background:var(--card);border-bottom:1px solid var(--line);
  padding-top:env(safe-area-inset-top)}
.top-inner{display:flex;align-items:center;gap:10px;padding:8px 14px 0}
.brand{flex:1;min-width:0}
.brand-main{font-size:16px;font-weight:700;line-height:1.3;overflow-wrap:anywhere}
.brand-sub{font-size:12px;color:var(--muted);margin-top:1px;overflow-wrap:anywhere}
.ver{font-variant-numeric:tabular-nums;color:var(--accent);font-weight:600}
.refresh{flex:0 0 auto;min-height:44px;min-width:60px;padding:0 14px;border-radius:10px;
  border:1px solid var(--line);background:var(--soft);color:var(--fg);font-size:15px}
.refresh:disabled{opacity:.6}
.top-meta{display:flex;flex-wrap:wrap;gap:4px 10px;padding:4px 14px 8px;font-size:12px;color:var(--muted)}
.top-meta span{overflow-wrap:anywhere}
main{padding:12px 12px calc(158px + env(safe-area-inset-bottom))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:12px 14px;margin:0 0 12px}
.card-head{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;margin-bottom:6px}
h2{font-size:17px;margin:0}
h3{font-size:13px;margin:14px 0 6px;color:var(--muted);font-weight:600;letter-spacing:.02em}
.hint{font-size:12px;color:var(--muted);font-weight:400;overflow-wrap:anywhere}
.pill{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid var(--line);white-space:nowrap}
.pill-warn{color:var(--warnc);background:var(--warnbg)}
.hero{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;margin:2px 0 8px}
.hero-num{font-size:30px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere}
.hero-unit{font-size:13px;color:var(--muted)}
.hero-ts{margin-left:auto;font-size:12px;color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(78px,1fr));gap:7px}
.stat{background:var(--soft);border:1px solid var(--line);border-radius:10px;
  padding:7px 9px;min-width:0}
.stat b{display:block;font-size:16px;line-height:1.25;font-variant-numeric:tabular-nums;
  overflow-wrap:anywhere}
.stat span{display:block;font-size:12px;color:var(--muted);margin-top:1px;overflow-wrap:anywhere}
.stat.sev b{color:var(--sev)}
.stat.warn b{color:var(--warnc)}
.stat.info b{color:var(--doing)}
.repo{display:grid;gap:5px}
.repo-row{display:flex;gap:8px;font-size:13px;min-width:0}
.repo-row .k{flex:0 0 58px;color:var(--muted);font-size:12px;padding-top:1px}
.repo-row .v{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-word}
ul.reports{list-style:none;margin:0;padding:0;display:grid;gap:4px}
ul.reports li{display:flex;gap:8px;align-items:baseline;font-size:13px;min-width:0}
.rep-name{flex:1;min-width:0;overflow-wrap:anywhere;word-break:break-word}
.rep-time{flex:0 0 auto;font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.empty{color:var(--muted);font-size:13px;margin:6px 0}
.queue{display:block}
.cmd{padding:10px 0;border-top:1px solid var(--line);min-width:0}
.cmd:first-child{border-top:0;padding-top:2px}
.cmd-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.cmd-top time{font-variant-numeric:tabular-nums}
.src{font-size:11px;padding:0 6px;border-radius:999px;background:var(--soft);border:1px solid var(--line)}
.cmd-text{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;font-size:15px}
.badge{display:inline-block;font-size:12px;line-height:1.5;padding:1px 8px;border-radius:999px;
  border:1px solid transparent;white-space:nowrap;font-weight:600}
.badge.pending{color:var(--pending);background:var(--pendingbg)}
.badge.doing{color:var(--doing);background:var(--doingbg)}
.badge.done{color:var(--done);background:var(--donebg)}
.badge.blocked{color:var(--blocked);background:var(--blockedbg)}
.reply{margin:8px 0 0;padding:7px 10px;background:var(--soft);border-radius:9px}
.reply-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px;color:var(--muted)}
.reply-text{margin:4px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;word-break:break-word;
  font-size:14px}
.foot-note{font-size:12px;color:var(--muted);margin:2px 2px 0;text-align:center;overflow-wrap:anywhere}
.composer{position:fixed;left:0;right:0;bottom:0;z-index:20;background:var(--card);
  border-top:1px solid var(--line);box-shadow:0 -6px 18px rgba(0,0,0,.06);
  padding:8px 12px calc(8px + env(safe-area-inset-bottom))}
.composer-row{display:flex;gap:8px;align-items:flex-end}
#text{flex:1;min-width:0;resize:none;font-size:16px;line-height:1.45;padding:9px 10px;
  border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--fg);
  max-height:132px;overflow-y:auto}
#send{flex:0 0 auto;min-width:76px;min-height:44px;padding:0 14px;font-size:16px;font-weight:600;
  border-radius:10px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-fg)}
#send:disabled{opacity:.6}
.composer-meta{display:flex;justify-content:space-between;align-items:baseline;gap:8px;
  margin-top:4px;min-height:17px;font-size:12px;color:var(--muted)}
.note{overflow-wrap:anywhere;word-break:break-word}
.note.err{color:var(--sev)}
.note.ok{color:var(--done)}
.count{flex:0 0 auto;font-variant-numeric:tabular-nums}
@media (max-width:359px){
  main{padding:10px 8px calc(158px + env(safe-area-inset-bottom))}
  .top-inner{padding-left:10px;padding-right:10px}
  .top-meta{padding-left:10px;padding-right:10px}
  .card{padding:10px 11px}
  .composer{padding-left:8px;padding-right:8px}
}
</style>
</head>
<body>
<header class="top">
  <div class="top-inner">
    <div class="brand">
      <div class="brand-main">药品商品名跨国定位站</div>
      <div class="brand-sub">手机看板 · <span class="ver" id="ver">__VERSION__</span></div>
    </div>
    <button type="button" class="refresh" id="refresh">刷新</button>
  </div>
  <div class="top-meta">
    <span>页面生成 __NOW__</span>
    <span id="snap">进度读取中…</span>
  </div>
</header>

<main>
  <section class="card" aria-labelledby="h-progress">
    <div class="card-head">
      <h2 id="h-progress">数据进度</h2>
      <span class="pill pill-warn" id="building" hidden>可能正在建站</span>
    </div>
    <div class="hero">
      <span class="hero-num" id="total">—</span>
      <span class="hero-unit">个产品</span>
      <span class="hero-ts" id="ts"></span>
    </div>
    <div class="stats" id="db-stats"></div>
    <h3>碰撞 <span class="hint">同名不同成分，按规则自动推导</span></h3>
    <div class="stats" id="collision-stats"></div>
    <h3>国家 / 地区</h3>
    <div class="stats" id="country-stats"></div>
    <h3>站点</h3>
    <div class="stats" id="site-stats"></div>
    <h3>仓库</h3>
    <div class="repo" id="repo"></div>
    <h3>最近报告</h3>
    <ul class="reports" id="reports"><li class="muted">读取中…</li></ul>
  </section>

  <section class="card" aria-labelledby="h-queue">
    <div class="card-head">
      <h2 id="h-queue">指令队列</h2>
      <span class="hint" id="qcounts">—</span>
    </div>
    <div class="queue" id="queue"><p class="empty">读取中…</p></div>
  </section>

  <p class="foot-note">只做名字对应与「不可互换」提示，不给用药建议、不做剂量换算。</p>
</main>

<form class="composer" id="composer" autocomplete="off">
  <div class="composer-row">
    <textarea id="text" rows="2" maxlength="2000" enterkeyhint="send"
      aria-label="指令内容"
      placeholder="写一句话下达下一步，agent 下次开工会读到…"></textarea>
    <button type="submit" id="send">发送</button>
  </div>
  <div class="composer-meta">
    <span class="note" id="err" role="status" aria-live="polite"></span>
    <span class="count" id="count">0 / 2000</span>
  </div>
</form>

<script>
(function () {
  "use strict";
  var REFRESH_MS = 20000;
  var MAX_ITEMS = 50;
  var STATUS_LABEL = {pending: "待处理", doing: "进行中", done: "已完成", blocked: "受阻"};
  var STATUS_ORDER = {pending: 0, doing: 1, blocked: 2, done: 3};
  var COUNTRIES = [
    ["US", "美国"], ["GB", "英国"], ["CN", "中国"], ["ES", "西班牙"],
    ["MX", "墨西哥"], ["AU", "澳大利亚"], ["CA", "加拿大"]
  ];
  var timer = null;
  var warmTimer = null;
  var loading = false;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }
  function setText(id, text) {
    var node = $(id);
    if (node) { node.textContent = text; }
  }
  function num(value) {
    if (value === null || value === undefined || value === "") { return "—"; }
    var n = Number(value);
    if (!isFinite(n)) { return "—"; }
    return String(n).replace(/\\B(?=(\\d{3})+(?!\\d))/g, ",");
  }
  function pad(x) { return (x < 10 ? "0" : "") + x; }
  function clockText(iso) {
    if (!iso) { return ""; }
    var m = String(iso).match(/T(\\d{2}:\\d{2}:\\d{2})/);
    if (m) { return m[1]; }
    var d = new Date(iso);
    if (!isNaN(d.getTime())) {
      return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    }
    return String(iso);
  }
  function timeText(ts) {
    if (!ts) { return "—"; }
    var d = new Date(ts);
    if (isNaN(d.getTime())) { return String(ts).replace("T", " ").slice(5, 16); }
    return pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
           pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function stat(label, value, cls) {
    var box = el("div", "stat" + (cls ? " " + cls : ""));
    box.appendChild(el("b", null, value));
    box.appendChild(el("span", null, label));
    return box;
  }
  function fill(id, rows) {
    var box = $(id);
    if (!box) { return; }
    box.textContent = "";
    for (var i = 0; i < rows.length; i++) {
      box.appendChild(stat(rows[i][0], rows[i][1], rows[i][2]));
    }
  }
  function repoRow(key, value) {
    var row = el("div", "repo-row");
    row.appendChild(el("span", "k", key));
    row.appendChild(el("span", "v", value));
    return row;
  }
  function badge(status) {
    var s = String(status || "pending");
    return el("span", "badge " + s, STATUS_LABEL[s] || s);
  }
  function note(text, isError) {
    var node = $("err");
    if (!node) { return; }
    node.textContent = text || "";
    node.className = "note " + (isError ? "err" : "ok");
  }

  var VERSION = "__VERSION__";

  function renderProgress(p) {
    if (!p) { return; }
    var db = p.db || {}, site = p.site || {}, repo = p.repo || {};
    setText("total", num(db.total));
    setText("ts", p.ts ? "快照 " + p.ts : "");
    fill("db-stats", [
      ["成分", num(db.subst)],
      ["商品名", num(db.named)],
      ["名字键", num(db.keys)]
    ]);
    fill("collision-stats", [
      ["严重", num(db.severe), "sev"],
      ["警告", num(db.warn), "warn"],
      ["提示", num(db.info), "info"]
    ]);
    fill("country-stats", COUNTRIES.map(function (c) {
      return [c[1], num(db[c[0]])];
    }));
    var siteRows = [
      ["站点文件", num(site.files)],
      ["索引体积", site.index_mb === null || site.index_mb === undefined
        ? "—" : Number(site.index_mb).toFixed(1) + " MB"],
      ["构建时间", site.built_at || "—"]
    ];
    if (site.age_min !== null && site.age_min !== undefined) {
      siteRows.push(["距今", site.age_min + " 分钟"]);
    }
    siteRows.push(["药品页", num(site.drug)]);
    siteRows.push(["名字页", num(site.name)]);
    fill("site-stats", siteRows);

    var building = $("building");
    if (building) { building.hidden = !site.building; }

    var repoBox = $("repo");
    repoBox.textContent = "";
    repoBox.appendChild(repoRow("分支", repo.branch || "—"));
    repoBox.appendChild(repoRow("HEAD", repo.head || "—"));
    repoBox.appendChild(repoRow("未提交", repo.dirty === null || repo.dirty === undefined
      ? "—" : (repo.dirty === 0 ? "干净" : repo.dirty + " 个文件")));
    if (repo.version) { setText("ver", repo.version); }

    var ul = $("reports");
    ul.textContent = "";
    var reports = Array.isArray(p.reports) ? p.reports : [];
    if (!reports.length) {
      ul.appendChild(el("li", "muted", "暂时没有报告"));
    } else {
      reports.forEach(function (r) {
        var li = el("li");
        li.appendChild(el("span", "rep-name", r.name || "—"));
        li.appendChild(el("span", "rep-time", r.mtime || ""));
        ul.appendChild(li);
      });
    }
    if (repo.version_date) {
      var sub = document.querySelector(".brand-sub");
      if (sub) {
        sub.textContent = "手机看板 · " + (repo.version || VERSION) + " · " + repo.version_date;
      }
    }
  }

  function renderQueue(q) {
    var cmds = (q && q.commands) || [];
    var counts = (q && q.counts) || {};
    setText("qcounts", "共 " + num(counts.total || 0) + " 条 · 待处理 " +
      num(counts.pending || 0) + " · 进行中 " + num(counts.doing || 0) +
      " · 已完成 " + num(counts.done || 0) + " · 受阻 " + num(counts.blocked || 0));

    var box = $("queue");
    box.textContent = "";
    if (!cmds.length) {
      box.appendChild(el("p", "empty", "还没有指令。在下面写一句话，agent 下次开工会读到。"));
      return;
    }
    var sorted = cmds.slice().sort(function (a, b) {
      var pa = STATUS_ORDER[a.status];
      var pb = STATUS_ORDER[b.status];
      if (pa === undefined) { pa = 9; }
      if (pb === undefined) { pb = 9; }
      if (pa !== pb) { return pa - pb; }
      return String(b.ts || "").localeCompare(String(a.ts || ""));
    });
    sorted.slice(0, MAX_ITEMS).forEach(function (cmd) {
      box.appendChild(cmdItem(cmd));
    });
    if (sorted.length > MAX_ITEMS) {
      box.appendChild(el("p", "empty", "只显示最近 " + MAX_ITEMS + " 条，共 " +
        sorted.length + " 条。"));
    }
  }

  function cmdItem(cmd) {
    var item = el("article", "cmd");
    var top = el("div", "cmd-top");
    top.appendChild(badge(cmd.status));
    top.appendChild(el("time", null, timeText(cmd.ts)));
    top.appendChild(el("span", "src", cmd.source === "phone" ? "手机" : (cmd.source || "")));
    item.appendChild(top);
    item.appendChild(el("p", "cmd-text", cmd.text || ""));

    var replies = Array.isArray(cmd.replies) ? cmd.replies : [];
    replies.forEach(function (r) {
      var box = el("div", "reply");
      var head = el("div", "reply-top");
      head.appendChild(badge(r.status));
      head.appendChild(el("time", null, timeText(r.ts)));
      head.appendChild(el("span", "src", r.source === "agent" ? "agent" : (r.source || "")));
      box.appendChild(head);
      box.appendChild(el("p", "reply-text", r.text || ""));
      item.appendChild(box);
    });
    return item;
  }

  function retrySoon(ms) {
    if (warmTimer) { return; }
    warmTimer = setTimeout(function () {
      warmTimer = null;
      refresh(false);
    }, ms || 3000);
  }

  async function refresh(manual) {
    if (loading) { return; }
    loading = true;
    var btn = $("refresh");
    if (manual && btn) { btn.disabled = true; btn.textContent = "刷新中…"; }
    try {
      var res = await fetch(manual ? "/api/state?fresh=1" : "/api/state", {
        cache: "no-store",
        headers: {"Accept": "application/json"}
      });
      if (!res.ok) { throw new Error("HTTP " + res.status); }
      var data = await res.json();
      if (!data || !data.ok) { throw new Error("返回格式不对"); }
      if (data.warming || !data.progress) {
        setText("snap", "正在统计数据…");
        setText("total", "—");
        setText("ts", "第一次统计约需 10–15 秒");
        retrySoon(3000);
      } else {
        renderProgress(data.progress);
        var snapText = "数据统计于 " + (clockText(data.computed_at) || "—");
        if (data.stale) { snapText += " · 已过期"; }
        if (data.refreshing) { snapText += " · 正在更新"; }
        setText("snap", snapText);
        if (manual && data.refreshing) { retrySoon(3000); }
      }
      renderQueue(data.queue);
      note("", false);
    } catch (e) {
      note("刷新失败：" + (e && e.message ? e.message : "网络错误"), true);
      setText("snap", "刷新失败，稍后自动重试");
    } finally {
      loading = false;
      if (manual && btn) { btn.disabled = false; btn.textContent = "刷新"; }
    }
  }

  async function send() {
    var ta = $("text"), btn = $("send");
    var text = ta.value.trim();
    if (!text) {
      note("先写一句话再发送。", true);
      ta.focus();
      return;
    }
    btn.disabled = true;
    btn.textContent = "发送中…";
    try {
      var res = await fetch("/api/command", {
        method: "POST",
        headers: {"Content-Type": "application/json", "Accept": "application/json"},
        body: JSON.stringify({text: text})
      });
      var data = null;
      try { data = await res.json(); } catch (_) { data = null; }
      if (!res.ok) {
        if (res.status === 429) { throw new Error("发得太频繁，等一分钟再试。"); }
        if (res.status === 401) { throw new Error("链接已失效，请重新用带 k= 的链接打开。"); }
        throw new Error((data && data.error) || ("HTTP " + res.status));
      }
      ta.value = "";
      updateCount();
      note("已发送，agent 下次开工会读到。", false);
      refresh(false);
    } catch (e) {
      note("发送失败：" + (e && e.message ? e.message : "网络错误"), true);
    } finally {
      btn.disabled = false;
      btn.textContent = "发送";
    }
  }

  function updateCount() {
    var ta = $("text");
    setText("count", ta.value.length + " / 2000");
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) { refresh(false); }
  });
  $("refresh").addEventListener("click", function () { refresh(true); });
  $("composer").addEventListener("submit", function (ev) {
    ev.preventDefault();
    send();
  });
  $("text").addEventListener("input", updateCount);

  updateCount();
  refresh(false);
  timer = setInterval(function () {
    if (!document.hidden) { refresh(false); }
  }, REFRESH_MS);
  window.addEventListener("pagehide", function () {
    if (timer) { clearInterval(timer); timer = null; }
    if (warmTimer) { clearTimeout(warmTimer); warmTimer = null; }
  });
})();
</script>
</body>
</html>
"""

_DENIED = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="robots" content="noindex">
<title>401 · 手机看板</title>
<style>
:root{--bg:#fbfbf9;--fg:#1f2328;--muted:#646b73;--line:#e3e1da;--card:#fff;--accent:#0b6b53}
@media (prefers-color-scheme:dark){
  :root{--bg:#0f1214;--fg:#e7eaec;--muted:#98a2aa;--line:#2a3137;--card:#161a1e;--accent:#5cc9a7}
}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
  background:var(--bg);color:var(--fg);padding:24px;
  font:16px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.box{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:22px 20px;max-width:420px;width:100%}
.code{font-size:13px;letter-spacing:.14em;color:var(--accent);font-weight:700}
h1{font-size:20px;margin:6px 0 8px}
p{margin:8px 0 0;font-size:14px;color:var(--muted);overflow-wrap:anywhere}
</style>
</head>
<body>
<div class="box">
  <div class="code">401</div>
  <h1>需要带 token 的链接</h1>
  <p>这个页面不是公开站点。请回到电脑，运行 <code>mobile/server.py</code>，
     用启动时打印的带 <code>?k=</code> 的完整链接打开。</p>
</div>
</body>
</html>
"""


def render_index(version: str, now: str) -> str:
    """返回手机看板完整页面（单页，内联 CSS+JS，零外部请求）。"""
    return (_PAGE
            .replace("__VERSION__", html.escape(version or "—", quote=True))
            .replace("__NOW__", html.escape(now or "—", quote=True)))


def render_denied() -> str:
    """返回 401 页：不解释是 token 缺失还是错误，不泄露信息。"""
    return _DENIED
