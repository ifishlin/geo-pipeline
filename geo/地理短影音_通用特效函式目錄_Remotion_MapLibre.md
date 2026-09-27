# 地理短影音通用特效函式目錄

給影片規劃 LLM 選用、給本機 Codex 實作的規格。依據先前三支格陵蘭、聖嬰現象、太平洋戰爭短影音的特效拆解，並加入 Remotion 與 MapLibre GL JS 官方文件支援的能力。**函式按視覺行為分類，不按地理題材命名**：暖水、冷水、風、軍隊、船隻只是同一組通用特效的不同資料與素材。

## 一、整體設計

LLM 輸出的是宣告式 `EffectSpec[]`；渲染器負責解讀、驗證及逐影格產生畫面。不要讓 LLM 直接輸出任意 JS 程式或 MapLibre 的 `flyTo()` 呼叫。

```
腳本與地理資料 → LLM 選擇函式與參數 → schema 驗證與素材解析
              → 每影格求值 → MapLibre 地圖／地理圖層
                           → Remotion SVG／Canvas／圖片／文字／音訊 → 影片
```

### 共通契約

```ts
type LonLat = [longitude: number, latitude: number]; // WGS84，順序固定
type GeoPoint = {space: 'geo'; coordinate: LonLat};
type ScreenPoint = {space: 'screen'; x: number; y: number}; // 0..1，相對影片畫面
type Anchor = GeoPoint | ScreenPoint;
type Region = {polygon: LonLat[][]} | {region_id: string};
type Strength = number; // 0..1；每個函式明定如何映射至尺寸、速度、透明度等

type EffectBase = {
  id: string;
  type: string;
  start_s: number;
  duration_s: number;
  layer: 'map' | 'geo_overlay' | 'screen_overlay' | 'cutaway' | 'audio';
  easing?: 'linear' | 'ease_in_out' | 'spring';
  enter_s?: number; exit_s?: number;
  seed?: number; // 隨機外觀固定
};
```

- 時間用秒作為對外 API；編譯時轉影格 `round(seconds * fps)`，同一影片統一 FPS。`duration_s > 0`，進退場時長不可超過總長。
- 地理座標一律 `[經度, 緯度]`；多點路徑至少兩點，區域使用 GeoJSON 相容的封閉 rings 或 `region_id`。跨 180° 經線應先拆線或經度展開，避免線繞地球一圈。
- `asset_id` 是已審核的本機素材清單索引；素材含圖、影片、聲音、SVG。透明 PNG/WebP/SVG 用於地理圖上物件；實際來源與授權由素材清單管理。
- `intensity` 是相對力度，不能假裝是真實物理數值；如果是資料視覺化，另提供 `data_ref`、單位、數值範圍與圖例。
- 每項效果可選 `opacity`、`blend_mode`、`palette_id`、`caption`、`priority`；有必要時用 `keyframes: [{t: 0..1, value: ...}]`，而非增加題材專用函式。
- LLM 選用說明應同時列「何時選」「何時不要選」「需要哪些資料」。找不到必要座標或素材時回報缺資料，不得憑空發明精確地點。

### 渲染準則

Remotion 的 `useCurrentFrame()`、`useVideoConfig()` 和 `interpolate()`／`spring()` 決定當前時間與動畫值；`<Sequence>`、`TransitionSeries` 管理片段和轉場。MapLibre 的圖層負責真正貼合地表的面、線、點、熱圖、地形；React/SVG/Canvas 負責角色、光暈、粒子、排版和全畫面特效。地理錨點每一影格由 `map.project(lonLat)` 投影到畫面，鏡頭移動時才能跟隨。[Remotion fundamentals](https://www.remotion.dev/docs/the-fundamentals) · [useCurrentFrame](https://www.remotion.dev/docs/use-current-frame) · [MapLibre Map API](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/)

**逐格一致性是核心驗收條件。** Remotion 可平行、跳格渲染，效果必須是 `render(frame, spec, seed)` 的純計算。鏡頭逐格算狀態並使用 `map.jumpTo()`，不要依賴瀏覽器真實時間、`flyTo()`／`easeTo()` 自行播放、未設定 seed 的 `Math.random()`、上一影格累積的位置。MapLibre style transition 設為 0。地圖載入、圖磚及 `GeoJSONSource.setData()` 屬非同步操作；等待當前狀態完成並在輸出畫面前確認地圖已繪製，Remotion 可用 `delayRender()/continueRender()` 控制等待，錯誤應明確中止。預覽和正式輸出各測一次。[MapLibre GeoJSONSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/) · [Remotion delayRender](https://www.remotion.dev/docs/delay-render)

## 二、給 LLM 的函式目錄

以下 17 個函式是對外語意介面；底層可以共用繪圖引擎。`geo` 表地理錨點，`screen` 表畫面錨點。括號內為實作優先序：P0 先做、P1 加值、P2 進階。

| 函式 | 給 LLM 的選用說明 | 位置與必要參數 | 可調參數／素材 | Codex 建議實作 |
|---|---|---|---|---|
| `animate_camera` P0 | 強調地點、從全局推進到局部、跟隨敘事移動。不要拿來表達現象本身。 | `from`、`to`: `{center: LonLat, zoom, bearing?, pitch?}`；或 `keyframes` | `intensity` 控制移動幅度的建議值、`easing`、`focus` | Remotion 逐格插值相機參數，MapLibre `jumpTo`；經度取最短路徑、地圖投影與 pitch 設界限。 |
| `set_map_appearance` P1 | 切換地圖主題、球體／平面、地形或建築立體感；用於時代和尺度變化。不要逐影格切換 style。 | `style_id`、`projection: mercator/globe`（版本支援時） | `terrain_id`、`hillshade`、`buildings_3d`、色調、`transition_s` | 預載核准的 style；場景邊界切換 MapLibre projection/style，地形 `setTerrain`、hillshade、fill-extrusion 圖層；轉場以雙畫面合成，避免中途載入閃爍。 |
| `highlight_region` P0 | 高亮國家、島嶼、海域或任意區域；可表達暖區、冷區、勢力範圍。不要把示意區域說成精確觀測。 | `region` | `fill_color`、`outline_color`、`opacity`、`intensity`、`pulse`、`feather` | GeoJSON fill/line 圖層；透明度及顏色逐格更新。柔邊另用 Canvas/WebGL 蒙版或預烘 raster，因基本 fill 邊界硬。 |
| `reveal_boundary` P0 | 描繪國境、海岸、分界、包圍圈。需要可追蹤的輪廓時用。 | `path: LonLat[]` 或 `region` 的邊界 | `color`、`width_px`、`dash`、`intensity` | 預算線段累積長度，依進度裁切 GeoJSON LineString 後 `setData`；實線可用 line layer，光暈疊一條寬而透明的線。 |
| `draw_route` P0 | 畫航線、飛行線、遷移或因果連線；方向清楚但沒有連續流場。 | `path: LonLat[]`；可含多段 | `curve`、`color`、`width_px`、`head`、`trail`、`intensity` | 地理曲線預採樣，依影格揭露線段，箭頭或移動點沿累積距離取樣；MapLibre line + symbol，跨日期變更線處理。 |
| `animate_flow` P1 | 表達海流、風向、交通流、擴散的方向。適用有流向資料或明確示意方向。不要用一條線冒充整片流場。 | `field_ref`（格網向量）或 `paths: LonLat[][]` | `density`、`speed`、`intensity`、`particle_size`、`seed`、`palette_id` | Canvas/WebGL 粒子在地理向量場按絕對時間取位置，或預先採樣流線；每影格經地圖投影，遮罩裁海陸。全程固定 seed。 |
| `animate_field` P1 | 表達連續的溫度、冷暖水帶、氣壓、降雨帶、煙霧、擴散等面狀強弱。不要替代真實資料熱圖。 | `region` 或 `centerline: LonLat[]` 或 `data_ref` | `kind: glow/band/contour/noise`、`intensity`、`width_km`、`spread`、`palette_id`、`direction` | 先以地理座標產生格網／等值面與時間函數，再渲染成地理配準 raster、WebGL custom layer 或逐格 Canvas；MapLibre image/raster source 適合預烘帧。指定示意或資料模式。 |
| `show_point_data` P1 | 表達大量地理點的密度、群聚、分布或數值；適合震央、事件、人口點。不要拿密度熱圖代表溫度場。 | `points_ref`（每點位置及可選權重） | `mode: dots/cluster/heatmap`、`radius`、`weight_field`、`intensity`、`legend` | GeoJSON source，circle/symbol/heatmap 圖層；cluster 啟用 source 聚合；MapLibre expression 映射色彩及大小。熱圖是點密度。 |
| `extrude_data` P2 | 地區數值需要高度比較、3D 建築或地貌抬升時用。沒有數值或會遮擋關鍵地名時別用。 | `regions_ref`，`height_field` 或固定 `height_m` | `color_field`、`base_m`、`intensity`、`opacity` | GeoJSON polygon + MapLibre fill-extrusion；高度 expression 依資料值映射，鏡頭適度 pitch。地形使用支援的 DEM source。 |
| `place_geo_asset` P0 | 在地理點固定放旗幟、船、飛機、人物、標記或圖示。物體有位移時選下一項。 | `at: GeoPoint`、`asset_id` | `scale`、`rotation_deg`、`intensity`、`anchor`、`altitude`（進階） | 常規 icon 可 MapLibre symbol layer；插畫／可動角色用透明 React/SVG 元素，每影格 `map.project` 定位與縮放、處理視野外隱藏。 |
| `move_geo_asset` P0 | 船、飛機、箭頭、部隊、角色從一地移往另一地。不要用來畫不具有單一物體的氣流。 | `path: LonLat[]`、`asset_id` | `orientation: tangent/fixed`、`scale`、`trail`、`intensity`、`bob` | 路徑按距離及緩動取樣；每影格投影，CSS/SVG 旋轉或分鏡圖幀切換；可組合 `draw_route` 留軌跡。 |
| `pulse_point` P0 | 單點定位、事件發生、抵達或需要短促聚焦。 | `at: GeoPoint` | `rings`、`radius_px`、`color`、`intensity`、`repeat` | `map.project` 後 SVG 同心圓由影格算半徑及透明度；鏡頭改變仍黏在地點。 |
| `emit_particles` P1 | 雨、雪、火花、爆炸碎屑、煙塵或群體散射；需表現局部事件或氛圍。 | `origin: GeoPoint/ScreenPoint` 或 `path`／`region` | `preset: rain/snow/sparks/smoke/debris`、`count`、`intensity`、`spread`、`gravity`、`seed`、`mask` | 固定 seed 生成每顆粒子的初值，按粒子出生時間及當前影格求解析位置；Canvas/SVG/圖片序列；地理錨點投影後再計局部位移。 |
| `animate_geo_label` P0 | 在地點旁顯示地名、數值或註解，鏡頭移動仍指向同一位置。不要放長段落。 | `at: GeoPoint`、`text` | `leader_line`、`offset_px`、`style_id`、`intensity`、`collision_priority` | `map.project` + React 文字與 SVG 引線；字體預載，設安全區與簡單避碰，進場由 Remotion 影格控制。若是大量固定地名可選 MapLibre symbol。 |
| `animate_screen_text` P0 | 標題、關鍵字、數字、字幕、旁白摘要；不需要跟著經緯度移動。 | `at: ScreenPoint`、`text` | `preset: type/reveal/count/slide`、`font_id`、`emphasis`、`intensity` | Remotion React/SVG 逐格控制裁切、字距、位移與透明度；數字依資料值插值，字幕由時間碼進場，保持安全邊距。 |
| `show_cutaway` P0 | 暫離地圖插入照片、檔案畫面、示意圖、角色近景或獨立背景，之後回地圖。 | `asset_id` 或 `scene_id` | `crop`、`caption`、`fit`、`background`、`intensity` | Remotion `<Sequence>` 安排圖片／影片／自訂 scene；圖像預載、影片素材按時間裁切；地圖可留底或暫停在指定相機狀態。 |
| `transition_scene` P0 | 在地圖與地圖、地圖與 cutaway 間切換。無場景切換就不要濫用。 | `from_scene_id`、`to_scene_id`、`duration_s` | `preset: fade/wipe/flash/zoom/mask`、`direction`、`intensity`、`mask_asset_id` | Remotion `TransitionSeries` 可實作基本轉場；複雜遮罩由雙層畫面 + SVG/Canvas mask。轉場期間兩場景都須備妥。 |
| `play_audio_cue` P1 | 為撞擊、轉場、移動、環境或旁白安排聲音，應與畫面事件對齊。 | `asset_id`、`start_s`、`duration_s` | `volume`、`fade_in_s`、`fade_out_s`、`loop`、`intensity` | Remotion 時間軸內安排音訊與音量函數；混音限制峰值，畫面事件共用同一時間碼。 |

> 上表為 **18 個函式**。其中 `set_map_appearance`、`show_point_data`、`extrude_data` 是根據 MapLibre 功能加入；`show_cutaway`、`transition_scene`、`play_audio_cue` 對應 Remotion 合成能力。角色眨眼、嘴型和肢體並不獨立成一個題材函式：素材可用 sprite sheet／Lottie／SVG rig，作為 `place_geo_asset`、`move_geo_asset` 或 `show_cutaway` 的 `animation_id` 參數；複雜角色表演可在第二階段增加 `animate_asset` 子模組。

## 三、每種效果的資料形狀與邊界

| 地理輸入形狀 | 對應函式 | 例子 |
|---|---|---|
| 單點 | `place_geo_asset`、`pulse_point`、`animate_geo_label`、`emit_particles` | 城市冒出標記、爆炸點 |
| 多點／路徑 | `draw_route`、`move_geo_asset`、`animate_flow`、`reveal_boundary` | 航線、洋流、海岸線 |
| 區域／多邊形 | `highlight_region`、`animate_field`、`emit_particles`、`extrude_data` | 海溫帶、勢力範圍、降雨區 |
| 點資料集 | `show_point_data` | 聚類、密度熱圖 |
| 相機視圖 | `animate_camera`、`set_map_appearance` | 推進、旋轉、球體切換 |
| 螢幕座標／媒體 | `animate_screen_text`、`show_cutaway`、`transition_scene`、`play_audio_cue` | 標題、照片插畫、轉場、音效 |

`animate_field` 和 `show_point_data` 一定要分開。前者是連續地理場，可輸入格網或示意區域；後者的 heatmap 是**點密度加權渲染**，不能自動表示海水溫度或風速。`animate_flow` 需要方向資訊，若只有一條航線改用 `draw_route`。這是 LLM 選用規則的重要負例。

## 四、從先前影片對應到通用函式

| 影片中看到的敘事效果 | 組合方式 |
|---|---|
| 地圖推近格陵蘭、島嶼染色、圈出區域 | `animate_camera` + `highlight_region` + `reveal_boundary` + `animate_geo_label` |
| 暖水帶、冷水擴散、海流／風場 | `animate_field`（顏色與擴散） + `animate_flow`（方向粒子） + `animate_geo_label`（說明） |
| 航線、軍艦或飛機移動、抵達閃光 | `draw_route` + `move_geo_asset` + `pulse_point`／`emit_particles` |
| 戰事中途切入照片、漫畫角色，再回到地圖 | `show_cutaway` + `transition_scene` + `place_geo_asset`／`move_geo_asset` |
| 時代標題、數字、字幕、爆炸聲 | `animate_screen_text` + `emit_particles` + `play_audio_cue` |

原本影片中的更複雜表現，如整張地圖碎裂、照片受 3D 透視旋轉、手繪角色完整演技，宜以 `show_cutaway` 中的專用 `scene_id` 或離線預烘素材承載；不應為單一參考影片污染通用函式目錄。

## 五、可直接交給 Codex 的呼叫範例

以下是示意設定，位置與數字須由實際腳本和資料確認。

```json
{
  "fps": 30,
  "width": 1080,
  "height": 1920,
  "effects": [
    {
      "id": "camera-pacific", "type": "animate_camera", "layer": "map",
      "start_s": 0, "duration_s": 2.4, "easing": "ease_in_out",
      "from": {"center": [-160, 10], "zoom": 2.2, "bearing": 0, "pitch": 0},
      "to": {"center": [-155, 5], "zoom": 3.8, "bearing": 8, "pitch": 18}
    },
    {
      "id": "current", "type": "animate_flow", "layer": "geo_overlay",
      "start_s": 1.2, "duration_s": 4.0,
      "paths": [[[-170, 0], [-150, 1], [-130, 3]]],
      "density": 0.6, "speed": 0.5, "intensity": 0.7, "seed": 32,
      "palette_id": "warm"
    },
    {
      "id": "callout", "type": "animate_geo_label", "layer": "geo_overlay",
      "start_s": 2.0, "duration_s": 2.5,
      "at": {"space": "geo", "coordinate": [-150, 1]},
      "text": "暖流示意", "offset_px": [30, -45], "leader_line": true
    }
  ]
}
```

### LLM 選用提示詞（可直接放入系統／工具描述）

> 你是地理短影音分鏡規劃器。只可從函式目錄選擇 `type`，可組合多項效果。先判斷敘事是單點、路徑、區域、資料場、相機，還是非地圖畫面，再填入必要座標、素材與時間。地理座標固定 `[經度, 緯度]`。不可把主題名稱發明成新函式。`intensity` 為 0 到 1 的視覺力度；不得偽稱科學測量。實測資料與示意效果須標示 `data_ref` 或 `caption`。輸出符合 schema 的 JSON，沒有足夠座標或素材時列出 `missing_inputs`，不要猜測。

### 各函式 metadata 形狀

```ts
type FunctionDescription = {
  name: string;
  description: string; // 一句話：畫面上發生甚麼
  use_when: string[];
  avoid_when: string[];
  required_inputs: string[];
  optional_inputs: string[];
  location_shape: 'none' | 'point' | 'path' | 'region' | 'field' | 'screen';
  implementation_tier: 'P0' | 'P1' | 'P2';
};
```

對 LLM 提供本表的「選用說明」和參數 schema；把 Codex 實作欄留給開發文件。函式判斷可先按 `location_shape` 篩選，再由 `use_when/avoid_when` 決定，減少把海流誤選為航線等問題。

## 六、工程落地順序

1. **資料層**：實作 `EffectSpec` discriminated union、每個 type 的 runtime schema、座標／時間／素材驗證、缺資料回報。地理資料與素材用 ID 查表，不讓 LLM 傳任意路徑或網址。
2. **地圖橋接**：建立單一 MapLibre map instance 與一組固定 layer/source IDs；`evaluateFrame(frame)` 先算相機、更新必要資料／樣式，再投影錨點。`map.jumpTo`、`map.project`、`setData`、`setPaintProperty` 封裝在 adapter。處理 style 重新載入後重建圖層。
3. **P0 視覺**：先完成相機、區域、路線、地理標記／移動物件／標籤、畫面文字、cutaway、轉場；以三支舊片各挑一段重組驗收。
4. **P1 動態**：加入連續場、向量流、粒子、點密度與音效；流場與粒子每顆位置必須由 `(frame, seed)` 決定。區分資料模式和示意模式。
5. **P2 立體**：投影、地形、建築與數值擠出；測不同 MapLibre 版本的支援，必要時用預烘畫面替代。

### 建議程式結構

```text
src/effects/schema.ts            # discriminated union + metadata
src/effects/registry.ts          # type → renderer + description
src/effects/evaluate.ts          # frame → 純狀態
src/map/MapScene.tsx             # map lifecycle / readiness
src/map/MapAdapter.ts            # camera, sources, layers, project
src/overlays/GeoOverlay.tsx      # SVG/Canvas 地理錨點
src/overlays/ScreenOverlay.tsx   # 字幕、角色、轉場
src/assets/manifest.ts           # 圖片、影片、音訊、字體
src/video/Composition.tsx        # Remotion 時間軸與合成
```

### 最低驗收

- 同一 JSON 在任意影格順序、不同渲染並行數和重跑時，視覺結果一致；特別測 0、1、中間、最後一格。
- 鏡頭平移／縮放期間，標記、路徑、粒子與地理標籤仍與地圖對齊；跨 180° 經線路線不亂繞。
- 地圖圖磚、字體、圖片載入完成才擷取；缺檔、無效座標及不支援的 type 顯示可理解的錯誤。
- 場景切換不閃白、不漏掉地圖圖層；直式 1080×1920 文字不越安全區。

## 七、官方文件對照

| 功能 | 文件 |
|---|---|
| Remotion 影格、插值、彈簧、片段 | [fundamentals](https://www.remotion.dev/docs/the-fundamentals) · [useCurrentFrame](https://www.remotion.dev/docs/use-current-frame) · [interpolate](https://www.remotion.dev/docs/interpolate) · [spring](https://www.remotion.dev/docs/spring) · [Sequence](https://www.remotion.dev/docs/sequence) |
| Remotion 轉場、異步載入、音視訊 | [transitions](https://www.remotion.dev/docs/transitioning) · [delayRender](https://www.remotion.dev/docs/delay-render) · [timing and trimming](https://www.remotion.dev/docs/timing) |
| MapLibre 相機、投影、來源更新 | [Map API](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/) · [GeoJSONSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/) · [ImageSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/ImageSource/) |
| MapLibre 圖層、資料樣式、熱圖、群聚、3D | [examples index](https://maplibre.org/maplibre-gl-js/docs/examples/) · [style layers](https://maplibre.org/maplibre-style-spec/layers/) · [expressions](https://maplibre.org/maplibre-style-spec/expressions/) · [custom layer](https://maplibre.org/maplibre-gl-js/docs/API/interfaces/CustomLayerInterface/) |

> API 細節與 projection／terrain 的支援依專案安裝版本為準。上面是設計規格，Codex 應先查 `package.json` 的實際 Remotion、MapLibre 版本，按該版本官方型別完成 adapter。
