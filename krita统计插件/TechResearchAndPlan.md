# Krita统计插件 - 技术调研与开发规划

## 1. API 深度调研

### 1.1 DockWidget 生命周期

```
Krita 启动
  → 加载 pykrita 目录插件
    → 执行模块顶层代码（工厂注册）
      → DockWidgetFactory 注册到 Krita 实例
        → 用户打开面板时创建实例
          → __init__() 初始化 UI
            → 用户切换文档时触发 canvasChanged()
```

关键方法：

| 方法 | 说明 |
|------|------|
| `__init__()` | 必须调用 `super().__init__()`，否则 C++ 底层对象无法正确初始化 |
| `canvasChanged(canvas)` | 当前画布切换时触发，每个窗口仅一个 docker 实例 |
| `canvas()` | 获取当前关联的画布对象（Krita 4.0+） |

注意事项：
- 每个主窗口**只会创建一个 docker 实例**，不是每个画布一个
- `canvasChanged()` 在用户切换文档/视图时调用

### 1.2 Action 系统

```python
# 获取所有 Action 列表（用于探索可用动作）
for action in Krita.instance().actions():
    print([action.objectName(), action.text()])

# 触发动作
Krita.instance().action('document_info').trigger()
```

本项目相关 Action：

| Action ID | 功能 | 用途 |
|-----------|------|------|
| `document_info` | 文档信息对话框 | 点击卡片打开详情 |
| `python_scripter` | 打开 Scripter | 调试辅助 |

### 1.3 Document 类可用方法

| 方法 | 返回值 | 说明 | 版本 |
|------|--------|------|------|
| `documentInfo()` | `str` | 获取文档信息 XML 字符串 | 4.0.0 |
| `fileName()` | `str` | 文件路径 | 4.0.0 |
| `name()` | `str` | 文档名称 | 4.0.0 |
| `width()` / `height()` | `int` | 画布尺寸 | 4.0.0 |
| `modified()` | `bool` | 是否有未保存修改 | 4.1.2 |
| `projection(x,y,w,h)` | `QImage` | 获取渲染后图像 | 4.0.0 |
| `activeNode()` | `Node` | 获取当前活跃图层 | 4.0.0 |
| `setBatchmode(bool)` | `void` | 设置批量模式（无弹窗） | 4.0.0 |

### 1.4 Krita 内置文档信息对话框

触发方式：`Krita.instance().action('document_info').trigger()`

对话框包含两个标签页：
- **关于**：标题、描述、主题、关键词、创建者、编辑时间等
- **作者**：姓名、邮件、公司等

---

## 2. .kra 文件格式深度解析

### 2.1 完整目录结构

```
MyDrawing.kra (ZIP 压缩包)
├── mimetype                    # "application/x-kra"（固定）
├── documentinfo.xml            # 文档元信息（编辑时间、作者等）
├── maindoc.xml                 # 文档主结构（图层树、画布尺寸等）
├── preview.png                 # 预览缩略图（小尺寸）
├── mergedimage.png             # 全尺寸合并预览图
└── MyDrawing/                  # 以文档名命名的子目录
    ├── annotations/            # 注释数据
    ├── layers/                 # 图层数据
    │   ├── layer0              # 像素数据（LZF 压缩）
    │   ├── layer0.defaultpixel # 默认像素值（4字节 RGBA）
    │   ├── layer0.icc          # ICC 色彩配置文件
    │   ├── layer0.keyframes.xml # 动画关键帧（仅动画图层）
    │   ├── layer1
    │   └── ...
    └── ...
```

### 2.2 documentinfo.xml 完整结构

```xml
<document-info>
  <about>
    <title>文档标题</title>
    <description>描述</description>
    <subject>主题</subject>
    <abstract><![CDATA[]]></abstract>
    <keyword>关键词</keyword>
    <initial-creator>创建者</initial-creator>
    <editing-cycles>1</editing-cycles>     <!-- 编辑循环次数 -->
    <editing-time>35</editing-time>        <!-- ★ 总编辑时间（秒） -->
    <date>2017-02-27T20:15:09</date>       <!-- 最后保存时间 -->
    <creation-date>2017-02-27T20:14:33</creation-date>  <!-- 创建时间 -->
    <language></language>
  </about>
  <author>
    <full-name>作者名</full-name>
    <email>邮箱</email>
    <company>公司</company>
    <!-- ... 更多作者字段 -->
  </author>
</document-info>
```

### 2.3 preview.png vs mergedimage.png

| 特性 | preview.png | mergedimage.png |
|------|-------------|-----------------|
| 尺寸 | 小（缩略图） | 全尺寸（画布原始分辨率） |
| 用途 | 快速预览 | 完整预览（第三方软件集成） |
| 保存速度 | 快 | 慢 |
| 缺失情况 | 旧版可能没有 | .krz 格式没有 |
| 优先级 | 首选 | 回退方案 |

### 2.4 maindoc.xml 关键信息

```xml
<IMAGE width="256" height="128" colorspacename="RGBA" name="KRAExample">
  <layers>
    <layer filename="layer0" nodetype="paintlayer" name="图层1"
           visible="1" locked="0" opacity="255" compositeop="normal"/>
  </layers>
</IMAGE>
```

---

## 3. PyQt5 相册 UI 实现方案

### 3.1 整体布局架构

```
DockWidget
  └── QWidget (main)
       ├── QHBoxLayout (top_bar)
       │    ├── QLabel("排序:")
       │    ├── QComboBox [按创建时间, 按修改时间]
       │    ├── QSpacerItem (stretch)
       │    └── QPushButton("刷新")
       │
       ├── QScrollArea (album)  ← 可滚动
       │    └── QWidget (content)
       │         └── QVBoxLayout (album_layout)
       │              ├── QLabel("📁 2026-07  月总耗时: 12h 30m")  [加粗标题]
       │              │    └── QGridLayout (4列卡片网格)
       │              │         ├── 作品卡片1
       │              │         ├── 作品卡片2
       │              │         └── ...
       │              ├── QLabel("  📅 2026-07-24  日总耗时: 2h 15m") [缩进标题]
       │              │    └── QGridLayout
       │              └── ...
       │
       └── QHBoxLayout (bottom_bar)
            ├── QLabel("文件数: XX")
            ├── QLabel("总耗时: XXh XXm")
            ├── QLabel("最早: XXXX-XX-XX")
            ├── QLabel("最晚: XXXX-XX-XX")
            ├── QLabel("本月: XXh")
            ├── QLabel("本年: XXh")
            └── QLabel("总计: XXh")
```

### 3.2 作品卡片结构

```
QWidget (card, 200x260)
  └── QVBoxLayout
       ├── QStackedLayout [StackAll 模式] ← 实现角标叠加
       │    ├── [底层] QLabel (thumbnail, 192x144)
       │    └── [顶层] QLabel (badge, 右上角)
       ├── QLabel (文件名, wordWrap)
       ├── QLabel (创建时间)
       └── QLabel (修改时间)
```

两种角标实现方案对比：

| 方案 | 优点 | 缺点 |
|------|------|------|
| QStackedLayout + StackAll | 简单，纯布局方案 | 需要调整对齐 |
| paintEvent 自定义绘制 | 更灵活，性能更好 | 需要重写绘制逻辑 |

推荐方案：先用 QStackedLayout，后续优化时改用 paintEvent。

### 3.3 性能优化策略

#### 策略一：分片处理（替代 QThread）

Krita 5.x 中 QThread 存在 Bug #441956，推荐用 QTimer 分片：

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
        pass  # 子类实现
```

#### 策略二：懒加载（Lazy Loading）

仅在滚动到可见区域时加载卡片和缩略图，不可见的卡片从布局中移除。

#### 策略三：三层缓存架构

```
L1: 内存缓存（当前会话，上限 500 条）
L2: 磁盘缓存（跨会话持久化，JSON + PNG）
L3: 源文件（.kra 内的原始数据）
```

缓存失效机制：对比文件修改时间 `st_mtime`

### 3.4 文件监控

```python
class KraDirectoryMonitor(QObject):
    """监控 .kra 文件新增/删除/修改"""

    kra_added = pyqtSignal(str)
    kra_removed = pyqtSignal(str)
    kra_modified = pyqtSignal(str)

    def __init__(self, root_path):
        # 使用 QFileSystemWatcher + 目录变化信号
        # 防抖定时器 300ms
        # 初始化文件快照，对比变化
```

注意事项：
- QFileSystemWatcher **不递归监控子目录**，需手动添加
- 文件保存时可能触发多次信号，必须防抖
- Krita 打开文件时可能锁定，需捕获异常

---

## 4. 参考项目研究

### 4.1 loentar 统计脚本

- **来源**：https://gist.github.com/loentar/08913e49844d130d9d0b68c515208dec
- **功能**：计算目录中所有 .kra 文件的总绘画时间
- **可借鉴**：documentinfo.xml 解析核心逻辑可直接复用
- **差异**：本项目需要 UI 展示，不是命令行脚本

### 4.2 Ramen5000 预览插件

- **来源**：Krita Artists 论坛
- **可借鉴**：目录选择 + 缩略图预览 + 点击打开的交互模式
- **差异**：本项目需要相册布局和时间统计，而非简单预览

### 4.3 KnowZero 调试工具

- **来源**：https://github.com/KnowZero/Krita-PythonPluginDeveloperTools
- **功能**：在 Krita 内查看 Python API 对象树
- **用途**：开发调试时探索 API 属性

### 4.4 Grum999 Photobash 插件

- **来源**：https://github.com/veryprofessionaldodo/Krita-Photobash-Images-Plugin
- **可借鉴**：缩略图缓存机制（"加载10000个文件的缩略图到树形视图只需约1.2秒"）
- **技术点**：JSON 元数据缓存 + PNG 缩略图缓存 + 增量更新

---

## 5. 关键 API 参考

### 5.1 文档资源

| 资源 | 链接 | 说明 |
|------|------|------|
| Grum999 Python API 文档 | https://apidoc.krita.maou-maou.fr/ | 每日更新，Python 语法展示 |
| 官方 C++ API（Doxygen） | https://api.kde.org/legacy/krita/html/index.html | LibKis 底层参考 |
| 官方用户手册 - 脚本篇 | https://docs.krita.org/en/user_manual/python_scripting.html | 入门教程 |
| Krita Scripting School | https://scripting.krita.org/ | 系统课程 + Action 字典 |
| Krita Artists 插件开发板块 | https://krita-artists.org/c/develop/plugins-development/16 | 社区讨论 |
| KRA 格式文档 | https://github.com/2shady4u/godot-kra-psd-importer/blob/master/docs/KRA_FORMAT.md | 最完整格式说明 |

### 5.2 PyQt5 参考

- 官方文档：https://www.riverbankcomputing.com/static/Docs/PyQt5/
- 布局教程：https://www.pythonguis.com/faq/pyqt5-gridlayout-issues-arranging-stuffs-non-format/

---

## 6. 开发规划

### 6.1 版本里程碑

```
v0.1 原型阶段
  ├── 扫描指定目录下的 .kra 文件
  ├── 解析编辑时间和缩略图
  ├── 基础 UI 框架（顶部栏 + 滚动区 + 底部栏）
  └── 按天/月分组展示

v0.2 交互优化
  ├── 点击卡片打开文档信息
  ├── 排序切换（创建时间 / 修改时间）
  ├── 刷新按钮
  └── 耗时格式化显示

v0.3 性能增强
  ├── 分片加载（避免 UI 卡顿）
  ├── 缩略图懒加载
  └── 缩略图缓存（内存 + 磁盘）

v0.4 功能完善
  ├── 自定义目录选择
  ├── 文件监控自动刷新（QFileSystemWatcher）
  ├── 年月统计汇总
  └── 加载动画

v1.0 稳定版
  ├── 错误处理完善
  ├── 边缘情况处理
  ├── 性能优化
  └── 用户文档
```

### 6.2 任务分解

#### Phase 1 — 核心数据层（对应 v0.1）

- [ ] 实现 `scan_kra_files()` 递归扫描目录
- [ ] 实现 `parse_kra_file()` 解析单文件（编辑时间 + 缩略图）
- [ ] 实现 `process_data()` 按时间排序和分组
- [ ] 实现 `format_time()` 时间格式化
- [ ] 单元测试：mock .kra 文件测试解析逻辑

#### Phase 2 — UI 层（对应 v0.1 ~ v0.2）

- [ ] 实现 `build_ui()` 搭建三栏布局
- [ ] 实现 `render_album()` 渲染月/日分组标题
- [ ] 实现 `create_card()` 作品卡片（缩略图 + 角标 + 信息）
- [ ] 实现 `open_document_info()` 点击打开文档信息
- [ ] 绑定排序切换逻辑
- [ ] 绑定刷新按钮逻辑

#### Phase 3 — 性能优化（对应 v0.3）

- [ ] 实现 `ChunkedProcessor` 分片加载
- [ ] 实现 `ThumbnailCache` 三层缓存
- [ ] 实现懒加载（滚动时按需加载卡片）
- [ ] 添加加载进度指示

#### Phase 4 — 高级功能（对应 v0.4）

- [ ] 添加目录选择对话框（QFileDialog）
- [ ] 实现 `KraDirectoryMonitor` 文件监控
- [ ] 实现自动刷新逻辑（防抖）
- [ ] 添加年月统计汇总

#### Phase 5 — 完善（对应 v1.0）

- [ ] 错误处理和用户提示
- [ ] 空状态 / 加载状态 UI
- [ ] 设置持久化（保存上次扫描目录）
- [ ] 性能基准测试

### 6.3 技术决策记录

| 决策 | 选项 | 选择 | 理由 |
|------|------|------|------|
| 扫描方式 | os.walk / glob | os.walk | 递归支持好，可扩展 |
| 角标实现 | QStackedLayout / paintEvent | QStackedLayout（初期） | 实现简单，后期可优化 |
| 并发方案 | QThread / QTimer 分片 | QTimer 分片 | Krita 5 QThread 有 Bug |
| 缓存路径 | 用户目录 / 插件目录 | ~/.krita_stats_cache/ | 与 Krita 配置一致 |
| 排序方式 | created / modified | 两种都支持（下拉切换） | 用户需求明确 |

---

## 7. 风险与应对

| 风险 | 影响 | 应对方案 |
|------|------|----------|
| Krita 5 QThread 不可用 | 并发处理受限 | 使用 QTimer 分片方案 |
| .kra 文件被锁定 | 解析失败 | 捕获异常，跳过 |
| 大目录（10000+ 文件） | 首次加载慢 | 分片 + 缓存 + 进度提示 |
| 中文路径/文件名 | 编码问题 | 使用 Python 原生 unicode 支持 |
| 不同 Krita 版本 API 差异 | 兼容性问题 | 参考 apidoc 的版本标注 |
