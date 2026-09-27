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

# A → B → A 這種來回，整支片最多幾次。
#
# **使用者：「鏡頭切換的次數要減少，頭都暈了。」** 量出來的：58 格裡有
# 18 次來回，其中 44.7s 和 47.3s 那兩組疊在一起 —— 五格之內在兩個畫面
# 之間跳了四次。
#
# 最常見的來源是「兩個角色來回講話」：丹麥說一句、格陵蘭回一句、丹麥再
# 說一句，而分鏡跟著人跑。那是一段對話，不是三個場景 —— 找一個兩邊都
# 看得到的取景停著就好，讓聲音去分誰在講。
SWAP_MOST = 2

# 一格停超過這麼久就出聲。長鏡頭是一種選擇，但要被看見。
STARE = 6.0

# 而超過這麼久就擋。**「出聲不擋」在這一項上不夠**：2026-09-27 那一份
# 50 格裡有五格超過 6 秒，最長 11.8 秒 —— 十一秒盯著同一塊地不動，
# 觀眾會以為片子卡住了，而那正是「視覺刺激」的反面。
#
# 五格全部停在主角身上，因為那幾句台詞沒提到別的地方，模型就不換畫面。
# 它需要知道「沒有新地名也要動」——推近、拉遠、換個角度都算。
STARE_MOST = 9.0


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


def moves() -> dict[str, Any]:
    """特效目錄。**搬到 `geo/effects/` 了**，這裡只留一個轉接。

    留著是因為 `board.py`、`look.py`、`scene.py` 都在叫它；直接改名的話
    要同時改四個地方，而漏掉的那一個不會報錯。
    """
    from geo import effects
    return effects.catalogue()


def _moves_table() -> str:
    from geo import effects
    return effects.menu()


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
        # **集合裡的成員算看得到。** 這一格看的是「北約」，而北約包含
        # 美國 —— 畫面上真的畫著美國那一塊，只是名字叫北約。門比的是
        # 地名字面，不知道這件事，於是報「講美國而畫面上沒有」。
        #
        # 誤報的門會叫人去修沒有壞的東西，而修的方式是重問一趟（五分鐘、
        # $0.8）。
        inside = set(shown)
        for one in shown:
            for member in (atlas.get(one) or {}).get("draw") or []:
                for name, got in atlas.items():
                    if got.get("geoId") == member:
                        inside.add(name)
        missing = [x for x in want if x not in inside]
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
    if again or paths.raw_stale(story, raw_at, "storyboard", ("storyboard.md",)):
        # 骨幹現在是「一句一筆」（role + point），不是節點表。**送 role
        # 過去**：分鏡看得到哪幾句是吐槽、哪一句是翻面，才知道哪個接縫
        # 是真的斷點。
        nodes = "\n".join(
            f"{at:>3}　{one['role']:<4}　{one['point'][:46]}"
            for at, one in enumerate(bones["lines"]))
        lines = "\n".join(
            f"{at:>3}　{who}　{text}"
            for at, (who, text) in enumerate(zip(heard["who"],
                                                 heard["lines"])))
        got = ask.as_json(ask.send(story, "storyboard", ask.prompt_of(
            "storyboard.md", places=_places_table(atlas),
            title=spec["title"], turn=bones["turn"],
            ending=bones.get("ending", ""), nodes=nodes, lines=lines,
            seconds=f"{whole:.0f}", count=len(heard["lines"]),
            aim=aim, most=round(aim * MOST_TIMES),
            moves=_moves_table(),
            stare_most=f"{STARE_MOST:.0f}",
            swap_most=SWAP_MOST), say))
        raw_at.write_text(json.dumps(got, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    else:
        say(f"沿用 {raw_at.name}（上游沒動過；要重問加 --again）")
        got = json.loads(raw_at.read_text(encoding="utf-8"))

    menu = moves()
    rows = got.get("shots") or []
    if not rows:
        raise SystemExit("一格都沒有")
    wide, high = spec["video"]["width"], spec["video"]["height"]
    cuts: list[dict[str, Any]] = []
    # **不要叫 `dropped`** —— 底下「併掉幾格」那段已經用了這個
    # 名字，而它是整數。蓋掉之後 `len()` 當場炸，算好運；
    # 反過來（整數被 list 蓋掉）就是安靜地算錯。
    gaps: list[str] = []
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
        # **挑的動作要驗，而驗證是照目錄長出來的。**
        # 加一種特效不用碰這裡 —— 要什麼欄位、可以填哪些值，
        # 全部寫在 `geo/data/effects.json`。
        from geo import effects as fx
        acts = []
        for act in (one.get("do") or []):
            kind = act.get("type") or fx.by_name().get(act.get("move", ""))
            try:
                spec_ = fx.check(act, kind or str(act.get("move")), atlas,
                                 f"第 {at} 句")
            except fx.Incomplete as gap:
                gaps.append(str(gap))
                continue
            spec_["move"] = fx.catalogue()[spec_["type"]]["名"]
            acts.append(spec_)

        # **推近改的是相機，不是疊加層。**
        #
        # 它不畫任何東西 —— 它讓這一格的取景變成那塊地的某一角，而「推」
        # 那個動作是原本就有的滑鏡頭做的（上一格比較寬，滑過來就是推近）。
        # 所以它在這裡處理，`geo/effects/builders.py` 那一支是空的。
        #
        # 「西北角」查不到座標，但算得出來：把框切成九宮格取一格。
        closer = {one_["who"][0]: one_.get("方位", "整個")
                  for one_ in acts if one_["type"] == "closeup"}
        boxes = [camera_module.part_of(atlas[x]["bbox"], closer[x])
                 if x in closer else atlas[x]["bbox"]
                 for x in see if atlas[x]["kind"] == "area"]
        boxes += [_around(atlas[x]["at"]) for x in see
                  if atlas[x]["kind"] == "point"]
        astray = [x for x in closer if x not in see]
        if astray:
            raise SystemExit(
                f"第 {at} 句要推近「{'、'.join(astray)}」，"
                f"而那一格看的是 {'＋'.join(see)} —— 推近的對象要在 see 裡面")
        shot = _fit(camera_module.merge(boxes), wide, high, spec, at, see, say)
        tint = [str(x) for x in (one.get("tint") or see)]
        cuts.append({
            "at": round(when, 3), "line": at, "word": want,
            "see": see, "mark": [str(x) for x in (one.get("mark") or [])],
            "tint": [x for x in tint if atlas[x]["kind"] == "area"],
            "cut": bool(one.get("cut")),
            "why": str(one.get("why") or ""), "camera": shot,
            "do": acts,
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
    slow = [(one["at"], got) for one, got in zip(cuts, spans) if got > STARE]
    if slow:
        say(f"⚠ {len(slow)} 格停超過 {STARE:.0f} 秒沒換畫面："
            + "　".join(f"{a:.0f}s 停 {b:.1f}s" for a, b in slow[:5]))
    # **來回切。** 前一格和後一格看的是同一組地方，而中間這一格不是。
    # **推近的角落也算「看哪裡」。** 不算的話，「格陵蘭西北 → 格陵蘭
    # 東南 → 格陵蘭整個」三格的 `see` 都是「格陵蘭」，門看不出它在島上
    # 跳來跳去 —— 而那跟在兩個國家之間跳一樣暈。
    def _where(one):
        got = set(one["see"])
        for act in one.get("do") or []:
            if act["type"] == "closeup" and act.get("方位", "整個") != "整個":
                got = {f"{x}的{act['方位']}" if x == act["who"][0] else x
                       for x in got}
        return got

    sees = [_where(one) for one in cuts]
    # **只算真的跳走的。** A→B→A 分兩種：
    #
    #   中間那格跟前後有交集   只是退開一點、或推近其中一個 —— 不會暈
    #   中間那格完全是別的地方  跳到另一邊又跳回來 —— 這才是使用者說的那種
    #
    # 第一版兩種都算，於是「格陵蘭＋北歐 → 北歐＋挪威＋格陵蘭 → 北歐＋
    # 格陵蘭」（只是多帶一個挪威入鏡）也被判成來回，而那一格很合理。
    swaps = [i for i in range(1, len(sees) - 1)
             if sees[i - 1] == sees[i + 1] and not (sees[i] & sees[i - 1])]
    soft = [i for i in range(1, len(sees) - 1)
            if sees[i - 1] == sees[i + 1] != sees[i] and (sees[i] & sees[i - 1])]
    if soft:
        say(f"⚠ {len(soft)} 次「退開再回來」（中間那格跟前後有交集，不擋）")
    if len(swaps) > SWAP_MOST:
        raise SystemExit(
            f"來回切了 {len(swaps)} 次（最多 {SWAP_MOST}）—— "
            f"A→B→A 那種，觀眾剛認得畫面就換回去了。\n  "
            + "\n  ".join(
                f"{cuts[i-1]['at']:.0f}s　{'＋'.join(cuts[i-1]['see'])}"
                f" → {'＋'.join(cuts[i]['see'])}"
                f" → {'＋'.join(cuts[i+1]['see'])}" for i in swaps[:5])
            + "\n  兩個角色來回講話的時候，找一個兩邊都看得到的取景停著，"
              "不要跟著人跑。加 --again 重排")
    say(f"  來回切 {len(swaps)} 次（上限 {SWAP_MOST}）")

    worst = [(one["at"], got) for one, got in zip(cuts, spans)
             if got > STARE_MOST]
    if worst:
        raise SystemExit(
            f"這幾格停太久了（上限 {STARE_MOST:.0f} 秒）：\n  "
            + "\n  ".join(f"{a:.0f} 秒那一格停了 {b:.1f} 秒" for a, b in worst)
            + f"\n  盯著同一塊地十秒不動，觀眾會以為片子卡住。\n"
              f"  **沒有新地名也可以換畫面** —— 推近看細節、拉遠看它在哪、"
              f"換一個一起看的對象。加 --again 重排")

    # 少填欄位的丟掉了，但要出聲 —— 丟太多表示 prompt 沒講清楚，
    # 那是該回頭修的，不是每次手動忽略。
    if gaps:
        asked = sum(len(x.get("do") or []) for x in rows)
        say(f"⚠ {len(gaps)}/{asked} 個動作少了欄位，丟掉了：")
        for one_ in gaps[:5]:
            say(f"    {one_}")
        if len(gaps) > max(2, asked // 3):
            raise SystemExit(
                f"{len(gaps)}/{asked} 個動作少欄位 —— 太多了，"
                f"表示 prompt 沒把必填講清楚。加 --again 重問")

    # **整支片的上限，要走完才數得出來。** 「閃一下」一支片最多兩次，
    # 多了就像壞掉的燈 —— 而每一格各自看的時候都合法。
    used: dict[str, int] = {}
    for one in cuts:
        for act in one["do"]:
            used[act["type"]] = used.get(act["type"], 0) + 1
    over = [(k, v) for k, v in used.items()
            if menu[k].get("most_per_film")
            and v > int(menu[k]["most_per_film"])]
    if over:
        raise SystemExit(
            "這幾種用太多次了：\n  "
            + "\n  ".join(f"「{k}」{v} 次（整支片最多 "
                          f"{menu[k]['most_per_film']} 次）"
                          for k, v in over)
            + "\n加 --again 重排")
    if used:
        say("\n挑了這些動作：")
        for name, one_ in menu.items():
            if not one_.get("renders"):
                continue
            got_ = used.get(name, 0)
            say(f"  {one_['名']:<5}{got_:>3}　{'▮' * got_ if got_ else '—'}")
        never = [one_["名"] for name, one_ in menu.items()
                 if one_.get("renders") and name not in used]
        if never:
            say(f"  （這幾種一次都沒挑：{'、'.join(never)}）")
    else:
        say("⚠ 一個動作都沒挑 —— 46 格全部只有塗色")

    paths.save(story, "storyboard", {"seconds": whole, "cuts": cuts})
    return {"cuts": cuts}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
