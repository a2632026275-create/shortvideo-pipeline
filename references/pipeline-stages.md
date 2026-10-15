# 阶段操作详解

本文件按 5 个阶段给出具体执行步骤、工具调用方式与示例脚本骨架。SKILL.md 给总览与硬约束，本文件给"怎么做"。主题不限，示例以生活/美食类为默认调性，其他主题按 SKILL.md"按主题动态调整"表套用。

---

## 阶段 1：分镜策划（Ardot 画布）

**目标**：把用户贴的分镜文本固化成一页可编辑分镜看板，镜头号与最终文件命名 `01_~` 对齐。

**步骤**：
1. 解析用户分镜文本，抽取每个镜头的：镜头号、画面描述、景别、时长、文案。
2. 先判断主题归属（生活/美食、口播/知识、科技/演示、Vlog），套用对应画面调性。
3. 用 Ardot 画布建一页分镜板，每个镜头一个卡片，卡片内字段：`01_` 镜头号 / 画面描述 / 景别 / 时长 / 文案。
4. 布局用竖版卡片网格（9:16 调性），方便用户按页精修。
5. 镜头号严格按 `01_`、`02_`、`03_`… 顺序，与阶段3的素材文件名对齐，便于后续追溯。

**注意**：分镜数不固定，按文本实际条数编号，不要硬绑固定数量。

---

## 阶段 2：素材规范（文档）

**目标**：确认风格基线与命名映射，避免后续素材命名混乱。

**步骤**：
1. 复述风格基线（9:16 / 视频优先 / Pexels 为主 + Miora 补 / 画面调性按主题）。
2. 生成命名映射表：`镜头号 → 文件名`，如 `01_ → 01_秤上数字.mp4`、`02_ → 02_手撕鸡胸肉.mp4`。
3. 确认批次主题与存放路径：`剪辑/03_新剪辑归档/<批次主题>/`。

---

## 阶段 3：素材获取（Pexels + Miora）

**目标**：为每个镜头配齐视频素材，Pexels 为主，找不到的用 Miora 文生视频补。

**步骤**：
1. 按镜头画面描述搜 Pexels，按主题调性筛（生活/美食类筛竖屏/无脸/手部食物特写；口播类可筛出镜；科技类可筛屏幕/概念镜头）。搜索技巧：DuckDuckGo `site:pexels.com/video + 英文关键词`（WebFetch html.duckduckgo.com），比 WebSearch/Bing 有效。
2. Pexels 覆盖不到的（MG 动画 / 概念类 / 抽象镜头）用 Miora `miora_text_to_video` 生成视频。**只用视频，不要文生图。**
3. 下载 Pexels 视频 / 保存 Miora 生成视频，按命名映射表重命名后存入批次素材目录。
4. **尺寸统一（自动，无需人工调整）**：全部素材归一化为 1080×1920 竖屏——
   `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30` + libx264/yuv420p/CRF18/去音轨。
   横屏源自动中心裁剪、竖屏源原样保留，天然无拉伸、无黑边（可用 cropdetect 复核 offset 是否为 0）。
5. **水印自动去除**：AI 生成素材必须跑
   `python <本skill>/scripts/watermark_auto_remove.py <视频|目录>`——
   OpenCV 自动识别角落半透明文字水印并精确定位 bbox，ffmpeg delogo 只抹水印、不伤画面主体；
   识别不到时自动回退默认角落区域，必要时 `--region X,Y,W,H` 手动兜底。处理后再归一化（步骤4）。
6. 用 `miora_write_canvas` 把所有素材整理成一页素材板，便于用户预览核对。

**Miora 调用要点**（详见 miora-creative-core）：
- 先 `connect_cloud_service` 取 `clientTempToken` 作为 `tempKey`。
- `miora_text_to_video` 的 prompt 要明确：竖屏 9:16、画面调性（无脸/出镜/MG 等）、与镜头画面描述一致。
- 生成结果 `resultFiles[].localPath` → `miora_write_canvas` → `copied_assets` 再交付。

---

## 阶段 4：草稿搭建（jianying-editor）

**目标**：生成一个可直接在剪映打开的草稿，按镜头顺序排好素材 + 配音字幕 + 配乐 + 转场。

**前置**：
1. 环境验证：`python <JY_SKILL_ROOT>/scripts/api_validator.py`。
2. 脚本路径：项目根目录 `scripts/build_draft.py`，**禁止写进 skill 目录**。
3. ffmpeg/ffprobe 可用性：把有效二进制目录前置到 PATH（WinGet Links 下可能是 0 字节坏链接，会报 `[WinError 193]`）。备用方案：ffmpeg 用 imageio_ffmpeg 自带 exe，ffprobe 从 unpkg `ffprobe-static` 下载单文件。
4. 防横屏（必做）：jianying-editor 的 `normalize_video_for_jianying` 硬编码横屏 1920×1080，宽%16≠0 的竖屏素材（1080 宽即触发）会被转成横屏黑边。**搭建草稿前预生成竖屏缓存**：
   `9x16/__jycache__/<stem>.__jy_norm__.mp4`（内容=竖屏原片），且必须用 `shutil.copyfile` + `os.utime(dst, src_mtime+10)` 强制新鲜——用 `copy2` 会保留源 mtime，在 Windows 亚秒精度下被 `_is_cache_fresh` 误判过期，触发横屏重转。

**脚本骨架**：
```python
import os, sys
# 环境初始化（探测 jianying-editor skill root）
# ...（见 jianying-editor SKILL.md 快速开始的环境探测段）
from jy_wrapper import JyProject

# 按主视频比例设分辨率：9:16 竖屏用 width=1080, height=1920（注意签名是 width/height，不是 resolution 元组）
project = JyProject("短视频_<批次主题>", width=1080, height=1920, overwrite=True)

# 1) 先跑配音拿实际总时长 T（微秒）
T = project.add_narrated_subtitles(text=narration_script, speaker="<音色ID>", start_time="0s")

# 2) 按权重铺镜头：时间轴一律用「微秒整数累积」，禁止浮点秒字符串舍入
#    （舍入会造成 1ms 重叠，触发 SegmentOverlap——且其报错信息打印的是新段时间，极具误导性）
start_us = 0
for shot_file, weight in shot_plan:
    dur_us = int(round(T * weight / total_weight))
    project.add_media_safe(shot_file, start_us, duration=dur_us)
    start_us += dur_us

# 3) BGM / 转场 / 标题…（cloud_music_library.csv 检索选曲，音量 0.6 避让口播）

project.save()
```

**要点**：
- 竖屏 `width=1080, height=1920`；横屏主题用 `(1920, 1080)`，**不要用默认值盲目跑**。
- `add_narrated_subtitles` 一键完成配音+字幕对齐，是主力 API；先跑它拿总时长，再等比铺镜头，画面与配音同起同收。
- 配乐优先 `data/cloud_music_library.csv` 关键词过滤，推荐时主动询问用户。
- 草稿名带批次主题标识，避免与旧草稿混；**剪映运行中草稿目录会被锁定**，删除旧草稿会触发沙箱 SAFE_DELETE 拦截——重建草稿时优先换新名字，旧草稿让用户关闭剪映后手动删。
- 音色用剪映原生 speaker_id（如知性女声=晓晓：`BV009_DPE_streaming`，SAMI TTS 失败自动 fallback 到 edge-tts 同名音色）。

---

## 阶段 5：成片 / 发布

**目标**：精修后导出成片 MP4。

**步骤**：
1. 用户在剪映打开阶段4生成的草稿，手动精修（节奏/字幕样式/局部裁切）。
2. 导出方式二选一：
   - 手动：剪映内导出。
   - 无头：`python <JY_SKILL_ROOT>/scripts/auto_exporter.py "<草稿名>" "<输出.mp4>" --res 1080 --fps 60`（Windows UI 自动化）。
3. 成片归档到 `剪辑/03_新剪辑归档/<批次>/`，发布到抖音 / 小红书等为用户手工环节。

---

## 常见问题

- **Pexels 找不到某镜头**：判断是否为 MG 动画/概念类（数字跳动、抽象图形等），是则走 Miora；写实可拍类再换关键词重搜 Pexels。
- **草稿打不开/损坏**：用 `overwrite=True` 重新初始化 `JyProject` 触发自修复（支持 v5.9+）。
- **导出失败**：优先手动导出；无头导出依赖 Windows UI 自动化，剪映版本变动可能失效。
- **主题不明**：阶段1前主动问一句主题归属，再定画面调性，避免套错风格。
