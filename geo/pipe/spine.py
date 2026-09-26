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
import math
import re
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module

RULES = paths.GEO / "data" / "rules.json"

# 一句 point 裡有年份的樣子。「西元前 2500 年」「1953 年」「2026 年 9 月」
# 都算；「四千五百年前」那種相對時間不算 —— 它接得上上一句，年份不接。
YEAR = re.compile(r"(西元前\s*)?\d{3,4}\s*年|\b\d{4}\b")


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
    got_rules = rules()
    roles, got_shape = got_rules["roles"], got_rules["shape"]
    aim = float(spec.get("seconds") or 116)
    # **句數問寫台詞那一支，不要自己算。** 第一版這裡寫 `aim / 2.8`，
    # 排出 43 句 —— 而那個句數在字數額度下放不下，寫出來 129 秒（目標 116）。
    # 同一個數字兩個地方各算一次，就會有一個是錯的。
    from geo.pipe.script import budget as script_budget, rows_for
    rows = rows_for(aim)
    # **上下限算一次，門和 prompt 用同一份。** 只跟模型說「大約 30 句」而
    # 門在 27–33，等於罰它不知道的規矩 —— 它排 34 句被退，退回去的訊息
    # 才第一次告訴它真正的界線。
    #
    # **範圍從 ±12% 收到 ±6%，因為超排的代價不是「片子變長」。**
    # 秒數是固定的，所以多排的那幾句是從**每一句的字數**裡出的：
    #
    #   26 句 → 一句寫得下 16.8 字
    #   28 句 → 15.2 字      ← 落在舊範圍內，門不會叫
    #   29 句 → 14.4 字
    #
    # 上一趟就是這樣：門容許 23–29，它排 28，於是寫台詞那一步要把 29 個
    # 字的 point 壓成 15.2 字 —— 跑了四十分鐘沒寫出來。**門看得到句數，
    # 看不到每一句被壓得多扁**，而那才是真正壞掉的東西。
    fewest, most = math.ceil(rows * 0.94), math.floor(rows * 1.06)

    raw_at = paths.home(story) / "2-spine.raw.json"
    if again or paths.raw_stale(story, raw_at, "spine", ("spine.md",)):
        listing = "\n".join(
            f"{at:>3}　{one['said']}"
            + (f"　〔{'、'.join(one['entity'])}〕" if one["entity"] else "")
            for at, one in enumerate(facts, 1))
        got = ask.as_json(ask.send(story, "spine", ask.prompt_of(
            "spine.md", title=spec["title"], ask=spec.get("ask", ""),
            hero=spec.get("hero", ""), roles=roles_table(roles),
            facts=listing, count=len(facts), rows=rows,
            fewest=fewest, most=most,
            per_row=f"{script_budget(aim, rows) * 0.82 / rows:.1f}",
            per_row_most=f"{script_budget(aim, most) * 0.82 / most:.1f}",
            aside_gone=int(got_shape.get("aside_gone_most", 5)),
            refrain_most=int(got_shape.get("refrain_most", 10)),
            dated_most=f"{got_shape.get('dated_most', 0.3):.0%}",
            dated_rows=round(rows * got_shape.get("dated_most", 0.3))), say))
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

    # **refrain 要是「幾個字」，不是一整句。** 寫台詞那一步要把它原封不動
    # 用兩次，而**要模型把一整句話一字不差講兩次是機率，不是必然** ——
    # 17 字那一份就只出現了一次，整趟（406 秒、$1.06）被退回。
    #
    # 前兩份能過是因為剛好短（「沒有人問過它」6 字、「沒有人問過格陵蘭」
    # 8 字）。規則寫著「核心那幾個字」而沒有上限，靠的是運氣。
    refrain_len = len(re.sub(r"[，。！？、：；…—\s]", "",
                             str(got["refrain"])))
    cap_refrain = int(got_shape.get("refrain_most", 10))
    if refrain_len > cap_refrain:
        raise SystemExit(
            f"會回來的那句話有 {refrain_len} 個字（最多 {cap_refrain}）：\n"
            f"  「{got['refrain']}」\n"
            f"  這句話下一步要原封不動出現兩次，太長就複述不準。"
            f"留核心那幾個字就好。加 --again 重排")

    # **句數是有代價的，不是隨意的。** 一句話的固定開銷是 1.06 秒，
    # 所以多排四句就少四秒可以講話 —— 而字數額度是照句數反推的，句子
    # 越多每一句越短，短到裝不下主角＋內容（量過：12 字的時候主角被擠掉）。
    #
    # **上下限算一次。** 第一版比的是 `rows*1.12`、印的是 `round(rows*1.12)`
    # —— 30 句的片擋掉 34 句，然後告訴你「容許 26–34」。照著那句話改是改不
    # 過的，而錯的是那句話不是那個門。成品對、報告錯也是錯。
    if not fewest <= len(lines) <= most:
        raise SystemExit(
            f"排了 {len(lines)} 句，而 {aim:.0f} 秒放得下大約 {rows} 句"
            f"（容許 {fewest}–{most}）。\n"
            f"  一句話光是換氣就吃 1.06 秒，多排四句就少四秒可以講話，"
            f"而每一句會被壓到裝不下主角。加 --again 重排")

    # **年份本身沒有錯，整排都掛年份才是。** 第一版 17/33 句的 point
    # 綁著一個年份，寫成台詞之後 15/33 句帶年份 —— 而那是 narrate 修不掉
    # 的：「這一句要講 1953 年那件事」是這一步決定的。
    #
    # 每一句都可以獨立存在的稿子，就是一張清單。故事要的是每一句都接著
    # 上一句，而「後來」「同一年」「三年後」接得上，年份接不上。
    dated = [one for one in lines if YEAR.search(one["point"])]
    cap = float(got_shape.get("dated_most", 0.30))
    if len(dated) / len(lines) > cap:
        raise SystemExit(
            f"{len(dated)}/{len(lines)} 句的 point 綁著一個年份"
            f"（{len(dated) / len(lines):.0%}，上限 {cap:.0%}）—— "
            f"那會寫成一份年表。\n"
            f"  把幾件事合併成一句，或者用「後來」「同一年」「三年後」"
            f"這種接得上上一句的說法。加 --again 重排")

    # **下限擋不住「集中在前半段」。** 這一份三句吐槽落在第 4、11、14，
    # 而第 15–26 句 —— 最後十二句，也就是川普、關稅、簽約那一整段，觀眾
    # 最有感的地方 —— 一句態度都沒有。門數到 3 ≥ 2 就放行了。
    #
    # 數量和分布是兩件事，跟主角那道門（`HERO_GONE_MOST`）同一個形狀：
    # 「整篇提到幾次」和「有沒有一整段消失」要分開問。結尾之後不算，
    # 因為收尾本來就不吐槽。
    gone = most_gone = 0
    for one in lines:
        gone = 0 if one["role"] == "吐槽" else gone + 1
        most_gone = max(most_gone, gone)
    cap_gone = int(got_shape.get("aside_gone_most", 5))
    if most_gone > cap_gone:
        raise SystemExit(
            f"有一段連續 {most_gone} 句沒有「吐槽」（最多 {cap_gone}）"
            f" —— 那一段整段沒有態度，只是在推進劇情。\n"
            f"  吐槽總共 {sum(1 for x in lines if x['role'] == '吐槽')} 句，"
            f"數量夠了，問題是**它們擠在一起**。加 --again 重排")

    bad = check(lines, roles)
    if bad:
        raise SystemExit("骨幹的形狀不對：\n  " + "\n  ".join(bad)
                         + "\n\n加 --again 重排")

    body = {"turn": str(got["turn"]), "refrain": str(got["refrain"]),
            "ending": str(got.get("ending") or ""), "lines": lines}
    paths.save(story, "spine", body)

    kinds = [str(one["role"]) for one in lines]
    say(f"\n{len(lines)} 句　{len(dated)} 句綁年份"
        f"（{len(dated) / len(lines):.0%}，上限 {cap:.0%}）")
    # 截斷要看得出是截斷。沒有那三個點的話，「…到了今天，」讀起來像模型
    # 寫到一半停了 —— 而報告看起來壞掉，跟東西真的壞掉一樣會浪費人去查。
    def _cut(text: str, most: int) -> str:
        return text if len(text) <= most else text[:most] + "…"

    say(f"  轉：{_cut(body['turn'], 60)}")
    say(f"  會回來的那句：{body['refrain']}")
    say(f"  收：{_cut(body['ending'], 56)}")
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
