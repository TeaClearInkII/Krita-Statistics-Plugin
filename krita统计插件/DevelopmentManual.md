# Krita统计插件 — 最终开发手册

## 1. 项目概述

一个 Krita 停靠面板（DockWidget）插件，以相册形式展示 .kra 文件的绘画统计信息。
自动扫描 Krita 文档管理路径下的 .kra 文件，解析 Krita 内部记录的编辑时间，按日期分组展示，并提供全局统计汇总。

### 1.1 设计目标

- **只读统计**：插件只读取和展示，不修改 .kra 文件
- **视觉直观**：相册式布局，一眼看清创作时间线
- **与 Krita 集成**：复用 Krita 内置的文档信息对话框

### 1.2 用户原始需求

> 开发一个 Krita 插件，具有界面显示统计信息（本身不做记录）。扫描 Krita 文件管理路径下的 .kra 文件内的时间信息，以创建时间/修改时间排序。显示每张 .kra 的缩略图，右上角显示耗时，下方显示名称、创建时间和修改时间。界面像相册一样按天分割，每天标题后有当天总耗时，每月标题后有当月总耗时。底部显示全部统计结果：.kra 数量、总耗时、最早创建时间、最晚修改时间、本月/本年/总统计。点击图像使用 Krita 自带的文档属性查看详细信息。

---

## 2. 功能需求

### 2.1 核心数据

- 扫描 Krita 文档管理路径下的所有 .kra 文件（通过 Krita API 获取路径）
- 从每个 .kra 文件中提取：
  - **编辑时间**（`documentinfo.xml` 中的 `<editing-time>` 标签，单位秒）
  - **创建时间**（文件系统 `os.path.getctime()`）
  - **修改时间**（文件系统 `os.path.getmtime()`）
  - **缩略图**（.kra 压缩包中的 `preview.png` 或 `mergedimage.png`）
- 支持按创建时间 / 修改时间排序

### 2.2 UI 布局 — 相册风格

- **月分组**：每月一个分区，标题行显示月份 + 当月总耗时
- **日分组**：每天一个分区，标题行显示日期 + 当天总耗时
- **作品卡片**（每张图）：
  - 缩略图
  - 右上角叠加显示该图耗时
  - 图片下方显示：文件名、创建时间、修改时间
- **底部状态栏**：
  - .kra 文件总数
  - 总耗时
  - 最早的创建时间
  - 最晚的修改时间
  - 本月统计 / 本年统计

### 2.3 交互

- 点击卡片 → 使用 Krita 自带的"文档信息"对话框查看详情
- 排序下拉切换（按创建时间 / 修改时间）
- 刷新按钮手动重新扫描

---

## 3. 技术方案

### 3.1 技术选型

| 层级 | 技术选型 | 选型理由 |
|------|----------|----------|
| 插件类型 | `DockWidget`（停靠面板） | 可停靠在 Krita 主窗口侧边，拥有独立 UI 空间 |
| GUI 框架 | PyQt5（Krita 内置） | Krita Python API 基于 PyQt5，无需额外安装 |
| 文件解析 | `zipfile` + `xml.etree.ElementTree` | Python 标准库，无外部依赖 |
| 缩略图提取 | `zipfile` 读取 `preview.png` | .kra 压缩包内置预览图 |
| 文件系统 | `os` / `os.walk` | Python 标准库，跨平台兼容 |
| 并发方案 | QTimer 分片处理 | Krita 5.x QThread 存在 Bug #441956 |
| 缓存 | L1 内存 + L2 磁盘（`~/.krita_stats_cache/`） | 内存上限 500 条，磁盘持久化 |
| 列数策略 | 根据窗口宽度自适应 | 充分利用空间，自动重排 |

### 3.2 为什么选择 DockWidget 而非 Extension

```
Extension:    无 UI 界面，后台运行，适合自动任务
DockWidget:   有独立面板 UI，可停靠/浮动，适合交互式浏览
→ 本项目需要相册浏览界面，选择 DockWidget
```

### 3.3 .kra 文件结构

.kra 文件本质上是标准 ZIP 压缩包：

```
archive.kra
├── mimetype                    # "application/x-kra"（固定内容）
├── documentinfo.xml            # 文档元信息
├── maindoc.xml                 # 文档主结构
├── preview.png                 # 预览缩略图（首选）
├── mergedimage.png             # 全尺寸合并预览图（备选）
└── <文档名>/                    # 以文档名命名的子目录
    ├── annotations/            # 注释数据
    └── layers/                 # 图层像素数据（LZF 压缩）
```

#### documentinfo.xml 完整结构

```xml
<document-info>
  <about>
    <title>文档标题</title>
    <description>描述</description>
    <editing-cycles>1</editing-cycles>     <!-- 编辑循环次数 -->
    <editing-time>35</editing-time>        <!-- ★ 总编辑时间（秒） -->
    <date>2017-02-27T20:15:09</date>       <!-- 最后保存时间 -->
    <creation-date>2017-02-27T20:14:33</creation-date>
  </about>
  <author>
    <full-name>作者名</full-name>
    <email>邮箱</email>
    <company>公司</company>
  </author>
</document-info>
```

#### 缩略图提取优先级

| 文件名 | 优先级 | 说明 |
|--------|--------|------|
| `preview.png` | 首选 | 小尺寸缩略图，读取快 |
| `mergedimage.png` | 回退 | 全尺寸合并图，部分旧版或 .krz 格式缺失 |

---

## 4. 项目结构

```
pykrita/
├── opencode.json                # OpenCode 项目配置
├── krita统计插件.desktop         # 插件注册文件
├── ds对话.txt                    # 需求分析与技术讨论原始记录
└── krita统计插件/                # 插件代码包
    ├── __init__.py              # 插件入口
    ├── krita统计插件.py           # 主逻辑：DockWidget + UI + 数据处理
    ├── Manual.html              # Krita 插件管理器显示的手册
    ├── DevelopmentGuide.md      # 开发文档（旧版）
    ├── TechResearchAndPlan.md   # 技术调研与开发规划（旧版）
    └── DevelopmentManual.md     # ← 本文件：最终开发手册
```

### .desktop 文件

```ini
[Desktop Entry]
Type=Service
ServiceTypes=Krita/PythonPlugin
X-KDE-Library=krita统计插件
X-Krita-Manual=Manual.html
Name=Krita统计插件
Comment=统计图像信息，拥有相册布局，包含年月日统计。
```

---

## 5. 核心实现详解

### 5.1 Krita API 关键机制

#### DockWidget 生命周期

```
Krita 启动
  → 加载 pykrita 目录插件
    → 执行模块顶层代码（工厂注册）
      → DockWidgetFactory 注册到 Krita 实例
        → 用户打开面板时创建实例（每个主窗口仅一个）
          → __init__() 初始化 UI
            → 用户切换文档时触发 canvasChanged()
```

| 方法 | 说明 |
|------|------|
| `__init__()` | 必须调用 `super().__init__()`，否则 C++ 底层对象无法正确初始化 |
| `canvasChanged(canvas)` | 当前画布切换时触发 |
| `canvas()` | 获取当前关联的画布对象（Krita 4.0+） |

#### Action 系统

```python
# 触发文档信息对话框（本项目核心交互）
Krita.instance().action('document_info').trigger()
```

| Action ID | 功能 | 用途 |
|-----------|------|------|
| `document_info` | 文档信息对话框 | 点击卡片打开详情 |
| `python_scripter` | 打开 Scripter | 调试辅助 |

#### Document 类常用方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `fileName()` | `str` | 文件路径 |
| `name()` | `str` | 文档名称 |
| `width()` / `height()` | `int` | 画布尺寸 |
| `documentInfo()` | `str` | 获取文档信息 XML 字符串 |
| `setBatchmode(bool)` | `void` | 设置批量模式（无弹窗保存） |

### 5.2 插件入口（`__init__.py`）

```python
from .krita统计插件 import Krita统计插件
```

### 5.3 主类框架

```python
from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import zipfile, xml.etree.ElementTree as ET, os, datetime

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

### 5.4 扫描 .kra 文件

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

### 5.5 解析 .kra 文件数据

```python
def parse_kra_file(self, filepath):
    """解析单个 .kra 文件，返回数据字典"""
    result = {
        'path': filepath,
        'name': os.path.basename(filepath),
        'editing_time': 0,
        'created_time': None,
        'modified_time': None,
        'thumbnail': None,
    }
    stat = os.stat(filepath)
    result['created_time'] = datetime.datetime.fromtimestamp(stat.st_ctime)
    result['modified_time'] = datetime.datetime.fromtimestamp(stat.st_mtime)

    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            if 'documentinfo.xml' in zf.namelist():
                xml_data = zf.read('documentinfo.xml')
                root = ET.fromstring(xml_data)
                time_elem = root.find('.//editing-time')
                if time_elem is not None:
                    result['editing_time'] = int(time_elem.text)

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

### 5.6 数据分组与统计

```python
def process_data(self, records, sort_by='created'):
    """按时间排序并分组"""
    key = 'created_time' if sort_by == 'created' else 'modified_time'
    records.sort(key=lambda r: r[key], reverse=True)

    day_groups = {}
    for rec in records:
        day_key = rec[key].strftime('%Y-%m-%d')
        if day_key not in day_groups:
            day_groups[day_key] = []
        day_groups[day_key].append(rec)

    month_groups = {}
    for rec in records:
        month_key = rec[key].strftime('%Y-%m')
        if month_key not in month_groups:
            month_groups[month_key] = []
        month_groups[month_key].append(rec)

    stats = {
        'total_count': len(records),
        'total_time': sum(r['editing_time'] for r in records),
        'earliest_created': min(r['created_time'] for r in records) if records else None,
        'latest_modified': max(r['modified_time'] for r in records) if records else None,
    }
    return day_groups, month_groups, stats
```

### 5.7 UI 构建

```
DockWidget
  └── QWidget (main)
       ├── QHBoxLayout (top_bar)
       │    ├── QLabel("排序:")
       │    ├── QComboBox [按创建时间, 按修改时间]
       │    ├── QSpacerItem (stretch)
       │    └── QPushButton("刷新")
       │
       ├── QScrollArea (album)
       │    └── QWidget (content)
       │         └── QVBoxLayout (album_layout)
       │              ├── [月标题] QLabel("📁 2026-07  月总耗时: 12h 30m")
       │              │    └── QGridLayout (自适应列数)
       │              │         ├── 作品卡片
       │              │         └── ...
       │              ├── [日标题] QLabel("  📅 2026-07-24  日总耗时: 2h 15m")
       │              │    └── QGridLayout
       │              └── ...
       │
       └── QHBoxLayout (bottom_bar)
            ├── QLabel("文件数: XX")
            ├── QLabel("总耗时: XXh XXm")
            ├── QLabel("最早: XXXX-XX-XX")
            ├── QLabel("最晚: XXXX-XX-XX")
            ├── QLabel("本月: XXh")
            └── QLabel("本年: XXh")
```

```python
def build_ui(self):
    """构建相册界面"""
    main_widget = QWidget()
    main_layout = QVBoxLayout(main_widget)

    # 顶部栏
    top_bar = QHBoxLayout()
    self.sort_combo = QComboBox()
    self.sort_combo.addItems(['按创建时间', '按修改时间'])
    refresh_btn = QPushButton('刷新')
    top_bar.addWidget(QLabel('排序:'))
    top_bar.addWidget(self.sort_combo)
    top_bar.addStretch()
    top_bar.addWidget(refresh_btn)

    # 滚动相册区
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_content = QWidget()
    self.album_layout = QVBoxLayout(scroll_content)
    scroll_area.setWidget(scroll_content)

    # 底部统计栏
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

### 5.8 渲染相册内容

```python
def render_album(self, day_groups, month_groups, stats):
    """将分组数据渲染为相册布局（自适应列数）"""
    # 清空旧内容
    while self.album_layout.count():
        item = self.album_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()

    # 计算自适应列数
    cols = self._calc_columns()

    for month_key in sorted(month_groups.keys(), reverse=True):
        month_records = month_groups[month_key]
        month_total = sum(r['editing_time'] for r in month_records)
        month_label = QLabel(f"📁 {month_key}  月总耗时: {self.format_time(month_total)}")
        month_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        self.album_layout.addWidget(month_label)

        for day_key in sorted(day_groups.keys(), reverse=True):
            if not day_key.startswith(month_key):
                continue
            day_records = day_groups[day_key]
            day_total = sum(r['editing_time'] for r in day_records)
            day_label = QLabel(f"  📅 {day_key}  日总耗时: {self.format_time(day_total)}")
            day_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 4px 16px;")
            self.album_layout.addWidget(day_label)

            grid = QGridLayout()
            for i, rec in enumerate(day_records):
                card = self.create_card(rec)
                grid.addWidget(card, i // cols, i % cols)
            self.album_layout.addLayout(grid)

    self.update_stats(stats)

def _calc_columns(self):
    """根据滚动区宽度计算每行卡片数"""
    scroll_width = self.scroll_area.viewport().width()
    card_width = 200          # 卡片宽度
    spacing = 8               # 间距
    min_cols = 1
    max_cols = max(1, (scroll_width + spacing) // (card_width + spacing))
    return max(min_cols, min(max_cols, 6))  # 1~6列范围
```

### 5.9 作品卡片

```
QWidget (card, 200x260)
  └── QVBoxLayout
       ├── QStackedLayout [StackAll 模式] ← 角标叠加
       │    ├── [底层] QLabel (thumbnail, 192x144)
       │    └── [顶层] QLabel (badge, 右上角)
       ├── QLabel (文件名, wordWrap)
       ├── QLabel (创建时间)
       └── QLabel (修改时间)
```

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

    # 缩略图 + 角标（使用 QStackedLayout 叠加）
    thumb_label = QLabel()
    thumb_label.setFixedSize(192, 144)
    thumb_label.setAlignment(Qt.AlignCenter)
    thumbnail = None
    if record['thumbnail'] and not record['thumbnail'].isNull():
        thumbnail = record['thumbnail'].scaled(
            192, 144, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        thumb_label.setPixmap(thumbnail)

    badge = QLabel(self.format_time(record['editing_time']))
    badge.setAlignment(Qt.AlignTop | Qt.AlignRight)
    badge.setStyleSheet("""
        background: rgba(0, 0, 0, 160);
        color: white;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: bold;
    """)

    stack = QStackedLayout()
    stack.setStackingMode(QStackedLayout.StackAll)
    stack.addWidget(thumb_label)
    stack.addWidget(badge)

    # 文件信息
    name_label = QLabel(record['name'])
    name_label.setWordWrap(True)
    name_label.setStyleSheet("font-size: 11px;")
    ctime_label = QLabel(f"创建: {record['created_time'].strftime('%Y-%m-%d %H:%M')}")
    ctime_label.setStyleSheet("font-size: 10px; color: #888;")
    mtime_label = QLabel(f"修改: {record['modified_time'].strftime('%Y-%m-%d %H:%M')}")
    mtime_label.setStyleSheet("font-size: 10px; color: #888;")

    layout.addLayout(stack)
    layout.addWidget(name_label)
    layout.addWidget(ctime_label)
    layout.addWidget(mtime_label)

    # 点击事件
    card.mousePressEvent = lambda e, p=record['path']: self.open_document_info(p)
    return card
```

### 5.10 点击打开文档信息

```python
def open_document_info(self, filepath):
    """使用 Krita API 打开文档信息对话框"""
    doc = Krita.instance().openDocument(filepath)
    if doc:
        action = Krita.instance().action('document_info')
        if action:
            action.trigger()
```

### 5.11 工厂注册

```python
instance = Krita.instance()
dock_widget_factory = DockWidgetFactory(
    DOCKER_ID,
    DockWidgetFactoryBase.DockPosition.DockRight,
    Krita统计插件
)
instance.addDockWidgetFactory(dock_widget_factory)
```

### 5.12 时间格式化

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

---

## 6. 性能优化

### 6.1 分片处理（替代 QThread）

Krita 5.x 中 QThread 存在 Bug #441956，使用 QTimer 分片处理避免 UI 卡顿：

```python
class ChunkedProcessor(QObject):
    """将大任务拆成小片，每片间隔 10ms 让 UI 保持响应"""

    progress_updated = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal()

    def __init__(self, items, chunk_size=10):
        super().__init__()
        self.items = items
        self.chunk_size = chunk_size
        self.index = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self._process_chunk)
        self.timer.setInterval(10)

    def start(self):
        self.index = 0
        self.timer.start()

    def _process_chunk(self):
        end = min(self.index + self.chunk_size, len(self.items))
        for i in range(self.index, end):
            self._process_item(self.items[i])
        self.index = end
        self.progress_updated.emit(self.index, len(self.items))
        if self.index >= len(self.items):
            self.timer.stop()
            self.finished.emit()

    def _process_item(self, item):
        pass  # 子类重写
```

### 6.2 懒加载（Lazy Loading）

仅在滚动到可见区域时加载卡片和缩略图，不可见卡片从布局中移除。

### 6.3 三层缓存架构

缓存路径：`~/.krita_stats_cache/`

```
L1: 内存缓存（当前会话，上限 500 条）
L2: 磁盘缓存（跨会话持久化，JSON + PNG）
L3: 源文件（.kra 内的原始数据）
```

缓存失效机制：对比文件修改时间 `st_mtime`，变化则重解析。

---

## 7. 文件监控

使用 `QFileSystemWatcher` 监控 .kra 文件变化，实现自动刷新。

```python
class KraDirectoryMonitor(QObject):
    """监控 .kra 文件新增/删除/修改"""

    kra_added = pyqtSignal(str)
    kra_removed = pyqtSignal(str)
    kra_modified = pyqtSignal(str)

    def __init__(self, root_path):
        super().__init__()
        self.root_path = root_path
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(self._on_directory_changed)
        self._file_snapshot = self._scan_kra_files()
        self._add_all_subdirs()
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._check_changes)
```

注意事项：
- QFileSystemWatcher **不递归监控子目录**，需手动递归添加
- 文件保存时可能触发多次信号，必须防抖（300ms）
- Krita 打开文件时可能锁定，需捕获异常

---

## 8. 参考项目

| 项目 | 可借鉴点 |
|------|----------|
| [loentar 统计脚本](https://gist.github.com/loentar/08913e49844d130d9d0b68c515208dec) | documentinfo.xml 解析核心逻辑 |
| [Ramen5000 预览插件](https://krita-artists.org/t/i-have-been-developing-a-new-plugin-for-krita-and-this-is-what-i-have-so-far/68371) | 目录扫描 + 缩略图预览 + 点击打开交互 |
| [Grum999 Photobash 插件](https://github.com/veryprofessionaldodo/Krita-Photobash-Images-Plugin) | 缩略图缓存机制（10000文件约1.2秒加载） |
| [KnowZero 调试工具](https://github.com/KnowZero/Krita-PythonPluginDeveloperTools) | Krita 内查看 Python API 对象树 |

---

## 9. 开发与调试

### 9.1 启用插件

1. 将 `krita统计插件/` 文件夹和 `krita统计插件.desktop` 放入 Krita 的 `pykrita/` 目录
2. 启动 Krita → **设置 → 配置 Krita → Python 插件管理器**
3. 勾选 **Krita统计插件** → 应用 → 重启 Krita
4. 在 **设置 → 面板** 中找到并启用

### 9.2 调试技巧

- **Scripter**（工具 → 脚本 → Scripter）：快速测试代码片段
- **Print 输出**：`print()` 输出到控制台（Windows 需查看 Krita 的 stderr）
- **KnowZero 调试工具**：安装后可在 Krita 内探索 API 对象树
- **Action 探索**：在 Scripter 中运行 `for a in Krita.instance().actions(): print([a.objectName(), a.text()])`

### 9.3 关键文档资源

| 资源 | 链接 | 说明 |
|------|------|------|
| Grum999 Python API 文档 | https://apidoc.krita.maou-maou.fr/ | 每日更新，Python 语法展示 |
| 官方 C++ API | https://api.kde.org/legacy/krita/html/index.html | LibKis 底层参考 |
| 官方用户手册 - 脚本篇 | https://docs.krita.org/en/user_manual/python_scripting.html | 入门教程 |
| Krita Scripting School | https://scripting.krita.org/ | 系统课程 + Action 字典 |
| Krita Artists 插件开发 | https://krita-artists.org/c/develop/plugins-development/16 | 社区讨论 |
| KRA 格式文档 | https://github.com/2shady4u/godot-kra-psd-importer/blob/master/docs/KRA_FORMAT.md | 最完整格式说明 |
| PyQt5 官方文档 | https://www.riverbankcomputing.com/static/Docs/PyQt5/ | Qt 绑定文档 |

---

## 10. 开发规划

### 10.1 版本里程碑

```
v0.1 — 原型阶段
  ├── 扫描 Krita 文档管理路径下的 .kra 文件
  ├── 解析编辑时间和缩略图
  ├── 基础 UI 框架（三栏布局）
  └── 按天/月分组展示

v0.2 — 交互优化
  ├── 点击卡片打开文档信息
  ├── 排序切换（创建时间 / 修改时间）
  ├── 刷新按钮
  └── 自适应列数

v0.3 — 性能增强
  ├── 分片加载（避免 UI 卡顿）
  ├── 缩略图懒加载
  └── 三层缓存（内存 + 磁盘）

v0.4 — 功能完善
  ├── 文件监控自动刷新（QFileSystemWatcher）
  ├── 年月统计汇总
  └── 加载状态指示

v1.0 — 稳定版
  ├── 错误处理完善
  ├── 边缘情况处理
  ├── 性能优化
  └── 用户文档
```

### 10.2 任务分解

#### Phase 1 — 核心数据层（v0.1）

- [ ] `scan_kra_files()` — 递归扫描目录
- [ ] `parse_kra_file()` — 解析单文件（编辑时间 + 缩略图）
- [ ] `process_data()` — 排序和分组
- [ ] `format_time()` — 时间格式化
- [ ] 获取 Krita 文档管理路径（API 调研）

#### Phase 2 — UI 层（v0.1 ~ v0.2）

- [ ] `build_ui()` — 搭建三栏布局
- [ ] `render_album()` — 渲染月/日分组标题
- [ ] `create_card()` — 作品卡片（缩略图 + 角标 + 信息）
- [ ] `open_document_info()` — 点击打开文档信息
- [ ] `_calc_columns()` — 自适应列数
- [ ] 绑定排序切换和刷新

#### Phase 3 — 性能优化（v0.3）

- [ ] `ChunkedProcessor` — 分片加载
- [ ] `ThumbnailCache` — 三层缓存
- [ ] 懒加载（滚动时按需加载）
- [ ] 加载进度指示

#### Phase 4 — 高级功能（v0.4）

- [ ] `KraDirectoryMonitor` — 文件监控
- [ ] 自动刷新逻辑（防抖）
- [ ] 年月统计汇总

#### Phase 5 — 完善（v1.0）

- [ ] 错误处理和用户提示
- [ ] 空状态 / 加载状态 UI
- [ ] 设置持久化（保存排序偏好等）
- [ ] 性能基准测试

### 10.3 技术决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 插件类型 | Extension / DockWidget | DockWidget | 需要独立 UI 空间 |
| 扫描方式 | os.walk / glob | os.walk | 递归支持好 |
| 默认目录 | Krita API / 手动选择 / 文档目录 | Krita 文档管理路径 | 用户需求 |
| 列数策略 | 固定4列 / 自适应 | 自适应 | 充分利用空间 |
| 角标方案 | QStackedLayout / paintEvent | QStackedLayout（初期） | 实现简单 |
| 并发方案 | QThread / QTimer 分片 | QTimer 分片 | Krita 5 QThread Bug |
| 缓存位置 | 用户目录 / 系统临时目录 | ~/.krita_stats_cache/ | 持久化不丢失 |
| 排序方式 | created / modified | 两种都支持 | 用户需求明确 |

---

## 11. 风险与应对

| 风险 | 影响 | 应对方案 |
|------|------|----------|
| Krita 5 QThread Bug | 并发处理受限 | 使用 QTimer 分片方案 |
| .kra 文件被 Krita 锁定 | 解析失败 | 捕获异常，跳过该文件 |
| 大目录（10000+ 文件） | 首次加载慢 | 分片 + 缓存 + 进度提示 |
| 中文路径/文件名 | 编码问题 | Python 原生 unicode 支持 |
| 不同 Krita 版本 API 差异 | 兼容性问题 | 参考 apidoc 版本标注 |

---

## 12. 已知问题

| 问题 | 说明 |
|------|------|
| 缩略图提取 | 部分旧版 .kra 可能不包含 `preview.png`，需回退到 `mergedimage.png` |
| 创建时间 | `os.stat().st_ctime` 在 Windows 上为创建时间，在 Linux/macOS 上为元数据变更时间 |
| 大目录性能 | 首次扫描大量 .kra 文件可能较慢，建议添加加载动画或后台线程 |
| 文件锁定 | Krita 中已打开的文件可能被锁定，`zipfile` 读取时应捕获异常 |

---

## 13. 后续扩展建议

- [ ] **图表统计**：集成 Matplotlib 或 PyQtChart 显示月度趋势图
- [ ] **标签/搜索**：支持按文件名搜索或按标签筛选
- [ ] **导出报告**：将统计结果导出为 CSV 或 HTML 报告
- [ ] **多语言**：支持中/英文界面切换
- [ ] **缩略图缓存**：缓存解析结果到本地 JSON 文件，避免重复解压
