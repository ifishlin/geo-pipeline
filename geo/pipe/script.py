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

# 唸多久 ＝ 字數 / RATE ＋ 句數 × PER_LINE ＋ 宣告的停頓。
# 兩個數字是拿兩次真實合成解出來的（572 字 36 句 → 116.74 秒；
# 585 字 49 句 → 133.10 秒）。句數那一項很大：字數只差 13 個，秒數差 16 秒。
RATE = 8.22
PER_LINE = 1.060
# 一句話幾個字。**12 太短了** —— 中文一句 12 個字寫不下主角＋內容，
# 於是模型把主角擠掉（量到 0/43 句提到它）。而且一句話的固定開銷是
# 1.06 秒，句子越短、開銷佔比越高：43 句就是 46 秒，四成的預算花在換氣上。
#
# 15 個字：句數降到 37，開銷 39 秒，字數額度反而從 505 升到 555。
PER_ROW = 15
HOLDS = 10.0
SLACK = 0.06

# 旁白自己的形狀。**「年份開頭」不是錯的寫法，整篇都這樣才是** ——
# 那是一張清單，不是一個故事。所以是上限，不是禁止。
#
#                     我們第一版   參考片   訂
#   以年份開頭          87%        11%     ≤30%
#   提到主角            27%        42%     ≥35%
#   態度句（不帶新事實）  0 句       3 句     ≥2 句
#
# 參考片三道全過，我們第一版三道全不過。
DATE_HEAD_MOST = 0.30
HERO_LEAST = 0.35
# 主角最多連續幾句不出現。**比例是弱的代理，這個才是要擋的東西** ——
# 「主角整段消失」是一段連續的沉默，不是一個百分比。
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


def guess(said: int, rows: int, holds: float) -> float:
    return said / RATE + rows * PER_LINE + holds


def rows_for(aim: float) -> int:
    """這麼多秒放得下幾句。

    **只有這一支算得出這個數字。** 骨幹排幾句和台詞的字數額度是同一件事
    的兩面：`秒 = 字/RATE + 句×PER_LINE + 停`，而 `字 = 句×PER_ROW`。
    兩邊各算一次的話就會像第一版那樣 —— 骨幹用 `aim/2.8` 排了 43 句，
    而那個句數在字數額度下根本放不下，多出 13 秒。
    """
    return max(6, round((aim - HOLDS) / (PER_ROW / RATE + PER_LINE)))


def budget(aim: float) -> int:
    """這麼多秒唸得完幾個字。"""
    return rows_for(aim) * PER_ROW


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


def run(story: str, say=print, again: bool = False,
        plain: bool = False) -> dict[str, Any]:
    paths.insist(story, "script")
    spec = story_module.load(story)
    bones = paths.load(story, "spine")
    facts = paths.load(story, "facts")
    cast = story_module.cast_of(spec)
    aim = float(spec.get("seconds") or 116)
    words = budget(aim)
    narrator = next((name for name, one in cast.items()
                     if one["slot"] == "narrator"), "旁白")

    # —— 第一支：旁白稿 ————————————————————————————————
    raw_at = paths.home(story) / "3-script.raw.json"
    if again or paths.raw_stale(story, raw_at, "script"):
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
            slack=8, rows=round(words / PER_ROW),
            rate=RATE, per_line=PER_ROW, line_cost=PER_LINE,
            holds=f"{HOLDS:.0f}"), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    plan = bones["lines"]
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
    long = guess(said, len(says), total_hold)
    if abs(long - aim) > aim * SLACK:
        raise SystemExit(
            f"這份稿子唸出來大約 {long:.0f} 秒，目標 {aim:.0f}"
            f"（容許 {aim * (1 - SLACK):.0f}–{aim * (1 + SLACK):.0f}）。\n"
            f"  {said} 字 ÷ {RATE} ＝ {said / RATE:.0f}s"
            f"　＋ {len(says)} 句 × {PER_LINE} ＝ {len(says) * PER_LINE:.0f}s"
            f"　＋ 停 {total_hold:.0f}s\n"
            f"  **句數也要算錢** —— 一句拆成兩句多 {PER_LINE} 秒。加 --again")

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
    if len(asides) < ASIDE_LEAST:
        bad.append(
            f"只有 {len(asides)} 句標了 aside（至少 {ASIDE_LEAST} 句）"
            f"—— 不帶新事實、只有態度的句子。參考片的笑點大半在這裡")
    if bad:
        raise SystemExit(
            "旁白寫成年表了：\n  " + "\n  ".join(bad)
            + "\n加 --again 重寫")
    say(f"  年份開頭 {len(dated) / len(says):.0%}"
        + (f"　提到主角 {len(shown) / len(says):.0%}"
           f"（最長連續 {gone} 句沒有）" if hero else "")
        + f"　吐槽 {len(asides)} 句")

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
    stale = (not parts_at.is_file()
             or parts_at.stat().st_mtime < raw_at.stat().st_mtime)
    if again or stale:
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

    fresh = sum(_han(one) for one in says)
    if abs(fresh - said) > said * 0.15:
        raise SystemExit(
            f"改寫之後從 {said} 字變成 {fresh} 字 —— 改的是說法，"
            f"不是長度。加 --again")

    paths.save(story, "script", "\n".join(_rows(who, says, holds_after)) + "\n")
    say(f"\n角色 {sum(1 for x in who if x != narrator)} 句／{len(says)} 句"
        f"（{shape['share']:.0%}）　{shape['runs']} 群　"
        f"最長一群 {shape['run_most']}　最長旁白連續 {shape['narration_run']}")
    for name in cast:
        say(f"  {name:<5}{sum(1 for x in who if x == name):>3} 句")
    say(f"  改寫後 {fresh} 字（原本 {said}）　"
        f"估計 {guess(fresh, len(says), total_hold):.0f} 秒")
    return {"lines": says, "who": who}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "",
        again="--again" in sys.argv, plain="--plain" in sys.argv)
