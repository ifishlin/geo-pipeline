"""這一支片會用到哪些地方，以及各自的相機。

    python3 -m geo.pipe.make <題目> atlas

讀 `3-script.tsv`，**把稿子裡出現的地名掃出來**，一個一個解析成：

```
geoId     畫的時候要指哪一塊（國家用 ISO3，集合用 _EU 這種，點沒有）
bbox      主體外框
camera    只看它一個的時候，相機在哪
```

## 為什麼用掃的，不是列一張表

列表要人維護，而漏掉一個的症狀是「模型想指那塊地，但它不在清單上」——
然後模型會挑一個看起來差不多的。掃出來的話，稿子改了地名自己會跟著變。

掃的依據是 `geo/data/places.json` 的中文名（Natural Earth 的 `NAME_ZHT`）
和 `geo/data/points.json`。兩份都是資料，不是我打的表。

## 一個沒擋的洞，寫在這裡

掃字串會漏掉「沒有被直接講出名字」的地方 —— 稿子寫「聯合國大會場邊」，
掃不到紐約。那不是 bug，是這個做法的邊界：**故事檔的 `places` 可以補**，
補的那幾個會在報告裡標 `+`，看得見自己補了什麼。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import camera as camera_module
from geo.pipe import paths, story as story_module
from geo.pipe import voice as voice_module

PLACES = paths.GEO / "data" / "places.json"
POINTS = paths.GEO / "data" / "points.json"


def known() -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """（每塊地, 中文名→id, 點）。"""
    got = json.loads(PLACES.read_text(encoding="utf-8"))
    spots = json.loads(POINTS.read_text(encoding="utf-8"))["points"]
    spots = {k: v for k, v in spots.items() if not k.startswith("_")}
    # 別名展開成一樣的點。**指回同一筆**，不是抄一份 —— 抄的話改了本體
    # 別名不會跟著動，而不同步的那份不會報錯。
    for name, one in list(spots.items()):
        for other in one.get("also") or []:
            if other in spots:
                raise SystemExit(f"別名「{other}」撞到已經有的點")
            spots[other] = one
    return got["places"], got["named"], spots


def found_in(text: str, named: dict[str, str], spots: dict[str, Any]
             ) -> list[str]:
    """這段字裡出現過哪些認得的地名。

    **長的先比**：有「南非」也有「非洲」的時候，先認長的那一個，
    不然「南非」會被拆成兩半，而兩半都認得出東西。
    """
    out: list[str] = []
    for name in sorted(set(named) | set(spots), key=len, reverse=True):
        if name in text and not any(name in one for one in out):
            out.append(name)
    return out


def run(story: str, say=print) -> dict[str, Any]:
    paths.insist(story, "atlas")
    spec = story_module.load(story)
    places, named, spots = known()
    rows = voice_module.read_script(story)
    said = "　".join(text for who, text in rows if who != "停")

    seen = found_in(said, named, spots)
    extra = [one for one in (spec.get("places") or []) if one not in seen]
    unknown = [one for one in extra if one not in named and one not in spots]
    if unknown:
        raise SystemExit(
            f"故事檔的 places 裡有查不到的地方：{'、'.join(unknown)}。"
            f"國家和大區看 geo/data/places.json，城市和基地看 points.json；"
            f"真的沒有就去 points.json 加一筆（要寫 note）")

    wide = spec["video"]["width"]
    high = spec["video"]["height"]
    out: dict[str, Any] = {}
    for name in seen + extra:
        if name in named:
            key = named[name]
            got = places[key]
            shot = camera_module.fit(got["bbox"], wide, high,
                                     pad=spec["pad"], hold=spec["hold"],
                                     lift=spec["lift"])
            out[name] = {"kind": "area", "geoId": key,
                         "draw": got.get("of") or [key],
                         "bbox": got["bbox"], "at": got["label"],
                         "camera": shot}
        else:
            got = spots[name]
            out[name] = {"kind": "point", "at": got["at"],
                         "note": got.get("note", "")}

    say(f"稿子裡掃到 {len(seen)} 個地方"
        + (f"，故事檔補了 {len(extra)} 個" if extra else ""))
    say("")
    say(f"{'地方':<14}{'種類':<6}{'id':<10}{'zoom':>6}")
    for name, got in out.items():
        mark = "＋" if name in extra else "　"
        if got["kind"] == "area":
            say(f"{mark}{name:<13}{'一塊地':<6}{got['geoId']:<10}"
                f"{got['camera']['zoom']:>6.2f}"
                + (f"　{len(got['draw'])} 塊" if len(got["draw"]) > 1 else ""))
        else:
            say(f"{mark}{name:<13}{'一個點':<6}{str(got['at']):<18}{got['note']}")
    paths.save(story, "atlas", out)
    return out


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
