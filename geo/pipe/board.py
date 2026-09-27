"""把分鏡攤成一張看得懂的表。

    python3 -m geo.pipe.board <題目>

## 為什麼要這一支

分鏡現在只活在 `6-storyboard.json` 裡 —— 46 筆 JSON，沒有人會一筆一筆
打開看。而下一個看到畫面的機會是**九分鐘之後的成片**，那時候要指出
「第 23 格取景不對」已經很難。

這個專案對這種問題的解法寫在 CLAUDE.md：**每次都產出，逼迫「看」發生**。
照片那邊是接觸表，這裡是這張分鏡表。

## 一格一行，跟時間軸對齊

左邊是時間和長度，中間是鏡頭做什麼，右邊是那一格在講的台詞 ——
**畫面和台詞擺在同一行**，「這句話的時候在看哪裡」才對得起來。
"""
from __future__ import annotations

import sys
from typing import Any

from geo.pipe import marks, paths, voice as voice_module


def fields(act: dict[str, Any]) -> str:
    """一個動作的欄位，印成一行：`who=格陵蘭→丹麥　many=3`。

    **只准這一份。** 本來 board、look、watch 各抄一份，都假設值不是字串
    就是清單 —— 「跑數字」帶進一個整數，三頁一起炸，而修了一份還剩兩份。
    """
    return "　".join(
        f"{k}={'→'.join(map(str, v)) if isinstance(v, list) else v}"
        for k, v in act.items() if k not in ("move", "why"))


def rows(story: str) -> list[dict[str, Any]]:
    """一格一筆，補上長度和那一格蓋到哪幾句。"""
    board = paths.load(story, "storyboard")
    cuts, whole = board["cuts"], float(board["seconds"])
    said = voice_module.read_script(story)
    lines = [text for who, text in said if who != "停"]
    who = [w for w, _ in said if w != "停"]
    out = []
    for at, one in enumerate(cuts):
        until = cuts[at + 1]["at"] if at + 1 < len(cuts) else whole
        # 這一格蓋到的句子：從它那一句，到下一格那一句之前
        first = one["line"]
        last = (cuts[at + 1]["line"] if at + 1 < len(cuts) else len(lines)) - 1
        if at + 1 < len(cuts) and cuts[at + 1]["line"] == first:
            last = first                       # 同一句裡再切一次
        out.append({
            **one,
            "for": round(until - one["at"], 2),
            "says": [(who[i], marks.strip(lines[i]))
                     for i in range(first, min(last, len(lines) - 1) + 1)],
        })
    return out


def show(story: str, say=print) -> None:
    got = rows(story)
    say(f"{len(got)} 格　"
        f"{sum(1 for x in got if x['cut'])} 切　"
        f"{sum(1 for x in got if not x['cut'])} 滑　"
        f"動作 {sum(len(x['do']) for x in got)} 個\n")
    for at, one in enumerate(got, 1):
        head = (f"{at:>3}  {one['at']:>6.1f}s {one['for']:>4.1f}s  "
                f"{'切' if one['cut'] else '滑'}  "
                f"{'＋'.join(one['see'])}")
        if one.get("mark"):
            head += f"　標 {'＋'.join(one['mark'])}"
        say(head)
        for act in one["do"]:
            say(f"        ◆ {act['move']}　{fields(act)}　（{act.get('why', '')}）")
        say(f"        {one['why']}")
        for name, text in one["says"]:
            say(f"        {name}｜{text}")
        say("")


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python3 -m geo.pipe.board <題目>")
        return 1
    show(sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
