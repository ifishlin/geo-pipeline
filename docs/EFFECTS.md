# 特效函式庫

模型在 `storyboard` 那一步挑「這一格要做什麼動作」，這一層把它翻成渲染器
吃的疊加層。照使用者給的
[通用特效函式目錄](../geo/地理短影音_通用特效函式目錄_Remotion_MapLibre.md)
建的。

## 加一種特效要動兩個地方，而且只有兩個

```
geo/data/effects.json      一格：中文名、什麼時候用、什麼時候不要用、
                           要什麼資料、參數的預設值、畫不畫得出來
geo/effects/builders.py    一支同名的 builder，用 @builds("type") 註冊
```

**分派邏輯不用動。** 上一版是一條長長的 `if how == …` 鏈，加一種就要在
中間插一段，而**插錯地方不會報錯** —— 那一種只是安靜地不畫。

改完跑 `python3 -m geo.checks._effects`：它逐個比對目錄和 builder，
**目錄有而沒 builder**、**builder 有而目錄沒列**，兩邊都會叫。

## 二十五種，二十種畫得出來

| 名 | `type` | 層 |
|---|---|---|
| 塗色 | `highlight_region` | map |
| 依序亮 | `highlight_sequence` | map |
| 亮燈 | `light_up` | map |
| 航線 | `draw_route` | geo_overlay |
| 風 | `animate_flow` | map |
| 一片區域 | `animate_field` | map |
| 標點 | `pulse_point` | geo_overlay |
| 小圖示 | `place_geo_asset` | geo_overlay |
| 表情 | `animate_face` | geo_overlay |
| 圈起來 | `circle_place` | geo_overlay |
| 上台 | `lift_to_stage` | screen_overlay |
| 掙脫 | `detach_place` | map |
| 跑數字 | `count_up` | screen_overlay |
| 推近 | `closeup` | map |
| 標題卡 | `title_card` | screen_overlay |
| 壓暗 | `dim_map` | screen_overlay |
| 閃一下 | `flash` | screen_overlay |
| 震一下 | `shake` | screen_overlay |
| 掃過去 | `transition_scene` | screen_overlay |
| 描邊界 | `reveal_boundary` | map |

還畫不出來的五種（`renders: false`）：**移動物件**、**點資料**、
**粒子**、**插畫面**、**音效**。每一格都寫著「沒做」的理由，而且
**不會進選單** —— 混在一起的話模型會挑一個畫不出來的，然後分鏡表和成片
各說各話，兩邊都不報錯。

### 「畫不出來」要真的去試過才算數

「描邊界」本來也在那一列，理由是「渲染器的 `draw` 只對線狀的地區有效，
而我們的字典只有面」。那句話沒錯，**錯的是從它推論到「所以做不到」**。

繞過去的路跟原本設想的 API 完全無關：輪廓切成 48 段、排 48 筆 `lines`、
每段晚 0.033 秒開始。量出來 48 條線只讓那一格慢 1.7%。

**「這一支 API 做不到」不等於「這件事做不到」**，而寫進目錄的「沒做」
會讓沒有人再去想第二條路。

## 模型只選話，程式選形狀

`effects.json` 的每一格混著三種軸，而**模型只選得動「在說什麼話」那一軸**：

```
畫成什麼形狀   ← 程式選（`ways`：多給哪一個欄位就換一批畫法）
放幾個東西     ← 程式選
在說什麼話     ← 模型選
```

舊專案吃過這個虧：十六種卡，模型只用過六種，`bars`／`clock`／`queue`
一次都沒被選過，而材料明明有。收成 7 種之後才動得起來。

## 選單是長出來的，不是手寫的

`effects.menu()` 從 `effects.json` 生給模型看的那張表 ——
手寫的話加一種要改兩個地方，而漏掉的那一邊不會報錯。

`別名` 那張表（33 筆）把模型填的中文欄位名換成程式用的英文。
prompt 印中文給它看（「要給：誰、從、到」），它就照著填中文 ——
**那不是它的錯，是我們印什麼它填什麼**。

## 驗證是照目錄長出來的

`effects.check(act, kind, atlas, where)` 一支，加一種特效不用碰它：

```
不認得的種類、地圖上沒有的地名、清單外的值   → SystemExit（停）
少填一個必填欄位                            → Incomplete（丟掉那一個，出聲）
沒填有預設的（表情／圖示／調色／方位）        → 用清單的第一個，不退回
```

26 個動作裡少一個欄位而重問一趟是五分鐘、$0.8 —— **那個代價不成比例**。
超過三分之一被丟掉才停。

builder 自己發現畫不出來（沒座標、不是一塊地、`to` 不是數字）就
`raise SkipThis`，理由會被印出來。**不要猜資料** —— 從台詞猜一個數字
出來，是「回報一個看起來合理的替代品」，比回報零更貴。

## 欄位名一律去隔壁的 `src/schema.ts` 查過

猜錯過三次，三次都是**看起來很合理的猜測**：

```
curve: "arc"        enum 其實是 greatCircle | straight
fields 的 blobs     要包在 keys 裡，不是頂層
小圖示「警告」       對到 "marker"，不是 "warning"
```

猜錯的下場是那一格什麼都沒畫 —— 型別是對的，`npm run validate` 之外
看不出來。**壓片前一定先 validate**：一秒鐘，而錯過的話是壓十二分鐘才炸。

## 疊加層的時間軸是整支片，不是那一格

`lines`、`faces`、`highlights` 這些是**影片層**，`start`／`end` 都從影片
開頭算。builder 收到的 `spec["start_s"]` 已經是絕對秒數，**不要自己算
時間軸的原點**。

放不下的時候（幾塊地依序亮，擠到下限還是超出這一格）它會溢到下一格 ——
那是對的。
