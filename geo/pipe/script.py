"""骨幹 → 台詞。**三支 prompt，三件事。**

    python3 -m geo.pipe.make <題目> script
    python3 -m geo.pipe.make <題目> script --plain    只寫旁白，不配角色

```
script.md    寫旁白稿。一個聲音從頭講到尾，故事本身要完整
parts.md     角色插進反應。**追加，不是取代** —— 旁白一個字都不動
narrate.md   接成一段話：接詞、語助詞，把插進去那幾個接縫磨順
```

## 角色不准碰劇情

第一版一支 prompt 同時要「講好故事」和「有對白」，旁白先把事實講完、
角色再用第一人稱複述一次 —— 那是註解，不是對話。所以第二版改成**取代**：
角色要講話就從旁白手上拿走那一句，句數不變，重複在結構上不可能發生。

而取代治的其實是另一個病：「把插話拿掉，剩下的故事就不成立」。那個病
現在由第一支治了 —— 它被要求寫出一份「一句都不改也講得通」的旁白稿，
而且真的寫得出來。**同一個病治兩次，第二道就只是在拆第一道的成果。**

量出來的證據：11 句角色台詞跟被它取代的那句旁白，字面相似度中位數 84%，
八句只是把「它」換成「我」。角色沒帶進任何旁白說不出來的東西，只是換了
名牌的旁白；而故事那條線被切了八刀（使用者的說法：破碎感）。

所以現在角色只做四件事 —— 附和、吐槽、自嘲、用自己的語氣重申一次
（`rules.json` 的 `parts.kinds`），**每一種都是反應，沒有一種推進劇情**。

「旁白稿一個字都沒被動到」不是一道門，是這段程式做不到的事：
`says` 那一列只會被插入，不會被指派。**做不到比擋得住可靠。**

## 反應句的秒數是預付的

一句反應要 0.50（行）＋ 0.425（句號）＋ 字數/8.22，八句大約 17 秒。
不先從旁白那邊扣掉的話，第三趟必撞長度門，而撞的時候分不出是內容太多
還是反應太多。所以 `rows_for()` 先扣 `react_cost()` 再算旁白排幾句 ——
**骨幹排幾句、旁白寫幾個字、插幾句反應，是同一條算式的三個出口。**
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from geo.pipe import ask, marks, paths, story as story_module
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
#
# **21 寫出來是五言絕句。** 2026-09-26 使用者逐句指出九種破法，全部是
# 省字省出來的：
#
#     島也能用買的？那上面的人呢。      問題沒問完
#     管它叫綠地，騙人來。              騙誰？來幹嘛？
#     這島四千五百年前就有人。          哪種人？觀眾以為是外星人
#     他們向挪威國王低頭                「他們」沒有先行詞
#     它沒動，主人換了                  「沒動」不是話，是壓縮出來的詞
#     三百年後丹麥來找他們，留下努克      努克是什麼？第一次出現就當已知
#
# 一句 20 個字塞得下「誰做了什麼」，塞不下「對誰做、為什麼、結果怎樣」。
# 而省字的時候最容易挑到最文的那個詞（「頭一次歸別人」），所以連文言腔
# 都是這一格造成的。
#
# 改成 30。**句數和內容都不動，讓片子變長** —— 拿句數去換字數等於少講
# 故事，而使用者說「時間長短不是重點，故事講好才是重點」。
# 26 句 × 20 字（116 秒）→ 26 句 × 29 字（148 秒）。
PER_ROW = 30
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

# 反應句的秒數要**先付**。
#
# 一句反應不是免費的：它有自己的行開銷（0.50）、自己的句號（0.425），
# 再加上它自己的字。八句大約十七秒 —— 那是 116 秒裡的 15%，不先從旁白
# 那邊扣掉的話，narrate 那一趟必撞長度門，而撞的時候分不出是內容太多
# 還是反應太多（`talk.room` 當初就是為了這件事才存在的）。
#
# 反應句一句幾個字是估的（上限 14，實際多半八到十二），估錯的方向是
# 「旁白少寫幾個字」，不是「片子超長」。
REACT_WORDS = 14


def react_cost(many: int) -> float:
    """這麼多句反應吃掉幾秒。字、行、句號都算。"""
    return many * (REACT_WORDS / RATE + PER_LINE + PER_END)

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
    return len(re.findall(r"\d+(?:[.,]\d+)*",
                          DATE.sub("〇", marks.strip(text))))


def _han(text: str) -> int:
    """唸得出來的字數：漢字加數字，不算標點。

    **先脫掉就地標記。** `⏸0.3` 和 `⟪-10 …⟫` 的符號跟數字一個字都不會唸
    出來，照原字串算的話「⏸0.3」會被當成一個字加三位數字 —— 而字數是
    整條路的預算來源，錯在這裡每一道門都跟著錯。
    """
    text = marks.strip(text)
    return len(re.findall(r"[一-鿿]", text)) + \
        sum(len(one) for one in re.findall(r"\d+", text))


def guess(said: int, rows: int, holds: float, ends: int | None = None) -> float:
    """唸出來大概幾秒。`ends` 不給就假設一行一句。"""
    return (said / RATE + rows * PER_LINE
            + (rows if ends is None else ends) * PER_END + holds)


def _closed(text: str) -> str:
    """句尾沒有標點就補一個句號。

    **這是機械的事，不該靠模型記得。** 換過範例之後有一趟它 26 句全部不加
    句號，而句號決定秒數（一個 0.425 秒，26 個就是 11 秒）—— 那一趟估出來
    134 秒、目標 148，被門擋掉，訊息還說「不該多切出句號」（narrate 只是
    把它們補回去而已）。**報告指錯地方，比沒有報告更糟。**

    補句號不改變意思，所以程式做得起；漏了句號會改變長度，所以不能不做。
    """
    text = text.rstrip()
    return text if text and text[-1] in "。！？…」』》）" else text + "。"


def _ends(text: str) -> int:
    """這一行有幾個句尾標點。每一個都要 0.425 秒。標記先脫掉。"""
    return len(re.findall(r"[。！？：；]", marks.strip(text)))


def reacts_for() -> int:
    """預計會插進幾句反應。

    **取上下限的中間。** 拿上限算的話實際少插幾句，片子就偏短；拿下限
    算就偏長。中間值兩邊的誤差一樣大，而秒數的門容許 ±6%。
    """
    got = _rules()["parts"]
    return round((got["least"] + got["most"]) / 2)


def rows_for(aim: float) -> int:
    """這麼多秒放得下幾句**旁白**。

    **只有這一支算得出這個數字。** 骨幹排幾句和台詞的字數額度是同一件事
    的兩面：`秒 = 字/RATE + 句×PER_LINE + 停`，而 `字 = 句×PER_ROW`。
    兩邊各算一次的話就會像第一版那樣 —— 骨幹用 `aim/2.8` 排了 43 句，
    而那個句數在字數額度下根本放不下，多出 13 秒。
    """
    per = PER_ROW / RATE + PER_LINE + PER_ROW_ENDS * PER_END
    return max(6, round((aim - HOLDS - react_cost(reacts_for())) / per))


def budget(aim: float, rows: int | None = None) -> int:
    """這麼多秒、這麼多句，唸得完幾個字。

    **句數要用骨幹實際排的，不是理想的那個。** 骨幹排 41 句而理想是 37 句
    的時候，每一句的固定開銷就多了 4×1.06 秒 —— 照理想句數給的字數額度會
    多出四秒。差不多，但沒有理由差。
    """
    many = rows_for(aim) if rows is None else rows
    cost = (many * (PER_LINE + PER_ROW_ENDS * PER_END)
            + react_cost(reacts_for()))
    return max(50, round((aim - HOLDS - cost) * RATE))


# 角色講話的樣子。**這一條沒寫進 prompt，所以它沒發生** —— 量出來
# 八句只有兩句有「我」。角色不用第一人稱，就只是換了嗓子的旁白。
SELF = re.compile(r"我|咱|俺")

# 專有名詞長什麼樣：兩個字以上的人名地名國名。**用來擋反應句夾帶新東西**
# —— 放寬字數上限之後，「不准推劇情」不能再靠短來保證了。
NAMED = re.compile(r"[一-鿿]{2,}(?:國|島|群島|王國|洲|市|灣|海|山|"
                   r"共同體|聯邦|王室)|[A-Z][a-z]+")


def skeleton(text: str, most: int = 10) -> str:
    """把句子開頭「自己重複的那一段」換成 ◯，留下骨架。

    **為了抓「同一個句型用兩次」，而那查字面查不到** ——「好聽歸好聽」和
    「照顧歸照顧」一個字都不重疊，可是骨架都是 `◯歸◯`。

    這樣寫的好處是不用一種一種列（`A歸A`、`A就A`、`A是A`、`越A越A`…）。
    **列清單就會變成打地鼠**，而下一次模型找到的會是還沒列進去的那一種。
    """
    head = text[:most]
    # 只認「兩次出現靠得很近」的那種（中間隔 0–2 個字）。隔遠了就不是句型，
    # 只是同一個詞在一句話裡出現兩次。**而且只留骨架本身，不留後面的內容**
    # —— 留了的話「◯歸◯，那批北歐」跟「◯歸◯，法羅群島」就不會撞。
    for size in range(4, 0, -1):
        for at in range(len(head) - size * 2 + 1):
            bit = head[at:at + size]
            if re.search(r"[，。！？、：；…—\s]", bit):
                continue
            # **疊字不算句型。**「偏偏」「漸漸」「剛剛」是正常的中文詞，
            # 不是「A 歸 A」那種套用的模板。中間要隔至少一個字才算。
            for gap in range(1, 3):
                later = at + size + gap
                if head[later:later + size] == bit:
                    return "◯" + head[at + size:later] + "◯"
    return ""


def check_parts(where: dict[int, tuple[str, str, str]],
                react: dict[str, Any],
                said: list[str] | None = None) -> list[str]:
    """反應句的形狀。回一串說得出口的問題。

    **抽成一支是為了餵得進違規。** 這幾道門一條都還沒被真的觸發過，而
    這個專案有過一道門自己就帶著它要擋的錯、靜默放行了一整輪 —— 抓到是
    因為真的去製造一次違規。`_parts.py` 就是那件事。
    """
    bad: list[str] = []
    if not react["least"] <= len(where) <= react["most"]:
        bad.append(f"插了 {len(where)} 句反應"
                   f"（要 {react['least']}–{react['most']} 句）")
    # **反應句不准帶阿拉伯數字。** 新事實幾乎都是靠數字進來的，而角色
    # 一旦負責交代一件旁白沒講過的事，故事那條線就斷在它那裡。
    # 中文數字（「四百年」）放行 —— 那多半是在複述旁白剛講過的。
    digits = [(at, x[1]) for at, x in where.items() if re.search(r"\d", x[1])]
    if digits:
        bad.append("這幾句反應裡有數字，那是在講新的事實，不是在反應：\n    "
                   + "\n    ".join(f"{at}　{one}" for at, one in digits[:4]))
    # **短是結構保證，不是風格要求。** 十四個字塞不進一個年份加一個因果。
    longs = [(at, x[1]) for at, x in where.items()
             if _han(x[1]) > react["words_most"]]
    if longs:
        bad.append(f"這幾句反應超過 {react['words_most']} 個字：\n    "
                   + "\n    ".join(f"{at}　{one}（{_han(one)} 字）"
                                   for at, one in longs[:4]))
    spots = sorted(where)
    tight = [(a, b) for a, b in zip(spots, spots[1:])
             if b - a < react["gap_least"]]
    if tight:
        bad.append(
            f"這幾對插入點隔太近（至少要隔 {react['gap_least']} 句旁白）："
            + "　".join(f"{a}→{b}" for a, b in tight[:4]))

    # **角色講話要用第一人稱。** 量出來 8 句只有 2 句有「我」—— 而
    # `parts.md` 根本沒寫這一條。沒說的事不會發生。
    flat = [(at, x[1]) for at, x in where.items() if not SELF.search(x[1])]
    if flat:
        bad.append("這幾句沒有第一人稱（我／咱），聽起來還是旁白：\n    "
                   + "\n    ".join(f"{at}　{one}" for at, one in flat[:4]))

    # **一個角色不能包辦。** 主角是受害的那一個，而受害者複述自己被害
    # 不可能好笑；有意思的那兩句都是加害者若無其事講出自己的邏輯。
    tally: dict[str, int] = {}
    for name, _, _ in where.values():
        tally[name] = tally.get(name, 0) + 1
    cap = react.get("one_share_most", 0.5)
    hog = [(k, v) for k, v in tally.items() if v > len(where) * cap]
    if hog:
        bad.append(
            "、".join(f"「{k}」講了 {v}/{len(where)} 句" for k, v in hog)
            + f"（一個角色最多 {cap:.0%}）—— 一個人講完就變成訴苦，"
              "而落差要靠別人講出來")
    if len(tally) < 1 + int(react.get("self_least", 1)):
        bad.append(f"只有 {len(tally)} 個角色開口"
                   f"（至少要 {1 + int(react.get('self_least', 1))} 個）")

    # **放寬字數之後，「不推劇情」改用這一道守。** 原本靠 14 字的上限保證
    # 塞不進新東西，而那也讓笑話塞不進鋪陳。改成：反應句提到的專有名詞，
    # 旁白必須已經講過。
    if said is not None:
        whole = "".join(said)
        smuggled = []
        for at, (_, text, _) in where.items():
            fresh = [x for x in NAMED.findall(text) if x not in whole]
            if fresh:
                smuggled.append((at, text, fresh))
        if smuggled:
            bad.append(
                "這幾句反應帶進了旁白沒講過的名字，那是在推劇情：\n    "
                + "\n    ".join(f"{at}　{one}　（{'、'.join(x)}）"
                                for at, one, x in smuggled[:4]))
    return bad


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
    """這句話裡的數字，照原樣。改說法不准改數字，靠這個比。

    **先脫掉就地標記。** `⏸0.3` 的 0.3 是標記的參數，不是台詞裡的數字。
    不脫的話，narrate 標一個停頓就會被判成「把數字改掉了」，而那句台詞
    一個數字都沒動 —— 這是誤報，而誤報會叫人去修沒有壞的東西。
    """
    return sorted(re.findall(r"\d+(?:[.,]\d+)*", marks.strip(text)))


def run(story: str, say=print, again: bool = False, plain: bool = False,
        parts: bool = False, narrate: bool = False) -> dict[str, Any]:
    """`again` 兩支都重問，`parts` 只重問配角色那一支。

    分開是因為它們一次 10–25 分鐘，而**通常只有一支要重來** —— 旁白稿
    寫得好、只是某一句改成角色講的時候寫壞了，沒有理由把好的那一份丟掉。
    """
    paths.insist(story, "script")
    # **誰可以講話，先問過。** 沒有 cast 就讓模型從事實清單挑（`cast.py`）；
    # 已經有了就原樣用 —— 檔案說了算，改 story.json 就算數。
    #
    # 不做成獨立一步，是因為那會把 `2-spine` 之後的檔名全部往後推，而
    # 改檔名是動到「身分」，每一個讀取點都要重新確認。它產出的是
    # story.json 的一個欄位，不是一份新的產物。
    from geo.pipe import cast as cast_module
    cast_module.settle(story, say)
    spec = story_module.load(story)
    bones = paths.load(story, "spine")
    facts = paths.load(story, "facts")
    cast = story_module.cast_of(spec)
    aim = float(spec.get("seconds") or 116)
    plan = bones["lines"]
    got_rules = _rules()
    talk, react = got_rules["talk"], got_rules["parts"]
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
        # **把每個角色的立場一起送過去。** `cast` 那一步已經寫出來了
        # （「它不覺得自己在搶，它覺得自己只是把一件早該屬於它的東西辦好
        # 手續」），而上一版只送名字 —— 於是寫反應的時候沒有任何東西告訴
        # 模型這個角色該用什麼口氣。**產出來的東西沒有被下游讀到，等於
        # 沒有產出。**
        stance = spec.get("cast_why") or {}
        folk = "\n".join(
            f"- **{name}**" + (f"　{stance[name]}" if name in stance else "")
            for name in cast if name != narrator)
        kinds = "\n".join(f"**{name}** —— {one['what']}\n  例：{one['eg']}"
                          for name, one in react["kinds"].items())
        got2 = ask.as_json(ask.send(story, "parts", ask.prompt_of(
            "parts.md", cast=folk, lines=listing, rows=len(says),
            kinds=kinds, least=react["least"], most=react["most"],
            words_most=react["words_most"], gap=react["gap_least"],
            one_most=int(react["most"] * react.get("one_share_most", .5))),
            say))
        parts_at.write_text(json.dumps(got2, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    else:
        say(f"沿用 {parts_at.name}")
        got2 = json.loads(parts_at.read_text(encoding="utf-8"))

    # **插進去，不是蓋掉。** 旁白那一列從頭到尾沒有被指派過，所以
    # 「旁白稿一個字都沒被動到」不是一道門，是這段程式做不到的事 ——
    # 而做不到比擋得住可靠。
    #
    # 上一版是 `who[at], says[at] = name, text`：角色要講話就得從旁白
    # 手上拿走一句，於是那一句的劇情跟著換了嘴。量出來 11 句裡 8 句只是
    # 「它」換成「我」—— 角色沒帶進任何東西，而故事那條線被切了八刀。
    where: dict[int, tuple[str, str, str]] = {}
    for one in (got2.get("parts") or []):
        at = int(one.get("after", -1))
        name = str(one.get("who") or "")
        kind = str(one.get("kind") or "")
        text = str(one.get("say") or "").strip()
        if not 0 <= at < len(says):
            raise SystemExit(
                f"要插在第 {at} 句後面，而旁白只有 {len(says)} 句")
        if at in where:
            raise SystemExit(
                f"第 {at} 句後面插了兩句（「{where[at][1]}」和「{text}」）"
                f"—— 一個位置只能插一句，連兩句就變成兩人對談，"
                f"旁白那條線被切斷。加 --parts 重問")
        if name not in cast or name == narrator:
            raise SystemExit(
                f"「{name}」不是可以講話的角色，可以的有："
                + "、".join(x for x in cast if x != narrator))
        if kind not in react["kinds"]:
            raise SystemExit(
                f"不認得的反應：「{kind}」。可以用的是 "
                + "、".join(react["kinds"]))
        if not text:
            raise SystemExit(f"第 {at} 句後面那句是空的")
        where[at] = (name, text, kind)

    bad = check_parts(where, react, says)
    if bad:
        raise SystemExit("反應句的形狀不對：\n  " + "\n  ".join(bad)
                         + "\n加 --parts 重問")

    # 插進去。停頓跟著那一群走 —— 反應講完才停，不是旁白講完就停。
    grown_says: list[str] = []
    grown_who: list[str] = []
    grown_holds: dict[int, float] = {}
    if -1 in holds_after:
        grown_holds[-1] = holds_after[-1]
    for at, (name, text) in enumerate(zip(who, says)):
        grown_says.append(text)
        grown_who.append(name)
        if at in where:
            grown_who.append(where[at][0])
            grown_says.append(where[at][1])
        if at in holds_after:
            grown_holds[len(grown_says) - 1] = holds_after[at]
    react_said = sum(_han(x[1]) for x in where.values())
    before_parts = says
    who, says, holds_after = grown_who, grown_says, grown_holds
    # **基準要跟著插入一起動。** `ends` 原本數的是 26 句旁白的句號，而
    # 插完之後有 33 句 —— 第三趟那道「不該多切出句號」的門拿 33 去比 26，
    # 多出來的七個其實是七句反應自己的句號，它一個都沒多切。
    # 誤報的門會叫人去修沒有壞的東西，而它退回去重問一次要三分鐘。
    ends = sum(_ends(one) for one in says)
    shape = shape_of(who, narrator)

    # **中文稿裡不要有拉丁字母。** 「我讓 Hans Egede 回島上」——
    # zh-TW 的合成器唸外文人名會唸成一串音節，而它照樣唸得出來、
    # 照樣壓得出片，只有聽的人知道不對。人名要用中譯，或者根本不提。
    latin = [one for one in says if re.search(r"[A-Za-z]{2,}", one)]
    if latin:
        raise SystemExit(
            "這幾句裡有拉丁字母，中文語音唸不好：\n  "
            + "\n  ".join(latin[:5])
            + "\n\n人名用中譯，或者不提名字。加 --again")

    # **反應句的字數額度是先付過的**（`react_cost`），所以這裡比的是
    # 「有沒有超支」，不是「有沒有改長度」—— 上一版那道門量的是改寫，
    # 而現在旁白根本不會被改寫，它永遠不會叫。不會叫的門跟沒有門一樣。
    paid = reacts_for() * REACT_WORDS
    if react_said > paid * 1.35:
        raise SystemExit(
            f"{len(where)} 句反應共 {react_said} 個字，預付的額度是 {paid}"
            f"（{reacts_for()} 句 × {REACT_WORDS} 字，容許到 "
            f"{round(paid * 1.35)}）—— 超出的部分會讓片子變長。\n"
            f"  反應句是應一聲，不是再講一段。加 --parts 重問")

    fresh = sum(_han(one) for one in says)
    (paths.home(story) / "3-script.parts.tsv").write_text(
        "\n".join(_rows(who, says, holds_after)) + "\n", encoding="utf-8")
    say(f"\n插了 {len(where)} 句反應　旁白 {len(before_parts)} 句不動　"
        f"共 {len(says)} 句（角色佔 {shape['share']:.0%}）")
    for name, one in react["kinds"].items():
        got_ = sum(1 for x in where.values() if x[2] == name)
        say(f"  {name:<4}{got_:>3}　{'▮' * got_ if got_ else '—'}")
    for name in cast:
        if name != narrator:
            say(f"  {name:<5}{sum(1 for x in who if x == name):>3} 句")
    say(f"  反應 {react_said} 字（預付 {paid}）　"
        f"合計 {fresh} 字（旁白 {said}）")

    # —— 第三支：接成一段話 ————————————————————————————
    talk_at = paths.home(story) / "3-narrate.raw.json"
    stale = (paths.raw_stale(story, talk_at, "script", ("narrate.md",))
             or talk_at.stat().st_mtime < parts_at.stat().st_mtime)
    # 這一趟的上限要含反應句已經花掉的字 —— `full` 是旁白那條線的額度，
    # 反應句的秒數是另外預付的。不加回來的話它會被自己沒花的錢擋下來。
    ceiling = full + react_said
    if again or narrate or stale:
        listing = "\n".join(f"{at:>3}　{w}　{s}"
                             for at, (w, s) in enumerate(zip(who, says)))
        got3 = ask.as_json(ask.send(story, "narrate", ask.prompt_of(
            "narrate.md", lines=listing, now=fresh, most=ceiling,
            room=ceiling - fresh, fillers="、".join(talk["fillers"]),
            pauses="、".join(str(x) for x
                            in (got_rules.get("voice") or {}).get("pauses", [])),
            rates="、".join(f"{int(x):+d}" for x
                            in (got_rules.get("voice") or {}).get("rates", [])),
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

    # **不要叫 `marks`** —— 那是模組名（就地標記那一支），在這個函式裡
    # 蓋掉它的話 `marks.check()` 會變成對 list 取屬性，而 `geo.check`
    # 掃不到：那個名字存在，只是指向別的東西。
    fills = [sum(one.count(f) for f in talk["fillers"]) for one in says]
    with_ = sum(1 for one in fills if one)
    need = len(says) // talk["every"]
    bad = []
    if with_ < need:
        bad.append(f"只有 {with_}/{len(says)} 句有語助詞，"
                   f"每 {talk['every']} 句要有一句（至少 {need} 句）"
                   f"—— 沒有語助詞的中文旁白聽起來像在唸稿")
    thickest = [one for one, n in zip(says, fills)
                if n > talk["most_per_line"]]
    if thickest:
        bad.append(f"{len(thickest)} 句的語助詞超過 "
                   f"{talk['most_per_line']} 個："
                   + "　".join(one[:16] for one in thickest[:3]))
    # **同一個句型不准用兩次。** 八個接縫裡有六個用回聲接（把角色剛說的
    # 詞拿來當開頭），而其中兩個是同一個模板：「好聽歸好聽」「照顧歸照顧」。
    #
    # 根因在 prompt：我只給了**一個**接縫的範例，而它就是回聲 —— 範例會被
    # 當成答案。prompt 現在給四種接法，這道門擋的是它又找到一招套滿全場。
    #
    # 查字面查不到（那兩句一個字都不重疊），所以比的是骨架。
    shapes: dict[str, list[str]] = {}
    for one in says:
        key = skeleton(one)
        if key:
            shapes.setdefault(key, []).append(one)
    twice = {k: v for k, v in shapes.items() if len(v) > 1}
    if twice:
        bad.append(
            "同一個句型用了不只一次：\n    "
            + "\n    ".join(
                f"{k}　×{len(v)}　" + "／".join(one[:14] for one in v)
                for k, v in twice.items()))

    # **就地標記要被檢查，而且它停的秒數要算進長度。**
    # 不檢查的話 `⏸2.5` 會安靜地在片子中間開一個兩秒半的洞 —— 那是合法的
    # SSML，壓得出片，只有看的人知道不對。
    how = got_rules.get("voice") or {}
    pauses = [float(x) for x in (how.get("pauses") or [])]
    speeds = [int(x) for x in (how.get("rates") or [])]
    marked = []
    for at, one in enumerate(says):
        marked += [f"第 {at} 句：{x}" for x in marks.check(one, pauses, speeds)]
    if marked:
        bad.append("標記不合規矩：\n    " + "\n    ".join(marked[:5]))
    held = sum(marks.held(one) for one in says)

    # **「結尾不准出現新字」那道門拿掉了。**
    #
    # 加它是為了擋「第一個開口問的，是來要它天空的人」——「天空」整篇只出現
    # 在最後一句，觀眾要在最後半秒自己把它跟前面的「飛機」接起來。
    #
    # 而字面查不出「名詞」和「虛詞」的差別：下一份稿子的結尾是「這份協議
    # 沒有結束的一天」，它擋的是「結」「束」「乎」—— 常用詞。改成查兩個字
    # 更糟（連「沒有」「的一」都算新的，因為跨詞切）。
    #
    # 更根本的是**它擋不到根源**：那一句是 spine 的 `ending` 帶下來的，
    # narrate 重寫十次都一樣。連著擋了三趟、花了 $0.7，一次都沒有讓稿子
    # 變好。**誤擋的門比沒有門糟**，所以拿掉，改用 `spine.md` 的規則
    # （「只能用前面出現過的東西」）。

    grown = sum(_han(one) for one in says)
    grown_ends = sum(_ends(one) for one in says)
    # **句號由寫的人寫，程式不補。** 補了會把「兩個短句連著講」變成
    # 「兩句各自收尾」，而一個句號是 0.425 秒 —— 26 行就是 11 秒憑空多出
    # 來的空白。這道門擋的是 narrate 多切，不是擋沒有句號。
    if grown_ends > ends * 1.25:
        bad.append(f"接完之後句尾標點從 {ends} 個變成 {grown_ends} 個 —— "
                   f"接句子不該多切出句號，每一個 {PER_END} 秒")
    # 句子中間那些 `⏸` 也是真的秒數，要一起算進去。
    whole = guess(grown, len(says), total_hold + held, grown_ends)
    if abs(whole - aim) > aim * SLACK:
        bad.append(
            f"三趟做完唸出來 {whole:.0f} 秒，目標 {aim:.0f}"
            f"（容許 {aim * (1 - SLACK):.0f}–{aim * (1 + SLACK):.0f}）"
            f"　{grown} 字、{len(says)} 行、{grown_ends} 個句號")
    if grown > ceiling * 1.06:
        bad.append(f"接完之後 {grown} 字，上限 {ceiling}"
                   f"（原本 {fresh}，額度 {ceiling - fresh}）"
                   f"—— 接詞和語助詞的字，不是新內容的字")
    if bad:
        raise SystemExit("接起來那一步不合規矩：\n  " + "\n  ".join(bad)
                         + "\n加 --narrate 重問")

    paths.save(story, "script", "\n".join(_rows(who, says, holds_after)) + "\n")
    changed = sum(1 for a, b in zip(before, says) if a != b)
    say(f"\n接起來　改寫 {changed}/{len(says)} 句　"
        f"{grown} 字（原本 {fresh}，上限 {ceiling}）")
    say(f"  語助詞 {with_}/{len(says)} 句（至少 {need}）　"
        f"句號 {grown_ends} 個　"
        f"估計 {guess(grown, len(says), total_hold, grown_ends):.0f} 秒")
    return {"lines": says, "who": who}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "",
        again="--again" in sys.argv, plain="--plain" in sys.argv,
        parts="--parts" in sys.argv, narrate="--narrate" in sys.argv)
