"""成片和分鏡表擺在同一頁，而且連動。

    python3 -m geo.pipe.watch <題目>

## 為什麼需要它

看成片的時候發現「這裡怪怪的」，然後呢？要回頭在 50 格的 JSON 裡找出
那一秒是哪一格、模型為什麼那樣排 —— 而等找到的時候已經忘了哪裡怪。

這一頁把兩邊接起來：

```
影片播到哪        分鏡表那一行就亮起來，自己捲到看得見
點分鏡表哪一行     影片跳到那一秒
←  →             上一格、下一格
空白鍵            播放／暫停
```

**指出問題的成本從「找五分鐘」降到「記下行號」。** 這條路上每一次故事
變好，都是使用者指出行號之後量出來的 —— 畫面那一半也需要同一種東西。

## 為什麼不做進 look.html

那一頁是「整條路的過程」，一路捲下來九步。這一頁是**拿著看片子的時候
用的**：影片釘在上面、表格在下面捲，兩邊一直對著。用途不同，擠在一起
兩邊都不好用。
"""
from __future__ import annotations

import html
import subprocess
import sys

from geo.pipe import board as board_module, paths

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#14161a;color:#e8eaed;
     font:15px/1.65 -apple-system,"PingFang TC","Noto Sans TC",sans-serif}
.top{position:sticky;top:0;z-index:9;background:#0d0f12;
     border-bottom:1px solid #262a30;display:flex;gap:16px;padding:10px 14px}
video{max-height:46vh;border-radius:8px;background:#000}
.now-box{flex:1;min-width:0;padding-top:4px}
.now-box h2{margin:0 0 6px;font-size:15px;color:#9aa4b2;font-weight:500}
.big{font-size:19px;line-height:1.5}
.big .who{color:#ffb454}
.hint{color:#6b7280;font-size:12.5px;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:14px}
td{border-bottom:1px solid #22262c;padding:7px 9px;vertical-align:top}
tr{cursor:pointer}
tr:hover{background:#1b1f25}
tr.on{background:#20303f}
tr.on td:first-child{box-shadow:inset 3px 0 0 #4aa3ff}
.num{text-align:right;color:#7d8794;white-space:nowrap;
     font-variant-numeric:tabular-nums}
.see{white-space:nowrap;color:#9fd3ff}
.why{color:#8b95a3;font-size:13px}
.say{color:#d7dbe0}
.say .who{color:#ffb454}
.act{color:#ffca6e;font-size:13px}
.cut{color:#ff8f6e}
.slow{color:#ff8f6e}
"""

JS = """
const film = document.querySelector('video');
const rows = [...document.querySelectorAll('tr[data-at]')];
const at = rows.map(r => parseFloat(r.dataset.at));
const box = document.getElementById('now');
let last = -1;
function land(i){
  if(i === last) return;
  last = i;
  rows.forEach(r => r.classList.remove('on'));
  if(i < 0) return;
  const row = rows[i];
  row.classList.add('on');
  const r = row.getBoundingClientRect();
  if(r.top < 150 || r.bottom > innerHeight - 20)
    row.scrollIntoView({block:'center', behavior:'smooth'});
  box.innerHTML = row.dataset.now;
}
film.addEventListener('timeupdate', () => {
  let i = -1;
  for(let k = 0; k < at.length; k++) if(at[k] <= film.currentTime + 0.01) i = k;
  land(i);
});
rows.forEach((r, i) => r.onclick = () => {
  film.currentTime = parseFloat(r.dataset.at) + 0.02;
  film.play();
});
addEventListener('keydown', e => {
  if(e.key === ' '){ e.preventDefault(); film.paused ? film.play() : film.pause(); }
  if(e.key === 'ArrowRight' && last + 1 < at.length) film.currentTime = at[last+1] + 0.02;
  if(e.key === 'ArrowLeft'  && last > 0)             film.currentTime = at[last-1] + 0.02;
});
"""


def esc(text: object) -> str:
    return html.escape(str(text))


def build(story: str):
    got = board_module.rows(story)
    film = paths.at(story, "film")
    out = [f"<!doctype html><meta charset=utf-8><title>{esc(story)}｜看片</title>",
           f"<style>{CSS}</style>",
           '<div class=top>',
           f'<video controls src="{esc(film.name)}"></video>',
           '<div class=now-box><h2>現在這一格</h2><div class=big id=now>'
           '按播放，或點下面任何一行</div>'
           '<p class=hint>點一行跳到那一秒　·　← → 上一格下一格　·　'
           '空白鍵播放暫停</p></div>',
           '</div><table>']
    for at, one in enumerate(got, 1):
        acts = "<br>".join(
            f"◆ {esc(a['move'])} "
            + esc("　".join(f"{k}={v if isinstance(v, str) else '→'.join(v)}"
                            for k, v in a.items() if k not in ("move", "why")))
            for a in one["do"])
        says = "<br>".join(
            f"<span class=who>{esc(w)}</span> {esc(t)}" for w, t in one["says"])
        now = (f"<span class=who>{esc('＋'.join(one['see']))}</span>"
               f"　<span style='color:#8b95a3'>{esc(one['why'])}</span>"
               + (f"<br>{acts}" if acts else "")
               + (f"<br>{says}" if says else ""))
        slow = " class=slow" if one["for"] > 6 else ""
        out.append(
            f'<tr data-at="{one["at"]}" data-now="{esc(now)}">'
            f'<td class=num>{at}</td>'
            f'<td class=num>{one["at"]:.1f}s</td>'
            f'<td class=num{slow}>{one["for"]:.1f}s</td>'
            f'<td class="num{" cut" if one["cut"] else ""}">'
            f'{"切" if one["cut"] else "滑"}</td>'
            f'<td class=see>{esc("＋".join(one["see"]))}</td>'
            f'<td class=act>{acts}</td>'
            f'<td><div class=why>{esc(one["why"])}</div>'
            f'<div class=say>{says}</div></td></tr>')
    out.append(f"</table><script>{JS}</script>")
    page = paths.home(story) / "watch.html"
    page.write_text("".join(out), encoding="utf-8")
    return page


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python3 -m geo.pipe.watch <題目>")
        return 1
    page = build(sys.argv[1])
    print(f"寫好了 {page.relative_to(paths.ROOT)}")
    subprocess.run(["open", str(page)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
