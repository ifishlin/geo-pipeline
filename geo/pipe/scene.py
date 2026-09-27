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

from geo.pipe import marks, camera as camera_module
from geo.pipe import paths, story as story_module
from geo.pipe import voice as voice_module

THEME = paths.GEO / "data" / "theme.json"

# 可以斷句的地方，照優先順序。中文標點後面斷，不是前面。
BREAKS = "。！？；，、：…"


# 鏡頭移動的那幾格參數搬到 `geo/data/theme.json` 的 `camera` 了 ——
# 它們是判斷不是事實（「多久算太短」「重疊多少算同一帶地方」），
# 而判斷應該讓人改得到，不是寫死在程式裡。每一格的理由寫在那份的說明裡。


# 兩個標籤在畫面上靠得比這麼近（像素），就會疊在一起看不懂。
#
# **量出來的**：丹麥（9.02, 55.97）和哥本哈根（12.57, 55.68）在 zoom 3 的
# 畫面上只差 47 像素，兩張白底名牌直接互相蓋掉，畫出來是「丹麥根」。
# 而它畫得出來、不會報錯 —— 只有人看的時候才存在。
#
# 120 是名牌的大約寬度（46 級的字、三四個漢字）加一點餘裕。
APART = 120.0


def _unstack(labels: list[dict[str, Any]], shot: dict[str, Any],
             wide: int, high: int) -> None:
    """靠太近的標籤往上疊開。就地改 `offset`。

    往上不往下：名牌底下就是它指的那個點，往下會蓋住標記本身。
    """
    if len(labels) < 2:
        return
    scale = camera_module.WORLD * 2 ** float(shot["zoom"])
    lon0, lat0 = (float(x) for x in shot["center"])
    def where(one: dict[str, Any]) -> tuple[float, float]:
        lon, lat = (float(x) for x in one["coordinates"])
        return ((lon - lon0) / 360 * scale + wide / 2,
                (camera_module.merc_y(lat) - camera_module.merc_y(lat0))
                * scale + high / 2)
    placed: list[tuple[float, float]] = []
    for one in sorted(labels, key=lambda x: where(x)[1]):
        x, y = where(one)
        lift = float((one.get("offset") or [0, 0])[1])
        while any(abs(x - a) < APART and abs(y + lift - b) < 52
                  for a, b in placed):
            lift -= 52
        one["offset"] = [float((one.get("offset") or [0, 0])[0]), lift]
        placed.append((x, y + lift))


def _legs(one: dict[str, Any], nxt: dict[str, Any] | None, span: float,
          wide: int, high: int, knobs: dict[str, Any]
          ) -> tuple[str, list[tuple[float, dict[str, Any], dict[str, Any]]]]:
    """這一格要拆成幾段、每一段的相機從哪到哪。

    回 `(種類, [(幾秒, 起, 訖), …])`。**種類是它自己說的，不是從段數推的** ——
    第一版讓報告數段數，而「滑」從兩段改成三段（停、走、到位停）之後，
    報告就開始說「滑 0、拉遠 27」，其實那 27 個全是滑的。數字說謊比沒有
    數字糟。

    **滑是預設，切是例外。** 觀眾看的是一張地圖，地圖一直跳人會暈，而且
    會失去「這些地方彼此在哪」的感覺 —— 那正是地理短影音唯一能給的東西。
    所以只有分鏡指名 `cut` 的接縫才硬切；其餘一律滑過去。

    **提早到位，再停一下。** 移動在這一格的後段，而且在下一句開口前
    `settle` 秒就到 —— 不然「這一句還在講，畫面已經在往別的地方跑」。

    四種結果：

    ```
    切       停在自己的鏡頭            分鏡說這裡是斷點，或這一格太短
    滑       停一下，滑過去            預設
    拉遠     停、拉遠到兩邊都看得到、推進   兩邊離太遠，直接滑過去是一片海
    ```
    """
    here = one["camera"]
    if nxt is None or span < knobs["move_least"]:
        return ("cut", [(span, here, here)])
    there = nxt["camera"]
    if here == there or nxt.get("cut"):
        return ("cut", [(span, here, here)])

    # **三段加起來必須剛好等於這一格。** 第一版的補救寫成「room 至少 0.3」，
    # 於是短格子的 hold+room+settle 比 span 大，105 段累積下來整支片多了
    # 0.46 秒 —— 影音就對不齊了，而那是壓完才看得到的。
    # 現在把 settle 和 room 一起夾在 span 以內，hold 吃剩下的。
    settle = min(float(knobs.get("settle", 0.25)), span * 0.3)
    room = min(span * knobs["travel"], knobs["travel_most"], span - settle)
    hold = span - room - settle
    if hold < 0:                                  # 理論上不會，保險
        return ("cut", [(span, here, here)])

    # **移動排在一格的哪裡，是設定檔決定的。**
    #
    # 本來寫死「後段」，理由是「不然這一句還在講，畫面已經在往別的地方
    # 跑」—— 而那是一個**可以改的選擇**，不是事實。寫死在程式裡的話，
    # 想試另一種就得改程式，而改程式的人不會知道原本為什麼那樣選。
    #
    #   late    停一下 → 走 → 停穩    下一句開口前就到位
    #   early   走 → 停著看           一換格就出發，到了就停著
    #   whole   整格都在走             沒有停，最連續但最暈
    when = str(knobs.get("when", "late"))
    close = camera_module.overlap(here, there, wide, high)
    if close >= knobs["together"]:
        if when == "whole":
            return ("glide", [(span, here, there)])
        if when == "early":
            return ("glide", [(room, here, there), (hold + settle, there, there)])
        return ("glide", [(hold, here, here), (room, here, there),
                          (settle, there, there)])

    # 離太遠：直接滑過去是一整段沒有意義的海。先拉遠到兩邊都進得來，
    # 再推進去。**這不是戲，是為了滑得順** —— 引擎一段只能直線移動，
    # 中心和縮放都單調地變，所以拉遠再推進做不到一段裡。
    if span < knobs["move_least"] * 2:
        return ("cut", [(span, here, here)])
    both = camera_module.merge([camera_module.view(here, wide, high),
                                camera_module.view(there, wide, high)])
    try:
        out = camera_module.fit(both, wide, high, pad=0.03, hold=1.0, lift=0.0)
    except ValueError:
        return ("cut", [(span, here, here)])
    if when == "whole":
        return ("out", [(span / 2, here, out), (span / 2, out, there)])
    if when == "early":
        return ("out", [(room / 2, here, out), (room / 2, out, there),
                        (hold + settle, there, there)])
    return ("out", [(hold, here, here), (room / 2, here, out),
                    (room / 2, out, there), (settle, there, there)])


def theme(spec: dict[str, Any]) -> dict[str, Any]:
    """外觀，**顏色照底圖挑那一套**。

    一套顏色配所有底圖是行不通的：`clean` 那套的半透明深紅在空照圖的地形
    上會消失，而那不是「比較不明顯」—— 是整塊地看不出有沒有上色，而畫面
    照樣畫得完、每道門都過。
    """
    got = json.loads(THEME.read_text(encoding="utf-8"))
    got = {k: v for k, v in got.items() if not k.startswith("_")}
    style = str(spec.get("map_style", "clean"))
    looks = got.pop("looks")
    # `satellite-hd` 之類的變體跟著它的主底圖走；認不得就用 clean 那套，
    # 而且說一聲 —— 悄悄用錯一套顏色是看不出來的。
    key = style if style in looks else style.split("-")[0]
    if key not in looks:
        print(f"⚠ 底圖 {style} 沒有對應的顏色，先用 clean 那套")
        key = "clean"
    got.update(looks[key])
    for name, value in (spec.get("theme") or {}).items():
        got[name] = ({**got[name], **value}
                     if isinstance(value, dict) and isinstance(got.get(name), dict)
                     else value)
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
    """一句話的字幕：切成幾塊，每塊的起訖從逐字事件查。

    **先脫掉就地標記。** `⏸0.3` 和 `⟪-10 …⟫` 是給合成器看的，不是台詞
    —— 配音那邊脫了，字幕這邊沒脫，於是九塊字幕把符號燒進畫面：
    觀眾看到「⏸0.3它每次都是最後一」。

    而它**一路過了每一道門**：長度對、切點對、逐字時間對得上，成片壓得
    完完全全成功。抽一格出來看才發現 —— 視覺的錯不會報錯。
    """
    text = marks.strip(text)
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
    hero = str(spec.get("hero") or "")
    whole = float(board["seconds"])

    wide, high = spec["video"]["width"], spec["video"]["height"]
    fps = int(spec["video"]["fps"])
    scenes: list[dict[str, Any]] = []
    moves: dict[str, int] = {}
    for at, one in enumerate(cuts):
        until = cuts[at + 1]["at"] if at + 1 < len(cuts) else whole
        if until <= one["at"]:
            continue
        # 誰用主色。**主角固定是主角**，不是「模型把誰排第一」——
        # 上一版用 `see[0]`，於是同一塊地在不同格會換顏色，而觀眾是靠
        # 顏色認人的。主角沒被塗到的那幾格，才退回用排第一的。
        lead = hero if hero in one["tint"] else (
            one["tint"][0] if one["tint"] else one["see"][0])
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
        #
        # **已經被 mark 的就不要再插一根針。** 丹麥被分鏡標了、又被算成
        # 太小，於是同一個座標上兩根針（黃的一根、紅的一根）疊在一起 ——
        # 畫得出來、不會報錯，只是看起來像畫壞了。
        for name in [x for x in one["faint"] if x not in one["mark"]]:
            spot = atlas[name]["at"]
            markers.append({"coordinates": spot, **look["faint"]})
            labels.append({"text": name, "coordinates": spot,
                           "offset": [0, -56], **look["label"]})
        _unstack(labels, one["camera"], wide, high)
        body = {"highlights": highlights, "markers": markers, "labels": labels}
        nxt = cuts[at + 1] if at + 1 < len(cuts) else None
        kind, legs = _legs(one, nxt, until - one["at"], wide, high,
                           look["camera"])
        moves[kind] = moves.get(kind, 0) + 1
        # **邊界對齊到整幀，從絕對時間算，不是每一段各自四捨五入。**
        #
        # 這是量出來的：`settle` 是 0.25 秒，在 30fps 剛好是 7.5 幀 ——
        # 每一次都往同一邊進位，27 個滑鏡頭累積出 13.5 幀＝0.45 秒。
        # 我這邊的檢查看秒數（122.138），渲染器按幀算（122.58），
        # 兩邊都「對」，而成片的影音差了將近半秒。
        #
        # 從絕對時間算的話誤差不會累積：每一個邊界各自取整，相鄰兩個
        # 邊界相減就是那一段的幀數，總和永遠等於最後一個邊界。
        walk = one["at"]
        for n, (span, a, b) in enumerate(legs):
            head, tail = walk, walk + span
            frames = round(tail * fps) - round(head * fps)
            walk = tail
            if frames <= 0:
                continue
            scenes.append({
                "id": f"{one['at']:06.2f}{'-移' + str(n) if n else ''}"
                      f"-{one['why'][:16] or lead}",
                "duration": frames / fps,
                "camera": {"from": a, "to": b,
                           "easing": "linear" if a == b else "easeInOut"},
                **body,
            })

    # **分段之後總長要等於原本的時間軸。** 一格拆成三段的算式只要有一個
    # 分支加起來不等於 span，105 段累積下來就是半秒，而那是壓完十分鐘
    # 之後在「影音等長」那道門才叫的。擋在這裡便宜得多。
    drawn = sum(one["duration"] for one in scenes)
    # 容許一幀 —— 最後一格的尾巴本來就會落在幀的邊界上。
    if abs(drawn - whole) > 1.5 / fps:
        raise SystemExit(
            f"畫面加起來 {drawn:.3f} 秒，而聲音是 {whole:.3f} 秒 —— "
            f"差 {abs(drawn - whole):.3f}。分段的算式有一條加起來不等於"
            f"那一格的長度")

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
        # 硬切：每一格從第一幀就完整。`soft` 會淡入，而一秒的格子淡入
        # 會吃掉一大半。鏡頭移動是另一回事 —— 那是 camera 的 from→to，
        # 跟這一格無關。
        "cuts": "hard",
        "basemapBrightness": look.get("brightness", 1.0),
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
    # **分鏡挑的動作，在這裡變成真的疊加層。**
    #
    # 它們是「影片層」的 —— 秒數從影片開頭算起，所以一個動作可以跨過
    # 切點（一條航線畫到一半換鏡頭，線還在）。那是渲染器的設計。
    from geo import effects as fx
    body.update(fx.build(cuts, {"atlas": atlas, "whole": whole,
                                "spec": spec}, say))
    # **燒進畫面的字裡不准有標記符號。**
    #
    # `⏸0.3` 和 `⟪-10 …⟫` 是給合成器看的。配音那邊脫掉了，字幕這邊漏了
    # —— 九塊字幕把符號燒進成片，而每一道門都過（長度對、切點對、逐字
    # 時間對得上），抽一格出來看才發現。
    #
    # 一個東西有兩條路會被用到（唸出來、印出來），就會有一條忘了處理。
    dirty = [one["text"] for one in subtitles
             if any(x in one["text"] for x in (marks.PAUSE, marks.OPEN,
                                               marks.CLOSE))]
    if dirty:
        raise SystemExit(
            f"{len(dirty)} 塊字幕裡有標記符號，那會被燒進畫面：\n  "
            + "\n  ".join(dirty[:5])
            + "\n  標記是給合成器看的，字幕要先 marks.strip()")

    paths.save(story, "scene", body)

    # **寫完就驗。** 隔壁的 `npm run validate` 一秒鐘，而它抓到過兩個我
    # 用推的推錯的欄位（`curve: "arc"` 而 enum 是 `greatCircle`、
    # `fields` 的 blobs 要包在 `keys` 裡）。型別都是對的，schema 以外
    # 看不出來。
    #
    # `render.py` 本來就會驗，但那是壓片那一步 —— 驗證該放在**寫檔的
    # 那一步**，不然單跑 `scene` 的人以為沒事。
    from geo.pipe import render as render_module
    render_module.check(paths.at(story, "scene"), say)

    long = max((one["end"] - one["start"] for one in subtitles), default=0)
    say(f"鏡頭　切 {moves.get('cut', 0)}　滑 {moves.get('glide', 0)}　"
        f"拉遠再推進 {moves.get('out', 0)}"
        + f"　（{sum(moves.values())} 個切點 → {len(scenes)} 段）")
    # **「滑幾格」不是「鏡頭在動多久」。**
    #
    # 這一行印了很久的「滑 38」，而量成片才發現鏡頭只有 26% 的時間在動
    # —— 一格拆成「停 → 移動 → 停穩」，移動只佔一半。兩個數字都是真的，
    # 而**只有後者是觀眾感覺得到的**，偏偏報告只印前者。
    #
    # 使用者的目標是「運鏡絲滑」，所以這一格要在畫面上。
    busy = sum(one["duration"] for one in scenes
               if one["camera"]["from"] != one["camera"]["to"])
    whole_secs = sum(one["duration"] for one in scenes)
    say(f"  鏡頭真的在動 {busy / whole_secs:.0%}"
        f"（{busy:.0f} 秒，其餘 {whole_secs - busy:.0f} 秒停著）"
        f"　camera.travel = {look['camera']['travel']}")
    say(f"{len(scenes)} 格、{len(subtitles)} 塊字幕　"
        f"共 {sum(one['duration'] for one in scenes):.1f} 秒")
    say(f"  字幕最長一塊 {long:.1f} 秒、最多 "
        f"{max(len(one['text']) for one in subtitles)} 個字"
        f"（上限 {look['subtitle']['per_row']}）")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
