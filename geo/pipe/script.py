"""骨幹 → 台詞。**兩支 prompt，兩件事。**

    python3 -m geo.pipe.make <題目> script
    python3 -m geo.pipe.make <題目> script --plain    只寫旁白，不配角色

```
script.md   寫旁白稿。一個聲音從頭講到尾，故事要完整
parts.md    挑幾句改成角色講。**取代，不是追加**
```

## 為什麼分開

第一版一支 prompt 同時要「講好故事」和「有對白」，寫出來是這樣：

```
旁白    1814 年，挪威被劃給瑞典。
丹麥    格陵蘭歸我。
格陵蘭  一場跟我無關的敗仗，我換了主人。
```

**旁白先把事實講完，角色再用第一人稱複述一次。** 資訊已經到了，然後有
個聲音進來把同一件事再說一遍 —— 那就是「突兀」的來源：對白不是事件，
是註解。

分開之後，第二支回的是「第 12 句改成丹麥講、內容改寫成這樣」，程式做
替換。句子總數不變，所以**重複在結構上不可能發生**。

## 四道門是拿參考片量出來的

```
                參考片   訂的範圍
角色佔比         0.39    0.25–0.45
群數             6       3–8
最長一群         4       ≤4
最長旁白連續     6       ≥4
```

參考片四道全過，我們第一版三道不過（0.64／14 群／最長旁白 2 句）。

**訂一組連要模仿的東西都過不了的門，是沒有意義的。**
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module
from geo.pipe.spine import rules as _rules

# 唸多久 ＝ 字數 / RATE ＋ 句數 × PER_LINE ＋ 宣告的停頓。
# 兩個數字是拿兩次真實合成解出來的（572 字 36 句 → 116.74 秒；
# 585 字 49 句 → 133.10 秒）。句數那一項很大：字數只差 13 個，秒數差 16 秒。
# 唸多久 ＝ 字數/RATE ＋ 行數×PER_LINE ＋ 句號數×PER_END ＋ 宣告的停頓
#
# **句號比行更貴，而且擋不掉。** 第一版只有「每行 1.06 秒」，那是把兩件事
# 混成一個數字。拆開是量出來的：
#
#   整份稿子   41 行、54 個句號、564 字 → 開銷 43.5 秒
#   單獨測     1 行、4 個句號、28 字   → 開銷 2.2 秒
#
#   兩式解出   每行 0.50 秒　每個句號 0.425 秒
#   驗算       41×0.50 + 54×0.425 = 43.5 ✅
#
# 那 0.425 秒是 Azure 自己在句號後面加的，關不掉：把 `sentence_gap_ms`
# 從 150 調到 0，四個句號只省 0.34 秒（而從預設調到 150 省了 1.18 秒，
# 所以那一格本身是有效的，只是已經調到底了）。
#
# 可以動的是**句號的數量**：一行寫一句，比一行寫三句省 0.85 秒。
RATE = 8.22
PER_LINE = 0.50
PER_END = 0.425

# 一行幾個字、幾個句號。**一行一句** —— 多一個句號就多 0.425 秒，
# 而那些秒數本來可以拿去講話。
PER_ROW = 21
PER_ROW_ENDS = 1

HOLDS = 10.0
SLACK = 0.06

# 一行最多幾個句尾標點。超過就是把三句話塞在一行裡，每一個都在付錢。
ENDS_MOST = 2

# 旁白自己的形狀。**「年份開頭」不是錯的寫法，整篇都這樣才是** ——
# 那是一張清單，不是一個故事。所以是上限，不是禁止。
DATE_HEAD_MOST = 0.30
HERO_LEAST = 0.35
# 主角最多連續幾行不出現。比例是弱的代理，「整段消失」才是要擋的。
HERO_GONE_MOST = 5

# 角色對白的形狀，四個數字都拿參考片驗過（見模組說明）。
SHARE = (0.25, 0.45)
RUNS = (3, 8)
RUN_MOST = 4
NARRATION_RUN = 4

DATE = re.compile(r"\d+\s*年(\s*\d+\s*月)?(\s*\d+\s*日)?")

# 句子開頭就是時間。「同一年」「四千五百年前」也算 —— 它們一樣把句子
# 變成年表的一列。
DATE_HEAD = re.compile(
    r"^\s*(\d|[一二三四五六七八九十百千萬]+\s*年前|同一年|隔年|後來|"
    r"到了|直到)")


def _numbers(text: str) -> int:
    """這句話裡有幾個「要記住的數字」。一個完整日期算一個。

    **只數阿拉伯數字。** 中文數字（「八個盟國」）抓不到 —— 要抓就得分辨
    「三個主人」和「八個盟國」，那條界線我畫不出來。寧可漏也不要亂叫。
    """
    return len(re.findall(r"\d+(?:[.,]\d+)*", DATE.sub("〇", text)))


def _han(text: str) -> int:
    """唸得出來的字數：漢字加數字，不算標點。"""
    return len(re.findall(r"[一-鿿]", text)) + \
        sum(len(one) for one in re.findall(r"\d+", text))


def guess(said: int, rows: int, holds: float, ends: int | None = None) -> float:
    """唸出來大概幾秒。`ends` 不給就假設一行一句。"""
    return (said / RATE + rows * PER_LINE
            + (rows if ends is None else ends) * PER_END + holds)


def _ends(text: str) -> int:
    """這一行有幾個句尾標點。每一個都要 0.425 秒。"""
    return len(re.findall(r"[。！？：；]", text))


def rows_for(aim: float) -> int:
    """這麼多秒放得下幾句。

    **只有這一支算得出這個數字。** 骨幹排幾句和台詞的字數額度是同一件事
    的兩面：`秒 = 字/RATE + 句×PER_LINE + 停`，而 `字 = 句×PER_ROW`。
    兩邊各算一次的話就會像第一版那樣 —— 骨幹用 `aim/2.8` 排了 43 句，
    而那個句數在字數額度下根本放不下，多出 13 秒。
    """
    per = PER_ROW / RATE + PER_LINE + PER_ROW_ENDS * PER_END
    return max(6, round((aim - HOLDS) / per))


def budget(aim: float, rows: int | None = None) -> int:
    """這麼多秒、這麼多句，唸得完幾個字。

    **句數要用骨幹實際排的，不是理想的那個。** 骨幹排 41 句而理想是 37 句
    的時候，每一句的固定開銷就多了 4×1.06 秒 —— 照理想句數給的字數額度會
    多出四秒。差不多，但沒有理由差。
    """
    many = rows_for(aim) if rows is None else rows
    cost = many * (PER_LINE + PER_ROW_ENDS * PER_END)
    return max(50, round((aim - HOLDS - cost) * RATE))


def shape_of(who: list[str], narrator: str) -> dict[str, Any]:
    """對白的形狀：佔比、幾群、每群多長、旁白最長連續幾句。"""
    spots = [i for i, one in enumerate(who) if one != narrator]
    runs: list[list[int]] = []
    last = -9
    for i in spots:
        if i - last > 1:
            runs.append([i])
        else:
            runs[-1].append(i)
        last = i
    best = run = 0
    for one in who:
        if one == narrator:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return {"share": len(spots) / max(1, len(who)), "runs": len(runs),
            "run_most": max((len(one) for one in runs), default=0),
            "narration_run": best}


def _rows(who: list[str], says: list[str],
          holds_after: dict[int, float]) -> list[str]:
    out: list[str] = []
    if -1 in holds_after:
        out.append(f"停\t{holds_after[-1]}")
    for at, (name, text) in enumerate(zip(who, says)):
        out.append(f"{name}\t{text}")
        if at in holds_after:
            out.append(f"停\t{holds_after[at]}")
    return out


def _numbers_in(text: str) -> list[str]:
    """這句話裡的數字，照原樣。改說法不准改數字，靠這個比。"""
    return sorted(re.findall(r"\d+(?:[.,]\d+)*", text))


def run(story: str, say=print, again: bool = False, plain: bool = False,
        parts: bool = False, narrate: bool = False) -> dict[str, Any]:
    """`again` 兩支都重問，`parts` 只重問配角色那一支。

    分開是因為它們一次 10–25 分鐘，而**通常只有一支要重來** —— 旁白稿
    寫得好、只是某一句改成角色講的時候寫壞了，沒有理由把好的那一份丟掉。
    """
    paths.insist(story, "script")
    spec = story_module.load(story)
    bones = paths.load(story, "spine")
    facts = paths.load(story, "facts")
    cast = story_module.cast_of(spec)
    aim = float(spec.get("seconds") or 116)
    plan = bones["lines"]
    talk = _rules()["talk"]
    # **字數額度先留一塊給「接起來」那一步。** 不先留的話它每次都會撞
    # 長度的門，而撞的時候分不出是內容太多還是接詞太多。
    full = budget(aim, len(plan))
    words = round(full * (1 - talk["room"]))
    narrator = next((name for name, one in cast.items()
                     if one["slot"] == "narrator"), "旁白")

    # —— 第一支：旁白稿 ————————————————————————————————
    raw_at = paths.home(story) / "3-script.raw.json"
    if (again and not parts) or paths.raw_stale(story, raw_at, "script", ("script.md",)):
        nodes = "\n".join(
            f"{at:>3}　{one['role']:<4}　{one['point']}"
            + ("".join(f"\n        · {facts[i - 1]['said'][:52]}"
                       for i in (one.get("from") or [])
                       if 1 <= i <= len(facts)))
            for at, one in enumerate(bones["lines"]))
        got = ask.as_json(ask.send(story, "script", ask.prompt_of(
            "script.md", title=spec["title"], turn=bones["turn"],
            ending=bones.get("ending", ""), nodes=nodes,
            refrain=bones.get("refrain", ""),
            hero=spec.get("hero", ""),
            date_most=f"{DATE_HEAD_MOST:.0%}",
            hero_least=f"{HERO_LEAST:.0%}",
            seconds=f"{aim:.0f}", words=words,
            least=round(words * 0.92), most=round(words * 1.08),
            slack=8, rows=len(plan),
            rate=RATE, per_line=PER_ROW, line_cost=PER_LINE,
            end_cost=PER_END,
            holds=f"{HOLDS:.0f}"), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    says: list[str] = []
    asides: list[int] = []
    holds_after: dict[int, float] = {}
    total_hold = 0.0
    for at, one in enumerate(got.get("lines") or []):
        if one.get("hold") is not None:
            many = float(one["hold"])
            holds_after[len(says) - 1] = holds_after.get(len(says) - 1, 0) + many
            total_hold += many
            continue
        text = str(one.get("say") or "").strip()
        if not text:
            raise SystemExit(f"第 {at} 行沒有內容")
        says.append(text)
    if len(says) != len(plan):
        raise SystemExit(
            f"骨幹排了 {len(plan)} 句，台詞寫了 {len(says)} 句 —— "
            f"要一句對一句。加 --again")
    # **「吐槽」是骨幹標的，不是台詞那一步另外宣告的。** 兩個地方各標一次
    # 的話，就會有一份是假的。
    asides = [i for i, one in enumerate(plan) if one["role"] == "吐槽"]
    if not says:
        raise SystemExit("一句台詞都沒有")

    said = sum(_han(one) for one in says)
    ends = sum(_ends(one) for one in says)
    long = guess(said, len(says), total_hold, ends)
    # **這一步量的是字數，不是秒數。** 旁白稿只用 `words`（總額度的
    # 82%），剩下的留給「接起來」那一步的接詞和語助詞 —— 拿 100% 的
    # 秒數去量它，寫得剛好反而被判太短（量到 108 秒，而容許 109 起）。
    # 秒數那道門在最後，等三趟都做完才量。
    if abs(said - words) > words * 0.10:
        raise SystemExit(
            f"旁白稿 {said} 個字，額度是 {words}"
            f"（容許 {round(words * 0.9)}–{round(words * 1.1)}）。\n"
            f"  這是留給內容的額度，接詞和語助詞的字另外算"
            f"（總額度 {full}）。\n"
            f"  {said} 字 ÷ {RATE} ＝ {said / RATE:.0f}s"
            f"　＋ {len(says)} 行 × {PER_LINE} ＝ {len(says) * PER_LINE:.0f}s"
            f"　＋ {ends} 個句號 × {PER_END} ＝ {ends * PER_END:.0f}s"
            f"　＋ 停 {total_hold:.0f}s\n"
            f"  現在估計 {long:.0f} 秒（三趟做完的目標是 {aim:.0f}）。"
            f"加 --again")

    refrain = str(bones.get("refrain") or "").strip()
    if refrain:
        whole = "".join(says)
        bare = re.sub(r"[，。！？、：；…—\s]", "", whole)
        times = whole.count(refrain) or bare.count(
            re.sub(r"[，。！？、：；…—\s]", "", refrain))
        if times < 2:
            raise SystemExit(
                f"「{refrain}」在稿子裡只出現 {times} 次，要兩次 —— "
                f"前面鋪一次、最後收一次。加 --again")
        say(f"  「{refrain}」出現 {times} 次")

    # —— 旁白的形狀 ——
    # **主角可以用代名詞。** 第一版只查全名「格陵蘭」，量出 0/43 —— 而
    # 那份稿子每一句的主詞都是它，用的是「它」和「島」。那是正常的中文，
    # 一句一個全名才是壞的。誤報的門會叫人去修沒有壞的東西。
    #
    # 代名詞寫在故事檔的 `hero_as`，因為「它」指誰是這一支片的事。
    hero = str(spec.get("hero") or "").strip()
    names = [hero, *(spec.get("hero_as") or [])] if hero else []
    here = [bool(names) and any(x in one for x in names) for one in says]
    dated = [one for one in says if DATE_HEAD.match(one)]
    shown = [one for one, yes in zip(says, here) if yes]
    gone = run_ = 0
    for yes in here:
        run_ = 0 if yes else run_ + 1
        gone = max(gone, run_)
    bad = []
    if len(dated) / len(says) > DATE_HEAD_MOST:
        bad.append(
            f"{len(dated)}/{len(says)} 句以年份開頭"
            f"（{len(dated) / len(says):.0%}，上限 {DATE_HEAD_MOST:.0%}）"
            f"—— 那是年表，不是故事")
    if hero and len(shown) / len(says) < HERO_LEAST:
        bad.append(
            f"只有 {len(shown)}/{len(says)} 句提到主角"
            f"（{len(shown) / len(says):.0%}，至少 {HERO_LEAST:.0%}）"
            f"　認得的說法：{'、'.join(names)}")
    if hero and gone > HERO_GONE_MOST:
        bad.append(
            f"有一段連續 {gone} 句沒有主角（最多 {HERO_GONE_MOST}）"
            f"—— 那一段變成世界大事年表")
    # 「吐槽幾句」那道門在 spine（`rules.json` 的 roles.吐槽.least）——
    # 那裡是決定「這一句要幹嘛」的地方。這裡再擋一次就是同一件事兩個
    # 地方管，而兩個地方就會有一個是假的。
    if bad:
        raise SystemExit(
            "旁白寫成年表了：\n  " + "\n  ".join(bad)
            + "\n加 --again 重寫")
    say(f"  {ends} 個句號（一行 {ends / len(says):.1f} 個）")
    say(f"  年份開頭 {len(dated) / len(says):.0%}"
        + (f"　提到主角 {len(shown) / len(says):.0%}"
           f"（最長連續 {gone} 句沒有）" if hero else "")
        + f"　吐槽 {len(asides)} 句")

    # **一行最多兩個句尾標點。** 每一個 0.425 秒，而那些秒數本來可以
    # 拿去講話。三句塞在一行裡，長度上等於多寫了七個字。
    crowded = [one for one in says if _ends(one) > ENDS_MOST]
    if crowded:
        bad.append(
            f"{len(crowded)} 行的句尾標點超過 {ENDS_MOST} 個"
            f"（每一個 {PER_END} 秒）："
            + "　".join(one[:20] for one in crowded[:3]))

    thick = [one for one in says if _numbers(one) >= 2]
    if thick:
        say(f"⚠ {len(thick)} 句裡有兩個以上的數字："
            + "　".join(one[:18] for one in thick[:3]))

    who = [narrator] * len(says)
    (paths.home(story) / "3-script.plain.tsv").write_text(
        "\n".join(_rows(who, says, holds_after)) + "\n", encoding="utf-8")
    say(f"\n旁白稿　{len(says)} 句、{said} 字、停 {total_hold:.0f} 秒　"
        f"估計 {long:.0f} 秒（目標 {aim:.0f}）")
    if plain:
        paths.save(story, "script",
                   "\n".join(_rows(who, says, holds_after)) + "\n")
        say("（--plain：停在旁白稿，沒有配角色）")
        return {"lines": says, "who": who}

    # —— 第二支：挑幾句交給角色 ——————————————————————————
    parts_at = paths.home(story) / "3-parts.raw.json"
    stale = (paths.raw_stale(story, parts_at, "script", ("parts.md",))
             or parts_at.stat().st_mtime < raw_at.stat().st_mtime)
    if again or parts or stale:
        listing = "\n".join(f"{at:>3}　{one}" for at, one in enumerate(says))
        folk = "\n".join(f"- **{name}**" for name in cast if name != narrator)
        got2 = ask.as_json(ask.send(story, "parts", ask.prompt_of(
            "parts.md", cast=folk, lines=listing, rows=len(says),
            least_lines=round(len(says) * SHARE[0]),
            most_lines=round(len(says) * SHARE[1]),
            least_runs=RUNS[0], most_runs=RUNS[1]), say))
        parts_at.write_text(json.dumps(got2, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    else:
        say(f"沿用 {parts_at.name}")
        got2 = json.loads(parts_at.read_text(encoding="utf-8"))

    for one in (got2.get("parts") or []):
        at = int(one.get("at", -1))
        name = str(one.get("who") or "")
        text = str(one.get("say") or "").strip()
        if not 0 <= at < len(says):
            raise SystemExit(f"要改第 {at} 句，而只有 {len(says)} 句")
        if name not in cast or name == narrator:
            raise SystemExit(
                f"第 {at} 句要交給「{name}」，而可以講話的只有："
                + "、".join(x for x in cast if x != narrator))
        if not text:
            raise SystemExit(f"第 {at} 句沒有改寫後的內容")
        who[at], says[at] = name, text

    shape = shape_of(who, narrator)
    bad = []
    if not SHARE[0] <= shape["share"] <= SHARE[1]:
        bad.append(f"角色佔 {shape['share']:.0%}"
                   f"（要 {SHARE[0]:.0%}–{SHARE[1]:.0%}）")
    if not RUNS[0] <= shape["runs"] <= RUNS[1]:
        bad.append(f"分成 {shape['runs']} 群（要 {RUNS[0]}–{RUNS[1]} 群）")
    if shape["run_most"] > RUN_MOST:
        bad.append(f"最長一群 {shape['run_most']} 句（最多 {RUN_MOST}）")
    if shape["narration_run"] < NARRATION_RUN:
        bad.append(f"最長旁白連續只有 {shape['narration_run']} 句"
                   f"（至少 {NARRATION_RUN}）—— 沒有一段是純粹在講故事的")
    if bad:
        raise SystemExit(
            "對白的形狀不對：\n  " + "\n  ".join(bad)
            + "\n\n（參考片：佔 39%、6 群、最長一群 4 句、最長旁白連續 6 句）"
              "\n加 --again 重問")

    # **中文稿裡不要有拉丁字母。** 「我讓 Hans Egede 回島上」——
    # zh-TW 的合成器唸外文人名會唸成一串音節，而它照樣唸得出來、
    # 照樣壓得出片，只有聽的人知道不對。人名要用中譯，或者根本不提。
    latin = [one for one in says if re.search(r"[A-Za-z]{2,}", one)]
    if latin:
        raise SystemExit(
            "這幾句裡有拉丁字母，中文語音唸不好：\n  "
            + "\n  ".join(latin[:5])
            + "\n\n人名用中譯，或者不提名字。加 --again")

    fresh = sum(_han(one) for one in says)
    if abs(fresh - said) > said * 0.15:
        raise SystemExit(
            f"改寫之後從 {said} 字變成 {fresh} 字 —— 改的是說法，"
            f"不是長度。加 --again")

    (paths.home(story) / "3-script.parts.tsv").write_text(
        "\n".join(_rows(who, says, holds_after)) + "\n", encoding="utf-8")
    say(f"\n角色 {sum(1 for x in who if x != narrator)} 句／{len(says)} 句"
        f"（{shape['share']:.0%}）　{shape['runs']} 群　"
        f"最長一群 {shape['run_most']}　最長旁白連續 {shape['narration_run']}")
    for name in cast:
        say(f"  {name:<5}{sum(1 for x in who if x == name):>3} 句")
    say(f"  改寫後 {fresh} 字（原本 {said}）")

    # —— 第三支：接成一段話 ————————————————————————————
    talk_at = paths.home(story) / "3-narrate.raw.json"
    stale = (paths.raw_stale(story, talk_at, "script", ("narrate.md",))
             or talk_at.stat().st_mtime < parts_at.stat().st_mtime)
    if again or narrate or stale:
        listing = "\n".join(f"{at:>3}　{w}　{s}"
                             for at, (w, s) in enumerate(zip(who, says)))
        got3 = ask.as_json(ask.send(story, "narrate", ask.prompt_of(
            "narrate.md", lines=listing, now=fresh, most=full,
            room=full - fresh, fillers="、".join(talk["fillers"]),
            every=talk["every"],
            most_per_line=talk["most_per_line"]), say))
        talk_at.write_text(json.dumps(got3, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    else:
        say(f"沿用 {talk_at.name}")
        got3 = json.loads(talk_at.read_text(encoding="utf-8"))

    before = list(says)
    seen: set[int] = set()
    for one in (got3.get("lines") or []):
        at = int(one.get("at", -1))
        text = str(one.get("say") or "").strip()
        if not 0 <= at < len(says):
            raise SystemExit(f"要改第 {at} 句，而只有 {len(says)} 句")
        if not text:
            raise SystemExit(f"第 {at} 句改成空的")
        # **改說法不准改數字。** 接句子的時候最容易把年份和百分比弄丟，
        # 或者把「1261 年」講成「13 世紀」—— 聽起來一樣對，而事實變了。
        if _numbers_in(text) != _numbers_in(says[at]):
            raise SystemExit(
                f"第 {at} 句的數字被改了：\n"
                f"  原本：{says[at]}\n"
                f"  改成：{text}\n"
                f"改說法可以，改數字不行。加 --narrate 重問")
        says[at], seen = text, seen | {at}
    missing = [i for i in range(len(says)) if i not in seen]
    if missing:
        say(f"⚠ 這 {len(missing)} 句沒有改寫，照原樣：{missing[:8]}")

    marks = [sum(one.count(f) for f in talk["fillers"]) for one in says]
    with_ = sum(1 for one in marks if one)
    need = len(says) // talk["every"]
    bad = []
    if with_ < need:
        bad.append(f"只有 {with_}/{len(says)} 句有語助詞，"
                   f"每 {talk['every']} 句要有一句（至少 {need} 句）"
                   f"—— 沒有語助詞的中文旁白聽起來像在唸稿")
    thickest = [one for one, n in zip(says, marks)
                if n > talk["most_per_line"]]
    if thickest:
        bad.append(f"{len(thickest)} 句的語助詞超過 "
                   f"{talk['most_per_line']} 個："
                   + "　".join(one[:16] for one in thickest[:3]))
    grown = sum(_han(one) for one in says)
    grown_ends = sum(_ends(one) for one in says)
    if grown_ends > ends * 1.25:
        bad.append(f"接完之後句號從 {ends} 個變成 {grown_ends} 個 —— "
                   f"每一個 {PER_END} 秒，接句子不該多切出句號")
    whole = guess(grown, len(says), total_hold, grown_ends)
    if abs(whole - aim) > aim * SLACK:
        bad.append(
            f"三趟做完唸出來 {whole:.0f} 秒，目標 {aim:.0f}"
            f"（容許 {aim * (1 - SLACK):.0f}–{aim * (1 + SLACK):.0f}）"
            f"　{grown} 字、{len(says)} 行、{grown_ends} 個句號")
    if grown > full * 1.06:
        bad.append(f"接完之後 {grown} 字，上限 {full}"
                   f"（原本 {fresh}，額度 {full - fresh}）"
                   f"—— 接詞和語助詞的字，不是新內容的字")
    if bad:
        raise SystemExit("接起來那一步不合規矩：\n  " + "\n  ".join(bad)
                         + "\n加 --narrate 重問")

    paths.save(story, "script", "\n".join(_rows(who, says, holds_after)) + "\n")
    changed = sum(1 for a, b in zip(before, says) if a != b)
    say(f"\n接起來　改寫 {changed}/{len(says)} 句　"
        f"{grown} 字（原本 {fresh}，上限 {full}）")
    say(f"  語助詞 {with_}/{len(says)} 句（至少 {need}）　"
        f"句號 {grown_ends} 個　"
        f"估計 {guess(grown, len(says), total_hold, grown_ends):.0f} 秒")
    return {"lines": says, "who": who}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "",
        again="--again" in sys.argv, plain="--plain" in sys.argv,
        parts="--parts" in sys.argv, narrate="--narrate" in sys.argv)
