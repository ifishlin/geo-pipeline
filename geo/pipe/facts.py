"""來源 → 事實清單。每一則帶 quote 和 entity。

    python3 -m geo.pipe.make <題目> facts

## quote 是這條路的骨頭

每一則事實要**逐字抄**一小段原文，而程式回頭去原文裡比對，比不到就退回。

這件事在隔壁那個專案付過學費：15 句台詞句句忠實於它引的事實，而挑畫面的
那一步從另一張清單挑，兩張清單零個連結 —— 對不上是結構必然。修法不是加
一道比對的門，是**讓它們從同一個地方長出來**。

這邊的 `entity` 就是那條連結：畫面只能從事實提過的地方裡挑。

## 比對要寬一點，但不能寬到沒有

原文抓回來會有多餘的空白、全形半形不一致。所以比對前兩邊都**把空白拿掉**，
但**字本身一個都不准差** —— 允許改字的話，這道門就只是在問「你有沒有寫東西」。
"""
from __future__ import annotations

import re
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module


def _bare(text: str) -> str:
    """拿掉空白，其他不動。"""
    return re.sub(r"\s+", "", text)


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "facts")
    spec = story_module.load(story)
    rows = paths.load(story, "sources")
    bodies = [(paths.home(story) / one["file"]).read_text(encoding="utf-8")
              for one in rows]

    raw_at = paths.home(story) / "1-facts.raw.json"
    if again or paths.raw_stale(story, raw_at, "facts", ("facts.md",)):
        listing = "\n\n".join(
            f"### 來源 {at}　（{one['kind']}　{one['why']}）\n{one['url']}\n\n"
            + body[:24000]
            for at, (one, body) in enumerate(zip(rows, bodies), 1))
        got = ask.as_json(ask.send(story, "facts", ask.prompt_of(
            "facts.md", title=spec["title"], ask=spec.get("ask", ""),
            sources=listing), say))
        raw_at.write_text(__import__("json").dumps(
            got, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = __import__("json").loads(raw_at.read_text(encoding="utf-8"))

    kept: list[dict[str, Any]] = []
    lost: list[str] = []
    for one in (got.get("facts") or []):
        quote = str(one.get("quote") or "")
        at = int(one.get("where") or 0)
        if not quote or not 1 <= at <= len(bodies):
            lost.append(f"{str(one.get('said'))[:26]}…（沒有 quote 或來源編號錯）")
            continue
        if _bare(quote) not in _bare(bodies[at - 1]):
            # 在別的來源裡找得到的話，是編號寫錯，救得回來。
            other = [i + 1 for i, body in enumerate(bodies)
                     if _bare(quote) in _bare(body)]
            if other:
                at = other[0]
            else:
                lost.append(f"{str(one.get('said'))[:26]}…（quote 在原文裡找不到）")
                continue
        kept.append({"said": str(one.get("said") or ""), "quote": quote,
                     "where": at, "url": rows[at - 1]["url"],
                     "entity": [str(x) for x in (one.get("entity") or [])]})

    if not kept:
        raise SystemExit("一則事實都沒有留下來 —— 全部的 quote 都對不上原文")
    say(f"\n{len(kept)} 則留下　{len(lost)} 則退回")
    for one in lost[:8]:
        say(f"  退回　{one}")
    spots: dict[str, int] = {}
    for one in kept:
        for name in one["entity"]:
            spots[name] = spots.get(name, 0) + 1
    say(f"  提到 {len(spots)} 個地方："
        + "、".join(f"{k}({v})" for k, v in
                    sorted(spots.items(), key=lambda x: -x[1])[:10]))
    if not spots:
        raise SystemExit(
            "沒有任何一則事實提到地方 —— 那畫面就沒有東西可以挑。"
            "entity 那一欄是事實和地圖之間唯一的連結")
    paths.save(story, "facts", kept)
    return {"facts": kept}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
