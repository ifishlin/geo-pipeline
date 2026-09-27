"""網頁上的兩個書架：所有的 md，和每一次問模型的原文。

    /docs                   repo 裡每一份 md，照目錄分
    /docs/<路徑>            那一份，渲染過的；md 之間的相對連結點得過去
    /asks                   每一次問模型：哪一步、什麼時候、花多少、收完沒
    /asks/<題目>/<那一趟>    送出去的原文、收回來的原文、挖出來的 JSON、外殼

## 為什麼要看原文

「模型為什麼這樣答」只有送出去的那一份答得出來 —— 而送出去的不是
`geo/prompts/*.md`，是**代入之後**的那一份（`{cover.most_words}` 換成數字、
事實清單整段貼進去）。改 prompt 之前要看的是這一份，不是模板。

## 為什麼 md 自己渲染

WEB.md 的規矩是「不用裝任何東西」。這裡的文件用到的只有標題、清單、
表格、程式碼圍欄、粗體、連結 —— 一百行寫得完，而多一個相依套件就多一個
「換一台機器打不開」的理由。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from geo.pipe import paths, skin

esc = skin.esc


# ── md → html ──────────────────────────────────────────

def _inline(text: str, here: Path) -> str:
    """一行裡面的：`程式碼`、**粗體**、[連結](目標)、<網址>。"""
    keep: list[str] = []

    def stash(html_: str) -> str:
        keep.append(html_)
        return f"\x00{len(keep) - 1}\x00"

    # 程式碼先收起來，裡面的 ** 和 [] 不算數
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{esc(m[1])}</code>"),
                  text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
                  lambda m: stash(f"<span class=tag>圖：{esc(m[1])}</span>"), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash(_link(m[1], m[2], here)), text)
    text = re.sub(r"<(https?://[^>\s]+)>",
                  lambda m: stash(f'<a href="{esc(m[1])}" target=_blank>'
                                  f'{esc(m[1])}</a>'), text)
    text = esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m[1])], text)


def _link(label: str, target: str, here: Path) -> str:
    """md 之間的相對連結換成站內的；外面的另開分頁；其他的照字印。"""
    if target.startswith(("http://", "https://")):
        return f'<a href="{esc(target)}" target=_blank>{esc(label)}</a>'
    if target.startswith("#"):
        return f'<a href="{esc(target)}">{esc(label)}</a>'
    file_, _, part = target.partition("#")
    where = (here.parent / file_).resolve()
    try:
        rel = where.relative_to(paths.ROOT)
    except ValueError:
        return esc(label)
    if where.suffix == ".md" and where.is_file():
        return (f'<a href="/docs/{urllib.parse.quote(str(rel))}'
                f'{"#" + esc(part) if part else ""}">{esc(label)}</a>')
    # 指到程式碼或目錄：沒有頁可以開，但路徑要看得到
    return f'{esc(label)} <span class=tag>{esc(str(rel))}</span>'


def _slug(text: str) -> str:
    return re.sub(r"[^\w一-鿿-]+", "-", text.strip().lower()).strip("-")


def md_html(body: str, here: Path) -> str:
    """一份 md 變成 html。**只收這個 repo 用得到的那幾種寫法。**"""
    out: list[str] = []
    rows = body.splitlines()
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para), here)}</p>")
            para.clear()

    while i < len(rows):
        row = rows[i]
        bare = row.strip()
        if bare.startswith("```"):
            flush()
            fence = []
            i += 1
            while i < len(rows) and not rows[i].strip().startswith("```"):
                fence.append(rows[i])
                i += 1
            out.append(f"<pre class=code>{esc(chr(10).join(fence))}</pre>")
            i += 1
            continue
        head = re.match(r"(#{1,6})\s+(.*)", bare)
        if head:
            flush()
            n = len(head[1])
            out.append(f"<h{n} id=\"{esc(_slug(head[2]))}\">"
                       f"{_inline(head[2], here)}</h{n}>")
        elif re.fullmatch(r"-{3,}|\*{3,}", bare):
            flush()
            out.append("<hr>")
        elif bare.startswith("|"):
            flush()
            block = []
            while i < len(rows) and rows[i].strip().startswith("|"):
                block.append(rows[i].strip().strip("|"))
                i += 1
            cells = [[c.strip() for c in one.split("|")] for one in block]
            if len(cells) > 1 and all(re.fullmatch(r":?-+:?", c)
                                      for c in cells[1] if c):
                top, cells = cells[0], cells[2:]
            else:
                top = []
            out.append("<table>" + (
                "<tr>" + "".join(f"<th>{_inline(c, here)}</th>" for c in top)
                + "</tr>" if top else "") + "".join(
                "<tr>" + "".join(f"<td>{_inline(c, here)}</td>" for c in one)
                + "</tr>" for one in cells) + "</table>")
            continue
        elif re.match(r"([-*]|\d+\.)\s", bare):
            flush()
            tag = "ol" if bare[0].isdigit() else "ul"
            items: list[str] = []
            while i < len(rows):
                now = rows[i].strip()
                hit = re.match(r"([-*]|\d+\.)\s+(.*)", now)
                if hit:
                    items.append(hit[2])
                elif now and rows[i].startswith((" ", "\t")) and items:
                    items[-1] += " " + now          # 縮排的是上一條的續行
                else:
                    break
                i += 1
            out.append(f"<{tag}>" + "".join(
                f"<li>{_inline(one, here)}</li>" for one in items) + f"</{tag}>")
            continue
        elif bare.startswith(">"):
            flush()
            quote = []
            while i < len(rows) and rows[i].strip().startswith(">"):
                quote.append(rows[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{_inline(' '.join(quote), here)}"
                       f"</blockquote>")
            continue
        elif not bare:
            flush()
        else:
            para.append(bare)
        i += 1
    flush()
    return "".join(out)


# ── 文件 ───────────────────────────────────────────────

def docs_page() -> str:
    got = paths.docs()
    out = [f"<h1>文件</h1><p class=sub>{len(got)} 份 md"
           f"　·　送給模型的原文在<a href='/asks'>問答</a>那一頁</p>"]
    groups: dict[str, list[Path]] = {}
    for one in got:
        rel = one.relative_to(paths.ROOT)
        groups.setdefault(str(rel.parent) if str(rel.parent) != "." else "（根目錄）",
                          []).append(one)
    for folder, files in groups.items():
        out.append(f"<h2>{esc(folder)}</h2><table>")
        for one in files:
            rel = one.relative_to(paths.ROOT)
            body = one.read_text(encoding="utf-8", errors="replace")
            first = next((r.lstrip("# ").strip() for r in body.splitlines()
                          if r.strip()), "")
            out.append(
                f"<tr><td><a href='/docs/{urllib.parse.quote(str(rel))}'>"
                f"{esc(one.name)}</a></td>"
                f"<td class=why>{esc(first[:60])}</td>"
                f"<td class=num>{len(body.splitlines())} 行</td>"
                f"<td class='num why'>{_ago(one.stat().st_mtime)}</td></tr>")
        out.append("</table>")
    return skin.page("文件", "".join(out), here="/docs")


def doc_page(rel: str) -> tuple[str, int]:
    """回 (html, 狀態碼)。**只給 `paths.docs()` 列出來的** —— 不是任何路徑。"""
    want = (paths.ROOT / rel).resolve()
    if want not in paths.docs():
        return skin.page("沒有這份", f"<h1>沒有這份文件</h1><p>{esc(rel)}</p>"
                         "<p><a class=btn href='/docs'>回文件</a></p>"), 404
    body = want.read_text(encoding="utf-8", errors="replace")
    head = (f"<p class=sub><a href='/docs'>文件</a>　/　{esc(rel)}"
            f"　·　{len(body.splitlines())} 行　·　改於 {_ago(want.stat().st_mtime)}"
            "</p>")
    return skin.page(want.name, head + f"<article class=md>"
                     f"{md_html(body, want)}</article>", here="/docs"), 200


# ── 問答 ───────────────────────────────────────────────

def _trips(story: str) -> list[dict[str, Any]]:
    """一個題目問過的每一趟。**從檔案數出來**，不靠 spend.jsonl ——
    那一份是後來才開始記的，前面幾十趟不在裡面。"""
    into = paths.home(story) / "_ask"
    if not into.is_dir():
        return []
    out = []
    for sent in into.glob("*.prompt.md"):
        key = sent.name[:-len(".prompt.md")]
        task = key.rsplit("-", 2)[0]
        said = into / f"{key}.said.md"
        meta_at = into / f"{key}.meta.json"
        meta: dict[str, Any] = {}
        if meta_at.is_file():
            try:
                meta = json.loads(meta_at.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                meta = {"_壞掉": True}
        out.append({"story": story, "key": key, "task": task,
                    "when": sent.stat().st_mtime,
                    "sent": sent.stat().st_size,
                    "said": said.stat().st_size if said.is_file() else None,
                    "meta": meta})
    return sorted(out, key=lambda x: x["when"], reverse=True)


def _state(trip: dict[str, Any]) -> str:
    """這一趟收完沒。**沒有回答和回答是空的要分得開。**"""
    meta = trip["meta"]
    if trip["said"] is None:
        return '<span class="tag bad">沒有回答檔</span>'
    if not trip["said"]:
        return '<span class="tag bad">回答是空的</span>'
    if meta.get("_壞掉"):
        return '<span class="tag warn">外殼讀不出來</span>'
    if meta.get("is_error"):
        return f'<span class="tag bad">出錯 {esc(meta.get("subtype", ""))}</span>'
    if not meta:
        return '<span class=tag>沒有外殼</span>'
    return '<span class="tag ok">收完</span>'


def asks_page(query: dict[str, list[str]]) -> str:
    story_want = (query.get("story") or [""])[0]
    task_want = (query.get("task") or [""])[0]
    every = [t for s in paths.stories() for t in _trips(s)]
    shown = [t for t in every
             if (not story_want or t["story"] == story_want)
             and (not task_want or t["task"] == task_want)]
    tasks: dict[str, int] = {}
    for one in every:
        tasks[one["task"]] = tasks.get(one["task"], 0) + 1
    cost = sum(float(t["meta"].get("total_cost_usd") or 0) for t in shown)
    out = [f"<h1>問答</h1><p class=sub>{len(shown)}/{len(every)} 趟"
           f"　·　有外殼的共 ${cost:.2f}"
           "　·　每一趟都是<b>代入之後</b>真的送出去的那一份</p>"]
    if not every:
        out.append("<div class=card><p class=why>⚠ 一趟都沒有。可能是還沒問過，"
                   "也可能 <code>_ask/</code> 不在這台機器上 —— "
                   "兩種在畫面上長得一樣。</p></div>")
    pills = [f"<a class=btn href='/asks'>全部 {len(every)}</a>"] + [
        f"<a class='btn{' go' if name == task_want else ''}' "
        f"href='/asks?task={urllib.parse.quote(name)}'>{esc(name)} {n}</a>"
        for name, n in sorted(tasks.items(), key=lambda x: -x[1])]
    out.append("<p>" + " ".join(pills) + "</p>")
    out.append("<table><tr><th>什麼時候</th><th>題目</th><th>哪一步</th>"
               "<th>狀態</th><th class=num>送出</th><th class=num>收回</th>"
               "<th class=num>秒</th><th class=num>出 token</th>"
               "<th class=num>美金</th></tr>")
    for one in shown[:500]:
        meta = one["meta"]
        link = (f"/asks/{urllib.parse.quote(one['story'])}/"
                f"{urllib.parse.quote(one['key'])}")
        secs = meta.get("duration_ms")
        usd = meta.get("total_cost_usd")
        spent = f"{usd:.3f}" if usd else "—"
        took = f"{secs / 1000:.0f}" if secs else "—"
        said = _size(one["said"])
        made = (meta.get("usage") or {}).get("output_tokens", "—")
        out.append(
            f"<tr><td><a href='{link}'>"
            f"{time.strftime('%m-%d %H:%M:%S', time.localtime(one['when']))}"
            f"</a></td><td class=why>{esc(one['story'])}</td>"
            f"<td><b>{esc(one['task'])}</b></td><td>{_state(one)}</td>"
            f"<td class=num>{_size(one['sent'])}</td>"
            f"<td class=num>{said}</td><td class=num>{took}</td>"
            f"<td class=num>{made}</td><td class=num>{spent}</td></tr>")
    out.append("</table>")
    if len(shown) > 500:
        out.append(f"<p class=sub>只列最新的 500 趟（共 {len(shown)}）</p>")
    return skin.page("問答", "".join(out), here="/asks")


def ask_page(story: str, key: str) -> tuple[str, int]:
    trips = _trips(story) if story in paths.stories() else []
    at = next((n for n, t in enumerate(trips) if t["key"] == key), None)
    if at is None:
        return skin.page("沒有這一趟", f"<h1>沒有這一趟</h1><p>{esc(story)}／"
                         f"{esc(key)}</p><p><a class=btn href='/asks'>回問答</a>"
                         "</p>"), 404
    trip = trips[at]
    into = paths.home(story) / "_ask"
    sent = (into / f"{key}.prompt.md").read_text(encoding="utf-8",
                                                 errors="replace")
    said_at = into / f"{key}.said.md"
    said = (said_at.read_text(encoding="utf-8", errors="replace")
            if said_at.is_file() else None)
    meta_at = into / f"{key}.meta.json"

    # 同一步的上一趟、下一趟（時間順）
    same = [t for t in trips if t["task"] == trip["task"]]
    n = same.index(trip)
    def hop(t: dict[str, Any] | None, word: str) -> str:
        if not t:
            return f"<button class=btn disabled>{word}</button>"
        return (f"<a class=btn href='/asks/{urllib.parse.quote(story)}/"
                f"{urllib.parse.quote(t['key'])}'>{word}</a>")
    older = same[n + 1] if n + 1 < len(same) else None
    newer = same[n - 1] if n > 0 else None

    raw = lambda name: (f"<a class=btn href='/f/{urllib.parse.quote(story)}/_ask/"
                        f"{urllib.parse.quote(name)}' target=_blank>原始檔</a>")
    out = [f"<h1>{esc(trip['task'])}<span class=tag>{esc(story)}</span></h1>",
           f"<p class=sub>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(trip['when']))}"
           f"　·　{_state(trip)}　·　這一步的第 {len(same) - n}/{len(same)} 趟</p>",
           f"<p>{hop(older, '← 上一趟')} {hop(newer, '下一趟 →')} "
           f"<a class=btn href='/asks?task={urllib.parse.quote(trip['task'])}'>"
           f"這一步全部</a> <a class=btn href='/asks'>問答</a>"
           "　跳到：<a href='#sent'>送出</a>　<a href='#said'>收回</a>"
           "　<a href='#json'>JSON</a>　<a href='#meta'>外殼</a></p>"]

    meta = trip["meta"]
    if meta and not meta.get("_壞掉"):
        use = meta.get("usage") or {}
        out.append(
            "<div class=card><p class=why>"
            f"花了 <b>${float(meta.get('total_cost_usd') or 0):.3f}</b>"
            f"　·　{float(meta.get('duration_ms') or 0) / 1000:.0f} 秒"
            f"（第一個字 {float(meta.get('ttft_ms') or 0) / 1000:.0f} 秒）"
            f"　·　進 {use.get('input_tokens', 0)}"
            f" ＋ 讀快取 {use.get('cache_read_input_tokens', 0)}"
            f" ＋ 寫快取 {use.get('cache_creation_input_tokens', 0)}"
            f"　·　出 {use.get('output_tokens', 0)}"
            f"　·　停在 {esc(meta.get('stop_reason', '?'))}"
            f"　·　session {esc(str(meta.get('session_id', ''))[:8])}</p></div>")

    out.append(f"<h2 id=sent>送出去的<span class=tag>{len(sent):,} 字</span>"
               f"<span class=tag>{len(sent.splitlines())} 行</span></h2>"
               f"<p>{raw(key + '.prompt.md')}</p>"
               f"<div class='log tall'>{esc(sent)}</div>")

    if said is None:
        out.append('<div class="card broken"><h3>沒有回答檔</h3><p class=why>'
                   '送出去了，而 <code>.said.md</code> 不在 —— 逾時被砍、'
                   '或這一趟還在跑。</p></div>')
    else:
        out.append(f"<h2 id=said>收回來的<span class=tag>{len(said):,} 字</span></h2>"
                   f"<p>{raw(key + '.said.md')}</p>"
                   f"<div class='log tall'>{esc(said) or '（空的）'}</div>")
        # 挖 JSON 用的是跟管線同一支 —— 另寫一份的話，這一頁挖得出來
        # 而管線挖不出來，看的人會以為沒事。
        from geo.pipe import ask as ask_module
        if not said.strip():
            out.append('<div class="card broken" id=json><h3>回答是空的</h3>'
                       '<p class=why>檔案在，一個字都沒有 —— 通常是逾時被砍，'
                       '或 CLI 出錯而錯誤只寫在外殼裡。</p></div>')
        else:
            try:
                got = ask_module.as_json(said)
                out.append("<h2 id=json>挖出來的 JSON<span class=tag>"
                           "跟管線用同一支 ask.as_json()</span></h2>"
                           f"<div class='log tall'>"
                           f"{esc(json.dumps(got, ensure_ascii=False, indent=1))}"
                           "</div>")
            except SystemExit as bad:
                out.append('<div class="card broken" id=json><h3>挖不出 JSON'
                           f'</h3><p class=why>{esc(bad)}</p></div>')

    if meta_at.is_file():
        out.append(f"<h2 id=meta>外殼<span class=tag>CLI 回的 meta.json</span></h2>"
                   f"<p>{raw(key + '.meta.json')}</p>"
                   f"<div class=log>{esc(meta_at.read_text(encoding='utf-8'))}</div>")
    else:
        out.append("<h2 id=meta>外殼</h2><p class=sub>這一趟沒有 meta.json"
                   "（開始記外殼之前的那幾十趟都沒有）</p>")
    return skin.page(f"{trip['task']} {key}", "".join(out), here="/asks"), 200


# ── 小的 ───────────────────────────────────────────────

def _size(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def _ago(when: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(when))
