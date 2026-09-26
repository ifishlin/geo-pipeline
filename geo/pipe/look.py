"""把一個題目的整個過程攤成一頁。

    python3 -m geo.pipe.look <題目>        產出並打開 look.html
    python3 -m geo.pipe.look               列出有哪些題目

**跟原本的 studio/ 完全無關。** 這一支只讀 `geo/stories/<題目>/`，
產出一個單檔 HTML，沒有伺服器、沒有相依。原本那條路的網頁一行都沒動。

## 為什麼要這一頁

每一次問模型送出什麼、收回什麼，本來就都落地在 `_ask/` 了 —— 但那是
二十幾個檔案散在一個資料夾裡，沒有人會一個一個打開。**留著不等於看得到。**

這一頁把它們照時間排成一條，旁邊放那一步的產物和量出來的數字，
所以「模型為什麼這樣答」和「這樣答之後變成什麼」看得到同一個畫面上。

## 一頁，不是一個站

單檔 HTML 而不是伺服器，因為這是**拿來一起看的東西**，不是拿來操作的。
檔案可以直接丟給人、可以留存、不會因為 server 沒開就看不到。
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from geo.pipe import paths

# 每一步的中文名和一句話說明。**照 `paths.STEPS` 的順序長**，
# 加一步只要在那張表加，這裡補一行說明。
ABOUT: dict[str, tuple[str, str]] = {
    "sources": ("來源", "抓回來的網頁全文"),
    "facts": ("事實", "每一則帶 quote（逐字抄原文）和 entity（牽涉哪些地方）"),
    "spine": ("骨幹", "時間線的節點、轉在哪、會回來的那句話"),
    "script": ("台詞", "旁白稿，再挑幾句改成角色講"),
    "voice": ("配音", "一次合成，拿回每句起訖和每個字的毫秒"),
    "atlas": ("地理", "稿子裡掃到的地名 → 外框 → 相機"),
    "storyboard": ("分鏡", "哪一段看哪裡、哪個接縫是斷點"),
    "scene": ("編譯", "算成渲染器吃的格式：鏡頭怎麼移、字幕怎麼折"),
    "film": ("成片", ""),
}

# 哪一步用哪幾份 prompt，那一份在做什麼。**這張表是頁面最上面那一段的
# 唯一來源** —— 說明寫在這裡而不是寫在 HTML 裡，加一支 prompt 只要加一行。
#
# 沒有列到的步驟＝沒有模型參與，全部是程式算的。
USES: dict[str, list[tuple[str, str]]] = {
    "facts": [("facts.md",
               "從來源全文抽事實。每一則要逐字抄一段原文（quote），"
               "還要說牽涉到哪些地方（entity）—— 那一欄是事實和地圖之間"
               "唯一的連結")],
    "spine": [("spine.md",
               "排骨幹：時間線有哪幾個節點、轉在哪、會回來的那句話是什麼、"
               "怎麼收")],
    "script": [("script.md",
                "寫旁白稿。**只有旁白，沒有對白** —— 一個聲音把故事講完，"
                "就算一句都不改也要講得通"),
               ("parts.md",
                "挑幾句改成角色講。**取代，不是追加** —— 回的是「第 12 句"
                "改成丹麥講、改寫成這樣」，句子總數不變，所以重複在結構上"
                "不可能發生")],
    "storyboard": [("storyboard.md",
                    "哪一段看哪裡、哪個接縫是斷點。只給地名和句子裡的詞，"
                    "座標和秒數是程式算的")],
}

CSS = """
:root{--ink:#1a1d21;--dim:#6b7280;--line:#e5e7eb;--bg:#fbfbfc;
      --ask:#f3f6fb;--said:#fdf6ee;--hit:#0b6bcb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.7 -apple-system,"PingFang TC","Noto Sans TC",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 120px}
h1{font-size:26px;margin:0 0 4px}
.sub{color:var(--dim);margin-bottom:28px}
.rail{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:32px}
.rail a{text-decoration:none;color:var(--ink);border:1px solid var(--line);
        background:#fff;border-radius:999px;padding:5px 13px;font-size:13px}
.rail a.off{color:#b6bcc4}
.step{background:#fff;border:1px solid var(--line);border-radius:12px;
      margin-bottom:14px;overflow:hidden}
.step>summary.head{padding:14px 18px;display:flex;align-items:baseline;
      gap:10px;flex-wrap:wrap;cursor:pointer;list-style:none;color:var(--ink)}
.step[open]>summary.head{border-bottom:1px solid var(--line)}
.step>summary.head::-webkit-details-marker{display:none}
.step>summary.head:before{content:"▸";color:var(--dim);margin-right:2px}
.step[open]>summary.head:before{content:"▾"}
.head b{font-size:17px}
.head .n{color:var(--dim);font-size:13px}
.note{color:var(--dim);font-size:13px;padding:0 18px;margin:10px 0 0}
.body{padding:14px 18px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
td,th{border-bottom:1px solid var(--line);padding:5px 8px;
      text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
details{border-top:1px solid var(--line)}
details>summary{cursor:pointer;padding:10px 18px;font-size:13.5px;
                color:var(--hit);list-style:none;user-select:none}
details>summary::-webkit-details-marker{display:none}
details>summary:before{content:"▸ ";color:var(--dim)}
details[open]>summary:before{content:"▾ "}
pre{margin:0;padding:14px 18px;white-space:pre-wrap;word-break:break-word;
    font:12.5px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;
    max-height:60vh;overflow:auto}
pre.ask{background:var(--ask)}
pre.said{background:var(--said)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:0;
      border-top:1px solid var(--line)}
.pair>div{min-width:0}
.pair h4{margin:0;padding:8px 18px;font-size:12px;color:var(--dim);
         font-weight:500;background:#fff;border-bottom:1px solid var(--line)}
.pair>div+div{border-left:1px solid var(--line)}
.line{display:flex;gap:10px;padding:2px 0;font-size:14px}
.line .who{flex:0 0 68px;color:var(--dim);font-size:12.5px;padding-top:2px}
.line.hold{color:#b6bcc4;font-size:12.5px}
.who.role{color:#b4530f;font-weight:600}
.tag{display:inline-block;background:#eef1f5;border-radius:4px;
     padding:1px 6px;font-size:11.5px;color:var(--dim);margin-left:6px}
.warn{color:#b4530f}
.arch{background:#fff;border:1px solid var(--line);border-radius:12px;
      padding:6px 18px 14px;margin-bottom:28px}
.arch h3{font-size:15px;margin:14px 0 8px}
.arch td:first-child{white-space:nowrap;color:var(--dim)}
.arch code{background:#f3f6fb;border-radius:4px;padding:1px 6px;
           font-size:12.5px}
.tries{padding:2px 18px 10px;color:var(--dim);font-size:12.5px}
.now{background:#e9f3ea;color:#2f6b39}
@media(max-width:820px){.pair{grid-template-columns:1fr}
  .pair>div+div{border-left:0;border-top:1px solid var(--line)}}
"""


def esc(text: Any) -> str:
    return html.escape(str(text))


def _when(one: Path) -> str:
    return time.strftime("%H:%M", time.localtime(one.stat().st_mtime))


# 一趟問答屬於哪一步。**檔名不等於步驟名** —— 台詞那一步問三次
# （script／parts／narrate），而只有第一個跟步驟同名，另外兩趟就從
# 畫面上消失了。漏掉的正是「這一句為什麼變成這樣」最關鍵的兩趟。
BELONGS = {"parts": "script", "narrate": "script"}


def _asks(story: str) -> dict[str, list[tuple[Path, Path, str]]]:
    """每一步問過幾次，各自的 (送出去, 收回來, 哪一支 prompt)。照時間排。"""
    into = paths.home(story) / "_ask"
    out: dict[str, list[tuple[Path, Path, str]]] = {}
    if not into.is_dir():
        return out
    for one in sorted(into.glob("*.prompt.md")):
        said = one.with_name(one.name.replace(".prompt.md", ".said.md"))
        if not said.is_file():
            continue
        task = one.name.split("-")[0]
        out.setdefault(BELONGS.get(task, task), []).append((one, said, task))
    return out


def _table(rows: list[tuple[str, Any]]) -> str:
    return ("<table>" + "".join(
        f"<tr><th>{esc(a)}</th><td>{b}</td></tr>" for a, b in rows)
        + "</table>")


def _script(story: str) -> str:
    one = paths.at(story, "script")
    if not one.is_file():
        return ""
    out = []
    for row in one.read_text(encoding="utf-8").splitlines():
        if not row.strip():
            continue
        who, _, text = row.partition("\t")
        if who == "停":
            out.append(f'<div class="line hold">┄ 停 {esc(text)} 秒</div>')
        else:
            kind = "" if who == "旁白" else " role"
            out.append(f'<div class="line"><span class="who{kind}">'
                       f"{esc(who)}</span><span>{esc(text)}</span></div>")
    return "".join(out)


def _facts(story: str) -> str:
    try:
        rows = paths.load(story, "facts")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    out = ["<table><tr><th>#</th><th>事實</th><th>逐字抄的出處</th>"
           "<th>地方</th></tr>"]
    for at, one in enumerate(rows, 1):
        out.append(
            f"<tr><td class=num>{at}</td><td>{esc(one['said'])}</td>"
            f"<td style='color:#6b7280'>{esc(one['quote'][:90])}</td>"
            f"<td>{esc('、'.join(one['entity']))}</td></tr>")
    return "".join(out) + "</table>"


def _spine(story: str) -> str:
    try:
        got = paths.load(story, "spine")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    head = _table([("轉", esc(got.get("turn", ""))),
                   ("會回來的那句", esc(got.get("refrain", "（沒有）"))),
                   ("收", esc(got.get("ending", "")))])
    rows = ["<table><tr><th>時間</th><th>beat</th><th>發生什麼</th></tr>"]
    for one in got.get("nodes", []):
        rows.append(f"<tr><td>{esc(one.get('when',''))}</td>"
                    f"<td>{esc(one.get('beat',''))}</td>"
                    f"<td>{esc(one.get('what',''))}</td></tr>")
    return head + "".join(rows) + "</table>"


def _board(story: str) -> str:
    try:
        got = paths.load(story, "storyboard")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    cuts, whole = got["cuts"], got["seconds"]
    out = ["<table><tr><th>秒</th><th>長</th><th>接</th><th>看到</th>"
           "<th>為什麼</th></tr>"]
    for at, one in enumerate(cuts):
        until = cuts[at + 1]["at"] if at + 1 < len(cuts) else whole
        out.append(
            f"<tr><td class=num>{one['at']:.1f}</td>"
            f"<td class=num>{until - one['at']:.1f}s</td>"
            f"<td>{'切' if one.get('cut') else '滑'}</td>"
            f"<td>{esc('＋'.join(one['see']))}</td>"
            f"<td style='color:#6b7280'>{esc(one.get('why',''))}</td></tr>")
    return "".join(out) + "</table>"


def _voice(story: str) -> str:
    one = paths.at(story, "voice") / "said.json"
    if not one.is_file():
        return ""
    got = json.loads(one.read_text(encoding="utf-8"))
    return _table([
        ("長度", f"{got['seconds']:.1f} 秒"),
        ("句數", f"{len(got['lines'])} 句，逐字事件 {len(got['words'])} 個"),
        ("量到的基頻", "　".join(f"{k} {v:.0f} Hz"
                            for k, v in got.get("pitch", {}).items())),
    ])


def _scene(story: str) -> str:
    one = paths.at(story, "scene")
    if not one.is_file():
        return ""
    got = json.loads(one.read_text(encoding="utf-8"))
    moves = sum(1 for x in got["scenes"]
                if x["camera"]["from"] != x["camera"]["to"])
    return _table([
        ("段數", f"{len(got['scenes'])} 段，其中 {moves} 段鏡頭在走"),
        ("字幕", f"{len(got['subtitles'])} 塊"),
        ("底圖", esc(got.get("mapStyle", ""))),
    ])


def _film(story: str) -> str:
    one = paths.at(story, "film")
    if not one.is_file():
        return ""
    got = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "csv=p=0", str(one)], capture_output=True, text=True)
    bits = (got.stdout.strip() or ",").split(",")
    return _table([
        ("檔案", f"<code>{esc(one.relative_to(paths.ROOT))}</code>"),
        ("長度", f"{float(bits[0] or 0):.1f} 秒"),
        ("大小", f"{int(bits[1] or 0) / 1048576:.1f} MB"),
    ]) + f'<video controls style="width:100%;max-width:380px;margin-top:12px;' \
         f'border-radius:8px" src="{esc(one.name)}"></video>'


SHOW = {"facts": _facts, "spine": _spine, "script": _script,
        "voice": _voice, "storyboard": _board, "scene": _scene,
        "film": _film}


def _arch() -> str:
    """頁面最上面那一段：整條路的形狀，以及每一份 prompt 在做什麼。"""
    rows = ["<div class=arch><h3>整條路</h3>",
            "<p class=note style='padding:0'>九步，一步一個檔。"
            "每一步只讀前面的、只寫自己那一個 —— 一步壞掉重跑一步就好。"
            "<b>模型只在四步出現</b>，其餘都是程式算的。</p>",
            "<table><tr><th>步驟</th><th>產物</th><th>誰做</th>"
            "<th>做什麼</th></tr>"]
    for name in paths.STEPS:
        title, note = ABOUT[name]
        uses = USES.get(name) or []
        who = "模型 ＋ 程式" if uses else "程式"
        first = True
        span = max(1, len(uses))
        for at in range(span):
            rows.append("<tr>")
            if first:
                rows.append(
                    f"<td rowspan={span}><b>{esc(title)}</b></td>"
                    f"<td rowspan={span}><code>{esc(paths.STEPS[name])}</code>"
                    f"</td>")
            if uses:
                md, what = uses[at]
                rows.append(f"<td><code>{esc(md)}</code></td>"
                            f"<td>{esc(what)}</td>")
            else:
                rows.append(f"<td>{esc(who)}</td><td>{esc(note)}</td>")
            rows.append("</tr>")
            first = False
    rows.append("</table>")
    rows.append(
        "<h3>誰決定什麼</h3><table>"
        "<tr><th>模型</th><td>寫稿、挑事實、決定「這一句要看到哪裡」、"
        "哪個接縫是斷點</td></tr>"
        "<tr><th>程式</th><td>所有的數字：座標、縮放、秒數、鏡頭怎麼移、"
        "字幕怎麼折</td></tr></table>"
        "<p class=note style='padding:0'>模型看不到地圖，算不準座標；"
        "而外框查得到，算得準。叫它填座標的話，它不會說做不到 —— "
        "它會給一份格式正確、中心差三度的答案。</p></div>")
    return "".join(rows)


def _history(story: str, name: str,
             rows: list[tuple[Path, Path, str]]) -> str:
    """這一步問過幾次。**最後一次是現在用的，前面那幾次留著比對。**

    多問幾次是常態（字數不合、形狀不對、擋下來重寫），而「這一版跟上一版
    差在哪」只有把兩次的答案擺在一起才看得出來 —— 所以全部留著，不只留
    最後一次。
    """
    if not rows:
        return ""
    kinds: dict[str, int] = {}
    for _, _, task in rows:
        kinds[task] = kinds.get(task, 0) + 1
    out = [f'<p class=tries>'
           + "　".join(f"<b>{esc(k)}</b> 問過 {v} 次" for k, v in kinds.items())
           + "</p>"]
    last = {task: max(i for i, (_, _, t2) in enumerate(rows) if t2 == task)
            for task in kinds}
    for at, (one, said, task) in enumerate(rows):
        now = last[task] == at
        stamp = one.name.split("-", 1)[1].replace(".prompt.md", "")
        tag = '<span class="tag now">現在用的</span>' if now else \
              f'<span class=tag>第 {at} 次</span>'
        out.append(
            f"<details><summary><b>{esc(task)}</b>　{esc(stamp)}{tag}"
            f"　送出 {one.stat().st_size // 1000}k 字元、"
            f"回來 {said.stat().st_size // 1000}k</summary>"
            f'<div class=pair><div><h4>送出去的</h4>'
            f'<pre class=ask>{esc(one.read_text(encoding="utf-8"))}</pre>'
            f"</div><div><h4>收回來的</h4>"
            f'<pre class=said>{esc(said.read_text(encoding="utf-8"))}</pre>'
            f"</div></div></details>")
    return "".join(out)


def build(story: str) -> Path:
    asks = _asks(story)
    out = [f"<!doctype html><meta charset=utf-8>"
           f"<title>{esc(story)}｜過程</title>"
           f"<style>{CSS}</style><div class=wrap>",
           f"<h1>{esc(story)}</h1>",
           '<p class=sub>每一步送出什麼、收回什麼，以及那一步產出了什麼。'
           '　<b>這一頁只讀 geo/stories/，跟原本的管線無關。</b></p>',
           '<p class=sub><a href="#" onclick="document.querySelectorAll('
           "'details.step').forEach(d=>d.open=true);return false\">"
           '全部展開</a>　·　<a href="#" onclick="document.querySelectorAll('
           "'details').forEach(d=>d.open=false);return false\">"
           '全部收起</a></p>',
           _arch()]

    for at, name in enumerate(paths.STEPS):
        done = paths.done(story, name)
        title, note = ABOUT[name]
        where = paths.at(story, name)
        tries = asks.get(name, [])
        marks = []
        if done:
            marks.append(f'<span class=n>{_when(where)}</span>')
        else:
            marks.append('<span class="n warn">還沒跑</span>')
        if tries:
            marks.append(f'<span class=tag>問了 {len(tries)} 次</span>')
        old = paths.stale(story, name)
        if old:
            marks.append(f'<span class="tag warn">過期：'
                         f'{esc("、".join(old))}比它新</span>')

        out.append(
            f'<details class=step id="{name}"><summary class=head>'
            f"<b>{at}　{esc(title)}</b>"
            f'<span class=n>{esc(paths.STEPS[name])}</span>'
            + "".join(marks) + "</summary>")
        if note:
            out.append(f"<p class=note>{esc(note)}</p>")
        if done and name in SHOW:
            body = SHOW[name](story)
            if body:
                out.append(f"<div class=body>{body}</div>")
        out.append(_history(story, name, tries))
        out.append("</details>")

    out.append("</div>")
    page = paths.home(story) / "look.html"
    page.write_text("".join(out), encoding="utf-8")
    return page


def main() -> None:
    names = paths.stories()
    if len(sys.argv) < 2:
        print("題目：" + ("、".join(names) or "（一個都沒有）"))
        print("用法：python3 -m geo.pipe.look <題目>")
        return
    story = sys.argv[1]
    if story not in names:
        raise SystemExit(f"沒有這個題目：{story}。有的是：{'、'.join(names)}")
    page = build(story)
    print(f"寫好了 {page.relative_to(paths.ROOT)}")
    subprocess.run(["open", str(page)])


if __name__ == "__main__":
    main()
