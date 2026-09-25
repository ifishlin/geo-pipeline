"""切點 ＋ 時間軸 → 隔壁吃的那一份 JSON。

    python3 -m geo.pipe.make <題目> scene

這是兩邊的**交界**。契約是 `Map_Animation/src/schema.ts` 那份 schema，
不是它的 Python builder —— 他們自己的 README 就是這麼說的（「the contract
between whoever writes the video and the renderer」）。

所以這一支只產 JSON，**不 import 隔壁任何東西**。隔壁改它的內部結構不會
弄壞這裡；這裡寫錯欄位，`npm run validate` 一秒就擋下來。

## 字幕要切開

一句話最長 5.8 秒、28 個字。整句丟上去的話，74 級的字在 1080 寬的畫面上
要排三行，第三行會壓到畫面下緣。所以照標點切成幾塊，**每一塊的時間從
逐字事件查**，不是把句長平均分 —— 平均分的話「標點很多的那一塊」會停太久。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import paths, story as story_module

THEME = paths.GEO / "data" / "theme.json"

# 可以斷句的地方，照優先順序。中文標點後面斷，不是前面。
BREAKS = "。！？；，、：…"


def theme(spec: dict[str, Any]) -> dict[str, Any]:
    got = json.loads(THEME.read_text(encoding="utf-8"))
    got = {k: v for k, v in got.items() if not k.startswith("_")}
    for key, value in (spec.get("theme") or {}).items():
        got[key] = {**got[key], **value} if isinstance(value, dict) else value
    return got


# 不能從中間切開的東西：數字、數字＋單位、拉丁字母的字。
#
# **加這一條是因為畫出來看到的**：「2026 年 9 月 22 日」被 12 字上限切成
# 「2026 年 9 月 2」和「2 日」——畫面上是一個被腰斬的日期，而程式跑得完全
# 成功。中文一個字一個字切看起來沒問題，正是因為中文本來就一個字一個意思；
# 數字和外文字不是。
ATOM = __import__("re").compile(r"\d[\d,.]*\s*[年月日％%℃]?|[A-Za-z][A-Za-z'’.-]*")


def atoms(text: str) -> list[str]:
    """把一句話切成不可再分的塊。一個漢字一塊，一個數字（含單位）一塊。"""
    out: list[str] = []
    at = 0
    for hit in ATOM.finditer(text):
        out += list(text[at:hit.start()])
        out.append(hit.group())
        at = hit.end()
    out += list(text[at:])
    return [one for one in out if one]


def chop(text: str, most: int) -> list[str]:
    """一句話切成每塊不超過 `most` 個字。**在標點後面斷，不切開數字。**

    **塊數先算出來，再照平均長度排**。一路貼著上限塞的話，最後一塊會是
    剩下的零頭 ——「1991 年才被報紙挖出」＋「來。」，兩個字一閃而過。
    塊數是一樣的（都是兩塊），所以平均分不會多花時間，只是不難看。
    """
    room = len(text)
    many = max(1, -(-room // most))          # 向上取整
    return _pack(text, max(1, -(-room // many)), most)


def _pack(text: str, aim: int, most: int) -> list[str]:
    """照 `aim` 的長度排，但絕不超過 `most`。"""
    out: list[str] = []
    hold: list[str] = []
    room = 0
    best = -1                     # 最後一個「標點剛結束」的位置

    def close(at: int) -> None:
        nonlocal hold, room, best
        out.append("".join(hold[:at]).strip())
        hold, best = hold[at:], -1
        room = sum(len(one) for one in hold)

    for one in atoms(text):
        # 一、放不下了就一定要斷，在最近的標點後面，沒有標點就在原子邊界。
        if hold and room + len(one) > most:
            close(best if best > 0 else len(hold))
        # 二、已經到目標長度、而且剛好有個標點可以斷 —— 那就斷在那裡。
        #    這一條讓每一塊都落在目標附近，而不是「塞到滿、剩下的當零頭」。
        elif hold and room >= aim and best > 0:
            close(best)
        hold.append(one)
        room += len(one)
        if one in BREAKS:
            best = len(hold)
    if hold:
        out.append("".join(hold).strip())
    out = [one for one in out if one]

    return _no_orphans(out, most)


def _no_orphans(out: list[str], most: int) -> list[str]:
    """短到一閃而過的塊，併進鄰居或跟鄰居借字。

    **兩種孤兒，兩種解法**：
    「呃，」在開頭 —— 直接併進下一塊（`呃，你們 1951 年`，11 個字，放得下）。
    「來。」在結尾而前一塊已經滿了 —— 併不進去，就從前一塊借字，借到
    兩邊都不算孤兒為止（`1991 年才被報紙` ＋ `挖出來。`）。

    先試併，併不下才借 —— 併起來是一整句話，借字是把一句話切在奇怪的地方。
    """
    # **動過就從頭再掃一遍。** 借字會讓前一塊變短，而那一塊可能本來剛好
    # 不算孤兒、借完之後就併得進更前面那一塊了 ——`呃，`＋`你們 1951 年就在了`
    # 本來是 14 個字併不下，等後面那個 `。` 借走三個字之後變成 11，併得下。
    # 第一版只在「併」之後重掃、「借」之後往前走，於是開頭那個孤兒永遠留著。
    stuck: set[str] = set()          # 救不了的，記下來，不要一直回頭試
    for _ in range(4 * len(out) + 8):
        at = next((i for i, one in enumerate(out)
                   if len(one) < ORPHAN and one not in stuck
                   and len(out) > 1), None)
        if at is None:
            return out
        near = [i for i in (at + 1, at - 1) if 0 <= i < len(out)]
        joined = [i for i in near if len(out[i]) + len(out[at]) <= most]
        if joined:
            i = joined[0]
            out[min(at, i)] = out[min(at, i)] + out[max(at, i)]
            del out[max(at, i)]
            stuck.clear()            # 版面變了，剛才救不了的也許現在救得了
            continue
        if at > 0:
            give = atoms(out[at - 1])
            before = out[at]
            while len(out[at]) < ORPHAN and len("".join(give[:-1])) >= ORPHAN:
                out[at] = give[-1] + out[at]
                give = give[:-1]
            out[at - 1] = "".join(give)
            if out[at] != before:
                stuck.clear()
                continue
        # 併不下、也借不動：留著，換下一個。**留一個短的比把句子切壞好。**
        stuck.add(out[at])
    return out


# 一塊字幕短於這麼多個字就算孤兒 —— 閃一下，觀眾只看到它消失。
ORPHAN = 4


def caption_times(text: str, start: float, end: float,
                  words: list[dict[str, Any]], most: int
                  ) -> list[dict[str, Any]]:
    """一句話的字幕：切成幾塊，每塊的起訖從逐字事件查。"""
    pieces = chop(text, most)
    if len(pieces) == 1:
        return [{"start": round(start, 3), "end": round(end, 3),
                 "text": pieces[0]}]
    inside = [one for one in words if start - 0.02 <= one["at"] < end]
    joined = "".join(one["text"] for one in inside)
    starts: list[float] = []
    seen = 0
    for piece in pieces:
        # 字幕切塊時標點被 strip 掉了，所以拿「去掉標點的字」去對
        bare = "".join(ch for ch in piece if ch not in BREAKS + " ")
        spot = joined.find(bare[:4], seen) if bare else -1
        when = start
        if spot >= 0:
            run = 0
            for one in inside:
                if run + len(one["text"]) > spot:
                    when = float(one["at"])
                    break
                run += len(one["text"])
            seen = spot + len(bare)
        starts.append(when)

    # **對不到的、對到同一個點的，在這裡一次擺平。** 逐塊當場修的第一版
    # 產出三塊 `end <= start`，而那是隔壁 schema 擋下來的 —— 我這邊一路
    # 到壓片前都沒有人叫。中文字幕對不到很常見（標點被 strip、數字唸成
    # 別的字），所以這不是例外處理，是常態。
    #
    # 規則：起點只能往後走，而且每一塊至少 LEAST 秒；擠不下就從後面借，
    # 借不到就整句平分。**不 raise** —— 字幕晚 0.2 秒是小事，壓不出片是大事。
    least = 0.30
    room = end - start
    if room < least * len(pieces):
        starts = [start + room * i / len(pieces) for i in range(len(pieces))]
    else:
        floor = start
        for i, when in enumerate(starts):
            ceiling = end - least * (len(pieces) - i)
            starts[i] = min(max(when, floor), ceiling)
            floor = starts[i] + least
    return [{"start": round(starts[i], 3),
             "end": round(starts[i + 1] if i + 1 < len(starts) else end, 3),
             "text": piece}
            for i, piece in enumerate(pieces)]


def run(story: str, say=print) -> dict[str, Any]:
    paths.insist(story, "scene")
    spec = story_module.load(story)
    look = theme(spec)
    atlas = paths.load(story, "atlas")
    board = paths.load(story, "storyboard")
    heard = json.loads(
        (paths.at(story, "voice") / "said.json").read_text(encoding="utf-8"))
    cuts = board["cuts"]
    whole = float(board["seconds"])

    scenes: list[dict[str, Any]] = []
    for at, one in enumerate(cuts):
        until = cuts[at + 1]["at"] if at + 1 < len(cuts) else whole
        if until <= one["at"]:
            continue
        lead = one["see"][0]
        highlights = []
        for name in one["tint"]:
            style = look["subject"] if name == lead else look["other"]
            for geo in atlas[name]["draw"]:
                highlights.append({"geoId": geo, **style})
        markers = []
        labels = []
        for name in one["mark"]:
            got = atlas[name]
            spot = got["at"]
            markers.append({"coordinates": spot, **look["mark"]})
            labels.append({"text": name, "coordinates": spot,
                           "offset": [0, -52], **look["label"]})
        # 小到只靠填色看不出來的，改用標記去指。**程式判的，不是模型** ——
        # 它看不到畫面，算不出那塊地在這個相機下有幾個像素。
        for name in one["faint"]:
            spot = atlas[name]["at"]
            markers.append({"coordinates": spot, **look["faint"]})
            labels.append({"text": name, "coordinates": spot,
                           "offset": [0, -56], **look["label"]})
        scenes.append({
            "id": f"{one['at']:06.2f}-{one['why'][:18] or lead}",
            "duration": round(until - one["at"], 3),
            "camera": {"from": one["camera"], "to": one["camera"]},
            "highlights": highlights,
            "markers": markers,
            "labels": labels,
        })

    subtitles: list[dict[str, Any]] = []
    for at, (start, end) in enumerate(heard["bounds"]):
        subtitles += caption_times(heard["lines"][at], start, end,
                                   heard["words"], look["subtitle"]["per_row"])

    body = {
        "title": spec["title"],
        "video": spec["video"],
        "mapStyle": spec.get("map_style", "clean"),
        # 硬切：每一格從第一幀就完整。`soft` 會淡入，而 1.28 秒的格子
        # 淡入會吃掉一大半。
        "cuts": "hard",
        "motionBlur": look.get("motion_blur", 0),
        "subtitleStyle": {k: v for k, v in look["subtitle"].items()
                          if k in ("y", "box", "fontSize")},
        # **聲音不寫進這裡。** 隔壁的 `audio.src` 是相對於它的 `public/`，
        # 照做的話我們的 wav 得搬進它的 repo —— 而界線正是「我的檔案一個
        # 都不放進去」。改成壓無聲、聲音在 `render.py` 用 ffmpeg 接上去。
        # 這樣響度也歸我們管（隔壁 README 自己列著「只有一軌、不混音」）。
        "scenes": scenes,
        "subtitles": subtitles,
    }
    paths.save(story, "scene", body)
    long = max((one["end"] - one["start"] for one in subtitles), default=0)
    say(f"{len(scenes)} 格、{len(subtitles)} 塊字幕　"
        f"共 {sum(one['duration'] for one in scenes):.1f} 秒")
    say(f"  字幕最長一塊 {long:.1f} 秒、最多 "
        f"{max(len(one['text']) for one in subtitles)} 個字"
        f"（上限 {look['subtitle']['per_row']}）")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
