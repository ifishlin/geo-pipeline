"""geo 的網頁：跑一步、看產物、查目錄。

    python3 -m geo.pipe.server            開在 8765
    python3 -m geo.pipe.server 9000       換個埠

## 這一頁要解決的是什麼

命令列跑得動，而**跑得動跟看得見是兩件事**。這條路上每一個安靜的失敗
（文案 0、留言 0、事實那一節永遠空的）在終端機上都長得像成功 ——
它們只在有人**看**的時候才存在。所以這一頁的每一格都印分母，
而且零要自己叫出來。

## 背景 job 不能當同步請求

舊專案在這裡印過「寫好了：undefined」：網頁打了一支會跑十二分鐘的 API，
當場拿回 `undefined` 就印出來，而真正的工作還在跑。

這裡的規矩：**開 job 的那一支只回一個 id，畫面一定要有人盯著它。**
`geo/checks/_web.py` 掃 `STARTS_JOB` 那張表，每一支都要走 `run()`，
而 `run()` 一定要接 `watch()`。

## 為什麼不把 look.html / watch.html 重做一遍

它們已經在做那件事，而且是**離線打開就能看的單一檔案**（寄給別人、
關掉伺服器也還在）。這一頁只負責**產生它們**然後轉過去 ——
同一件事做兩次，就會有一次是假的。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from geo.pipe import paths, skin

esc = skin.esc

PORT = 8765

# 這幾支會開背景 job。**加一支就要在這裡加一行**，而且畫面上要有人盯著
# 它 —— `geo/checks/_web.py` 對這張表和 JS 逐一比對。
STARTS_JOB = ("/run",)

# 一個 job 一格。id → {step, story, lines, code, began}
JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

# 每一步跑完之後，這一格的產物怎麼數。**回 (數字, 單位, 分母的說明)**，
# 數不出來回 None —— 「數不出來」和「零」要分得開。
def _gist(story: str, step: str) -> str:
    try:
        if step == "sources":
            got = paths.load(story, "sources")
            rows = got if isinstance(got, list) else got.get("sources", [])
            return _count(len(rows), "份來源")
        if step == "facts":
            got = paths.load(story, "facts")
            rows = got if isinstance(got, list) else got.get("facts", [])
            quoted = sum(1 for one in rows if (one or {}).get("quote"))
            return (_count(len(rows), "則事實")
                    + f"，{quoted} 則帶 quote"
                    + ("　⚠ 沒有 quote 就生不出實拍" if not quoted else ""))
        if step == "spine":
            got = paths.load(story, "spine")
            rows = got.get("lines") or got.get("nodes") or []
            return _count(len(rows), "句骨幹")
        if step == "script":
            body = paths.at(story, "script").read_text(encoding="utf-8")
            rows = [one for one in body.splitlines() if one.strip()]
            holds = sum(1 for one in rows if one.startswith("停"))
            return _count(len(rows) - holds, "句台詞") + f"，{holds} 個停"
        if step == "voice":
            wav = paths.at(story, "voice") / "said.wav"
            if not wav.is_file():
                return "⚠ 目錄在，而 said.wav 不在"
            return f"{wav.stat().st_size / 1e6:.1f} MB"
        if step == "atlas":
            got = paths.load(story, "atlas")
            rows = got.get("places", got)
            return _count(len(rows), "個地名")
        if step == "storyboard":
            got = paths.load(story, "storyboard")
            cuts = got.get("cuts", got if isinstance(got, list) else [])
            acts = sum(len(one.get("do") or []) for one in cuts)
            return _count(len(cuts), "格") + f"，{acts} 個動作"
        if step == "scene":
            got = paths.load(story, "scene")
            return (_count(len(got.get("scenes") or []), "個鏡頭")
                    + f"，{len(got.get('subtitles') or [])} 句字幕")
        if step == "film":
            one = paths.at(story, "film")
            return f"{one.stat().st_size / 1e6:.0f} MB"
    except Exception as bad:                                  # noqa: BLE001
        # **讀不出來不是零。** 安靜跳過的話，畫面上會顯示「跑過了」而
        # 那個檔案其實壞了 —— 題目檔壞了四天沒人發現就是這樣來的。
        return f"⚠ 讀不出來（{type(bad).__name__}：{bad}）"
    return ""


def _count(n: int, unit: str) -> str:
    """**零要自己叫出來。** 「找到 0 筆」和「沒有去找」在畫面上一模一樣，
    而後者才是錯 —— 分不出來的時候，寧可每次都吵。"""
    return f"⚠ {unit} 0" if n == 0 else f"{n} {unit}"


def _marks(story: str) -> list[str]:
    out = []
    for one in paths.STEPS:
        if not paths.done(story, one):
            out.append("○")
        elif paths.stale(story, one):
            out.append("◐")          # 跑過了，但上游比它新
        else:
            out.append("●")
    return out


def _title(story: str) -> tuple[str, str]:
    """回 (標題, 壞掉的理由)。**壞掉的要說**，不要 `continue`。"""
    try:
        from geo.pipe import story as story_module
        return str(story_module.load(story).get("title") or story), ""
    except Exception as bad:                                  # noqa: BLE001
        return story, f"{type(bad).__name__}：{bad}"


# ── 頁 ──────────────────────────────────────────────────

def _home() -> str:
    names = paths.stories()
    out = [f"<h1>題目</h1><p class=sub>{len(names)} 個</p>"]
    if not names:
        out.append("<p class=sub>還沒有題目。用下面那張表開一個。</p>")
    for one in names:
        title, broken = _title(one)
        marks = _marks(one)
        spend = _spend_of(one)
        out.append(
            f'<div class="card{" broken" if broken else ""}">'
            f'<h3><a href="/story/{urllib.parse.quote(one)}">{esc(title)}</a>'
            f'<span class=tag>{esc(one)}</span></h3>'
            + (f'<p class=why><span class="tag bad">題目檔讀不出來</span> '
               f'{esc(broken)}</p>' if broken else "")
            + f'<p class=why>{skin.dots(marks)}'
            + (f'　·　問了 {spend[0]} 趟，${spend[1]:.2f}' if spend[0] else "")
            + '</p></div>')
    out.append(
        "<h2>開一個新題目</h2>"
        "<form class=card method=post action=/new>"
        "<div class=pair>"
        "<div><label>資料夾名字（英文，例 trump-greenland）</label>"
        "<input name=name required pattern='[a-z0-9-]+'></div>"
        "<div><label>標題</label><input name=title required></div></div>"
        "<label>要回答的問題</label><input name=ask required>"
        "<label>來源網址，一行一個</label>"
        "<textarea name=sources placeholder='https://en.wikipedia.org/wiki/…'>"
        "</textarea>"
        "<p style='margin:14px 0 0'><button class='btn go'>開</button></p>"
        "</form>")
    return skin.page("題目", "".join(out), here="/")


def _story(name: str) -> str:
    title, broken = _title(name)
    marks = _marks(name)
    out = [f"<h1>{esc(title)}</h1>"
           f"<p class=sub>{esc(name)}　·　{skin.dots(marks)}</p>"]
    if broken:
        out.append(f'<div class="card broken"><h3>題目檔讀不出來</h3>'
                   f'<p class=why>{esc(broken)}　'
                   f'—— 下面每一步都會照著壞掉的那份跑。</p></div>')

    seen = [f'<a class=btn href="/page/{urllib.parse.quote(name)}/look" '
            f'target=_blank>過程頁</a>']
    if paths.done(name, "film"):
        seen.append(f'<a class=btn href="/page/{urllib.parse.quote(name)}/watch"'
                    f' target=_blank>看片＋分鏡</a>')
    out.append("<p>" + "　".join(seen) + "</p>")

    out.append("<h2>九步</h2><table><tr><th>步</th><th>產物</th>"
               "<th>狀態</th><th></th></tr>")
    for at, (step, what) in enumerate(paths.STEPS.items()):
        done = paths.done(name, step)
        old = paths.stale(name, step) if done else []
        gap = paths.missing(name, step)
        if not done:
            state = (f'<span class="tag bad">缺 {esc("、".join(gap))}</span>'
                     if gap else '<span class=tag>還沒跑</span>')
        elif old:
            state = (f'<span class="tag warn">過期</span>'
                     f'<span class=why>{esc("、".join(old))} 比它新</span>')
        else:
            state = f'<span class="tag ok">跑過</span>'
        gist = _gist(name, step) if done else ""
        keep = urllib.parse.quote(name)
        btn = (f'<button class="btn go" onclick="run(\'{keep}\',\'{step}\')">'
               f'跑</button>')
        if done:
            btn += (f' <button class="btn again" '
                    f'onclick="run(\'{keep}\',\'{step}\',1)">重跑</button>')
        out.append(
            f"<tr><td class=num>{at}</td>"
            f"<td><b>{esc(step)}</b><br><span class=why>{esc(what)}</span></td>"
            f"<td>{state}<br><span class=why>{esc(gist)}</span></td>"
            f"<td style='white-space:nowrap'>{btn}</td></tr>")
    out.append("</table>")
    out.append('<h2>跑到哪了</h2><div class=log id=log></div>')
    return skin.page(title, "".join(out), js=JS)


def _effects() -> str:
    from geo import effects as fx
    book = fx.catalogue()
    can = [k for k, v in book.items() if v.get("renders")]
    out = [f"<h1>特效</h1><p class=sub>{len(book)} 種，"
           f"<b>{len(can)}</b> 種畫得出來</p>",
           "<table><tr><th>名</th><th>type</th><th>層</th><th>什麼時候用</th>"
           "<th>要給</th></tr>"]
    for kind, one in book.items():
        need = "、".join(zh for zh, _ in (one.get("要") or {}).values())
        spare = "、".join(f"{zh}（可省）"
                          for zh, _ in (one.get("選填") or {}).values())
        when = esc(one["當"]) if one.get("renders") else (
            f'<span class="tag bad">還畫不出來</span> '
            f'<span class=why>{esc(one.get("沒做", ""))}</span>')
        out.append(
            f"<tr><td><b>{esc(one['名'])}</b></td>"
            f"<td><code>{esc(kind)}</code></td>"
            f"<td class=why>{esc(one.get('layer', ''))}</td>"
            f"<td>{when}</td>"
            f"<td class=why>{esc('　'.join(x for x in (need, spare) if x))}"
            f"</td></tr>")
    out.append("</table>")
    out.append("<h2>模型看到的那張表</h2><p class=sub>"
               "從 <code>geo/data/effects.json</code> 長出來的，不是手寫的"
               "—— 手寫的話加一種要改兩個地方，而漏掉的那一邊不會報錯。</p>"
               f"<div class=log>{esc(fx.menu())}</div>")
    return skin.page("特效", "".join(out), here="/effects")


def _rules() -> str:
    out = ["<h1>門檻和外觀</h1><p class=sub>"
           "改這裡的檔案，程式和 prompt 兩邊都會跟著動 —— "
           "<b>數字只留一份</b>。這一頁是唯讀的。</p>"]
    for one in ("rules.json", "theme.json", "effects.json"):
        where = paths.GEO / "data" / one
        if not where.is_file():
            out.append(f'<div class="card broken"><h3>{esc(one)}</h3>'
                       f'<p class=why>檔案不在 {esc(where)}</p></div>')
            continue
        body = where.read_text(encoding="utf-8")
        out.append(f"<h2>{esc(one)}<span class=tag>"
                   f"{len(body.splitlines())} 行</span></h2>"
                   f"<div class=log>{esc(body[:40000])}</div>")
    return skin.page("門檻", "".join(out), here="/rules")


def _spend_of(story: str) -> tuple[int, float]:
    from geo.pipe import ask as ask_module
    rows = ask_module.spent(story)
    return len(rows), sum(float(one.get("cost_usd") or 0) for one in rows)


def _spend() -> str:
    out = ["<h1>花費</h1>"]
    grand = trips = 0.0
    rows = []
    for one in paths.stories():
        from geo.pipe import ask as ask_module
        for row in ask_module.spent(one):
            rows.append((one, row))
            grand += float(row.get("cost_usd") or 0)
            trips += 1
    out.append(f"<p class=sub>{int(trips)} 趟，共 ${grand:.2f}</p>")
    if not rows:
        out.append('<div class=card><p class=why>⚠ 一筆都沒有。'
                   '這可能是「還沒問過」，也可能是 <code>_ask/spend.jsonl</code>'
                   ' 沒被寫到 —— 兩種在畫面上長得一樣。</p></div>')
    out.append("<table><tr><th>題目</th><th>哪一步</th><th>什麼時候</th>"
               "<th class=num>秒</th><th class=num>美金</th></tr>")
    for story, row in sorted(rows, key=lambda x: str(x[1].get("at", "")),
                             reverse=True)[:200]:
        out.append(
            f"<tr><td>{esc(story)}</td><td>{esc(row.get('task', ''))}</td>"
            f"<td class=why>{esc(row.get('at', ''))}</td>"
            f"<td class=num>{float(row.get('seconds') or 0):.0f}</td>"
            f"<td class=num>{float(row.get('cost_usd') or 0):.3f}</td></tr>")
    out.append("</table>")
    return skin.page("花費", "".join(out), here="/spend")


# ── job ─────────────────────────────────────────────────

def _start(story: str, step: str, again: bool) -> str:
    """開一個背景 job，**馬上回 id**。跑完沒跑完由 `/job/<id>` 說。"""
    key = f"{int(time.time() * 1000):x}"
    args = [sys.executable, "-m", "geo.pipe.make", story, step]
    if again:
        args.append("--again")
    with _LOCK:
        JOBS[key] = {"story": story, "step": step, "lines": [],
                     "code": None, "began": time.time()}

    def chew() -> None:
        # `-u` 讓 python 不要緩衝 —— 緩衝的話畫面上會空白十分鐘然後
        # 一次噴出來，而那十分鐘正是最想看到「它還活著」的時候。
        proc = subprocess.Popen(
            [args[0], "-u"] + args[1:], cwd=str(paths.ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUNBUFFERED": "1"})
        for row in proc.stdout:                              # type: ignore
            with _LOCK:
                JOBS[key]["lines"].append(row.rstrip("\n"))
        proc.wait()
        with _LOCK:
            JOBS[key]["code"] = proc.returncode
            JOBS[key]["lines"].append(
                f"\n—— {'跑完了' if not proc.returncode else '停了'}，"
                f"用了 {time.time() - JOBS[key]['began']:.0f} 秒"
                f"（離開碼 {proc.returncode}）")

    threading.Thread(target=chew, daemon=True).start()
    return key


JS = """
const log = document.getElementById('log');
let now = null;

// **開 job 的那一支只回一個 id，一定要接 watch()。**
// 舊專案在這裡印過「寫好了：undefined」—— 網頁把一支跑十二分鐘的工作
// 當成同步請求，當場拿回 undefined 就印出來。geo/checks/_web.py 擋這個。
async function run(story, step, again){
  if(now){ alert('已經有一步在跑了，等它跑完'); return; }
  if(again && !confirm(
      step + '：重跑會丟掉現在這一份答案，問模型那幾步還要再付一次錢。\\n'
      + '確定嗎？')) return;
  document.querySelectorAll('.btn').forEach(b => b.disabled = true);
  log.textContent = '';
  const res = await fetch('/run', {method:'POST',
    headers:{'content-type':'application/json'},
    body: JSON.stringify({story, step, again: !!again})});
  const got = await res.json();
  now = got.job;
  watch(got.job, 0);
}

async function watch(job, from){
  const res = await fetch('/job/' + job + '?from=' + from);
  const got = await res.json();
  if(got.lines.length){
    log.textContent += got.lines.join('\\n') + '\\n';
    log.scrollTop = log.scrollHeight;
  }
  if(got.running){
    setTimeout(() => watch(job, from + got.lines.length), 700);
    return;
  }
  now = null;
  document.querySelectorAll('.btn').forEach(b => b.disabled = false);
  // 跑完就重讀一次，讓上面那張表的狀態跟著動 —— 不重讀的話畫面會停在
  // 「還沒跑」，而檔案已經在了。
  setTimeout(() => location.reload(), 900);
}
"""


# ── 伺服器 ──────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "geo"

    def log_message(self, *_: Any) -> None:          # 不要洗畫面
        return

    def _send(self, body: bytes, kind: str = "text/html; charset=utf-8",
              code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str, code: int = 200) -> None:
        self._send(text.encode("utf-8"), code=code)

    def _json(self, body: Any) -> None:
        self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:                                # noqa: N802
        where = urllib.parse.urlparse(self.path)
        bits = [urllib.parse.unquote(one)
                for one in where.path.strip("/").split("/") if one]
        try:
            self._route(bits, urllib.parse.parse_qs(where.query))
        except Exception as bad:                             # noqa: BLE001
            # **不要安靜吞掉。** 吞掉的話畫面是一片空白，而空白看不出
            # 是「沒有東西」還是「炸了」。
            import traceback
            self._html(skin.page("出事了", f"<h1>出事了</h1><div class=log>"
                                 f"{esc(traceback.format_exc())}</div>"), 500)

    def _route(self, bits: list[str], query: dict[str, list[str]]) -> None:
        if not bits:
            return self._html(_home())
        if bits[0] == "story" and len(bits) > 1:
            return self._html(_story(bits[1]))
        if bits[0] == "effects":
            return self._html(_effects())
        if bits[0] == "rules":
            return self._html(_rules())
        if bits[0] == "spend":
            return self._html(_spend())
        if bits[0] == "job" and len(bits) > 1:
            key = bits[1]
            with _LOCK:
                one = JOBS.get(key)
                if one is None:
                    return self._json({"lines": ["（沒有這個 job）"],
                                       "running": False})
                start = int((query.get("from") or ["0"])[0])
                return self._json({"lines": one["lines"][start:],
                                   "running": one["code"] is None,
                                   "code": one["code"]})
        if bits[0] == "page" and len(bits) > 2:
            return self._make_page(bits[1], bits[2])
        if bits[0] == "f" and len(bits) > 2:
            return self._file(bits[1], "/".join(bits[2:]))
        self._html(skin.page("沒有這一頁", "<h1>沒有這一頁</h1>"), 404)

    def _make_page(self, story: str, which: str) -> None:
        """產生 look.html / watch.html 然後轉過去。

        **每次都重產** —— 那兩份是快照，而畫面上看不出快照多舊。
        """
        if which == "look":
            from geo.pipe import look as look_module
            one = look_module.build(story)
        elif which == "watch":
            from geo.pipe import watch as watch_module
            one = watch_module.build(story)
        else:
            return self._html(skin.page("沒有這一頁", "<h1>沒有這一頁</h1>"), 404)
        self.send_response(302)
        self.send_header(
            "Location",
            f"/f/{urllib.parse.quote(story)}/{urllib.parse.quote(one.name)}")
        self.end_headers()

    def _file(self, story: str, rel: str) -> None:
        """題目資料夾裡的檔案。影片要能拖進度，所以要吃 Range。"""
        root = paths.home(story).resolve()
        one = (root / rel).resolve()
        if root not in one.parents and one != root:
            return self._html(skin.page("不給", "<h1>不給</h1>"), 403)
        if not one.is_file():
            return self._html(skin.page("沒這個檔",
                                        f"<h1>沒這個檔</h1><p>{esc(rel)}</p>"),
                              404)
        kind = {".mp4": "video/mp4", ".wav": "audio/wav", ".m4a": "audio/mp4",
                ".png": "image/png", ".jpg": "image/jpeg",
                ".html": "text/html; charset=utf-8",
                ".json": "application/json; charset=utf-8",
                ".tsv": "text/plain; charset=utf-8"}.get(
                    one.suffix.lower(), "application/octet-stream")
        size = one.stat().st_size
        span = self.headers.get("Range")
        # **沒有 Range 的話 Safari 的 <video> 拖不動進度**，而 watch.html
        # 整頁的用途就是「點一行跳到那一秒」。這不會報錯，只是點了沒反應。
        if span and span.startswith("bytes="):
            head, _, tail = span[6:].partition("-")
            begin = int(head or 0)
            end = int(tail) if tail else size - 1
            end = min(end, size - 1)
            with one.open("rb") as book:
                book.seek(begin)
                body = book.read(end - begin + 1)
            self.send_response(206)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Range", f"bytes {begin}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with one.open("rb") as book:
            while chunk := book.read(1 << 20):
                self.wfile.write(chunk)

    def do_POST(self) -> None:                               # noqa: N802
        where = urllib.parse.urlparse(self.path).path
        size = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(size)
        if where == "/run":
            got = json.loads(raw or b"{}")
            key = _start(str(got.get("story")), str(got.get("step")),
                         bool(got.get("again")))
            return self._json({"job": key})
        if where == "/new":
            form = urllib.parse.parse_qs(raw.decode("utf-8"))
            name = (form.get("name") or [""])[0].strip()
            try:
                _new_story(name, form)
            except Exception as bad:                         # noqa: BLE001
                return self._html(skin.page(
                    "開不起來", f"<h1>開不起來</h1><p>{esc(bad)}</p>"
                    f"<p><a class=btn href='/'>回去</a></p>"), 400)
            self.send_response(302)
            self.send_header("Location", f"/story/{urllib.parse.quote(name)}")
            self.end_headers()
            return
        self._html(skin.page("沒有這一支", "<h1>沒有這一支</h1>"), 404)


def _new_story(name: str, form: dict[str, list[str]]) -> None:
    """開一個題目的資料夾和 story.json。

    **已經有了就不要覆蓋。** 破壞性的步驟永遠放最後，而這一支的破壞
    （蓋掉一份已經跑了九步的題目檔）沒有任何產出可以抵。
    """
    if not name:
        raise ValueError("要給資料夾名字")
    where = paths.GEO / "stories" / name
    if where.exists():
        raise ValueError(f"「{name}」已經有了 —— 不覆蓋")
    urls = [one.strip() for one in
            (form.get("sources") or [""])[0].splitlines() if one.strip()]
    where.mkdir(parents=True)
    (where / "story.json").write_text(json.dumps({
        "title": (form.get("title") or [name])[0].strip(),
        "ask": (form.get("ask") or [""])[0].strip(),
        "sources": [{"url": one, "kind": "wiki", "why": ""} for one in urls],
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    where = f"http://127.0.0.1:{port}/"
    print(f"geo 網頁：{where}\n（Ctrl-C 收工）")
    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as box:
        try:
            box.serve_forever()
        except KeyboardInterrupt:
            print("\n收工")
    return 0


if __name__ == "__main__":
    sys.exit(main())
