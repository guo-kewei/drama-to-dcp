# 短剧转电影自动化平台

将短剧公司提供的**宽屏短剧**（多集 MP4/MOV/MKV）批量、全自动转制为影院放映设备可播放的 **DCP（数字电影包）**。

- **傻瓜化**：选文件夹 → 设参数 → 点「开始转换」
- **全自动流水线**：扫描 → 画幅转换 → 响度归一化 → 上混 5.1/7.1 → 拼接 → DCP 封装 → 自动质检
- **备案工作台**：影片项目档案 · 备案报告/主创表/完成台本自动生成 · DCP 技术自检报告 · 内容红线预检 · 流程跟踪
- **全开源免费后端**：FFmpeg + DCP-o-matic（GPL）+ funasr，无任何付费依赖

## 快速开始

### 1. 环境准备（一次性）

| 软件 | 说明 |
|---|---|
| Python ≥ 3.10 | 仅开发/命令行模式需要；普通用户双击 exe 无需 Python |
| FFmpeg | 项目 `tools/` 放便携版即可自动识别（或装到 PATH） |
| DCP-o-matic 2.18+ | 从 [dcpomatic.com/download](https://dcpomatic.com/download) 免费下载 Windows 64-bit 安装 |

```bash
python run.py doctor       # 环境自检（FFmpeg / DCP-o-matic / PySide6）
```

### 2. 图形界面（推荐）

**双击 `短剧转电影平台.exe`**（无需安装 Python），或开发模式 `python run.py`。

三步操作：
1. **新建转换**页 → 选择短剧文件夹（自动扫描显示集数/时长/推荐画幅）→ 填输出设置（一般全用默认）→ 点 **开始转换**
2. **任务队列**页 → 查看进度、取消/重试、看日志
3. 完成后点「打开输出目录」拿 DCP 文件夹

### DCP 命名（ISDCF 行业规范）

最终 DCP 名称遵循 **ISDCF DCNC 数字影院命名规范**：
`片名_内容类型_画幅_语言_声道_分辨率_日期_标准_版本`，如
`CYSKDAL_FTR-1_C-185_XX-XX_51_2K_20261114_SMPTE_OV`

- 输入影片名称后自动生成 DCP 片名段（**中文自动转拼音**，长标题取首字母缩写），可手动修改
- 界面实时预览最终完整名称；参数后缀由 DCP-o-matic 打包时按规范自动生成
- 片名段仅允许大写字母/数字/下划线（放映系统兼容性要求）

### 4. 备案工作台（精品化路线）

为走电影备案/审查流程的影片（建议 10-30 部/年量级）准备材料的效率工具：

1. **项目信息**：建立影片档案（片名/译名/出品单位/主创/梗概，梗概实时字数校验）
2. **材料生成**（一键 docx，输出到 `备案/<项目>/materials/`）：
   - 备案报告（对照备案申请表字段）
   - 主创人员登记表
   - 完成台本（funasr 中文转录，句级时间码，81 分钟片约 4 分钟转完；**转录引擎不随 exe 打包**，需 Python 环境运行 `pip install funasr`，exe 中点击会给出指引）
   - DCP 技术自检报告（解析成品 DCP 实测参数 + SMPTE/GY-T 自检清单）
3. **红线预检**：对照《电影产业促进法》第16条与《微短剧管理办法》红线方向的敏感词扫描（词表可编辑：`config/redline_keywords.json`）
4. **流程跟踪**：备案公示→初审→终审→技审→领证 各环节日期登记与周期提示

> ⚠ 免责：本工具只做材料准备与技术自检，**不替代任何行政审批**；单部正规流程仍需 3-5 个月人工审查。

> exe 重新构建：`python -m PyInstaller --onefile --noconsole --name 短剧转电影平台 --icon app.ico run.py`（图标由 `tools/make_icon.py` 生成）

### 3. 命令行模式（批量/自动化）

```bash
python run.py probe  "D:\短剧\某某剧100集"          # 只扫描探测
python run.py convert "D:\短剧\某某剧100集"          # 全流程（默认参数）
python run.py convert "D:\短剧\某某剧" --audio 7.1 --name MY_DRAMA_2026
python run.py resume  "D:\短剧\某某剧"               # 断点恢复（--out 转的任务需加 --out）
```

常用参数：`--container auto|flat|scope|full`（画幅）· `--res 2k|4k` · `--fit fill|fit`（裁切/黑边）· `--audio stereo|5.1|7.1` · `--engine rule|ai`（AI 预留）· `--gap 0.5`（集间黑场）· `--policy skip|abort`（坏集策略）· `--standard SMPTE|Interop` · `--out 目录`

## 输出目录结构

```
<输出根>/                 默认在源文件夹同级「DCP输出」
├── DCP/<名称>/           ✅ 成品 DCP（拷入影院服务器/硬盘）
├── 工作区/<任务ID>/       中间文件（可定期清理）
├── 隔离区/               质检未通过的 DCP
└── reports/              HTML 转制报告
```

## 处理流水线

| 阶段 | 处理 |
|---|---|
| 扫描 | 自然排序集序，ffprobe 逐集探测 |
| 分析 | 宽高比 ≥2.15 自动推荐 Scope，否则 Flat |
| 归一化 | 24fps / Lanczos 缩放裁切（或黑边）/ H.264 CRF12 中间件；loudnorm 两遍法响度统一 |
| 上混 | 可插拔引擎：v1 规则上混（对白中置 C=0.5L+0.5R）；**预留 AI 引擎接口**（未来生成 5.1/7.1/沉浸声） |
| 拼接 | 视频/音频 concat demuxer 无损拼接（RF64 防 4GB）+ 集间黑场静音（默认 0.5s） |
| 封装 | DCP-o-matic：SMPTE / 24fps / 不加密 / Flat(1998×1080) 或 Scope(2048×858) |
| 质检 | 结构 + CPL 参数（画幅/帧率/声道/时长）自动校验，失败进隔离区 |

## 支持与限制

- 源：**宽屏**短剧（16:9 或 2.35:1 等）；30fps 直接转 24fps（不插帧）
- Full 1.90:1 画幅需放映端配置预设，仅手动可选
- 视频超分（v1 预留接口）、AI 音频上混（v1 预留接口）
- DCP 不加密（批量发行模式，无需 KDM 分发）

## 开发

```bash
python tests/test_units.py            # 单元测试
python tests/make_test_media.py       # 生成合成测试短剧
python run.py convert tests/media/测试A_16x9   # 端到端冒烟
```

架构与决策详见 [docs/设计方案.md](docs/设计方案.md)。
