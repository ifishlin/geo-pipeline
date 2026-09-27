"""特效函式庫：目錄、驗證、分派。

    from geo import effects
    effects.menu()                 給模型看的那張表
    effects.build(cuts, world)     分鏡挑的 → 渲染器吃的疊加層

照 `geo/地理短影音_通用特效函式目錄_Remotion_MapLibre.md` 那份規格建。

## 加一種特效要動兩個地方，而且只有兩個

```
geo/data/effects.json      一格：中文名、什麼時候用、什麼時候不要用、
                           要什麼資料、參數的預設值、畫不畫得出來
geo/effects/builders.py    一支同名的 builder，用 @builds("type") 註冊
```

**分派邏輯不用動。** 上一版是一條長長的 `if how == …` 鏈，加一種就要在
中間插一段，而插錯地方不會報錯 —— 那一種只是安靜地不畫。

## 共通契約

每一個 spec 都有這幾格（規格書第 25 行那個 `EffectBase`）：

```
id          這一個的編號，除錯用
type        哪一種（英文，對得上規格書）
start_s     從影片開頭算幾秒
duration_s  多久
layer       map / geo_overlay / screen_overlay / cutaway / audio
seed        隨機外觀固定用（還沒有 builder 用到，但契約先留著）
```

**時間對外一律用秒。** 換算成影格是渲染那一端的事，我們不碰。

## 畫得出來和該往哪裡長，要分開

目錄裡有 `renders: false` 的那幾種（移動物件、點資料、粒子、插畫面、
音效）—— 規格書列了，而渲染器現在沒有。它們**不會進選單**，每一格都
寫著「沒做」的理由。

「畫不出來」要真的去試過才算數。描邊界本來也在這一列，理由是「渲染器的
`draw` 只對線狀的地區有效，而我們的字典只有面」—— 那句話沒錯，錯的是
我從它推論到「所以做不到」。繞過去的路是**拿 `lines` 串**（輪廓切成 48
段、每段晚一格開始），48 條線只讓那一格慢 1.7%。**「這一支 API 做不到」
不等於「這件事做不到」**，而寫進目錄的「沒做」會讓沒有人再去想第二條路。

混在一起的話，模型會挑一個畫不出來的，而成片裡沒有那個東西 ——
分鏡表和成片各說各話，兩邊都不報錯。
"""
from __future__ import annotations

import json
from typing import Any, Callable

from geo.pipe import paths

WHERE = paths.GEO / "data" / "effects.json"

# type → builder。`@builds("draw_route")` 註冊進來。
_MAKERS: dict[str, Callable[..., None]] = {}

# 渲染器影片層那幾個陣列。builder 往這裡加東西。
SLOTS = ("lines", "faces", "circles", "labels", "cards", "dims", "flashes",
         "shakes", "transitions", "icons", "fields", "winds", "highlights",
         "silhouettes", "markers")


def builds(kind: str) -> Callable:
    """把一支 builder 登記成某一種特效。"""
    def keep(fn: Callable) -> Callable:
        _MAKERS[kind] = fn
        return fn
    return keep


def _book() -> dict[str, Any]:
    return json.loads(WHERE.read_text(encoding="utf-8"))


def catalogue() -> dict[str, dict[str, Any]]:
    got = _book()["kinds"]
    return {k: v for k, v in got.items() if not k.startswith("_")}


def aliases() -> dict[str, str]:
    """模型填的欄位名 → 程式用的。**一張表管全部。**

    prompt 印中文給模型看（「要給：誰、從、到」），它就照著填中文 ——
    那不是它的錯，是我印什麼它填什麼。每一種各自對照的話會漏，
    而漏掉的症狀是「不認得的欄位」，退回重問一趟五分鐘。
    """
    return _book().get("別名") or {}


def doable() -> dict[str, dict[str, Any]]:
    """畫得出來的那幾種。**選單只列這些。**"""
    return {k: v for k, v in catalogue().items() if v.get("renders")}


def by_name() -> dict[str, str]:
    """中文名 → type。模型挑中文，程式用英文。"""
    return {v["名"]: k for k, v in catalogue().items()}


def menu() -> str:
    """給模型看的那張表。**從目錄長出來，不是手寫的散文。**

    手寫的話加一種要改兩個地方，而漏掉的那一邊不會報錯。
    """
    out = []
    for kind, one in doable().items():
        bits = [f"**{one['名']}** —— {one['當']}"]
        if one.get("不當"):
            bits.append(f"\n  不要：{one['不當']}")
        need = [f"{zh}（{why}）" for zh, why in
                (one.get("要") or {}).values()]
        need += [f"{zh}（{why}，可省）" for zh, why in
                 (one.get("選填") or {}).values()]
        if need:
            bits.append(f"\n  要給：{'、'.join(need)}")
        for key in ("表情", "圖示", "調色", "方位"):
            if one.get(key):
                got = one[key]
                bits.append(f"\n  {key}只能挑："
                            + "、".join(got if isinstance(got, list) else got))
        for zh, why in (one.get("選項") or {}).values():
            bits.append(f"\n  可以打開「{zh}」：{why}")
        if one.get("most_per_film"):
            bits.append(f"\n  **整支片最多 {one['most_per_film']} 次**")
        out.append("".join(bits))
    return "\n\n".join(out)


def check(act: dict[str, Any], kind: str, atlas: dict[str, Any],
          where: str) -> dict[str, Any]:
    """驗一個動作，回整理好的 spec。不合就 raise。

    **驗證是照目錄長出來的**，不是每一種寫一段 —— 加一種特效不用碰
    這支函式。
    """
    book = catalogue()
    if kind not in book:
        raise SystemExit(
            f"{where} 挑了不認得的動作「{kind}」。"
            f"可以挑的是：{'、'.join(v['名'] for v in doable().values())}")
    one = book[kind]
    if not one.get("renders"):
        raise SystemExit(
            f"{where} 挑了「{one['名']}」，而渲染器還畫不出來 ——"
            f"{one.get('沒做', '')}")

    # 先把中文欄位名換成程式用的
    fold = aliases()
    act = {fold.get(k, k): v for k, v in act.items()}

    got: dict[str, Any] = {}
    for key, (zh, why) in (one.get("要") or {}).items():
        val = act.get(key)
        if val in (None, "", []):
            raise Incomplete(f"{where} 的「{one['名']}」少了 {zh}（{why}）")
        if key in ("region", "who", "at", "from", "to"):
            names = [val] if isinstance(val, str) else list(val)
            bad = [x for x in names if x not in atlas]
            if bad:
                raise SystemExit(
                    f"{where} 的「{one['名']}」指到地圖上沒有的："
                    f"{'、'.join(bad)}")
            got[key] = names
        elif key in ("regions", "path"):
            names = list(val)
            bad = [x for x in names if x not in atlas]
            if bad:
                raise SystemExit(
                    f"{where} 的「{one['名']}」指到地圖上沒有的："
                    f"{'、'.join(bad)}")
            got[key] = names
        else:
            got[key] = val

    # 選填的：有給就收，沒給就讓 builder 用預設。**有合理預設的東西
    # 不該列成必填** —— 那會讓模型為了一個程式填得出來的空格被退回，
    # 而退一趟五分鐘。
    for key in (one.get("選填") or {}):
        if act.get(key) not in (None, "", []):
            got[key] = act[key]

    # **清單的第一個是預設。** 沒填就用它，不要退回重問 —— 退一趟五分鐘。
    for key in ("表情", "圖示", "調色", "方位"):
        if not one.get(key):
            continue
        choices = one[key]
        pick = str(act.get(key) or "")
        if not pick:
            pick = (choices[0] if isinstance(choices, list)
                    else next(iter(choices)))
        if pick not in choices:
            raise SystemExit(
                f"{where} 的「{one['名']}」{key} 是「{pick}」，可以用的："
                + "、".join(choices if isinstance(choices, list) else choices))
        got[key] = pick

    for key in (one.get("選項") or {}):
        got[key] = bool(act.get(key))

    spare = [k for k in act
             if k not in ("move", "why", "type")
             and k not in (one.get("要") or {})
             and k not in (one.get("選填") or {})
             and k not in (one.get("選項") or {})
             and k not in ("表情", "圖示", "調色", "方位")]
    if spare:
        raise SystemExit(
            f"{where} 的「{one['名']}」有不認得的欄位：{'、'.join(spare)}")

    got["type"] = kind
    got["why"] = str(act.get("why") or "")
    return got


def build(cuts: list[dict[str, Any]], world: dict[str, Any],
          say=print) -> dict[str, list[dict[str, Any]]]:
    """分鏡挑的動作 → 渲染器吃的疊加層。"""
    from geo.effects import builders            # noqa: F401  （註冊用）
    book = catalogue()
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in SLOTS}
    whole = float(world["whole"])
    missed: list[str] = []

    for at, one in enumerate(cuts):
        until = cuts[at + 1]["at"] if at + 1 < len(cuts) else whole
        start, span = float(one["at"]), float(until - one["at"])
        for act in one.get("do") or []:
            kind = act.get("type") or by_name().get(act.get("move", ""))
            got = book.get(kind or "")
            if not got or not got.get("renders"):
                missed.append(f"{start:.0f}s {act.get('move')}：畫不出來")
                continue
            maker = _MAKERS.get(kind)
            if maker is None:
                # **目錄有、builder 沒有，要出聲。** 這是「加了一格忘了
                # 註冊」的症狀，而不出聲的話那一種就安靜地不畫。
                missed.append(f"{start:.0f}s {got['名']}：沒有 builder")
                continue
            spec = {
                "id": f"{kind}-{at}", "type": kind,
                "start_s": round(start, 2),
                "duration_s": round(max(float(got.get("least") or 0.5),
                                        min(float(got.get("seconds") or 2.0),
                                            span)), 2),
                "span_s": round(span, 2),
                "layer": got.get("layer", "geo_overlay"),
                "params": dict(got.get("params") or {}),
                **{k: v for k, v in act.items()
                   if k not in ("move", "type", "why")},
            }
            try:
                maker(spec, got, world, out)
            except SkipThis as why:
                missed.append(f"{start:.0f}s {got['名']}：{why}")

    if missed:
        # **畫不出來的要出聲。** 分鏡表上寫著有這個動作，成片裡沒有 ——
        # 兩邊都不報錯，只有比對的人看得出來。
        say(f"⚠ {len(missed)} 個動作沒畫出來：")
        for one_ in missed[:6]:
            say(f"    {one_}")
    return {k: v for k, v in out.items() if v}


class SkipThis(Exception):
    """這一個畫不出來，但不該讓整支片停下來。理由會被印出來。"""


class Incomplete(Exception):
    """模型少填了一格。**丟掉這一個動作，不要停掉整支片。**

    26 個動作裡少一個欄位，而重問一趟是五分鐘、$0.8 —— 那個代價不成
    比例。丟掉並出聲，人看得到「少了什麼」就好。

    跟 `SystemExit` 的分別：填錯（不認得的種類、地圖上沒有的地方、
    清單外的值）是**錯**，要停；少填是**不完整**，丟掉那一個還是一支
    完整的片。
    """
