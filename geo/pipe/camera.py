"""外框 → 相機。**這一支決定「模型只講話」成不成立。**

模型說得出「這裡要看到格陵蘭跟丹麥」，說不出「中心點在西經 41.5 度、縮放
2.4 級」。後者是算得出來的，而算出來的每次都一樣；叫模型填的話每次不一樣，
而且它**不會說做不到，它會給一個格式正確、中心差三度的答案**。

所以：名字 → 外框（`atlas_build`）→ 相機（這裡），全程沒有模型。

## 麥卡托，不是經緯度平均

緯度在麥卡托投影上不是線性的。格陵蘭從北緯 60 到 84，**經緯度中點是 72，
麥卡托中點是 76.4** —— 差 4.4 度，在那個尺度下是畫面高度的六分之一。
用錯的那個，格陵蘭會偏在畫面下方，而畫面照樣畫得完。

## 地板

MapLibre 不讓人縮到「整個世界比畫面還矮」，而且到了那個極限會把中心
釘在赤道（隔壁 README 記著，1920 高的畫面大約是 zoom 1.91）。所以這裡
算出來低於地板就 raise —— 悄悄夾到地板的話，相機會跑到赤道，而畫面上
只是「怎麼看到非洲」。
"""
from __future__ import annotations

import math
from typing import Any, Sequence

# MapLibre 的世界寬度是 512 × 2^zoom 像素（512 的圖磚）。
WORLD = 512.0

# 畫面裝不下整個世界的那個縮放。隔壁 README 量的是 1920 高 → 約 1.91；
# 這裡照同一個式子算，換畫面尺寸自己會跟著變。
def floor_zoom(height: int) -> float:
    """再縮下去 MapLibre 就會把中心釘在赤道的那個縮放。"""
    return math.log2(height / WORLD)


def merc_y(lat: float) -> float:
    """緯度 → 麥卡托 y，0 是北極、1 是南極（畫面座標的方向）。"""
    lat = max(-85.05112878, min(85.05112878, lat))
    rad = math.radians(lat)
    return (1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2


def lat_of(y: float) -> float:
    """麥卡托 y → 緯度。"""
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


def merge(boxes: Sequence[Sequence[float]]) -> list[float]:
    """幾個外框併成一個。"""
    if not boxes:
        raise ValueError("沒有外框可以併")
    return [min(one[0] for one in boxes), min(one[1] for one in boxes),
            max(one[2] for one in boxes), max(one[3] for one in boxes)]


def fit(bbox: Sequence[float], width: int = 1080, height: int = 1920,
        *, pad: float = 0.12, hold: float = 1.0,
        lift: float = 0.0) -> dict[str, Any]:
    """讓這個外框剛好進畫面的相機。

    ```
    pad    四邊各留畫面的幾分之幾，讓那塊地不要貼著邊
    hold   只用畫面的上面這幾成來裝（字幕在下面，0.72 就是把字幕那塊讓開）
    lift   算完之後把中心往上推幾成畫面高（配合 hold 用）
    ```

    `hold` 和 `lift` 是同一件事的兩半：先用比較矮的框算縮放，再把中心抬上去，
    那塊地就落在畫面上方、字幕底下是空的。**兩個分開是因為它們可以不相等** ——
    留 28% 給字幕不代表主體要正好抬 14%。
    """
    west, south, east, north = (float(one) for one in bbox)
    if east <= west or north <= south:
        raise ValueError(f"外框不成立：{list(bbox)}")
    room_w = width * (1 - 2 * pad)
    room_h = height * hold * (1 - 2 * pad)
    if room_w <= 0 or room_h <= 0:
        raise ValueError(f"pad={pad} hold={hold} 把可用的畫面吃光了")

    span_x = (east - west) / 360.0
    span_y = abs(merc_y(south) - merc_y(north))
    zoom = min(math.log2(room_w / (WORLD * span_x)),
               math.log2(room_h / (WORLD * span_y)))

    lowest = floor_zoom(height)
    if zoom < lowest:
        raise ValueError(
            f"這個外框 {[round(one, 1) for one in bbox]} 要 zoom {zoom:.2f} 才裝得下，"
            f"而 {width}×{height} 的畫面到 {lowest:.2f} 就不能再縮了"
            f"（再縮 MapLibre 會把中心釘在赤道）。"
            f"拆成兩格、或降低 pad／提高 hold。")

    mid_y = (merc_y(north) + merc_y(south)) / 2 - lift * height / (WORLD * 2 ** zoom)
    lon = (west + east) / 2
    # 併過換日線的框（美國含阿拉斯加）經度會超過 180，折回來。
    if lon > 180:
        lon -= 360
    return {"center": [round(lon, 4), round(lat_of(mid_y), 4)],
            "zoom": round(zoom, 3)}


def span(shot: dict[str, Any], bbox: Sequence[float]) -> tuple[float, float]:
    """這塊地在這個相機下佔畫面幾個像素（寬, 高）。"""
    scale = WORLD * 2 ** float(shot["zoom"])
    west, south, east, north = (float(one) for one in bbox)
    return ((east - west) / 360 * scale,
            abs(merc_y(south) - merc_y(north)) * scale)


# 小於這麼多像素的一塊地，在 1080 寬的畫面上等於沒有畫。
#
# **量出來的**：「格陵蘭＋丹麥」那一格算出 zoom 2.714，丹麥在畫面上只有
# 66×27 像素，紅色一小點貼在右邊 —— 相機**算得對**（外框確實裝得下），
# 鏡頭卻沒有用。這種錯 `covers()` 抓不到，因為它問的是「在不在畫面裡」。
#
# 120 是這樣定的：低於它就看不出形狀，只看得出「那裡有顏色」，所以那一塊
# 要改用圈或標記來指，不能只靠填色。不是門，是**一個程式做得了的決定**。
TINY = 120.0


def too_small(shot: dict[str, Any], bbox: Sequence[float]) -> bool:
    """這塊地在這個相機下小到只靠填色看不出來嗎。"""
    wide, high = span(shot, bbox)
    return max(wide, high) < TINY


def view(shot: dict[str, Any], width: int = 1080,
         height: int = 1920) -> list[float]:
    """這個相機看得到的範圍，回成外框 (西, 南, 東, 北)。

    跟 `fit()` 是一對：那一支從外框算相機，這一支從相機算回外框。
    兩個鏡頭之間要不要用移動的，看的就是這兩個範圍有沒有重疊。
    """
    scale = WORLD * 2 ** float(shot["zoom"])
    lon, lat = (float(one) for one in shot["center"])
    half_x = width / 2 / scale * 360
    half_y = height / 2 / scale
    mid = merc_y(lat)
    return [lon - half_x, lat_of(min(1.0, mid + half_y)),
            lon + half_x, lat_of(max(0.0, mid - half_y))]


def overlap(a: dict[str, Any], b: dict[str, Any], width: int = 1080,
            height: int = 1920) -> float:
    """兩個鏡頭看得到的範圍重疊多少（0 到 1，取兩者中較小那個的比例）。

    **用來決定鏡頭是用移的還是用切的。** 重疊得多就是同一帶地方，
    鏡頭滑過去看得懂；完全不重疊就是跳到地球另一邊，直接滑過去的話
    觀眾會看到一整段沒有意義的海。
    """
    one, other = view(a, width, height), view(b, width, height)
    wide = min(one[2], other[2]) - max(one[0], other[0])
    high = min(one[3], other[3]) - max(one[1], other[1])
    if wide <= 0 or high <= 0:
        return 0.0
    small = min((one[2] - one[0]) * (one[3] - one[1]),
                (other[2] - other[0]) * (other[3] - other[1]))
    return (wide * high) / small if small > 0 else 0.0


def covers(shot: dict[str, Any], bbox: Sequence[float],
           width: int = 1080, height: int = 1920) -> bool:
    """這個相機**真的**把這個外框裝進去了嗎。

    算完不等於對 —— `fit()` 有 pad、hold、lift 三個旋鈕，任何一個寫錯都會
    算出一個看起來很正常的相機。這一支是反過來驗：把外框投影到畫面上，
    看四個角有沒有落在畫面裡。**門要問它，不要重算一次** —— 重算一次就是
    同一份邏輯的第二個版本，兩邊一起錯。
    """
    scale = WORLD * 2 ** float(shot["zoom"])
    lon0, lat0 = (float(one) for one in shot["center"])
    x0, y0 = (lon0 + 180) / 360 * scale, merc_y(lat0) * scale
    west, south, east, north = (float(one) for one in bbox)
    for lon, lat in ((west, north), (east, north), (west, south), (east, south)):
        x = (lon + 180) / 360 * scale - x0 + width / 2
        y = merc_y(lat) * scale - y0 + height / 2
        if not (0 <= x <= width and 0 <= y <= height):
            return False
    return True
