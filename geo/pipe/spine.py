"""事實 → 骨幹。時間線的節點、轉在哪、怎麼收。

    python3 -m geo.pipe.make <題目> spine

## 為什麼骨幹要單獨存一份

因為**改台詞不該重排骨幹**。台詞會改很多次（長度、語氣、笑點），而
「這支片從哪講到哪」通常一次就定了。分開存，重寫台詞的時候骨架沿用。

隔壁那個專案量過：挑畫面那一步 28 分鐘、$3.19，而骨幹加台詞四百多秒。
把它們綁在一起，改一個字就要付全部的錢。

## 三道門

```
beat 只有三種            模型很愛自己發明第四種
至少一個 turn 和 payoff  全是 setup 的話那是流水帳，不是一支片
from 指得到              指向不存在的事實編號＝這一格沒有出處
```
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module

BEATS = ("setup", "turn", "payoff")

# 一支兩分鐘的片大概放得下幾個節點。**算出來的**：36 句台詞、一個節點
# 通常兩三句，所以十幾個。這個數字只印進 prompt 當參考，不當門 ——
# 節點多寡是判斷，不是規則。
def room_for(seconds: float) -> int:
    return max(4, round(seconds / 9))


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "spine")
    spec = story_module.load(story)
    facts = paths.load(story, "facts")
    aim = float(spec.get("seconds") or 116)

    raw_at = paths.home(story) / "2-spine.raw.json"
    if again or paths.raw_stale(story, raw_at, "spine"):
        listing = "\n".join(
            f"{at:>3}　{one['said']}"
            + (f"　〔{'、'.join(one['entity'])}〕" if one["entity"] else "")
            for at, one in enumerate(facts, 1))
        got = ask.as_json(ask.send(story, "spine", ask.prompt_of(
            "spine.md", title=spec["title"], ask=spec.get("ask", ""),
            facts=listing, count=len(facts), room=room_for(aim)), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    nodes = got.get("nodes") or []
    if not nodes:
        raise SystemExit("骨幹是空的")
    for at, one in enumerate(nodes):
        beat = str(one.get("beat") or "")
        if beat not in BEATS:
            raise SystemExit(
                f"第 {at} 個節點的 beat 是 {beat!r}，只能是 "
                f"{'、'.join(BEATS)}。**不替它挑一個** —— 挑了的話那一格"
                f"在整條線上的角色就是我決定的，不是寫的人決定的")
        bad = [x for x in (one.get("from") or [])
               if not isinstance(x, int) or not 1 <= x <= len(facts)]
        if bad:
            raise SystemExit(f"第 {at} 個節點引的事實編號不存在：{bad}")
    kinds = {one: sum(1 for x in nodes if x["beat"] == one) for one in BEATS}
    if not kinds["turn"] or not kinds["payoff"]:
        raise SystemExit(
            f"整條線 {kinds} —— 沒有 turn 或沒有 payoff 的話，"
            f"那是一串事情，不是一支片")
    if not str(got.get("turn") or "").strip():
        raise SystemExit("沒有寫 turn 那一句 —— 那一句寫不出來，"
                         "通常表示這條線只是流水帳")

    body = {"turn": str(got.get("turn")), "ending": str(got.get("ending") or ""),
            "nodes": nodes}
    paths.save(story, "spine", body)
    say(f"\n{len(nodes)} 個節點　"
        + "　".join(f"{k} {v}" for k, v in kinds.items()))
    say(f"  轉：{body['turn']}")
    say(f"  收：{body['ending']}")
    for one in nodes:
        say(f"  {str(one.get('when','')):<8}{one['beat']:<8}{one['what'][:40]}")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
