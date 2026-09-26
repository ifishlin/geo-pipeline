"""故意違規，看門會不會叫。

    python3 -m geo.checks._parts

反應句那組門是今天才加的，**一條都還沒被真的觸發過**。這個專案有過一道
門自己就帶著它要擋的錯（存主鍵、讀檔名），永遠對不上、靜默回「沒過期」，
而抓到它是因為真的去改一次來試。

所以每一道門這裡都種一次錯，看它叫不叫；而且對照組（合法的那一份）要
不叫 —— **只驗「會叫」的話，一道永遠都叫的門也會通過。**
"""
from __future__ import annotations

import sys

from geo.pipe.script import check_parts, _han
from geo.pipe.spine import rules

RULES = rules()["parts"]


# 旁白稿。**反應句的門有幾道要拿它當背景**（引進來的名字算不算新的），
# 所以對照組和每一個反例都要有一份。
SAID = ["北歐人給這島取名叫綠地。", "島上早就有人住了。",
        "他們向挪威國王低頭。", "丹麥派船來找。", "美國簽了三次字。",
        "歐洲共同體要來了。", "它自己辦了公投。", "川普說要買下它。",
        "丹麥說不賣。", "三方最後簽了字。"] * 4


def _put(spots: list[int], text: str = "我看這名字取得是真好。",
         who: str = "格陵蘭") -> dict:
    return {at: (who, text, "吐槽") for at in spots}


def _mixed(spots: list[int], text: str = "我看這名字取得是真好。") -> dict:
    """插一輪，說話的人輪流 —— 對照組不能讓「一個角色包辦」那道門叫。"""
    folk = ["格陵蘭", "丹麥", "美國"]
    return {at: (folk[i % 3], text, "吐槽") for i, at in enumerate(spots)}


SPREAD = [0, 3, 6, 9, 12, 15, 18, 21]

# 每一列：這一份違反了什麼、餵什麼進去、錯誤訊息裡應該出現的字
CASES: list[tuple[str, dict, str]] = [
    ("插太少", _mixed([0, 4, 8]), "要 6"),
    ("插太多", _mixed(list(range(0, 36, 3))), "要 6"),
    ("帶了阿拉伯數字", _mixed(SPREAD[:7]) |
     {28: ("丹麥", "我記得 1953 年那次也沒問它。", "吐槽")}, "數字"),
    ("一句太長", _mixed(SPREAD[:7]) |
     {28: ("丹麥", "我最擅長的那件事情，就是在別人家的桌子上面，"
                   "替一座我從來沒有去過的島嶼簽下它的名字。", "自嘲")},
     "超過"),
    ("兩個插入點貼太近", _mixed([0, 1, 4, 8, 12, 16, 20]), "隔太近"),
    # —— 底下三道是 2026-09-26 加的 ——
    ("沒有第一人稱", _mixed(SPREAD[:7]) |
     {28: ("丹麥", "那名字取得是真好。", "吐槽")}, "第一人稱"),
    ("一個角色包辦", _put(SPREAD), "最多 50%"),
    ("夾帶旁白沒講過的名字", _mixed(SPREAD[:7]) |
     {28: ("丹麥", "我那時候還在忙著跟瑞典王國吵架呢。", "吐槽")},
     "沒講過的名字"),
]

GOOD = _mixed(SPREAD)


def main() -> int:
    print(f"門的設定：至少 {RULES['least']}、最多 {RULES['most']} 句，"
          f"一句最多 {RULES['words_most']} 字，至少隔 {RULES['gap_least']} 句\n")
    wrong = 0

    # 對照組：合法的那一份。**這一格比底下五格重要** —— 一道永遠都叫的
    # 門，底下五格全過，而它擋掉的是每一份稿子。
    bad = check_parts(GOOD, RULES, SAID)
    if bad:
        print(f"✗ 對照組（{len(GOOD)} 句、每隔 3 句、都很短）被擋了：")
        for one in bad:
            print(f"    {one}")
        wrong += 1
    else:
        print(f"✓ 對照組放行（{len(GOOD)} 句，最長 "
              f"{max(_han(x[1]) for x in GOOD.values())} 字）")

    for name, got, want in CASES:
        bad = check_parts(got, RULES, SAID)
        hit = [one for one in bad if want in one]
        if hit:
            print(f"✓ {name:<10}門叫了：{hit[0].splitlines()[0][:52]}")
        else:
            print(f"✗ {name:<10}門沒叫（{len(got)} 句）"
                  + (f"　它說的是：{bad[0][:40]}" if bad else "　它什麼都沒說"))
            wrong += 1

    print()
    if wrong:
        print(f"{wrong} 道門沒有照預期反應 —— 沒被觸發過的門跟沒有門一樣")
    else:
        print(f"{len(CASES)} 道門都會叫，而合法的那一份不會被誤擋")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
