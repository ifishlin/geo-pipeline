"""分鏡：哪一段看哪裡、哪個接縫是斷點。

    python3 -m geo.pipe.make <題目> storyboard

模型回的是**名字和詞**：「從第 4 句的『北歐人』那裡切進來，看北歐和格陵蘭」。
這一支把它變成數字：

```
名字 → atlas 查外框 → camera.fit() 算中心和縮放
詞   → 在那一句的逐字時間裡找 → 秒數
```

**秒數從頭到尾沒有經過模型。**

## 一格要夠久，鏡頭才滑得動

第一版跟模型說「參考頻道 72 秒切了 130 次」—— 那是**紐約那支**，硬切風格。
而這支片對標的是格陵蘭那支，它從頭到尾在滑。結果是 125 格擠在 122 秒裡，
平均 0.85 秒，而一格短於 0.9 秒就動不了 —— **63 格只能硬切。不是設定調得
不好，是切點太多、沒有時間滑。**

現在 prompt 要的是「一格兩秒半」，而且硬切變成要**指名**的例外。

## 五道門

```
不認得的地方     raise
詞找不到／兩個   raise —— 對不到時間就是不知道第幾秒切
切點倒退         raise
畫面種類夠多     raise
畫面在講的地方   raise —— 台詞提到的地名要在那一格看得到
```

最後一道管的是整支片最容易破功的地方：講到「丹麥拒絕了」的時候鏡頭還停在
格陵蘭，觀眾得自己想像。**那不會報錯，畫面照樣畫得完。**
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import ask
from geo.pipe import camera as camera_module
from geo.pipe import paths, story as story_module

# 一格大約幾秒。**鏡頭要滑得動就得有時間** —— 兩秒半是舒服的，一秒以下
# 滑不動只能硬切，而連續幾個那種就是在閃。
AIM_SECONDS = 2.5

# 最多幾格（照 `AIM_SECONDS` 算出來的幾倍）。超過就是切太碎。
MOST_TIMES = 2.0

# 一個點單獨當鏡頭的時候，周圍要看到多大（經度、緯度各往外幾度）。
#
# **量出來的**：第一版給 ±0.4°／±0.25°，那是「剛好裝得下一個點」的框，
# 算出來 zoom 9.6 —— 紐約那一格變成街道圖，看不出是紐約；圖勒基地那一格
# 是一整片白色的冰。**相機算得完全正確，鏡頭完全沒用。**
AROUND = (7.0, 3.5)

# 整支片至少要有這麼多種不同的畫面。參考頻道 72 秒用了 14 種。
FEWEST = 8

# 一格停超過這麼久就出聲。不擋 —— 長鏡頭是一種選擇，但要被看見。
STARE = 8.0


def _around(spot: list[float]) -> list[float]:
    return [spot[0] - AROUND[0], spot[1] - AROUND[1],
            spot[0] + AROUND[0], spot[1] + AROUND[1]]


def _shape(one: dict[str, Any]) -> tuple:
    """這一格「長什麼樣」。相機一樣、塗的標的一樣，畫面上就是同一張圖。"""
    return (round(one["camera"]["center"][0], 2),
            round(one["camera"]["center"][1], 2),
            round(one["camera"]["zoom"], 2),
            tuple(sorted(one["tint"])), tuple(sorted(one["mark"])),
            tuple(sorted(one["faint"])))


def _fit(box: list[float], wide: int, high: int, spec: dict[str, Any],
         line: int, see: list[str], say) -> dict[str, Any]:
    """裝得下就照設定裝，裝不下就讓字幕那塊空間，還是不行才停。

    **一格裝不下不該讓整趟白費。** 模型挑了「美國＋挪威」，橫跨 156 度，
    算出來要 zoom 1.89 而畫面的地板是 1.91 —— 差 0.02，而前面三分鐘的
    模型呼叫、一分鐘的配音全部作廢。那一格是救得回來的。
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
        f"{wide}×{high} 的畫面裝不下 —— 9:16 最多看得到約 202 度經度。\n"
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


def _word_time(words: list[dict[str, Any]], start: float, end: float,
               want: str, line: str) -> float:
    """那個詞在第幾秒被唸出來。

    逐字事件是一個字一個字的，而詞是好幾個字，所以把落在這一句裡的字
    接起來，找詞的起點是第幾個字，再回頭查那個字的時間。
    """
    inside = [one for one in words if start - 0.02 <= one["at"] < end]
    joined = "".join(one["text"] for one in inside)
    if joined.count(want) == 0:
        raise SystemExit(
            f"「{want}」在這一句唸出來的字裡找不到：{line}\n"
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


def offscreen(cuts: list[dict[str, Any]], heard: dict[str, Any],
              atlas: dict[str, Any], whole: float) -> list[str]:
    """哪幾句在講一個畫面上看不到的地方。

    **這是整支片最容易破功的地方**：講到「丹麥拒絕了」的時候鏡頭還停在
    格陵蘭，觀眾得自己想像。而它不會報錯 —— 畫面照樣畫得完、每一格都對，
    只是跟聲音講的不是同一件事。

    判準寬一點：一句話可能橫跨兩三格，只要**其中一格**看得到就算數；
    `mark` 也算看得到。嚴格要求每一格都有的話，一句話裡提到三個地方就
    不可能過。
    """
    from geo.pipe.atlas import found_in
    named = {name: name for name in atlas}
    spots = {name: one for name, one in atlas.items()
             if one["kind"] == "point"}
    bad: list[str] = []
    for at, (start, end) in enumerate(heard["bounds"]):
        text = heard["lines"][at]
        want = found_in(text, named, spots)
        if not want:
            continue
        shown: set[str] = set()
        for i, one in enumerate(cuts):
            until = cuts[i + 1]["at"] if i + 1 < len(cuts) else whole
            if until > start + 0.15 and one["at"] < end - 0.15:
                shown |= set(one["see"]) | set(one["mark"])
        missing = [x for x in want if x not in shown]
        if missing:
            bad.append(f"第 {at} 句講「{'、'.join(missing)}」而畫面上沒有"
                       f"：{text[:24]}")
    return bad


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "storyboard")
    spec = story_module.load(story)
    atlas = paths.load(story, "atlas")
    bones = paths.load(story, "spine")
    heard = json.loads(
        (paths.at(story, "voice") / "said.json").read_text(encoding="utf-8"))
    whole = float(heard["seconds"])
    aim = max(6, round(whole / AIM_SECONDS))

    raw_at = paths.home(story) / "6-storyboard.raw.json"
    if again or paths.raw_stale(story, raw_at, "storyboard"):
        nodes = "\n".join(
            f"- {one.get('when', '')}　〔{one['beat']}〕{one['what'][:44]}"
            for one in bones["nodes"])
        lines = "\n".join(
            f"{at:>3}　{who}　{text}"
            for at, (who, text) in enumerate(zip(heard["who"],
                                                 heard["lines"])))
        got = ask.as_json(ask.send(story, "storyboard", ask.prompt_of(
            "storyboard.md", places=_places_table(atlas),
            title=spec["title"], turn=bones["turn"],
            ending=bones.get("ending", ""), nodes=nodes, lines=lines,
            seconds=f"{whole:.0f}", count=len(heard["lines"]),
            aim=aim, most=round(aim * MOST_TIMES)), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    rows = got.get("shots") or []
    if not rows:
        raise SystemExit("一格都沒有")
    wide, high = spec["video"]["width"], spec["video"]["height"]
    cuts: list[dict[str, Any]] = []
    for one in rows:
        at = int(one.get("line", -1))
        if not 0 <= at < len(heard["lines"]):
            raise SystemExit(f"這一格指向第 {at} 句，而只有 "
                             f"{len(heard['lines'])} 句")
        start, end = heard["bounds"][at]
        want = str(one.get("word") or "")
        when = start if not want else _word_time(
            heard["words"], start, end, want, heard["lines"][at])
        see = [str(x) for x in (one.get("see") or [])]
        if not see:
            raise SystemExit(f"第 {at} 句那一格沒說要看哪裡")
        for key in ("see", "mark", "tint"):
            bad = [x for x in (one.get(key) or []) if x not in atlas]
            if bad:
                raise SystemExit(
                    f"第 {at} 句的 {key} 有 atlas 裡沒有的：{'、'.join(bad)}。"
                    f"有的是：{'、'.join(atlas)}")
        boxes = [atlas[x]["bbox"] for x in see if atlas[x]["kind"] == "area"]
        boxes += [_around(atlas[x]["at"]) for x in see
                  if atlas[x]["kind"] == "point"]
        shot = _fit(camera_module.merge(boxes), wide, high, spec, at, see, say)
        tint = [str(x) for x in (one.get("tint") or see)]
        cuts.append({
            "at": round(when, 3), "line": at, "word": want,
            "see": see, "mark": [str(x) for x in (one.get("mark") or [])],
            "tint": [x for x in tint if atlas[x]["kind"] == "area"],
            "cut": bool(one.get("cut")),
            "why": str(one.get("why") or ""), "camera": shot,
            "faint": [x for x in tint
                      if atlas[x]["kind"] == "area"
                      and camera_module.too_small(shot, atlas[x]["bbox"])],
        })

    cuts.sort(key=lambda one: one["at"])
    if cuts[0]["at"] > 0.05:
        # 第一格不從 0 開始＝開頭那一段沒有人決定過要看什麼。
        cuts[0]["at"] = 0.0
        cuts[0]["cut"] = True
    thin: list[dict[str, Any]] = []
    for one in cuts:
        if thin and _shape(thin[-1]) == _shape(one):
            continue
        thin.append(one)
    dropped = len(cuts) - len(thin)
    cuts = thin

    gap = offscreen(cuts, heard, atlas, whole)
    if gap:
        raise SystemExit(
            f"有 {len(gap)} 句在講畫面上看不到的地方：\n  "
            + "\n  ".join(gap[:8])
            + "\n\n聲音說丹麥而畫面是格陵蘭，觀眾得自己想像，"
              "而那不會報錯。加 --again 重問")

    look = {_shape(one) for one in cuts}
    spans = [cuts[i + 1]["at"] - one["at"] for i, one in enumerate(cuts[:-1])]
    spans.append(whole - cuts[-1]["at"])
    hard = sum(1 for one in cuts if one["cut"])
    say(f"\n{len(cuts)} 格　{whole:.1f} 秒　平均 {whole / len(cuts):.1f} 秒一格"
        + (f"　（併掉 {dropped} 個一樣的）" if dropped else ""))
    say(f"  不同的畫面 {len(look)} 種　最短 {min(spans):.1f}s　"
        f"最長 {max(spans):.1f}s")
    say(f"  模型標了 {hard} 個硬切，其餘 {len(cuts) - hard} 個要滑過去")
    short = sum(1 for one in spans if one < 1.0)
    if short:
        say(f"⚠ {short} 格短於 1 秒 —— 那幾格滑不動，只能硬切")
    if len(look) < FEWEST:
        raise SystemExit(f"整支片只有 {len(look)} 種畫面（至少 {FEWEST} 種）")
    if max(spans) > STARE:
        say(f"⚠ 有一格停了 {max(spans):.1f} 秒沒換畫面")
    paths.save(story, "storyboard", {"seconds": whole, "cuts": cuts})
    return {"cuts": cuts}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
