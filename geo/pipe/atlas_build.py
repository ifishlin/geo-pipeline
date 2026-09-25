"""從圖資產一份自己的地名索引。**跑一次就好，產出進版控。**

    python3 -m geo.pipe.atlas_build

## 為什麼要自己一份

隔壁 `Map_Animation` 有 Natural Earth 的 geojson，而我們需要的只是每一塊地的
**外框和名字** —— 幾百行數字，不是幾十 MB 的多邊形。抄一份小的過來，執行期
就完全不必碰那個 repo：那邊改目錄、換資料版本、甚至整個搬走，這條路照跑。

反過來說，**渲染那一步非得用那邊不可**（多邊形要畫出來），所以那一步本來就
依賴它。分界線劃在這裡：算相機用自己的索引，畫圖用他們的資料。

## 中文名是查出來的，不是手寫的

Natural Earth 的原始檔每一筆都有 `NAME_ZHT`（繁體）。所以「格陵蘭 → GRL」
這種對照**從資料長出來**，不是我打一張表 —— 手打的表會漏、會拼錯，而拼錯的
症狀是「那一塊沒有亮起來」，畫面照樣畫得完、每道門都過。

只有少數例外要補（例如「美國」在資料裡是「美利堅合眾國」），那些寫在
`ALSO` 裡，一個一行，看得見。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from geo.pipe import paths

# 隔壁的圖資在哪。**只有這一支用得到它**，而且只在建索引的時候。
MAPS = paths.ROOT.parent / "Map_Animation" / "public" / "data"
RAW = MAPS / "ne_50m_admin_0_countries.geojson"
OUT = paths.GEO / "data" / "places.json"

# 資料裡沒有、或叫法不一樣的別名。**一個一行，看得見**。
# 值是 geoId，鍵是我們在稿子和事實裡會寫的名字。
ALSO: dict[str, str] = {
    "美國": "USA",
    "美利堅合眾國": "USA",
    "英國": "GBR",
    "荷蘭": "NLD",
    "歐盟": "_EU",
    "歐洲共同體": "_EEC",
    "北歐": "_NORDIC",
}

# 幾個「不是一個國家」的集合。列出成員，外框由成員合併算出來。
# **寫在這裡而不是散在故事裡**，因為「歐盟有哪些國家」是地理知識，
# 不是這一支片的知識 —— 下一支片要用同一份。
GROUPS: dict[str, dict[str, Any]] = {
    "_EU": {
        "name": "歐盟",
        "of": ["AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN",
               "FRA", "DEU", "GRC", "HUN", "IRL", "ITA", "LVA", "LTU", "LUX",
               "MLT", "NLD", "POL", "PRT", "ROU", "SVK", "SVN", "ESP", "SWE"],
    },
    "_EEC": {
        "name": "歐洲共同體（1985 年時）",
        "of": ["BEL", "DNK", "FRA", "DEU", "GRC", "IRL", "ITA", "LUX",
               "NLD", "PRT", "ESP", "GBR"],
    },
    "_NORDIC": {
        "name": "北歐",
        "of": ["DNK", "NOR", "SWE", "FIN", "ISL"],
    },
}


def _bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    """一塊地的外框 (西, 南, 東, 北)。

    **跨換日線的要特別處理**：俄羅斯和斐濟的多邊形橫跨 ±180，直接取
    min/max 會得到「從 -180 到 180」——整個世界。那不是錯誤，是一個
    看起來合理的答案，而算出來的相機會對著非洲。
    """
    lons: list[float] = []
    lats: list[float] = []

    def walk(node: Any) -> None:
        if (isinstance(node, list) and len(node) == 2
                and all(isinstance(one, (int, float)) for one in node)):
            lons.append(float(node[0]))
            lats.append(float(node[1]))
            return
        if isinstance(node, list):
            for one in node:
                walk(one)

    walk(geometry.get("coordinates"))
    if not lons:
        raise ValueError("這一塊地沒有座標")
    west, east = min(lons), max(lons)
    # 橫跨換日線的判準：東西跨超過半個地球。那種改用 0–360 再算一次。
    if east - west > 180:
        shifted = [one if one >= 0 else one + 360 for one in lons]
        west, east = min(shifted), max(shifted)
    return west, min(lats), east, max(lats)


def _parts(geometry: dict[str, Any]) -> list[Any]:
    """一塊地由幾個分開的多邊形組成。"""
    if geometry.get("type") == "Polygon":
        return [geometry["coordinates"]]
    if geometry.get("type") == "MultiPolygon":
        return list(geometry["coordinates"])
    raise ValueError(f"不會處理的幾何：{geometry.get('type')}")


def _main_bbox(geometry: dict[str, Any], label: list[float] | None
               ) -> tuple[float, float, float, float]:
    """**主體**的外框，不是全部領土的。

    整塊算的話，挪威含央棉島（外框往西多 40 度）、法國含法屬圭亞那（跨到
    南美）、西班牙含加那利。拿那個外框算相機，鏡頭會對著大西洋中間，
    而畫面上該亮的那塊地變成一個點 —— **畫得出來、不會報錯、就是不對**。

    怎麼挑主體：Natural Earth 每一筆都有 `LABEL_X/Y`，那是人挑過的、該放
    國名的地方。取**包含那個點的那一塊**；沒有 label 或都不包含（點落在
    海灣裡）就取面積最大的那一塊。兩條路都是資料決定的，不是我列一張
    「這幾個國家要特別處理」的表 —— 那種表會漏，而漏掉不會報錯。
    """
    boxes = [_bbox({"type": "Polygon", "coordinates": one})
             for one in _parts(geometry)]
    got = None
    if label:
        lon, lat = float(label[0]), float(label[1])
        inside = [one for one in boxes
                  if one[0] <= lon <= one[2] and one[1] <= lat <= one[3]]
        if inside:
            # 點可能落在好幾塊的外框裡（外框會重疊），取最小的那一塊 ——
            # 那是真正裝著它的那一塊，不是恰好框住它的大島。
            got = min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    if got is None:
        got = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return _grow(got, boxes)


# 一塊離主體這麼近（度）以內的島，算同一個地方。
#
# **為什麼需要這一格**：只取「包含國名那一點的那一塊」的話，丹麥只剩日德蘭
# 半島（東到經度 11），而哥本哈根在 12.6 —— 相機會把首都切在畫面外，而畫面
# 照樣畫得完。往另一邊，挪威的斯瓦巴在北緯 76–80，併進來的話框子從 13 度
# 高變成 22 度，整個國家縮成一條。
#
# 3.0 是掃出來的。4.0 的時候挪威變成 58–80：**熊島（北緯 74.4）當了跳板** ——
# 它離本土 3.2 度所以併進來，併完北界推到 74.5，斯瓦巴就只差 1.6 度了。
# 一塊一塊接力，這是逐輪長大必然會有的行為，不是 bug。
#
#     NEAR   丹麥            挪威            法國
#     4.0    8–15 ✅         5–34 ❌         −5–10 ✅
#     3.0    8–15 ✅         5–31 ✅         −5–10 ✅
#     2.5    8–15 ✅         5–31 ✅         −5–10 ✅
#
# 2.5 跟 3.0 一模一樣，所以 3.0 在穩定帶中間，不是踩在懸崖邊上。
# 要換這個數字，跑一次 `atlas_build` 看那張表再換。
NEAR = 3.0


def _grow(seed: tuple[float, float, float, float],
          boxes: list[tuple[float, float, float, float]]
          ) -> tuple[float, float, float, float]:
    """從主體開始，把 `NEAR` 以內的塊併進來，併到不再長為止。

    一輪不夠：博恩霍爾姆離日德蘭 3.7 度，但要先併了西蘭島才在 2.0 以內。
    """
    west, south, east, north = seed
    for _ in range(len(boxes) + 1):
        grew = False
        for one in boxes:
            gap = max(one[0] - east, west - one[2], 0.0) + \
                  max(one[1] - north, south - one[3], 0.0)
            if gap > NEAR:
                continue
            fresh = (min(west, one[0]), min(south, one[1]),
                     max(east, one[2]), max(north, one[3]))
            if fresh != (west, south, east, north):
                west, south, east, north = fresh
                grew = True
        if not grew:
            break
    return west, south, east, north


def _merge(boxes: list[tuple[float, float, float, float]]
           ) -> tuple[float, float, float, float]:
    return (min(one[0] for one in boxes), min(one[1] for one in boxes),
            max(one[2] for one in boxes), max(one[3] for one in boxes))


def main() -> None:
    if not RAW.is_file():
        raise SystemExit(
            f"找不到圖資 {RAW}\n"
            f"那是 Natural Earth 的原始檔，在 Map_Animation 的 public/data/。"
            f"隔壁如果搬走了，改 MAPS 那一格，或照它 README 的 curl 重抓。")
    rows = json.loads(RAW.read_text(encoding="utf-8"))["features"]
    print(f"讀進 {len(rows)} 筆")

    out: dict[str, dict[str, Any]] = {}
    for one in rows:
        got = one["properties"]
        key = str(got.get("ADM0_A3") or "")
        if not key or key == "-99":
            continue
        # Natural Earth 自己標的放國名的點。**比外框中心好用** ——
        # 挪威的外框中心落在瑞典境內，而這一格是人挑過的。挑主體也靠它。
        spot = ([round(float(got["LABEL_X"]), 4),
                 round(float(got["LABEL_Y"]), 4)]
                if got.get("LABEL_X") is not None else None)
        whole = _bbox(one["geometry"])
        main = _main_bbox(one["geometry"], spot)
        out[key] = {
            "name": str(got.get("NAME_ZHT") or got.get("NAME_ZH") or ""),
            "name_en": str(got.get("NAME_EN") or got.get("NAME") or ""),
            # `bbox` 是算相機用的 —— **主體**。`bbox_all` 留著是為了看得見
            # 兩者差多少：差很大的那幾個（挪威、法國、美國）就是海外領土，
            # 哪天要畫「含海外領土」才換那一格，而換的時候是說得出口的選擇。
            "bbox": [round(one_, 4) for one_ in main],
            "bbox_all": [round(one_, 4) for one_ in whole],
            "label": spot,
        }

    for key, spec in GROUPS.items():
        boxes = [tuple(out[one]["bbox"]) for one in spec["of"] if one in out]
        if len(boxes) != len(spec["of"]):
            missing = [one for one in spec["of"] if one not in out]
            raise SystemExit(f"{key} 的成員查不到：{'、'.join(missing)}")
        west, south, east, north = _merge(boxes)          # type: ignore[arg-type]
        out[key] = {"name": spec["name"], "name_en": key.lstrip("_"),
                    "bbox": [west, south, east, north],
                    "bbox_all": [west, south, east, north],
                    "label": [round((west + east) / 2, 4),
                              round((south + north) / 2, 4)],
                    "of": spec["of"]}

    # 中文名 → geoId。**一個中文名對到兩個 id 就 raise** —— 安靜地挑一個
    # 的話，畫面上會亮錯一塊地，而那不會報錯。
    named: dict[str, str] = {}
    clash: list[str] = []
    for key, got in out.items():
        said = got["name"]
        if not said:
            continue
        if said in named and named[said] != key:
            clash.append(f"{said}（{named[said]} / {key}）")
        named[said] = key
    if clash:
        raise SystemExit("中文名撞了：" + "、".join(clash))
    for said, key in ALSO.items():
        if key not in out:
            raise SystemExit(f"ALSO 裡的「{said}」指向 {key}，而索引裡沒有這一個")
        named[said] = key

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"where": str(RAW.relative_to(RAW.parents[3])),
         "places": out, "named": named},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"寫好 {OUT.relative_to(paths.ROOT)}　"
          f"{len(out)} 塊地、{len(named)} 個中文名")
    print(f"{'名字':<10}{'id':<7}{'主體外框':<34}{'含海外領土':<34}")
    for said in ("格陵蘭", "丹麥", "挪威", "瑞典", "冰島", "美國",
                 "法國", "歐洲共同體", "歐盟", "北歐"):
        key = named.get(said)
        if not key:
            print(f"  {said}　查不到")
            continue
        got = out[key]
        same = got["bbox"] == got.get("bbox_all")
        print(f"{said:<10}{key:<7}"
              f"{str([round(x) for x in got['bbox']]):<34}"
              f"{'（同上）' if same else str([round(x) for x in got['bbox_all']])}")


if __name__ == "__main__":
    main()
