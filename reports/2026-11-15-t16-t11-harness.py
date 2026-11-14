"""T16 T11 对照框「释放」徽标行为验证（不需要浏览器）。

从 site/build.py 的 APP_JS 常量里**原样取出** t11Subs / t11RelList / t11CompareHTML
三段源码（测的就是要上线的那份 JS），套上最小 stub（IDX / esc / labelOf / T）后
用 Node 跑五个用例，断言「锁定两条记录才出相同/不同」：

  A 你 ER / 目标市场 IR+ER（多个候选）→ 中性「Pick a product」，不许出现 same/diff
  B 你 ER / 目标 ER                → Same
  C 你 ER / 目标 IR                → Different
  D 你 ER,DR（多种）/ 目标 ER      → 中性「Pick a product」
  E 你 ER / 目标未记录             → Not recorded

用法：$py .tmp\t16-t11-harness.py [node.exe 路径]
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
    r"C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe")

HARNESS = ROOT / ".tmp" / "t16-t11-harness.js"


def load_build():
    spec = importlib.util.spec_from_file_location("t16_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def extract_block(app_js: str) -> str:
    start = app_js.index("function t11Subs(")
    end = app_js.index("function t11AfterRender(")
    return app_js[start:end]


def main() -> int:
    build = load_build()
    block = extract_block(build.APP_JS)
    harness = """// 由 .tmp/t16-t11-harness.py 生成：stub + 从 site/build.py 原样取出的 T11 函数
const IDX = [];
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function labelOf(kind, code){ return String(code || ''); }
const TXT = {'t11.same':'Same','t11.diff':'Different','t11.missing':'Not recorded',
  't11.multi':'Pick a product','t11.release':'Release','t11.cmp_title':'cmp',
  't11.cmp_you':'Yours','t11.cmp_target':'Target','t11.cmp_note':'note',
  't11.name':'Registered name','t11.spec':'Strength'};
const T = (k) => (TXT[k] || k);

__BLOCK__

function relCell(html){
  const m = html.match(/<tr><th>Release<\\/th>[\\s\\S]*?<\\/tr>/);
  return m ? m[0] : '(no release row)';
}
const cases = [
  {name:'A 你 ER / 目标 IR+ER（多候选）', pe:{k:'lyrica',d:'Lyrica',v:'pregabalin',c:['US'],rl:'ER'},
   others:[{k:'a',d:'A',v:'pregabalin',c:['DE'],rl:'IR'},{k:'b',d:'B',v:'pregabalin',c:['DE'],rl:'ER'}]},
  {name:'B 你 ER / 目标 ER', pe:{k:'lyrica',d:'Lyrica',v:'pregabalin',c:['US'],rl:'ER'},
   others:[{k:'a',d:'A',v:'pregabalin',c:['DE'],rl:'ER'}]},
  {name:'C 你 ER / 目标 IR', pe:{k:'lyrica',d:'Lyrica',v:'pregabalin',c:['US'],rl:'ER'},
   others:[{k:'a',d:'A',v:'pregabalin',c:['DE'],rl:'IR'}]},
  {name:'D 你 ER,DR / 目标 ER', pe:{k:'x',d:'X',v:'pregabalin',c:['US'],rl:'ER,DR'},
   others:[{k:'a',d:'A',v:'pregabalin',c:['DE'],rl:'ER'}]},
  {name:'E 你 ER / 目标未记录', pe:{k:'lyrica',d:'Lyrica',v:'pregabalin',c:['US'],rl:'ER'},
   others:[{k:'a',d:'A',v:'pregabalin',c:['DE']}]},
];
const out = [];
for(const c of cases){
  IDX.length = 0;
  IDX.push(c.pe, ...c.others);
  const html = t11CompareHTML(c.pe, 'DE', [], T);
  out.push({case: c.name, cell: relCell(html)});
}
console.log(JSON.stringify(out, null, 1));
"""
    HARNESS.write_text(harness.replace("__BLOCK__", block), encoding="utf-8")
    proc = subprocess.run([str(NODE), str(HARNESS)], capture_output=True, text=True,
                          encoding="utf-8")
    print(proc.stdout or "")
    if proc.returncode != 0:
        print("node stderr:", proc.stderr)
        return proc.returncode
    rows = proc.stdout
    checks = [
        ('A', 'cmp-b multi', None, ['cmp-b same', 'cmp-b diff']),
        ('B', 'cmp-b same', None, ['cmp-b diff', 'cmp-b multi']),
        ('C', 'cmp-b diff', None, ['cmp-b same', 'cmp-b multi']),
        ('D', 'cmp-b multi', None, ['cmp-b same', 'cmp-b diff']),
        ('E', 'cmp-b miss', None, ['cmp-b same', 'cmp-b diff']),
    ]
    import json
    data = json.loads(rows)
    ok = True
    for (tag, want, _, forbid), row in zip(checks, data):
        cell = row["cell"]
        got = want in cell
        bad = [f for f in forbid if f in cell]
        status = "PASS" if got and not bad else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"{status} {row['case']}: 期望 {want}，禁止 {forbid}；实际 {cell[cell.find('<td>')+4:][:120]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
