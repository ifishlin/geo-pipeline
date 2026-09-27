"""截一格出來，把經緯度標上去。

    python3 -m geo.pipe.shot <題目> <第幾格>
    python3 -m geo.pipe.shot <題目> --at 12.5

## 為什麼要這一支

**討論鏡頭不准用文字描述位置。** 使用者 2026-09-27 交代的規矩，而它的
由來是我在同一個對話裡用推的推了四次、錯了四次：

```
1  merc_y 的方向    以為往北遞增，其實是往南（螢幕座標那種）
2  view() 的順序    以為 [西南東北]，用錯之後整張圖上下顛倒
3  TILE_SIZE        推成 256（常見預設），實際是 512，
                    於是算出「一半的鏡頭被 MapLibre 偷偷拉近」——
                    那個結論整個是假的
4  丹麥的位置        說它「被字幕蓋住」，實際在畫面 55% 高，沒有
```

每一次錯我都講得很有把握，因為**推出來的東西聽起來都很合理**。而畫出來
之後一眼就看得出對不對 —— 格線對不上海岸線就是錯的。

## 投影照抄渲染器，不要自己推

`Map_Animation/src/engine/projection.ts` 的 `geoToScreen` 是真相，
這裡逐行照抄（含 MapLibre 那個「不准在極點外留空白」的修正）。

**兩邊各推一次的話就會有一邊是錯的**，而錯的那一邊不會報錯 ——
標記畫在海裡，圖照樣產得出來。
"""
from __future__ import annotations

import math
import subprocess
import sys
from typing import Any

from geo.pipe import board as board_module, camera as cam, paths

# 照 Map_Animation/src/engine/projection.ts:18。**這個數字錯了整張圖就錯了**，
# 而錯法是「格線平移一段」，看起來只是沒對準，不像壞掉。
TILE = 512


def _world(lon: float, lat: float, zoom: float) -> tuple[float, float]:
    size = TILE * 2 ** zoom
    sin = math.sin(math.radians(lat))
    return (((lon + 180) / 360) * size,
            size * (0.5 - math.log((1 + sin) / (1 - sin)) / (4 * math.pi)))


def on_screen(lon: float, lat: float, shot: dict[str, Any],
              wide: int, high: int) -> tuple[float, float]:
    """那個經緯度落在畫面的哪個像素（左上角是 0,0）。"""
    zoom = max(float(shot["zoom"]), math.log2(high / TILE))
    size = TILE * 2 ** zoom
    clon, clat = (float(one) for one in shot["center"])
    _, ry = _world(clon, clat, zoom)
    mid_y = size / 2 if high >= size else min(max(ry, high / 2),
                                              size - high / 2)
    px, py = _world(lon, lat, zoom)
    cx, _ = _world(clon, clat, zoom)
    return wide / 2 + (px - cx), high / 2 + (py - mid_y)


def draw(story: str, which: int | None = None, at: float | None = None,
         say=print):
    from PIL import Image, ImageDraw, ImageFont

    rows = board_module.rows(story)
    if which is not None:
        one = rows[which - 1]
    else:
        one = [x for x in rows if x["at"] <= (at or 0)][-1]
    film = paths.at(story, "film")
    if not film.is_file():
        raise SystemExit(f"還沒有成片：{film}")
    atlas = paths.load(story, "atlas")
    spec = __import__("geo.pipe.story", fromlist=["load"]).load(story)
    wide, high = spec["video"]["width"], spec["video"]["height"]

    # **截這一格的開頭，不是結尾。**
    #
    # `camera.when = late` 的意思是「一格的後段才移動」，所以那一格設計好的
    # 取景出現在**開頭那段停著的時間**；到了結尾鏡頭已經在往下一格跑了。
    #
    # 第一版截 85% 處，畫出來的框整個偏掉 —— 而我以為是投影算錯，去翻了
    # 渲染器的原始碼、改了三次公式。**錯的是取樣的時間，不是公式。**
    #
    # `early` 和 `whole` 反過來（移動在前段），所以要看設定。
    knobs = __import__("json").loads(
        (paths.GEO / "data" / "theme.json").read_text(encoding="utf-8"))
    how = str((knobs.get("camera") or {}).get("when", "late"))
    share = 0.15 if how == "late" else 0.9
    when = one["at"] + max(0.05, min(one["for"] * share, one["for"] - 0.05))
    out = paths.home(story) / "_frames"
    out.mkdir(exist_ok=True)
    raw = out / f"{one['at']:07.2f}.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{when:.2f}",
                    "-i", str(film), "-frames:v", "1", str(raw)], check=True)

    shot = one["camera"]
    img = Image.open(raw).convert("RGB")
    pen = ImageDraw.Draw(img, "RGBA")
    face = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 32)

    for lat in range(-80, 90, 10):
        _, y = on_screen(0, lat, shot, wide, high)
        if 0 <= y <= high:
            pen.line([0, y, wide, y], fill=(0, 255, 255, 110), width=2)
            pen.text((8, y + 4), f"{lat}°N", fill=(0, 255, 255, 220),
                     font=face)
    colours = [(255, 90, 90), (90, 200, 255), (160, 255, 120), (255, 200, 90)]
    for at_, name in enumerate(one["see"]):
        got = atlas.get(name) or {}
        colour = colours[at_ % len(colours)]
        if got.get("bbox"):
            b = got["bbox"]
            x0, y0 = on_screen(b[0], b[3], shot, wide, high)
            x1, y1 = on_screen(b[2], b[1], shot, wide, high)
            pen.rectangle([x0, y0, x1, y1], outline=colour + (255,), width=6)
            pen.text((x0 + 8, y0 - 44), f"{name} 外框",
                     fill=colour + (255,), font=face)
        if got.get("at"):
            x, y = on_screen(got["at"][0], got["at"][1], shot, wide, high)
            pen.ellipse([x - 13, y - 13, x + 13, y + 13],
                        fill=colour + (255,))
    pen.line([wide / 2, 0, wide / 2, high], fill=(255, 255, 0, 120), width=3)
    pen.line([0, high / 2, wide, high / 2], fill=(255, 255, 0, 120), width=3)
    pen.ellipse([wide / 2 - 20, high / 2 - 20, wide / 2 + 20, high / 2 + 20],
                outline=(255, 255, 0, 255), width=5)

    page = out / f"{one['at']:07.2f}-標註.png"
    img.resize((wide // 2, high // 2)).save(page)
    say(f"第 {rows.index(one) + 1} 格　{one['at']:.1f}s 起 {one['for']:.1f} 秒"
        f"　看 {'＋'.join(one['see'])}")
    say(f"  {one['why']}")
    say(f"  截在 {when:.2f}s（到位之後）　{page.relative_to(paths.ROOT)}")
    return page


def main() -> int:
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not args:
        print("用法：python3 -m geo.pipe.shot <題目> <第幾格>")
        print("　　　python3 -m geo.pipe.shot <題目> --at 12.5")
        return 1
    at = None
    if "--at" in sys.argv:
        at = float(sys.argv[sys.argv.index("--at") + 1])
        page = draw(args[0], at=at)
    else:
        page = draw(args[0], which=int(args[1]) if len(args) > 1 else 1)
    subprocess.run(["open", str(page)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
