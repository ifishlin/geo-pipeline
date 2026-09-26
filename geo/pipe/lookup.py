"""字典查不到的地方，上網查一次，存起來。

    python3 -m geo.pipe.lookup 麻六甲海峽 直布羅陀

## 為什麼需要這一層

字典有三層：國家 242、州省 294、手寫的集合和別名。加起來 552 個名字，
而**世界上的地名遠不只這些** —— 海峽、山脈、小城鎮、港口，隨便一個題目
都會碰到沒有的。

沒有這一層的話，碰到不認得的名字就是**安靜地不出現在畫面上**：不報錯、
不出聲，只是那一段的地圖少一塊。

## 查回來不能直接信

問「西伯利亞」，OpenStreetMap 回的是「新西伯利亞市」—— 一座城市，
而且 bbox 只有 0.4 度寬，畫出來是一張街道圖。

**那不是回零，是回一個看起來合理的替代品**，而這個專案怕的正是這種：
回零還看得出不對，這種連不對都看不出來。所以三道驗證，過不了就停下來
讓人看，不要硬存一個錯的。

## 存起來

查到又過驗證的寫進 `geo/data/points.json`，**下次不用再查**。
那一份進版控，所以查過一次全世界都受惠。
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

from geo.pipe import paths

WHERE = "https://nominatim.openstreetmap.org/search"

# OSM 的使用條款要求一個講得出是誰的 User-Agent，而且每秒最多一次。
# **不要拿掉** —— 沒有這一行他們會擋，而擋的樣子是空結果，看起來像「查不到」。
WHO = "geo-shorts/0.1 (ifishlin324@gmail.com)"
SLOW = 1.1

# 這幾種是「一塊地」，可以拿來當畫面的目標。
# city 之類的也收，但要過大小那一關（見 `judge`）。
AREAS = {"administrative", "region", "state", "province", "county",
         "island", "archipelago", "peninsula", "strait", "sea", "bay",
         "mountain_range", "desert", "continent", "water", "river",
         "canal", "strait", "gulf", "lake", "volcano", "city",
         "town", "village", "suburb", "military", "harbour"}

# 一塊「地區」至少要多大（度）。
#
# 量出來的：問「西伯利亞」回給我新西伯利亞市，bbox 0.37 度寬 —— 而真正的
# 西伯利亞跨 80 度。0.5 度大約 55 公里，比一座城市大、比任何一個值得
# 給鏡頭的地區小。
LEAST_WIDE = 0.5

# 一塊地大到這個程度，多半是查錯了（回了整個國家或整個洲）。
MOST_WIDE = 170.0


def _context() -> ssl.SSLContext:
    """**要用 certifi 的憑證。** macOS 的 Python 常常抓不到系統根憑證，
    而失敗長成 `CERTIFICATE_VERIFY_FAILED` —— 看起來像網路被擋。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def ask_osm(name: str, many: int = 3) -> list[dict[str, Any]]:
    url = WHERE + "?" + urllib.parse.urlencode(
        {"q": name, "format": "json", "limit": many,
         "accept-language": "zh-TW", "extratags": 1})
    req = urllib.request.Request(url, headers={"User-Agent": WHO})
    with urllib.request.urlopen(req, timeout=20, context=_context()) as got:
        return json.load(got)


def judge(name: str, one: dict[str, Any]) -> tuple[bool, str]:
    """這一筆能不能用。回 (行不行, 說得出口的理由)。

    **名字那一關比大小那一關重要。** 大小擋得掉「回了一座小鎮」，擋不掉
    「回了一個名字很像的鄰居」—— 問「西伯利亞」回「新西伯利亞州」，
    10×3.9 度，大小完全合理，而它是錯的。

    直布羅陀反過來：只有 0.3 度，大小看起來可疑，但那個地方本來就那麼小。
    **所以不能只看大小。**
    """
    south, north, west, east = (float(x) for x in one["boundingbox"])
    wide, high = abs(east - west), abs(north - south)
    kind = str(one.get("type") or "")
    klass = str(one.get("class") or "")
    got = str(one.get("display_name") or "")
    head = got.split(",")[0].strip()

    # 一、回的名字要**就是**問的那個。
    #
    # 真正要擋的是「前面多了字」：「新西伯利亞」包含「西伯利亞」，而它是
    # 隔壁。後面多了字沒關係（「麻六甲海峽」vs「麻六甲」），簡繁沒關係，
    # OSM 常常一格塞兩種寫法（「直布罗陀 / 直布羅陀」），所以要切開比。
    bare = _bare(name)
    heads = [_bare(x) for x in re.split(r"[/／]", head) if x.strip()]
    if not any(x == bare or x.startswith(bare) or bare.startswith(x)
               for x in heads):
        return False, f"名字對不上：問「{name}」回「{head}」"
    if all(len(x) > len(bare) and not bare.startswith(x) and x != bare
           and x.endswith(bare) for x in heads):
        # 每一種寫法都是「前面多了字」→ 那是鄰居
        return False, (f"名字對不上：問「{name}」回「{head}」"
                       f"—— 前面多出來的字通常表示那是隔壁，不是它")
    if max(wide, high) > MOST_WIDE:
        return False, f"太大了（{wide:.0f}×{high:.0f} 度），可能回了整個洲"
    if kind not in AREAS and klass not in ("boundary", "place", "natural"):
        return False, f"種類是 {klass}/{kind}，不像一塊地"
    if max(wide, high) < LEAST_WIDE:
        # 小不一定錯（直布羅陀就是小），但要說出來讓人看一眼。
        return True, (f"{klass}/{kind}　{wide:.2f}×{high:.2f} 度"
                      f"　⚠ 很小，確認一下是不是你要的")
    return True, f"{klass}/{kind}　{wide:.1f}×{high:.1f} 度"


# 譯名不同（不是簡繁）。一個一行，看得見。
SAME = {"麻六甲": "馬六甲", "雪梨": "悉尼", "首爾": "首尔",
        "寮國": "老撾", "紐西蘭": "新西蘭"}


def _bare(said: str) -> str:
    """比名字之前先抹平差異：簡繁、空白、常見後綴。"""
    try:
        from opencc import OpenCC
        said = OpenCC("s2twp").convert(said)
    except Exception:                                         # noqa: BLE001
        pass
    said = said.strip().replace(" ", "")
    for a, b in SAME.items():
        said = said.replace(a, b)
    for tail in ("特別行政區", "自治區", "聯邦管區", "直轄市",
                 "共和國", "群島", "半島", "海峽", "省", "州", "市", "縣"):
        if said.endswith(tail) and len(said) > len(tail) + 1:
            said = said[: -len(tail)]
    return said


def look(name: str, say=print) -> dict[str, Any] | None:
    """查一個名字。**過不了驗證就回 None 並說明**，不硬給一個。"""
    try:
        got = ask_osm(name)
    except Exception as bad:                                  # noqa: BLE001
        say(f"  {name}：查不到（{type(bad).__name__}：{str(bad)[:60]}）")
        return None
    if not got:
        say(f"  {name}：OpenStreetMap 沒有這個地方")
        return None
    for one in got:
        ok, why = judge(name, one)
        if ok:
            south, north, west, east = (float(x) for x in one["boundingbox"])
            say(f"  {name}：✓ {one.get('display_name', '')[:30]}　{why}")
            return {"name": name,
                    "bbox": [round(west, 4), round(south, 4),
                             round(east, 4), round(north, 4)],
                    "at": [round(float(one["lon"]), 4),
                           round(float(one["lat"]), 4)],
                    "note": f"OpenStreetMap：{one.get('display_name', '')[:60]}",
                    "from": "osm"}
        say(f"  {name}：✗ {why}")
    return None


def main() -> int:
    names = [one for one in sys.argv[1:] if not one.startswith("-")]
    if not names:
        print("用法：python3 -m geo.pipe.lookup <地名> [<地名> …]")
        return 1
    at = paths.GEO / "data" / "points.json"
    book = json.loads(at.read_text(encoding="utf-8"))
    got = 0
    for i, name in enumerate(names):
        if name in book["points"]:
            print(f"  {name}：已經有了")
            continue
        if i:
            time.sleep(SLOW)
        one = look(name)
        if one:
            book["points"][name] = {k: v for k, v in one.items()
                                    if k != "name"}
            got += 1
    if got:
        at.write_text(json.dumps(book, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print(f"\n存了 {got} 筆進 {at.relative_to(paths.ROOT)}")
    else:
        print("\n一筆都沒存 —— 查不到的自己加進 points.json（要寫 note）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
