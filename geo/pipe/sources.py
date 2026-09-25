"""把來源抓回來存成檔案。

    python3 -m geo.pipe.make <題目> sources

故事檔列網址，這一支抓回來、轉成純文字、落地。

```json
"sources": [
  {"url": "https://…", "why": "事件本身", "kind": "news"},
  {"url": "https://en.wikipedia.org/wiki/Greenland", "why": "歷史", "kind": "wiki"}
]
```

## 三種來源，不要混

```
事件   新聞。講「今天發生什麼」
歷史   維基、官方。講「幾百年不動的事」，這種題目的骨幹
誤解   留言、搜尋建議。講「大家原本以為什麼」——冷知識的來源不是知識，是誤解
```

`kind` 標出來，是因為抽事實那一步對三種的問法不一樣，而且**少了哪一種
看得出來**。一支地理片只有新聞來源的話，它就只是一則新聞。

## 抓回來要落地

存在記憶體裡的東西等於沒有。而且事實那一步要能回頭對 quote ——
「這句話真的在來源裡嗎」只有原文答得出來。
"""
from __future__ import annotations

import hashlib
import re
import sys
import urllib.error
import urllib.request
from typing import Any

from geo.pipe import paths, story as story_module

AGENT = "geo-pipeline (map shorts; contact via repo owner)"
KINDS = ("news", "wiki", "official", "voices")


def certs() -> Any:
    """HTTPS 的信任庫 —— **自己帶一份，不靠這台機器剛好設好。**

    這台上的 Python 不讀 macOS 的鑰匙圈，`ssl.get_default_verify_paths()`
    回的是 `None`，所以 urllib 碰 HTTPS 必定 `CERTIFICATE_VERIFY_FAILED`，
    而同一個網址 curl 通得過。`requests` 和 yt-dlp 自己帶 certifi 所以沒事。

    **不是關掉驗證。** 關掉會讓錯誤消失，而錯誤消失不等於連線安全。
    certifi 裝不起來就讓它照系統預設去試，失敗的時候訊息是真的。
    """
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _text_of(html: str) -> str:
    """HTML → 大致的純文字。**夠用就好** —— 這是給模型讀的，不是排版。"""
    html = re.sub(r"(?is)<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>",
                  " ", html)
    html = re.sub(r"(?is)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(a, b)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def run(story: str, say=print) -> dict[str, Any]:
    spec = story_module.load(story)
    rows = spec.get("sources") or []
    if not rows:
        raise SystemExit(
            f"{story_module.path_of(story)} 沒有 sources。\n"
            f"列網址，每一筆要有 url、why、kind（{'、'.join(KINDS)}）")
    into = paths.home(story) / "0-sources"
    into.mkdir(parents=True, exist_ok=True)

    out: list[dict[str, Any]] = []
    for at, one in enumerate(rows, 1):
        url = str(one.get("url") or "")
        kind = str(one.get("kind") or "")
        if kind not in KINDS:
            raise SystemExit(f"第 {at} 筆的 kind 是 {kind!r}，"
                             f"要是 {'、'.join(KINDS)} 其中之一")
        name = f"{kind}-{hashlib.md5(url.encode()).hexdigest()[:10]}.txt"
        where = into / name
        if where.is_file():
            say(f"  {at:>2} 已經有了　{name}")
        else:
            try:
                ask = urllib.request.Request(url, headers={"User-Agent": AGENT})
                with urllib.request.urlopen(ask, timeout=60,
                                            context=certs()) as answer:
                    body = answer.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError) as bad:
                # **抓不到不要靜靜跳過。** 少一個來源的症狀是「事實少幾則」，
                # 而那看起來跟「這個題目本來就沒那麼多事」一模一樣。
                raise SystemExit(f"第 {at} 筆抓不到：{url}\n  {bad}") from None
            text = _text_of(body)
            if len(text) < 400:
                raise SystemExit(
                    f"第 {at} 筆抓回來只有 {len(text)} 個字，八成是被擋了"
                    f"或需要 JavaScript：{url}")
            where.write_text(f"# {url}\n\n{text}", encoding="utf-8")
            say(f"  {at:>2} 抓好了　{len(text):>6} 字　{name}")
        out.append({"url": url, "kind": kind, "why": str(one.get("why") or ""),
                    "file": f"0-sources/{name}",
                    "chars": len(where.read_text(encoding="utf-8"))})

    missing = [one for one in ("news", "wiki") if
               not any(x["kind"] == one for x in out)]
    if missing:
        say(f"⚠ 沒有 {'、'.join(missing)} 類的來源 —— "
            f"只有新聞的話這支片就只是一則新聞，只有維基的話它沒有現在式")
    paths.save(story, "sources", out)
    say(f"\n{len(out)} 筆來源，共 {sum(x['chars'] for x in out):,} 字")
    for kind in KINDS:
        got = [x for x in out if x["kind"] == kind]
        if got:
            say(f"  {kind:<9}{len(got)} 筆")
    return {"sources": out}


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "")
