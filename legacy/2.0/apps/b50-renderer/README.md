# dududa B50 renderer

独立的 Arcaea B50 图片渲染器。程序只依赖 Pillow，不导入 AstrBot 或嘟嘟哒插件模块；曲绘从外部 Arcaea 素材目录读取。

## 运行

```bash
python3 -m pip install -r requirements.txt

python3 b50_renderer.py \
  --input example_b50.txt \
  --assets-root /path/to/arcaea/import \
  --output b50.png \
  --player-name PLAYER \
  --player-id 123456789
```

`--assets-root` 指向同时包含 `songlist` 和各曲目 ID 子目录的导入目录。默认读取脚本同级的 `background.png` 以及 `fonts/`。
仓库不提交大体积 CJK 字体。中文曲名优先使用环境变量
`DUDUDA_B50_CJK_FONT` 指定的字体，其次读取常见系统 CJK 字体；也可以通过
`--font-dir` 提供包含 `NotoSansCJKsc-Regular.otf` 的私有字体目录。
完整压缩包已将全曲曲绘放在 `assets/`，解压后可直接运行：

```bash
python3 b50_renderer.py \
  --input best_scores.csv \
  --assets-root assets \
  --output b50.png
```

## 输入格式

- TXT：`曲名 [FTR] 10.7: 9943293 (12.416) FAR 12 LOST 1 小P 150`。`FAR`、`LOST`、`小P` 均为可选字段，`小P` 也可写成 `SMALLP`；括号内的旧潜力值统一加 `0.2`。
- CSV：支持 `best_scores.csv` 的 `Far`、`Lost`、`Pure`、`MaxPure` 列，小 P 自动按 `Pure - MaxPure` 计算，也可用 `SmallPure` 列直接提供；`Potential` 视为已经加过 `0.2`，按潜力排序后取前 50 条。
- JSON：根对象使用 `scores`、`records` 或 `b50` 数组；成绩项可使用 `far`、`lost`、`pure`、`max_pure`、`small_pure`，未提供 `small_pure` 时会从 `pure - max_pure` 计算；`potential` 视为修正后的值，`raw_potential` 会加 `0.2`。玩家信息可放在 `player.name` 与 `player.user_id`。

TXT 按输入顺序渲染前 50 条；CSV 和 JSON 按潜力降序渲染前 50 条。
卡片中的单曲 PT 固定显示四位小数。
判定明细按 `P1199(+1049) F12 L1 HC` 格式显示；小 P 保留在输入数据中，不额外占用卡片字段。

## 打包

```bash
python3 -m pip install pyinstaller
pyinstaller --onefile --name b50-renderer \
  --add-data "background.png:." \
  --add-data "fonts:fonts" \
  b50_renderer.py
```

打包后曲绘素材仍通过 `--assets-root` 指定，不会被塞入可执行文件。字体使用 SIL Open Font License 1.1，许可证位于 `fonts/OFL-1.1.txt`。
