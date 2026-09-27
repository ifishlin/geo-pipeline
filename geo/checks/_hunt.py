"""找來源那幾道門，種違規給它們擋。

    python3 -m geo.checks._hunt

## 為什麼要這一支

`hunt` 那一步跑一趟十分鐘、兩塊美金，而它的門**在真的跑的時候幾乎不會
被觸發** —— 模型多半填得對。實測第二趟，收緊過的白名單一筆都沒擋到。

**一道沒有被觸發過的門，跟沒有門一樣。** 這一支在幾秒內把每一道都踩一次，
不花錢、不上網（除了兩個真的要驗網址的案例）。

## 已經抓到過的

第一趟：大學的新聞稿被標成 `official`（`.edu` 在白名單裡）——
白名單混淆了「可信」和「一手」。

第二趟：`brookings.edu` 被標成 `news`。**白名單是單向的** ——
只查「標 study 的是不是 study 網域」，往另一邊標就繞過去了。
"""
from __future__ import annotations

import sys
from typing import Any

from geo.pipe import hunt

# 一筆合法的。**控制組要先會過** —— 不然全部被擋也叫「每一道都會叫」。
FINE = {"url": "https://en.wikipedia.org/wiki/Greenland", "kind": "wiki",
        "why": "身分", "gist": "格陵蘭的地位變遷"}

# (名字, 這一筆, 該不該被收下)
SEEDS: list[tuple[str, dict[str, Any], bool]] = [
    ("控制組：合法的一筆", FINE, True),
    ("kind 不在清單裡",
     {**FINE, "url": "https://en.wikipedia.org/wiki/Denmark",
      "kind": "blog"}, False),
    ("official 標在非政府網域",
     {**FINE, "url": "https://www.atlanticcouncil.org/x/",
      "kind": "official"}, False),
    ("study 標在非學術網域",
     {**FINE, "url": "https://www.cbsnews.com/news/x/", "kind": "study"},
     False),
    ("智庫網域標成 news（反向）",
     {**FINE, "url": "https://www.brookings.edu/articles/x/",
      "kind": "news"}, False),
    ("政府網域標成 news（反向）",
     {**FINE, "url": "https://www.whitehouse.gov/x/", "kind": "news"},
     False),
    ("網址不存在",
     {**FINE, "url": "https://en.wikipedia.org/wiki/Zzz_no_such_xyz_page"},
     False),
]


def _fresh() -> dict[str, Any]:
    return {"spine": "", "read": [], "unknown": [], "rounds": [],
            "covered": {k: False for k in hunt.LANDS}}


def gates(say=print) -> int:
    rule = hunt._rules()
    bad = 0
    for name, one, want in SEEDS:
        state = _fresh()
        got = hunt._merge(state, {"found": [one]}, rule, 1, lambda *_: None)
        ok = (got == 1) == want
        bad += not ok
        say(f"  {'✅' if ok else '❌'} {name:<24}"
            f"{'收下' if got else '擋掉'}"
            f"{'' if ok else '　← 應該' + ('收下' if want else '擋掉')}")
    return bad


def dupes(say=print) -> int:
    """同一個網址給兩次，只能算一筆。"""
    state = _fresh()
    rule = hunt._rules()
    hunt._merge(state, {"found": [FINE]}, rule, 1, lambda *_: None)
    again = hunt._merge(state, {"found": [FINE]}, rule, 2, lambda *_: None)
    ok = again == 0 and len(state["read"]) == 1
    say(f"  {'✅' if ok else '❌'} 同一個網址給兩次　"
        f"第二次新增 {again} 筆、累計 {len(state['read'])} 筆")
    return not ok


def one_well(say=print) -> int:
    """同一個平台查兩次，只算一口井。**這是實測抓到的**。"""
    state = _fresh()
    rule = hunt._rules()
    hunt._merge(state, {"found": [
        {"url": "https://hn.algolia.com/api/v1/search?query=a",
         "kind": "voices", "why": "", "gist": ""},
        {"url": "https://hn.algolia.com/api/v1/search?query=b",
         "kind": "voices", "why": "", "gist": ""}]},
        rule, 1, lambda *_: None)
    dug = hunt.wells(state)
    ok = len(state["read"]) == 2 and len(dug) == 1
    say(f"  {'✅' if ok else '❌'} 同一口井打兩次　"
        f"收下 {len(state['read'])} 筆，但只算 {len(dug)} 口井")
    gap = [x for x in hunt._need(state, rule) if "井" in x]
    ok2 = bool(gap)
    say(f"  {'✅' if ok2 else '❌'} 而且「還缺什麼」要講出來　"
        f"{gap[0] if gap else '⚠ 沒講'}")
    return (not ok) + (not ok2)


def main() -> int:
    print("每一道門種一個違規：")
    bad = gates()
    print("重複和井：")
    bad += dupes() + one_well()
    print(f"\n{'每一道都會叫，而合法的那一筆不會被誤擋' if not bad else f'{bad} 道對不起來'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
