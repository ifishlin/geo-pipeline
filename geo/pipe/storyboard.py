"""模型挑畫面 → 每一個切點的時間和相機。

    python3 -m geo.pipe.make <題目> storyboard

模型回的是**名字和詞**：「這一格要看到格陵蘭跟丹麥，切在『公投』那個詞上」。
這一支把它變成數字：

```
名字 → atlas 查外框 → camera.fit() 算中心和縮放
詞   → 在那一句的逐字時間裡找 → 秒數
```

**秒數從頭到尾沒有經過模型。** 模型估不準秒數，但很會說「這句在講哪裡」。

## 四道門

```
不認得的地方   raise —— 模型想指一塊沒有的地，安靜跳過的話那一格會是空的
詞找不到       raise —— 對不到時間就是不知道第幾秒切
詞出現兩次     raise —— 兩個位置，挑一個就是猜
切點倒退       raise —— 後面的切點跑到前面去，時間軸就亂了
```

第三道和第四道是**加了才發現需要**的：模型很愛用「的」「在」當切點詞。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import ask
from geo.pipe import camera as camera_module
from geo.pipe import paths, story as story_module

# 一格至少要這麼久。比這個短的話觀眾只看到閃一下，而**閃一下跟畫錯很像**。
#
# 0.35 是從參考片量的：它平均 0.55 秒一格，最短的幾格在 0.2 上下，但那是
# 連續快切的一串。我們這支節奏慢很多（兩分鐘 36 句），單獨一格 0.2 秒
# 只會看起來像出錯。
LEAST = 0.35


# 一個點單獨當鏡頭的時候，周圍要看到多大（經度、緯度各往外幾度）。
#
# **量出來的**：第一版給 ±0.4°／±0.25°，那是「剛好裝得下一個點」的框，
# 算出來 zoom 9.6 —— 紐約那一格變成街道圖，看不出是紐約；圖勒基地那一格
# 是一整片白色的冰，連海岸線都沒有。**相機算得完全正確，鏡頭完全沒用。**
#
# ±7°／±3.5° 在 1080×1920 上算出來約 zoom 4.7：紐約那一格看得到整個東岸、
# 圖勒看得到格陵蘭西北角和海。點是用來「指」的，不是用來「看」的 ——
# 要看清楚一個點旁邊有什麼，那是 `see` 一塊地、`mark` 一個點的事。
AROUND = (7.0, 3.5)

# 整支片至少要有這麼多種不同的畫面。
#
# 參考頻道 72 秒的片用了 14 種（那份拆解文件數出來的）。我們這支兩分鐘，
# 所以 8 種是很低的底線 —— 它擋的不是「不夠好看」，是**「整支片其實只有
# 一張圖」**：第一版模型回了 91 個切點，而併掉重複的之後只剩幾種畫面，
# 十二張取樣裡有八張一模一樣。而報告當時說「91 格、平均 1.28 秒一格」。
FEWEST = 8

# 一格停超過這麼久就出聲。不擋 —— 長鏡頭是一種選擇，但要被看見。
STARE = 6.0


def _shape(one: dict[str, Any]) -> tuple:
    """這一格「長什麼樣」。相機一樣、塗的標的一樣，畫面上就是同一張圖。"""
    return (round(one["camera"]["center"][0], 2),
            round(one["camera"]["center"][1], 2),
            round(one["camera"]["zoom"], 2),
            tuple(sorted(one["tint"])), tuple(sorted(one["mark"])),
            tuple(sorted(one["faint"])))


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return _shape(a) == _shape(b)


def _around(spot: list[float]) -> list[float]:
    """一個點的「看得到周圍」框。"""
    return [spot[0] - AROUND[0], spot[1] - AROUND[1],
            spot[0] + AROUND[0], spot[1] + AROUND[1]]


def _fit(box: list[float], wide: int, high: int, spec: dict[str, Any],
         line: int, see: list[str], say) -> dict[str, Any]:
    """裝得下就照設定裝，裝不下就讓字幕那塊空間，還是不行才停。

    **一格裝不下不該讓整趟白費。** 模型挑了「美國＋挪威」，橫跨 156 度，
    算出來要 zoom 1.89 而畫面的地板是 1.91 —— 差 0.02。原本這裡直接
    raise，於是前面三分鐘的模型呼叫、一分鐘的配音全部作廢，而**能救的**。

    讓步的順序是有意義的：先少留白邊（`pad`），再把字幕那塊空間也拿來裝
    （`hold` → 1.0）。第二種會讓那塊地壓到字幕上，所以要出聲 —— 它是
    「勉強擠進去」，不是「剛好」。
    """
    tries = [(spec["pad"], spec["hold"], spec["lift"], ""),
             (0.05, spec["hold"], spec["lift"], "邊留少一點"),
             (0.04, 1.0, 0.0, "連字幕那塊空間都拿來裝")]
    for pad, hold, lift, note in tries:
        try:
            got = camera_module.fit(box, wide, high, pad=pad, hold=hold,
                                    lift=lift)
        except ValueError:
            continue
        if note:
            say(f"⚠ 第 {line} 句「{'＋'.join(see)}」裝不下，{note}")
        return got
    raise SystemExit(
        f"第 {line} 句要同時看到「{'＋'.join(see)}」，外框 "
        f"{[round(one) for one in box]} 橫跨 {box[2] - box[0]:.0f} 度，"
        f"{wide}×{high} 的畫面裝不下 —— 9:16 最多看得到約 202 度經度，"
        f"而那還是整個畫面都給它的時候。\n"
        f"  這一格要拆成兩格，或者只 see 其中一個、另一個用 mark。"
        f"加 --again 重問")


def _places_table(atlas: dict[str, Any]) -> str:
    rows = []
    for name, got in atlas.items():
        if got["kind"] == "area":
            many = f"（{len(got['draw'])} 個國家）" if len(got["draw"]) > 1 else ""
            rows.append(f"- **{name}** —— 一塊地，畫得出形狀{many}")
        else:
            rows.append(f"- **{name}** —— 一個點（{got['note']}），"
                        f"只能標記，不能塗色")
    return "\n".join(rows)


def _lines_table(who: list[str], said: list[str]) -> str:
    return "\n".join(f"{at:>3}　{name}　{text}"
                     for at, (name, text) in enumerate(zip(who, said)))


def _word_time(words: list[dict[str, Any]], start: float, end: float,
               want: str, line: str) -> float:
    """那個詞在第幾秒被唸出來。

    逐字事件是一個字一個字的，而詞是好幾個字，所以**把落在這一句裡的字
    接起來，找詞的起點是第幾個字**，再回頭查那個字的時間。
    """
    inside = [one for one in words if start - 0.02 <= one["at"] < end]
    joined = "".join(one["text"] for one in inside)
    if joined.count(want) == 0:
        raise SystemExit(
            f"「{want}」在這一句的唸出來的字裡找不到：{line}\n"
            f"（唸出來的是：{joined}）")
    if joined.count(want) > 1:
        raise SystemExit(
            f"「{want}」在這一句裡出現 {joined.count(want)} 次，"
            f"對不出是哪一個：{line}")
    at, seen = joined.index(want), 0
    for one in inside:
        if seen + len(one["text"]) > at:
            return float(one["at"])
        seen += len(one["text"])
    return start


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "storyboard")
    spec = story_module.load(story)
    atlas = paths.load(story, "atlas")
    heard = json.loads(
        (paths.at(story, "voice") / "said.json").read_text(encoding="utf-8"))

    raw_at = paths.home(story) / "6-storyboard.raw.json"
    if again or paths.raw_stale(story, raw_at, "storyboard"):
        prompt = ask.prompt_of(
            "storyboard.md",
            places=_places_table(atlas),
            title=spec["title"], turn=spec.get("turn", ""),
            lines=_lines_table(heard["who"], heard["lines"]),
            seconds=f"{heard['seconds']:.0f}", count=len(heard["lines"]))
        got = ask.as_json(ask.send(story, "storyboard", prompt, say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    shots = {int(one["line"]): one.get("cuts") or []
             for one in (got.get("shots") or [])}
    gap = [at for at in range(len(heard["lines"])) if not shots.get(at)]
    if gap:
        raise SystemExit(
            f"這幾句沒有畫面：{gap}。**不補一個預設的** —— 補了的話畫面上"
            f"看起來很正常，而那幾句其實沒有人決定過要看什麼")

    wide, high = spec["video"]["width"], spec["video"]["height"]
    cuts: list[dict[str, Any]] = []
    for at, (start, end) in enumerate(heard["bounds"]):
        line = heard["lines"][at]
        for one in shots[at]:
            want = str(one.get("word") or "")
            when = start if not want else _word_time(
                heard["words"], start, end, want, line)
            see = [str(x) for x in (one.get("see") or [])]
            bad = [x for x in see if x not in atlas]
            if bad:
                raise SystemExit(
                    f"第 {at} 句要看「{'、'.join(bad)}」，而 atlas 裡沒有。"
                    f"有的是：{'、'.join(atlas)}")
            if not see:
                raise SystemExit(f"第 {at} 句有一格沒說要看哪裡")
            boxes = [atlas[x]["bbox"] for x in see if atlas[x]["kind"] == "area"]
            spots = [atlas[x]["at"] for x in see if atlas[x]["kind"] == "point"]
            boxes += [_around(one_) for one_ in spots]
            box = camera_module.merge(boxes)
            shot = _fit(box, wide, high, spec, at, see, say)
            mark = [str(x) for x in (one.get("mark") or [])]
            bad = [x for x in mark if x not in atlas]
            if bad:
                raise SystemExit(f"第 {at} 句要標「{'、'.join(bad)}」，atlas 裡沒有")
            tint = [str(x) for x in (one.get("tint") or see)]
            bad = [x for x in tint if x not in atlas]
            if bad:
                raise SystemExit(f"第 {at} 句要塗「{'、'.join(bad)}」，atlas 裡沒有")
            cuts.append({
                "at": round(when, 3), "line": at, "word": want,
                "see": see, "mark": mark,
                "tint": [x for x in tint if atlas[x]["kind"] == "area"],
                "why": str(one.get("why") or ""),
                "camera": shot,
                # 小到只靠填色看不出來的，程式自己改成「加一個標記」——
                # 這是程式判得出來的事，不必回去問模型。
                "faint": [x for x in tint
                          if atlas[x]["kind"] == "area"
                          and camera_module.too_small(shot, atlas[x]["bbox"])],
            })

    cuts.sort(key=lambda one: one["at"])
    for i in range(1, len(cuts)):
        if cuts[i]["at"] < cuts[i - 1]["at"]:
            raise SystemExit("切點倒退了，時間軸會亂")

    # **切到一模一樣的畫面，不是切。** 模型回了 91 個切點，而其中一長串的
    # 相機、塗色、標記完全相同 —— 畫面上那是一格，不是十格。留著的話報告
    # 會說「91 格、平均 1.28 秒」，聽起來節奏很快，而實際上觀眾盯著同一張
    # 圖看了二十秒。**數字要說真話**，所以在這裡併掉。
    thin: list[dict[str, Any]] = []
    for one in cuts:
        if thin and _same(thin[-1], one):
            continue
        thin.append(one)
    dropped = len(cuts) - len(thin)
    cuts = thin
    short = [one for i, one in enumerate(cuts[:-1])
             if cuts[i + 1]["at"] - one["at"] < LEAST]
    if short:
        # 不擋 —— 快切本來就是這種片的做法。但要出聲，而且說得出是哪幾格。
        say(f"⚠ {len(short)} 格短於 {LEAST} 秒："
            + "、".join(f"{one['at']:.2f}s" for one in short[:6]))

    body = {"seconds": heard["seconds"], "cuts": cuts}
    paths.save(story, "storyboard", body)
    look = {_shape(one) for one in cuts}
    longest = max((cuts[i + 1]["at"] - one["at"]
                   for i, one in enumerate(cuts[:-1])), default=0.0)
    say(f"\n{len(cuts)} 格　{heard['seconds']:.1f} 秒　"
        f"平均 {heard['seconds'] / len(cuts):.2f} 秒一格"
        + (f"　（併掉 {dropped} 個「切到一樣的畫面」）" if dropped else ""))
    say(f"  不同的畫面 {len(look)} 種　最久一格停 {longest:.1f} 秒")
    faint = sum(1 for one in cuts if one["faint"])
    if faint:
        say(f"  其中 {faint} 格有「小到看不出來」的地方，程式會改用標記")
    if len(look) < FEWEST:
        raise SystemExit(
            f"整支片只有 {len(look)} 種畫面（至少要 {FEWEST} 種）。"
            f"這是一張地圖看兩分鐘 —— 參考頻道 72 秒用了 14 種。"
            f"回去改 prompt，或加 --again 重問")
    if longest > STARE:
        say(f"⚠ 有一格停了 {longest:.1f} 秒沒換畫面（超過 {STARE}）")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "",
        again="--again" in sys.argv)
