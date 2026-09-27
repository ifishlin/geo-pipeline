"""網頁的共用外觀：顏色、鈕、卡片、表格、外框。

**鈕的樣式只准有一份。** 舊專案那邊六頁各抄一份、另外二十頁沒抄，
於是那二十頁露出瀏覽器預設的灰塑膠鈕 —— 而那不會報錯，只有人打開
頁面才看得到。`geo/checks/_web.py` 擋第二份。

## 為什麼 `look.py` 和 `watch.py` 沒有改成用這一份

它們產的是**從磁碟直接打開的單一檔案**（不經過伺服器），而且是兩種模式：
`look` 是白底的「過程」頁，一路捲下來九步；`watch` 是黑底的「看片」頁，
影片釘在上面。兩邊的版面本來就不一樣，抄的不是同一個東西。

真正會重複的是**鈕**，而它們兩個都沒有鈕。所以這裡只收伺服器那幾頁用的，
等它們哪天長出鈕的時候再搬。
"""
from __future__ import annotations

import html
from typing import Any

CSS = """
:root{--ink:#1a1d21;--dim:#6b7280;--line:#e5e7eb;--bg:#fbfbfc;
      --hit:#0b6bcb;--ok:#2f6b39;--warn:#b4530f;--bad:#c0392b;
      --soft:#f3f6fb}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font:15px/1.7 -apple-system,"PingFang TC","Noto Sans TC",sans-serif}
a{color:var(--hit)}
.wrap{max-width:1100px;margin:0 auto;padding:26px 20px 120px}
h1{font-size:25px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 10px}
.sub{color:var(--dim);margin:0 0 24px}

/* 上面那排：每一頁都有，位置一樣 */
.rail{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 26px;
      padding-bottom:16px;border-bottom:1px solid var(--line)}
.rail a{text-decoration:none;color:var(--ink);border:1px solid var(--line);
        background:#fff;border-radius:999px;padding:5px 14px;font-size:13px}
.rail a.on{background:var(--ink);color:#fff;border-color:var(--ink)}

/* **鈕只有這一份。** 加第二份 checks/_web.py 會叫。 */
.btn{border:1px solid var(--line);background:#fff;color:var(--ink);
     border-radius:8px;padding:5px 12px;font-size:13px;cursor:pointer;
     font-family:inherit;line-height:1.5}
a.btn{text-decoration:none;display:inline-block}
.btn:hover{border-color:#b6bcc4}
.btn:disabled{opacity:.45;cursor:default}
.btn.go{background:var(--hit);border-color:var(--hit);color:#fff}
.btn.again{color:var(--warn);border-color:#e7cdb4}

.card{background:#fff;border:1px solid var(--line);border-radius:12px;
      padding:16px 18px;margin-bottom:12px}
.card.broken{border-color:var(--bad);background:#fff7f6}
.card h3{margin:0 0 6px;font-size:16px}
.card .why{color:var(--dim);font-size:13px;margin:0}

table{border-collapse:collapse;width:100%;font-size:13.5px;background:#fff}
td,th{border-bottom:1px solid var(--line);padding:7px 9px;
      text-align:left;vertical-align:top}
th{color:var(--dim);font-weight:500;font-size:12px}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}

.dots{font-size:15px;letter-spacing:2px;font-variant-numeric:tabular-nums}
.dots .yes{color:var(--ok)}
.dots .no{color:#c9ced6}
.dots .old{color:var(--warn)}

.tag{display:inline-block;background:var(--soft);border-radius:4px;
     padding:1px 7px;font-size:11.5px;color:var(--dim);margin-left:6px}
.tag.bad{background:#fdecea;color:var(--bad)}
.tag.warn{background:#fdf3e7;color:var(--warn)}
.tag.ok{background:#e9f3ea;color:var(--ok)}

.log{background:#14161a;color:#e8eaed;border-radius:10px;padding:14px 16px;
     font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
     white-space:pre-wrap;word-break:break-word;max-height:58vh;
     overflow:auto;margin:12px 0 0}
.log:empty{display:none}
.log.tall{max-height:78vh}

/* 渲染過的 md（/docs） */
.md{background:#fff;border:1px solid var(--line);border-radius:12px;
    padding:8px 28px 28px}
.md h1{margin-top:20px}.md h2{border-bottom:1px solid var(--line);padding-bottom:4px}
.md code{background:var(--soft);border-radius:4px;padding:1px 5px;font-size:.9em}
.md pre.code{background:#14161a;color:#e8eaed;border-radius:10px;
     padding:12px 16px;overflow:auto;font:12.5px/1.6 ui-monospace,Menlo,monospace}
.md table{margin:10px 0}
.md blockquote{margin:10px 0;padding:4px 14px;border-left:3px solid var(--line);
     color:var(--dim)}
.md hr{border:0;border-top:1px solid var(--line);margin:22px 0}
.spin{display:inline-block;width:9px;height:9px;border-radius:50%;
      background:var(--hit);margin-right:7px;
      animation:beat 1s ease-in-out infinite}
@keyframes beat{0%,100%{opacity:.25}50%{opacity:1}}

label{display:block;font-size:13px;color:var(--dim);margin:12px 0 4px}
input,textarea,select{width:100%;font:14px/1.6 inherit;padding:7px 10px;
       border:1px solid var(--line);border-radius:8px;background:#fff}
textarea{min-height:76px;resize:vertical}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:760px){.pair{grid-template-columns:1fr}}
"""


def esc(text: Any) -> str:
    return html.escape(str(text))


def page(title: str, body: str, *, here: str = "", js: str = "") -> str:
    """一頁的外框。**每一頁都從這裡出來**，所以那排連結的位置一樣。"""
    rail = "".join(
        f'<a href="{where}"{" class=on" if here == where else ""}>{name}</a>'
        for where, name in (("/", "題目"), ("/asks", "問答"),
                            ("/docs", "文件"), ("/effects", "特效"),
                            ("/rules", "門檻"), ("/spend", "花費")))
    return (f"<!doctype html><html lang=zh-Hant><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}｜geo</title><style>{CSS}</style>"
            f"<body><div class=wrap><div class=rail>{rail}</div>{body}</div>"
            + (f"<script>{js}</script>" if js else "")
            + "</body></html>")


def dots(marks: list[str]) -> str:
    """九步的 ●○。**分母一起寫** —— 一個「8」看不出是八步還是八成。"""
    kind = {"●": "yes", "○": "no", "◐": "old"}
    body = "".join(f'<span class={kind[one]}>{one}</span>' for one in marks)
    done = sum(1 for one in marks if one != "○")
    return f'<span class=dots>{body}</span> {done}/{len(marks)}'
