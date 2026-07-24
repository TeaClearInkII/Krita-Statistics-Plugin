# Krita Statistics Plugin / Krita统计插件

[![Krita](https://img.shields.io/badge/Krita-5.x-3daee9)](https://krita.org)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

A Krita dock widget that displays .kra file painting statistics in an album layout. Automatically scans directories for .kra files, parses editing time and metadata, and groups results by year/month/day.

以相册形式展示 .kra 文件绘画统计信息的 Krita 停靠面板插件。自动扫描目录下的 .kra 文件，解析编辑时间和元数据，按年/月/日分组展示。

---

## Features / 功能

**🇬🇧 English**
- Album-style gallery with thumbnails
- Year / Month / Day collapsible groups
- Sort by creation or modification time (ascending / descending)
- Real-time filename search
- Browse any directory for .kra files
- Click card to view image info & author contacts
- Statistics chart dialog (7d / 30d / 12m / all, bar / line / curve)
- Export self-contained HTML report with charts, thumbnails, sortable table
- Export to PDF via browser print
- Background scanning (non-blocking UI)
- Cache system for fast re-scan
- Settings persistence (path, sort, collapse state, export path)

**🇨🇳 中文**
- 相册式缩略图画廊
- 年/月/日可折叠分组
- 按创建/修改时间升/降序排序
- 实时文件名搜索
- 任意目录浏览
- 点击卡片查看图像信息与作者联系方式
- 统计图表对话框（7天/30天/12个月/全部，柱状/折线/曲线）
- 导出 HTML 报告（含图表、缩略图、可排序表格）
- 通过浏览器打印导出为 PDF
- 后台扫描（不阻塞 UI）
- 缓存系统加速重新扫描
- 配置持久化（路径、排序、折叠状态、导出路径）

---

## Screenshots / 截图

*(Add screenshots here)*

---

## Installation / 安装

### Windows
1. Download the latest ZIP from [Releases](https://github.com/TeaClearInkII/Krita-Statistics-Plugin/releases)
2. Extract to `%APPDATA%\krita\pykrita\`
3. Launch Krita → **Settings → Configure Krita → Python Plugin Manager**
4. Enable **Krita统计插件** → Apply → Restart
5. Go to **Settings → Dockers** → enable **Krita统计插件**

### Linux
```bash
cd ~/.local/share/krita/pykrita/
# Extract the ZIP here
```

### macOS
```bash
cd ~/Library/Application\ Support/krita/pykrita/
# Extract the ZIP here
```

Then follow steps 3–5 from Windows instructions.

### Required Files / 必需文件

```
pykrita/
├── krita统计插件.desktop
└── krita统计插件/
    ├── __init__.py
    ├── krita统计插件.py
    └── Manual.html
```

---

## Usage / 使用方法

| UI Area | Description |
|---------|-------------|
| Row 1 | Sort dropdown + Browse button + path + Refresh |
| Row 2 | Filename search bar (real-time filter) |
| Scroll area | Collapsible Year → Month → Day groups with artwork cards |
| Bottom row 1 | File count, total time, this month, this year |
| Bottom row 2 | Earliest / latest dates |
| Bottom row 3 | 📊 Chart / ℹ️ About / 📤 Export |

---

## File Structure / 文件结构

```
Krita-Statistics-Plugin/
├── README.md                          # This file
├── InstallationGuide.html             # English installation guide
├── 使用方法.html                       # Chinese installation guide
├── .gitignore
├── .gitattributes
├── krita统计插件.desktop               # Plugin registration
└── krita统计插件/                      # Plugin source
    ├── __init__.py
    ├── krita统计插件.py                 # Main plugin code (~1840 lines)
    ├── Manual.html                    # Bilingual manual (CN/EN)
    ├── Manual.html.bak
    ├── DevelopmentGuide.md
    ├── DevelopmentManual.md
    └── TechResearchAndPlan.md
```

---

## Build / 打包

```powershell
# Create distribution ZIP
Compress-Archive -Path "krita统计插件.desktop", "krita统计插件\__init__.py", "krita统计插件\krita统计插件.py", "krita统计插件\Manual.html" -DestinationPath "Krita统计插件_v1.0.zip"
```

---

## Author / 作者

**茶清墨刂**

- Bilibili: [space.bilibili.com/388428308](https://space.bilibili.com/388428308)

---

## License / 许可

MIT
