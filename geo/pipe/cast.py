"""誰可以在這支片裡講話。

**模型提案、你可以改、檔案說了算。**

    python3 -m geo.pipe.cast <題目>          沒有 cast 才問
    python3 -m geo.pipe.cast <題目> --again  重問一次

## 為什麼要這一步

在這之前 `story.json` 的 `cast` 是我開題目的時候手打的，沒有任何一步去想
「這個故事需要誰講話」。後果是像挪威、歐洲共同體這些在事實裡出現過的
地方，從頭到尾沒有發言的可能 —— **不是因為不該講，是因為我沒打上去**。

而材料一直都在：事實清單每一則都帶 `entity`（這一則牽涉到哪些地方），
那就是「這個故事裡有誰」的原始資料。

## 誰決定什麼

```
模型   挑誰、說出「這個地方在這故事裡有什麼立場」
程式   配聲音（哪個嗓子）、擋掉戲份太少的、擋掉超過位子數的
你     改 story.json，改了就算數 —— 這一步看到有 cast 就不問了
```

**誰講話是語義，用哪個嗓子是機械。** 上一版那一欄把兩件事混在一起，
所以想換角色就得順便想音色。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module


def _tally(facts: list[dict[str, Any]]) -> dict[str, int]:
    """每個地方在幾則事實裡出現過。**戲份的唯一客觀來源。**"""
    out: dict[str, int] = {}
    for one in facts:
        for who in one.get("entity") or []:
            out[who] = out.get(who, 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def settle(story: str, say=print, again: bool = False) -> dict[str, str]:
    """回 `{角色: 位子}`。已經有了就原樣回去。"""
    spec = story_module.load(story)
    got = spec.get("cast")
    if isinstance(got, dict) and len(got) > 1 and not again:
        return {k: str(v) for k, v in got.items()}

    facts = paths.load(story, "facts")
    seats = [k for k in story_module.voices() if k != "narrator"]
    react = json.loads((paths.GEO / "data" / "rules.json")
                       .read_text(encoding="utf-8"))["parts"]
    least = int(react.get("cast_least_facts", 3))
    counted = _tally(facts)
    # **先把撐不起來的濾掉再問。** 出現兩次的地方沒有幾個位置可以接話，
    # 挑了也只能硬寫。與其事後退回，不如一開始就不給它選。
    enough = {k: v for k, v in counted.items() if v >= least}
    hero = str(spec.get("hero") or "")

    listing = "\n".join(f"  {name:<10}在 {n} 則事實裡"
                        for name, n in enough.items())
    said = ask.as_json(ask.send(story, "cast", ask.prompt_of(
        "cast.md", title=spec["title"], ask=spec.get("ask", ""),
        hero=hero, places=listing, most=len(seats),
        least_facts=least), say))

    picked = said.get("cast") or []
    if not picked:
        raise SystemExit("沒有挑出任何角色")
    names: list[str] = []
    why: dict[str, str] = {}
    for one in picked:
        name = str(one.get("who") or "").strip()
        if name not in enough:
            raise SystemExit(
                f"挑了「{name}」，而它不在可以挑的清單裡"
                f"（要在至少 {least} 則事實裡出現過）。"
                f"可以挑的是：{'、'.join(enough)}")
        if name in names:
            raise SystemExit(f"「{name}」挑了兩次")
        if not str(one.get("why") or "").strip():
            raise SystemExit(f"「{name}」沒有寫理由 —— "
                             f"寫不出它的立場，它就沒有話可以講")
        names.append(name)
        why[name] = str(one["why"]).strip()
    if len(names) > len(seats):
        raise SystemExit(
            f"挑了 {len(names)} 個，而只有 {len(seats)} 個聲音位子"
            f"（{'、'.join(seats)}）")
    if hero and hero not in names:
        raise SystemExit(f"主角「{hero}」沒有被挑進來 —— "
                         f"它不講話的話，這支片就是在講它的事而不是它的故事")

    # **配聲音是程式的事。** 主角先配第一個位子，其餘照戲份排 ——
    # 一樣的輸入永遠得到一樣的結果，換一次角色不會連音色一起換掉。
    order = [hero] + [x for x in names if x != hero] if hero else names
    cast = {"旁白": "narrator"}
    for name, seat in zip(order, seats):
        cast[name] = seat

    at = paths.home(story) / "story.json"
    spec_raw = json.loads(at.read_text(encoding="utf-8"))
    spec_raw["cast"] = cast
    spec_raw["cast_why"] = why
    at.write_text(json.dumps(spec_raw, ensure_ascii=False, indent=1),
                  encoding="utf-8")

    say(f"\n挑了 {len(names)} 個角色（{len(enough)} 個地方夠格，"
        f"{len(counted) - len(enough)} 個戲份太少）")
    for name in order:
        say(f"  {name:<8}{cast[name]:<12}{counted[name]:>3} 則　{why[name]}")
    say(f"  （改 story.json 的 cast 就算數，這一步看到有 cast 就不問了）")
    return cast


if __name__ == "__main__":
    settle(sys.argv[1] if len(sys.argv) > 1 else "",
           again="--again" in sys.argv)
