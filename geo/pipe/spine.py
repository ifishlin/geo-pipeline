"""事實 → 骨幹。**每一句宣告它在幹嘛，然後檢查那個宣告。**

    python3 -m geo.pipe.make <題目> spine

## 為什麼骨幹要排到「句」，不是「節點」

第一版的節點是「哪一年發生什麼」—— 十三個節點、三種 beat。那是一張日期
表，所以下一步最省力的寫法就是一行一個年份：

```
1953 年，丹麥修憲。
1973 年，丹麥加入歐洲共同體。
1979 年，自治法公投通過。
```

十五句旁白有十三句這樣開頭。**而每一句單看都對**，所以沒有任何一道門攔得
下來 —— 攔不下來是因為沒有東西可以攔：「好不好看」不是一個欄位。

現在每一句要標 `role`（反常／起點／吐槽／翻面／收……），就攔得下來了：
一整排都是「事件」的話，一眼看得出這支片沒有態度、沒有翻面。

這是舊專案 `assets/prompts/spine.md` 的做法（417 行、六道門）。我一開始把
它簡化成 96 行，而**簡化掉的正好是說故事的那一層**。

## 詞彙先分細，之後拿數據併

十一種。卡片那邊做過一次相反的：一開始十六種，**量到模型只用過六種**，
才收成七種 —— 拿數據收的，不是憑感覺。所以這一支每次都印出各種用了幾句。
"""
from __future__ import annotations

import json
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module

RULES = paths.GEO / "data" / "rules.json"


def rules() -> dict[str, Any]:
    got = json.loads(RULES.read_text(encoding="utf-8"))
    return {k: v for k, v in got.items() if not k.startswith("_")}


def roles_table(roles: dict[str, Any]) -> str:
    """給模型看的那張表。

    **從設定檔長出來，不是手寫的散文** —— 手寫的話加一種角色要改兩個
    地方，而漏掉的那一邊不會報錯。
    """
    out = []
    for name, one in roles.items():
        limits = []
        if one.get("least"):
            limits.append(f"至少 {one['least']} 句")
        if one.get("most"):
            limits.append(f"最多 {one['most']} 句")
        at = str(one.get("at") or "")
        if at == "first":
            limits.append("只能是第一句")
        elif at == "last":
            limits.append("只能是最後一句")
        elif at.startswith("before"):
            limits.append(f"要落在前 {float(at.split()[1]):.0%}")
        out.append(
            f"**{name}** —— {one['what']}"
            + (f"　〔{'、'.join(limits)}〕" if limits else "")
            + f"\n  例：{one['eg']}")
    return "\n\n".join(out)


def check(lines: list[dict[str, Any]], roles: dict[str, Any]) -> list[str]:
    """宣告合不合規矩。回一串說得出口的問題。"""
    bad: list[str] = []
    kinds = [str(one.get("role") or "") for one in lines]
    unknown = sorted({one for one in kinds if one not in roles})
    if unknown:
        return [f"不認得的 role：{'、'.join(unknown)}。"
                f"可以用的是 {'、'.join(roles)}"]
    for name, one in roles.items():
        got = kinds.count(name)
        if one.get("least") and got < one["least"]:
            bad.append(f"「{name}」只有 {got} 句（至少 {one['least']}）"
                       f"—— {one['what']}")
        if one.get("most") and got > one["most"]:
            bad.append(f"「{name}」有 {got} 句（最多 {one['most']}）")
        at = str(one.get("at") or "")
        spots = [i for i, x in enumerate(kinds) if x == name]
        if at == "first" and spots and spots != [0]:
            bad.append(f"「{name}」要在第一句，而它在第 {spots[0]} 句")
        if at == "last" and spots and spots[-1] != len(kinds) - 1:
            bad.append(f"「{name}」要在最後，而最後一句是「{kinds[-1]}」")
        if at.startswith("before") and spots:
            share = float(at.split()[1])
            if spots[0] / len(kinds) > share:
                bad.append(
                    f"「{name}」第一次出現在第 {spots[0]} 句"
                    f"（{spots[0] / len(kinds):.0%}），要落在前 {share:.0%}"
                    f" —— 翻得太晚，前面那一大段沒有方向")
    return bad


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "spine")
    spec = story_module.load(story)
    facts = paths.load(story, "facts")
    roles = rules()["roles"]
    aim = float(spec.get("seconds") or 116)
    # **句數問寫台詞那一支，不要自己算。** 第一版這裡寫 `aim / 2.8`，
    # 排出 43 句 —— 而那個句數在字數額度下放不下，寫出來 129 秒（目標 116）。
    # 同一個數字兩個地方各算一次，就會有一個是錯的。
    from geo.pipe.script import rows_for
    rows = rows_for(aim)

    raw_at = paths.home(story) / "2-spine.raw.json"
    if again or paths.raw_stale(story, raw_at, "spine"):
        listing = "\n".join(
            f"{at:>3}　{one['said']}"
            + (f"　〔{'、'.join(one['entity'])}〕" if one["entity"] else "")
            for at, one in enumerate(facts, 1))
        got = ask.as_json(ask.send(story, "spine", ask.prompt_of(
            "spine.md", title=spec["title"], ask=spec.get("ask", ""),
            hero=spec.get("hero", ""), roles=roles_table(roles),
            facts=listing, count=len(facts), rows=rows), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    lines = got.get("lines") or []
    if not lines:
        raise SystemExit("骨幹是空的 —— 要的是一句一筆的清單，不是節點")
    for at, one in enumerate(lines):
        if not str(one.get("point") or "").strip():
            raise SystemExit(f"第 {at} 句沒有 point（這一句要讓觀眾知道什麼）")
        bad = [x for x in (one.get("from") or [])
               if not isinstance(x, int) or not 1 <= x <= len(facts)]
        if bad:
            raise SystemExit(f"第 {at} 句引的事實編號不存在：{bad}")
    for key, why in (("turn", "整支片在翻什麼"),
                     ("refrain", "會回來的那句話的核心幾個字")):
        if not str(got.get(key) or "").strip():
            raise SystemExit(f"沒有寫 {key} —— {why}")

    bad = check(lines, roles)
    if bad:
        raise SystemExit("骨幹的形狀不對：\n  " + "\n  ".join(bad)
                         + "\n\n加 --again 重排")

    body = {"turn": str(got["turn"]), "refrain": str(got["refrain"]),
            "ending": str(got.get("ending") or ""), "lines": lines}
    paths.save(story, "spine", body)

    kinds = [str(one["role"]) for one in lines]
    say(f"\n{len(lines)} 句")
    say(f"  轉：{body['turn'][:60]}")
    say(f"  會回來的那句：{body['refrain']}")
    say(f"  收：{body['ending'][:56]}")
    say("")
    # **每次都印各種用了幾句。** 詞彙先分細再併，而「該併哪幾種」要拿
    # 數據決定 —— 一次都沒被用過的那幾種，累積幾支片就看得出來。
    for name in roles:
        got_ = kinds.count(name)
        say(f"  {name:<4}{got_:>3}　{'▮' * got_ if got_ else '—'}")
    never = [x for x in roles if x not in kinds]
    if never:
        say(f"  （這幾種一次都沒用：{'、'.join(never)}）")
    return body


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
