"""每一種特效怎麼變成渲染器吃的東西。

一種一支，用 `@builds("type")` 登記。**加一種不用動別人。**

## 寫一支 builder 的規矩

```
吃    spec（共通契約 ＋ 那一種自己的欄位）、目錄那一格、world、out
做    往 out 的某個陣列塞東西
不做  不要自己算時間軸的原點（spec.start_s 已經是絕對秒數）
      不要猜資料 —— 缺什麼就 raise SkipThis，理由會被印出來
```

## 欄位名一律去 `src/schema.ts` 查過

`curve` 我照直覺寫 `"arc"`，而 enum 是 `greatCircle|straight`；
`fields` 的 blobs 要包在 `keys` 裡；`小圖示　警告` 對到 `"marker"` 不是
`"warning"`。三個都是**看起來很合理的猜測**，而猜錯的下場是那一格什麼
都沒畫 —— 型別是對的，`npm run validate` 之外看不出來。
"""
from __future__ import annotations

from typing import Any

from geo.effects import SkipThis, builds


def _spot(world: dict[str, Any], name: str) -> list[float]:
    got = (world["atlas"].get(name) or {}).get("at")
    if not got:
        raise SkipThis(f"「{name}」沒有座標")
    return list(got)


def _ids(world: dict[str, Any], name: str) -> list[str]:
    got = world["atlas"].get(name) or {}
    out = list(got.get("draw") or ([got["geoId"]] if got.get("geoId") else []))
    if not out:
        raise SkipThis(f"「{name}」不是一塊畫得出來的地")
    return out


def _end(spec: dict[str, Any], world: dict[str, Any],
         extra: float = 0.0) -> float:
    return round(min(spec["start_s"] + spec["duration_s"] + extra,
                     float(world["whole"])), 2)


# ── 畫在地圖上 ──────────────────────────────────────────

@builds("highlight_region")
def _tint(spec, got, world, out) -> None:
    box = spec["params"]
    for name in spec["region"]:
        for geo in _ids(world, name):
            out["highlights"].append({
                "geoId": geo, "start": spec["start_s"],
                "end": _end(spec, world), **box})


def _stagger(spec, got, world, out, names, box) -> None:
    """幾塊地依序亮。**間隔照格子長度縮，但不短於下限。**

    放不下的時候（擠到下限還是超出這一格），它會溢到下一格 —— 那是
    對的：疊加層的時間軸是整支片，不是那一格。
    """
    step = max(float(box.pop("gap_least", 0.25)),
               min(float(box.pop("gap", 0.45)),
                   spec["span_s"] / max(1, len(names))))
    for i, name in enumerate(names):
        for geo in _ids(world, name):
            out["highlights"].append({
                "geoId": geo, "start": round(spec["start_s"] + i * step, 2),
                "end": _end(spec, world, spec["span_s"]), **box})


@builds("highlight_sequence")
def _sequence(spec, got, world, out) -> None:
    _stagger(spec, got, world, out, spec["regions"], spec["params"])


@builds("light_up")
def _lights(spec, got, world, out) -> None:
    _stagger(spec, got, world, out, spec["regions"], spec["params"])
    if spec.get("globe"):
        # 地球儀是**整支片**的設定，不是一格的 —— 渲染器的 projection
        # 在頂層。中途換會整個重畫，所以只記下來讓 scene 決定。
        world.setdefault("wants", {})["globe"] = True


@builds("animate_field")
def _field(spec, got, world, out) -> None:
    box = spec["params"]
    spot = _spot(world, spec["region"][0])
    wide, high = box.pop("radius", [22.0, 9.0])
    out["fields"].append({
        "palette": (got.get("調色") or {}).get(spec.get("調色", ""), "cold"),
        # blobs 包在 `keys` 裡面，不是頂層 —— 那一格是「這一刻那幾團在哪」
        "keys": [{"at": spec["start_s"],
                  "blobs": [[spot[0], spot[1], wide, high, 1.0]]}],
        "start": spec["start_s"], "end": _end(spec, world), **box})


@builds("animate_flow")
def _wind(spec, got, world, out) -> None:
    box = spec["params"]
    a, b = (_spot(world, x) for x in (spec["box"][0], spec["box"][-1]))
    out["winds"].append({
        "box": [min(a[0], b[0]), min(a[1], b[1]),
                max(a[0], b[0]), max(a[1], b[1])],
        "direction": float(spec.get("direction", 270)),
        "start": spec["start_s"], "end": _end(spec, world), **box})


@builds("detach_place")
def _detach(spec, got, world, out) -> None:
    box = spec["params"]
    for name in spec["who"]:
        for geo in _ids(world, name):
            out["highlights"].append({
                "geoId": geo, "start": spec["start_s"],
                "end": _end(spec, world),
                "detach": {"at": spec["start_s"], **box}})


@builds("closeup")
def _closeup(spec, got, world, out) -> None:
    """推近改的是相機，在 `storyboard` 那一步做，這裡什麼都不畫。

    留一支空的 builder 是為了**別讓它落進「沒有 builder」那個警告** ——
    不然每一次推近都會印一行「畫不出來」，而它其實做了。
    """


# ── 畫在地圖上面 ────────────────────────────────────────

@builds("draw_route")
def _route(spec, got, world, out) -> None:
    box = spec["params"]
    out["lines"].append({
        "from": _spot(world, spec["from"][0]),
        "to": _spot(world, spec["to"][0]),
        "start": spec["start_s"], "duration": spec["duration_s"],
        "end": _end(spec, world, box.pop("stay", 3.0)), **box})


@builds("animate_face")
def _face(spec, got, world, out) -> None:
    box = spec["params"]
    arms = box.pop("arms", "down")
    out["faces"].append({
        "at": _spot(world, spec["who"][0]), "start": spec["start_s"],
        "end": _end(spec, world),
        "keys": [{"at": spec["start_s"], "arms": arms,
                  "mood": (got.get("表情") or {}).get(
                      spec.get("表情", ""), "neutral")}],
        **box})


@builds("circle_place")
def _circle(spec, got, world, out) -> None:
    box = spec["params"]
    out["circles"].append({
        "coordinates": _spot(world, spec["who"][0]),
        "start": spec["start_s"],
        "end": _end(spec, world, box.pop("stay", 1.8)), **box})


@builds("pulse_point")
def _pulse(spec, got, world, out) -> None:
    box = spec["params"]
    name = spec["at"][0]
    spot = _spot(world, name)
    font = box.pop("fontSize", 46)
    off = box.pop("offset", [0, -52])
    out["markers"].append({"coordinates": spot, "start": spec["start_s"],
                           "end": _end(spec, world), **box})
    out["labels"].append({"text": name, "coordinates": spot, "offset": off,
                          "fontSize": font, "style": "tag",
                          "start": spec["start_s"], "end": _end(spec, world)})


@builds("place_geo_asset")
def _icon(spec, got, world, out) -> None:
    out["icons"].append({
        "kind": (got.get("圖示") or {}).get(spec.get("圖示", ""), "marker"),
        "at": _spot(world, spec["at"][0]), "start": spec["start_s"],
        "end": _end(spec, world), **spec["params"]})


# ── 整個畫面 ────────────────────────────────────────────

@builds("lift_to_stage")
def _stage(spec, got, world, out) -> None:
    box = spec["params"]
    names = spec["who"]
    most = int(box.pop("most", 4))
    if len(names) > most:
        raise SkipThis(f"{len(names)} 個上台，最多 {most} 個")
    size = {1: box.pop("size_one", 460),
            2: box.pop("size_two", 380)}.get(len(names),
                                             box.pop("size_many", 240))
    for k in ("size_one", "size_two", "size_many"):
        box.pop(k, None)
    step = box.pop("gap", 0.1)
    out["dims"].append({"opacity": box.pop("dim", 0.5),
                        "start": spec["start_s"], "end": _end(spec, world)})
    wide = 1.0 / (len(names) + 1)
    # `same_scale` 打開的話照真實面積算：渲染器預設把每一塊塞進同樣大的
    # 方框（各自放大），所以要比大小就得自己算 size。
    areas = []
    for name in names:
        b = (world["atlas"].get(name) or {}).get("bbox")
        areas.append((b[2] - b[0]) * (b[3] - b[1]) if b else 1.0)
    biggest = max(areas) or 1.0
    for i, name in enumerate(names):
        one = size
        if spec.get("same_scale"):
            one = max(60, round(size * (areas[i] / biggest) ** 0.5))
        out["silhouettes"].append({
            "geoIds": _ids(world, name), "size": one,
            "screen": [round(wide * (i + 1), 3), 0.42], "label": name,
            "delay": round(i * step, 2), "start": spec["start_s"],
            "end": _end(spec, world), **box})


@builds("count_up")
def _counter(spec, got, world, out) -> None:
    box = spec["params"]
    many = spec.get("to")
    if not str(many).strip().lstrip("-").isdigit():
        raise SkipThis(f"`to` 不是數字（{many!r}）—— 不從台詞猜")
    out["labels"].append({
        "text": "{n}" + str(spec.get("unit") or ""),
        "coordinates": _spot(world, spec["at"][0]),
        "count": {"from": 0, "to": int(many),
                  "seconds": box.pop("seconds", 1.2)},
        "start": spec["start_s"], "end": _end(spec, world), **box})


@builds("title_card")
def _card(spec, got, world, out) -> None:
    # 目錄把 `標題` 列成選填，說「不給就用題目的標題」—— 那句話要在這裡
    # 兌現。**寫在說明裡而程式沒做，等於沒寫。**
    title = str(spec.get("title")
                or (world.get("spec") or {}).get("title") or "").strip()
    if not title:
        raise SkipThis("沒有標題，題目也沒有名字")
    out["cards"].append({"title": title, "start": spec["start_s"],
                         "end": _end(spec, world), **spec["params"]})


@builds("dim_map")
def _dim(spec, got, world, out) -> None:
    out["dims"].append({"start": spec["start_s"], "end": _end(spec, world),
                        **spec["params"]})


@builds("flash")
def _flash(spec, got, world, out) -> None:
    box = spec["params"]
    out["flashes"].append({
        "at": spec["start_s"], "seconds": box.get("seconds", 0.14),
        "colors": [box.get("color", "#FFF3E0")],
        "opacity": box.get("opacity", 0.8)})


@builds("shake")
def _shake(spec, got, world, out) -> None:
    box = spec["params"]
    out["shakes"].append({"at": spec["start_s"],
                          "seconds": box.get("seconds", 0.45),
                          "amount": box.get("amount", 14)})


@builds("transition_scene")
def _wipe(spec, got, world, out) -> None:
    box = spec["params"]
    out["transitions"].append({
        "at": spec["start_s"], "type": box.get("type", "wipe"),
        "seconds": box.get("seconds", 0.45),
        "color": box.get("color", "#1A1A1A"),
        "shape": box.get("shape", "curve")})


# ── 描邊界 ──────────────────────────────────────────────

_OUTLINES: dict[str, list] | None = None


def _outline(geo: str) -> list:
    """一塊地的輪廓，取樣過的。**讀我們自己那一份**，執行期不碰隔壁
    那個 40 MB 的 geojson（`atlas_build` 已經把它算成 185 KB）。"""
    global _OUTLINES
    if _OUTLINES is None:
        import json
        from geo.pipe import atlas_build
        _OUTLINES = json.loads(atlas_build.OUTLINES.read_text(encoding="utf-8"))
    return _OUTLINES.get(geo) or []


@builds("reveal_boundary")
def _boundary(spec, got, world, out) -> None:
    """一筆一筆把國界描出來。

    渲染器的 `draw`（線自己畫上去）只對**線狀**的地區有效，而國家是面 ——
    所以描不了。繞過去的做法是**拿 `lines` 串**：輪廓切成 N 段，排 N 筆
    線、每筆晚一格開始，看起來就是一條線描過去。

    第 i 段畫完的那一刻正好是第 i+1 段開始 —— 中間有縫的話會看見一節一
    節跳，而不是一條線在走。
    """
    box = spec["params"]
    # **模型填的贏預設，而預設一定要從 box 拿掉** —— 不拿掉的話
    # `points` 會混進 line 那一格，變成渲染器不認得的欄位。
    fallback = box.pop("points", 48)
    many = int(spec.get("points") or fallback)
    stay = box.pop("stay", 2.5)
    most = int(box.pop("most", 3))
    name = spec["region"][0]

    # **群體要擋下來，不是只描第一塊。** 「北約」在字典裡是 30 個 geoId，
    # `[0]` 會安靜地只描比利時 —— 分鏡表上寫著描北約，畫面上是比利時的
    # 邊界，兩邊都不報錯。這種「回報一個看起來合理的替代品」比回報零貴。
    geos = _ids(world, name)
    if len(geos) > most:
        raise SkipThis(f"「{name}」是 {len(geos)} 塊地，描邊界一次最多 {most} 塊")

    rings = [(geo, _outline(geo)) for geo in geos]
    rings = [(geo, r) for geo, r in rings if r]
    if not rings:
        raise SkipThis(f"「{name}」沒有輪廓（{'、'.join(geos)} 都查不到）")

    end = _end(spec, world, stay)
    share = spec["duration_s"] / len(rings)
    for n, (_, ring) in enumerate(rings):
        # 取樣密度由模型管不著的地方決定：輪廓存了 48 點，要少一點就抽。
        pts = ring[::max(1, len(ring) // many)]
        pts.append(pts[0])                   # 收口，不然差最後一段
        step = share / max(1, len(pts) - 1)
        began = spec["start_s"] + n * share
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            # **跨換日線的那一段要丟掉。** 經度從 179 跳到 −179 的話，
            # 兩點之間會被畫成一條橫跨整個地球的線 —— 俄羅斯、斐濟都會遇到。
            if abs(a[0] - b[0]) > 90:
                continue
            out["lines"].append({
                "from": list(a), "to": list(b),
                "start": round(began + i * step, 3),
                "duration": round(step, 3), "end": end,
                "curve": "straight", "bow": 0, "arrow": False, **box})
