"""骨幹 → 台詞。

    python3 -m geo.pipe.make <題目> script

## 字數是算出來的，而且算式要給模型看

「兩分鐘大約 500 個字」這種話模型會照自己的估計來。把**算式攤開**寫進
prompt（幾秒、每秒幾個字、扣掉幾秒停頓），它就照做 —— 這是隔壁那個專案
量出來的：給一個它自己一算就發現不合理的數字，它會在回覆裡明講「我不照它」。

## 停頓也是一行

`停⇥0.8` 跟台詞同一個檔、同一條時間軸。寫成台詞的附註（「這裡停一下」）
的話，配音那一步得去解析散文，而散文會有五種寫法。

## 三道門

```
角色認得      who 只能是 cast 宣告過的，或「停」
有人對話      整支片只有旁白的話，那是解說稿不是短劇
字數在範圍裡  差太多就退回 —— 長了會超秒，短了畫面撐不滿
```
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any

from geo.pipe import ask, paths, story as story_module

# 唸多久 ＝ 字數 / RATE ＋ 句數 × PER_LINE ＋ 宣告的停頓
#
# **句數那一項是後來才加的，而它很大。** 第一版只有「每秒幾個字」，
# 用的還是對照頻道那支片量出來的 5.53 —— 寫出 585 字估計 115 秒，
# 唸出來 133 秒，超了 15%。原因是句尾換氣、角色之間換聲音的接縫都跟
# **句數**成正比，跟字數無關：36 句那一版和 49 句這一版字數只差 13 個，
# 秒數差了 16 秒。
#
# 這兩個數字是拿兩次真實合成解出來的：
#
#     572 字 36 句 宣告停 9.0 → 116.74 秒
#     585 字 49 句 宣告停 10.0 → 133.10 秒
#
# 兩點解兩個未知數，所以一定吻合 —— **下一次跑才是真正的驗證**，
# 而配音那一步會拿量到的真秒數再擋一次。
RATE = 8.22
PER_LINE = 1.060

# 一句話平均幾個字。拿來把秒數的預算換算成給模型看的字數預算。
# 兩次量到 15.9（572/36）和 11.9（585/49）—— 對話多的那一版短句多。
# 取 12，因為我們要的就是對話多的那一種。
PER_ROW = 12

# 宣告的停頓總共幾秒。模型自己決定放幾個，這只是算預算用的假設。
HOLDS = 10.0

# 估計的秒數可以離目標多遠。**這一道用秒數不用字數** —— 字數一樣而句數
# 不一樣的兩份稿子，長度可以差 16 秒。
SLACK = 0.06


def guess(said: int, rows: int, holds: float) -> float:
    """這份稿子唸出來大概幾秒。"""
    return said / RATE + rows * PER_LINE + holds


def budget(aim: float) -> int:
    """要唸滿這麼多秒，大概要寫幾個字。

    把 `rows = said / PER_ROW` 代進 `guess()` 反解 —— 一句話本身就要
    1.06 秒，所以**拆句子是有代價的**，這一式把那個代價算進去了。
    """
    per = 1 / RATE + PER_LINE / PER_ROW
    return max(50, round((aim - HOLDS) / per))


def _han(text: str) -> int:
    """唸得出來的字數：漢字加數字，不算標點。"""
    return len(re.findall(r"[一-鿿]", text)) + \
        sum(len(one) for one in re.findall(r"\d+", text))


def run(story: str, say=print, again: bool = False) -> dict[str, Any]:
    paths.insist(story, "script")
    spec = story_module.load(story)
    bones = paths.load(story, "spine")
    facts = paths.load(story, "facts")
    cast = story_module.cast_of(spec)
    aim = float(spec.get("seconds") or 116)
    words = budget(aim)

    raw_at = paths.home(story) / "3-script.raw.json"
    if again or paths.raw_stale(story, raw_at, "script"):
        nodes = "\n\n".join(
            f"### {one.get('when','')}　〔{one['beat']}〕\n{one['what']}\n"
            + "\n".join(f"  · {facts[i - 1]['said']}"
                        for i in (one.get("from") or [])
                        if 1 <= i <= len(facts))
            for one in bones["nodes"])
        who = "\n".join(
            f"- **{name}**"
            + ("　（旁白）" if one["slot"] == "narrator" else "")
            for name, one in cast.items())
        got = ask.as_json(ask.send(story, "script", ask.prompt_of(
            "script.md", title=spec["title"], turn=bones["turn"],
            ending=bones.get("ending", ""), cast=who, nodes=nodes,
            # **prompt 印的範圍就是門用的範圍。** 兩邊各寫一個數字的話，
            # 模型照 prompt 寫、程式照門退回，而退回的訊息說的是一個它
            # 從來沒看過的數字 —— 那道門是在罰它不知道的規矩。
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

    rows = got.get("lines") or []
    if not rows:
        raise SystemExit("一句台詞都沒有")
    out: list[str] = []
    said = 0
    holds = 0.0
    for at, one in enumerate(rows):
        who = str(one.get("who") or "").strip()
        text = str(one.get("say") or "").strip()
        if not text:
            raise SystemExit(f"第 {at} 行沒有內容")
        if who == "停":
            try:
                holds += float(text)
            except ValueError:
                raise SystemExit(f"第 {at} 行的停頓不是數字：{text!r}") from None
        elif who not in cast:
            raise SystemExit(
                f"第 {at} 行的「{who}」不在 cast 裡。"
                f"宣告過的是：{'、'.join(cast)}")
        else:
            said += _han(text)
        out.append(f"{who}\t{text}")

    spoken = [one for one in rows if one.get("who") != "停"]
    voices = {str(one.get("who")) for one in spoken}
    if len(voices) < 2:
        raise SystemExit(
            f"整支片只有「{'、'.join(voices)}」在講話 —— 那是解說稿，"
            f"不是短劇。資訊要靠對白傳，不是靠旁白講")
    long = guess(said, len(spoken), holds)
    if abs(long - aim) > aim * SLACK:
        raise SystemExit(
            f"這份稿子唸出來大約 {long:.0f} 秒，而目標是 {aim:.0f}"
            f"（容許 {aim * (1 - SLACK):.0f}–{aim * (1 + SLACK):.0f}）。\n"
            f"  {said} 個字 ÷ {RATE} ＝ {said / RATE:.0f} 秒"
            f"　＋ {len(spoken)} 句 × {PER_LINE} ＝ {len(spoken) * PER_LINE:.0f} 秒"
            f"　＋ 停 {holds:.0f} 秒\n"
            f"  **句數也要算錢** —— 把一句拆成兩句要多 {PER_LINE} 秒。"
            f"加 --again 重寫")

    paths.save(story, "script", "\n".join(out) + "\n")
    say(f"\n{len(spoken)} 句、{len(rows) - len(spoken)} 個停頓　"
        f"{said} 個字（預算 {words}）")
    say(f"  估計 {long:.0f} 秒 ＝ 唸 {said / RATE:.0f} ＋ 句 "
        f"{len(spoken) * PER_LINE:.0f} ＋ 停 {holds:.0f}（目標 {aim:.0f}）")
    for name in cast:
        got_ = sum(1 for one in spoken if one.get("who") == name)
        say(f"  {name:<5}{got_:>3} 句")
    return {"lines": rows}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "", again="--again" in sys.argv)
