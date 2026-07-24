# Krita统计插件 - 开发文档

## 1. 项目概述

一个 Krita 停靠面板插件，以相册形式展示 .kra 文件的绘画统计信息。自动扫描指定目录下的 .kra 文件，解析 Krita 记录的编辑时间，按日期分组展示，并提供全局统计汇总。

## 2. 功能需求

### 2.1 核心数据
- 扫描 Krita 文件管理路径（或用户指定目录）下的所有 .kra 文件
- 从每个 .kra 文件中提取：
  - **编辑时间**（`documentinfo.xml` 中的 `<editing-time>` 标签，单位秒）
  - **创建时间**（文件系统 `os.path.getctime()`）
  - **修改时间**（文件系统 `os.path.getmtime()`）
  - **缩略图**（.kra 压缩包中的 `preview.png` 或 `mergedimage.png`）
- 支持按创建时间 / 修改时间排序

### 2.2 UI 布局 — 相册风格
- **日分组**：每天一个分区，标题行显示日期 + 当天总耗时
- **月分组**：每月一个分区，标题行显示月份 + 当月总耗时
- **作品卡片**（每张图）：
  - 缩略图
  - 右上角叠加显示该图耗时
  - 图片下方显示：文件名、创建时间、修改时间
- **底部状态栏**：
  - .kra 文件总数
  - 总耗时
  - 最早的创建时间
  - 最晚的修改时间
  - 本月统计 / 本年统计 / 总统计

### 2.3 交互
- 点击卡片 → 使用 Krita 自带的"文档信息"对话框查看详情

## 3. 技术方案

| 层级 | 技术选型 |
|------|----------|
| 插件类型 | `DockWidget`（停靠面板） |
| GUI 框架 | PyQt5（Krita 内置） |
| 文件解析 | `zipfile` + `xml.etree.ElementTree` |
| 缩略图提取 | `zipfile` 读取 `preview.png` |
| 文件系统 | `os`, `glob` |

## 4. 项目结构

```
pykrita/krita统计插件/
├── __init__.py                  # 插件入口，导入主类
├── krita统计插件.py              # 主逻辑：DockWidget + UI + 数据处理
├── Manual.html                  # Krita 插件管理器显示的手册
├── DevelopmentGuide.md          # 本开发文档
└── (krita统计插件.desktop 位于 pykrita/ 同级目录)
```

### .desktop 文件（`krita统计插件.desktop`）

```ini
[Desktop Entry]
Type=Service
ServiceTypes=Krita/PythonPlugin
X-KDE-Library=krita统计插件
X-Krita-Manual=Manual.html
Name=Krita统计插件
Comment=统计图像信息，拥有相册布局，包含年月日统计。
```

## 5. 核心实现详解

### 5.1 插件入口（`__init__.py`）

```python
from .krita统计插件 import Krita统计插件
```

将主类暴露给 Krita 插件加载器。

### 5.2 主类框架（`krita统计插件.py`）

#### 5.2.1 DockWidget 基础结构

```python
from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import zipfile
import xml.etree.ElementTree as ET
import os
import glob
import datetime

DOCKER_NAME = 'Krita统计插件'
DOCKER_ID = 'pykrita_krita统计插件'

class Krita统计插件(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(DOCKER_NAME)
        # TODO: 初始化 UI
        # TODO: 加载数据

    def canvasChanged(self, canvas):
        pass
```

#### 5.2.2 扫描 .kra 文件

```python
def scan_kra_files(self, root_dir):
    """递归扫描目录下所有 .kra 文件"""
    kra_files = []
    for root, dirs, files in os.walk(root_dir):
        for f in files:
            if f.lower().endswith('.kra'):
                kra_files.append(os.path.join(root, f))
    return kra_files
```

#### 5.2.3 解析 .kra 文件数据

```python
def parse_kra_file(self, filepath):
    """解析单个 .kra 文件，返回数据字典"""
    result = {
        'path': filepath,
        'name': os.path.basename(filepath),
        'editing_time': 0,      # 秒
        'created_time': None,   # datetime
        'modified_time': None,  # datetime
        'thumbnail': None,      # QPixmap
    }

    # 文件系统时间
    stat = os.stat(filepath)
    result['created_time'] = datetime.datetime.fromtimestamp(stat.st_ctime)
    result['modified_time'] = datetime.datetime.fromtimestamp(stat.st_mtime)

    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            # 提取编辑时间
            if 'documentinfo.xml' in zf.namelist():
                xml_data = zf.read('documentinfo.xml')
                root = ET.fromstring(xml_data)
                time_elem = root.find('.//editing-time')
                if time_elem is not None:
                    result['editing_time'] = int(time_elem.text)

            # 提取缩略图 (优先 preview.png)
            for thumb_name in ['preview.png', 'mergedimage.png']:
                if thumb_name in zf.namelist():
                    img_data = zf.read(thumb_name)
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_data)
                    result['thumbnail'] = pixmap
                    break
    except Exception as e:
        print(f"解析失败: {filepath} - {e}")

    return result
```

#### 5.2.4 数据分组与统计

```python
def process_data(self, records, sort_by='created'):
    """按时间排序并分组"""
    # 排序
    key = 'created_time' if sort_by == 'created' else 'modified_time'
    records.sort(key=lambda r: r[key], reverse=True)

    # 按天分组
    day_groups = {}
    for rec in records:
        day_key = rec[key].strftime('%Y-%m-%d')
        if day_key not in day_groups:
            day_groups[day_key] = []
        day_groups[day_key].append(rec)

    # 按月分组
    month_groups = {}
    for rec in records:
        month_key = rec[key].strftime('%Y-%m')
        if month_key not in month_groups:
            month_groups[month_key] = []
        month_groups[month_key].append(rec)

    # 统计信息
    stats = {
        'total_count': len(records),
        'total_time': sum(r['editing_time'] for r in records),
        'earliest_created': min(r['created_time'] for r in records) if records else None,
        'latest_modified': max(r['modified_time'] for r in records) if records else None,
    }

    return day_groups, month_groups, stats
```

#### 5.2.5 UI 构建

```python
def build_ui(self):
    """构建相册界面"""
    main_widget = QWidget()
    main_layout = QVBoxLayout(main_widget)

    # 顶部：排序/刷新控件
    top_bar = QHBoxLayout()
    self.sort_combo = QComboBox()
    self.sort_combo.addItems(['按创建时间', '按修改时间'])
    refresh_btn = QPushButton('刷新')
    top_bar.addWidget(QLabel('排序:'))
    top_bar.addWidget(self.sort_combo)
    top_bar.addStretch()
    top_bar.addWidget(refresh_btn)

    # 中部：可滚动相册
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_content = QWidget()
    self.album_layout = QVBoxLayout(scroll_content)
    scroll_area.setWidget(scroll_content)

    # 底部：统计栏
    bottom_bar = QHBoxLayout()
    self.stats_total_count = QLabel('文件数: 0')
    self.stats_total_time = QLabel('总耗时: 0s')
    self.stats_earliest = QLabel('最早: -')
    self.stats_latest = QLabel('最晚: -')
    self.stats_month = QLabel('本月: 0s')
    self.stats_year = QLabel('本年: 0s')
    bottom_bar.addWidget(self.stats_total_count)
    bottom_bar.addWidget(self.stats_total_time)
    bottom_bar.addWidget(self.stats_earliest)
    bottom_bar.addWidget(self.stats_latest)
    bottom_bar.addWidget(self.stats_month)
    bottom_bar.addWidget(self.stats_year)

    main_layout.addLayout(top_bar)
    main_layout.addWidget(scroll_area)
    main_layout.addLayout(bottom_bar)

    self.setWidget(main_widget)
```

#### 5.2.6 渲染相册内容

```python
def render_album(self, day_groups, month_groups, stats):
    """将分组数据渲染为相册布局"""
    # 清空旧内容
    while self.album_layout.count():
        item = self.album_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()

    # 按月分组渲染
    for month_key in sorted(month_groups.keys(), reverse=True):
        month_records = month_groups[month_key]
        month_total = sum(r['editing_time'] for r in month_records)
        month_label = QLabel(f"📁 {month_key}  月总耗时: {self.format_time(month_total)}")
        month_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        self.album_layout.addWidget(month_label)

        # 按天分组渲染
        for day_key in sorted(day_groups.keys(), reverse=True):
            if not day_key.startswith(month_key):
                continue
            day_records = day_groups[day_key]
            day_total = sum(r['editing_time'] for r in day_records)
            day_label = QLabel(f"  📅 {day_key}  日总耗时: {self.format_time(day_total)}")
            day_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px 16px;")
            self.album_layout.addWidget(day_label)

            # 作品卡片网格（每行 4 张）
            grid = QGridLayout()
            for i, rec in enumerate(day_records):
                card = self.create_card(rec)
                grid.addWidget(card, i // 4, i % 4)
            self.album_layout.addLayout(grid)

    # 更新底部统计
    self.update_stats(stats)
```

#### 5.2.7 作品卡片

```python
def create_card(self, record):
    """创建单个作品卡片"""
    card = QWidget()
    card.setFixedSize(200, 260)
    card.setStyleSheet("""
        QWidget { border: 1px solid #ccc; border-radius: 4px; }
        QWidget:hover { border-color: #4a9eff; }
    """)

    layout = QVBoxLayout(card)
    layout.setContentsMargins(4, 4, 4, 4)
    layout.setSpacing(2)

    # 缩略图
    thumb_label = QLabel()
    thumb_label.setFixedSize(192, 144)
    thumb_label.setAlignment(Qt.AlignCenter)
    if record['thumbnail'] and not record['thumbnail'].isNull():
        thumb = record['thumbnail'].scaled(192, 144, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumb_label.setPixmap(thumb)

    # 耗时角标（右上角覆盖）
    time_overlay = QLabel(self.format_time(record['editing_time']))
    time_overlay.setStyleSheet("""
        background: rgba(0,0,0,160);
        color: white;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 11px;
    """)
    # 使用 QStackedLayout 或手动布局实现叠加

    # 文件信息
    name_label = QLabel(record['name'])
    name_label.setWordWrap(True)
    name_label.setStyleSheet("font-size: 11px;")

    ctime_label = QLabel(f"创建: {record['created_time'].strftime('%Y-%m-%d %H:%M')}")
    ctime_label.setStyleSheet("font-size: 10px; color: #888;")
    mtime_label = QLabel(f"修改: {record['modified_time'].strftime('%Y-%m-%d %H:%M')}")
    mtime_label.setStyleSheet("font-size: 10px; color: #888;")

    layout.addWidget(thumb_label)
    layout.addWidget(name_label)
    layout.addWidget(ctime_label)
    layout.addWidget(mtime_label)

    # 点击事件
    card.mousePressEvent = lambda e, p=record['path']: self.open_document_info(p)

    return card
```

#### 5.2.8 点击打开文档信息

```python
def open_document_info(self, filepath):
    """使用 Krita API 打开文档信息对话框"""
    doc = Krita.instance().openDocument(filepath)
    if doc:
        # 触发文档信息动作
        action = Krita.instance().action('document_info')
        if action:
            action.trigger()
```

### 5.3 工厂注册

```python
instance = Krita.instance()
dock_widget_factory = DockWidgetFactory(
    DOCKER_ID,
    DockWidgetFactoryBase.DockPosition.DockRight,
    Krita统计插件
)
instance.addDockWidgetFactory(dock_widget_factory)
```

## 6. 时间格式化工具

```python
@staticmethod
def format_time(seconds):
    """将秒数格式化为可读字符串"""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    elif seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"
```

## 7. 开发与调试

### 7.1 启用插件
1. 将 `krita统计插件/` 文件夹和 `krita统计插件.desktop` 放入 Krita 的 `pykrita/` 目录
2. 启动 Krita → **设置 → 配置 Krita → Python 插件管理器**
3. 勾选 **Krita统计插件** → 应用 → 重启 Krita
4. 在 **设置 → 面板** 中找到并启用

### 7.2 调试技巧
- 使用 Krita 内置 **Scripter**（工具 → 脚本 → Scripter）快速测试代码片段
- 通过 `print()` 输出到控制台（Windows 需查看 Krita 的 stderr 输出）
- 推荐安装 [Krita-PythonPluginDeveloperTools](https://github.com/EyeOdin/Krita-PythonPluginDeveloperTools) 辅助调试

### 7.3 关键 API 参考
- [Krita Python API 文档](https://api.krita.org/)
- PyQt5 文档 — QtWidgets, QtCore, QtGui

## 8. 已知问题与注意事项

| 问题 | 说明 |
|------|------|
| 缩略图提取 | 部分旧版 .kra 可能不包含 `preview.png`，需回退到 `mergedimage.png` |
| 创建时间 | `os.stat().st_ctime` 在 Windows 上为创建时间，在 Linux/macOS 上为元数据变更时间 |
| 大目录性能 | 首次扫描大量 .kra 文件可能较慢，建议添加加载动画或后台线程 |
| 文件锁定 | Krita 中已打开的文件可能被锁定，`zipfile` 读取时应捕获异常 |

## 9. 后续扩展建议

- [ ] **实时监听**：使用 `QFileSystemWatcher` 监控目录变化，自动刷新
- [ ] **自定义目录**：允许用户选择任意文件夹而非固定路径
- [ ] **图表统计**：集成 Matplotlib 或 PyQtChart 显示月度趋势图
- [ ] **标签/搜索**：支持按文件名搜索或按标签筛选
- [ ] **导出报告**：将统计结果导出为 CSV 或 HTML 报告
- [ ] **多语言**：支持中/英文界面切换
- [ ] **缩略图缓存**：缓存解析结果到本地 JSON 文件，避免重复解压
