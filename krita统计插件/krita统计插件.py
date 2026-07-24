from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import zipfile
import xml.etree.ElementTree as ET
import os
import datetime

DOCKER_NAME = 'Krita统计插件'
DOCKER_ID = 'pykrita_krita统计插件'


class Krita统计插件(DockWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(DOCKER_NAME)
        self.records = []
        self.year_groups = {}
        self.month_groups = {}
        self.day_groups = {}
        self.stats = {}
        self.scan_path = self._get_default_scan_path()
        self._build_ui()
        QTimer.singleShot(100, self.refresh_data)

    def canvasChanged(self, canvas):
        pass

    def _get_default_scan_path(self):
        return QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)

    def _update_path_display(self):
        text = self.scan_path
        if len(text) > 35:
            text = "..." + text[-32:]
        self.path_label.setText(text)
        self.path_label.setToolTip(self.scan_path)

    def _browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择 .kra 文件目录", self.scan_path)
        if dir_path:
            self.scan_path = dir_path
            self._update_path_display()
            self.refresh_data()

    def scan_kra_files(self, root_dir):
        kra_files = []
        for root, dirs, files in os.walk(root_dir):
            for f in files:
                if f.lower().endswith('.kra'):
                    kra_files.append(os.path.join(root, f))
        return kra_files

    def parse_kra_file(self, filepath):
        result = {
            'path': filepath,
            'name': os.path.basename(filepath),
            'editing_time': 0,
            'created_time': None,
            'modified_time': None,
            'thumbnail': None,
        }
        try:
            stat = os.stat(filepath)
            result['created_time'] = datetime.datetime.fromtimestamp(
                stat.st_ctime)
            result['modified_time'] = datetime.datetime.fromtimestamp(
                stat.st_mtime)
        except OSError:
            return result

        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                if 'documentinfo.xml' in zf.namelist():
                    xml_data = zf.read('documentinfo.xml')
                    root = ET.fromstring(xml_data)
                    time_elem = root.find('.//editing-time')
                    if time_elem is not None and time_elem.text:
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

    def process_data(self, records, sort_by='created'):
        key = 'created_time' if sort_by == 'created' else 'modified_time'
        records.sort(key=lambda r: r[key] or datetime.datetime.min,
                     reverse=True)

        year_groups = {}
        month_groups = {}
        day_groups = {}
        for rec in records:
            dt = rec[key]
            if dt is None:
                continue
            year_key = dt.strftime('%Y')
            month_key = dt.strftime('%Y-%m')
            day_key = dt.strftime('%Y-%m-%d')
            if year_key not in year_groups:
                year_groups[year_key] = []
            year_groups[year_key].append(rec)
            if month_key not in month_groups:
                month_groups[month_key] = []
            month_groups[month_key].append(rec)
            if day_key not in day_groups:
                day_groups[day_key] = []
            day_groups[day_key].append(rec)

        now = datetime.datetime.now()
        month_total = sum(
            r['editing_time'] for r in records
            if r['created_time'] and r['created_time'].strftime('%Y-%m')
            == now.strftime('%Y-%m'))
        year_total = sum(
            r['editing_time'] for r in records
            if r['created_time'] and r['created_time'].strftime('%Y')
            == now.strftime('%Y'))

        stats = {
            'total_count': len(records),
            'total_time': sum(r['editing_time'] for r in records),
            'month_time': month_total,
            'year_time': year_total,
            'earliest_created': min(
                (r['created_time'] for r in records if r['created_time']),
                default=None),
            'latest_modified': max(
                (r['modified_time'] for r in records if r['modified_time']),
                default=None),
        }

        return year_groups, month_groups, day_groups, stats

    @staticmethod
    def format_time(seconds):
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

    def _build_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        top_bar = QHBoxLayout()
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(['按创建时间', '按修改时间'])
        browse_btn = QPushButton('📁 浏览')
        browse_btn.clicked.connect(self._browse_directory)
        self.path_label = QLabel('')
        self.path_label.setStyleSheet("font-size: 10px; color: #888;")
        refresh_btn = QPushButton('刷新')
        refresh_btn.clicked.connect(self.refresh_data)
        top_bar.addWidget(QLabel('排序:'))
        top_bar.addWidget(self.sort_combo)
        top_bar.addWidget(browse_btn)
        top_bar.addStretch()
        top_bar.addWidget(self.path_label)
        top_bar.addWidget(refresh_btn)

        self.scroll_area = AlbumScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        self.album_layout = QVBoxLayout(scroll_content)
        self.album_layout.setSpacing(2)
        self.album_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll_area.setWidget(scroll_content)
        self.scroll_area.resize_callback = self._on_album_resize

        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(8)
        self.stats_total_count = QLabel('文件: 0')
        self.stats_total_time = QLabel('总耗时: 0s')
        self.stats_earliest = QLabel('最早: -')
        self.stats_latest = QLabel('最晚: -')
        self.stats_month = QLabel('本月: 0s')
        self.stats_year = QLabel('本年: 0s')
        for w in [self.stats_total_count, self.stats_total_time,
                  self.stats_earliest, self.stats_latest,
                  self.stats_month, self.stats_year]:
            w.setStyleSheet("font-size: 13px;")
            bottom_bar.addWidget(w)

        main_layout.addLayout(top_bar)
        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(bottom_bar)
        self.setWidget(main_widget)

        self.sort_combo.currentIndexChanged.connect(self.refresh_data)
        self._update_path_display()

    def _on_album_resize(self):
        if self.records and self.stats:
            self.render_album(self.year_groups, self.month_groups, self.day_groups, self.stats)

    def render_album(self, year_groups, month_groups, day_groups, stats):
        self._clear_layout(self.album_layout)

        cols = self._calc_columns()

        for year_key in sorted(year_groups.keys(), reverse=True):
            year_records = year_groups[year_key]
            year_total = sum(r['editing_time'] for r in year_records)
            year_label = QLabel(
                f"📅 {year_key}  年总耗时: {self.format_time(year_total)}")
            year_label.setStyleSheet(
                "font-size: 17px; font-weight: bold; padding: 8px 4px 4px 4px;"
                " color: #2c3e50;")
            self.album_layout.addWidget(year_label)

            for month_key in sorted(month_groups.keys(), reverse=True):
                if not month_key.startswith(year_key):
                    continue
                month_records = month_groups[month_key]
                month_total = sum(r['editing_time'] for r in month_records)
                month_label = QLabel(
                    f"  📁 {month_key}  月总耗时: {self.format_time(month_total)}")
                month_label.setStyleSheet(
                    "font-size: 15px; font-weight: bold; padding: 4px 4px 2px 16px;")
                self.album_layout.addWidget(month_label)

                for day_key in sorted(day_groups.keys(), reverse=True):
                    if not day_key.startswith(month_key):
                        continue
                    day_records = day_groups[day_key]
                    day_total = sum(r['editing_time'] for r in day_records)
                    day_label = QLabel(
                        f"    📄 {day_key}  日总耗时: {self.format_time(day_total)}")
                    day_label.setStyleSheet(
                        "font-size: 13px; font-weight: bold; padding: 2px 4px 2px 28px;")
                    self.album_layout.addWidget(day_label)

                    if not day_records:
                        continue
                    grid = QGridLayout()
                    grid.setSpacing(6)
                    for i, rec in enumerate(day_records):
                        card = self.create_card(rec)
                        grid.addWidget(card, i // cols, i % cols)
                    self.album_layout.addLayout(grid)

        self.album_layout.addStretch()
        self.update_stats(stats)

    def _calc_columns(self):
        scroll_width = self.scroll_area.viewport().width()
        card_width = 208
        spacing = 6
        effective = scroll_width + spacing
        cols = max(1, effective // (card_width + spacing))
        return min(cols, 6)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                Krita统计插件._clear_layout(item.layout())

    def create_card(self, record):
        card = QWidget()
        card.setFixedSize(200, 250)
        card.setStyleSheet("""
            QWidget {
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                background: #ffffff;
            }
            QWidget:hover {
                border-color: #4a9eff;
                background: #f0f7ff;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        thumb_label = QLabel()
        thumb_label.setFixedSize(192, 140)
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("border: none; background: #f5f5f5;")
        if record['thumbnail'] and not record['thumbnail'].isNull():
            thumb = record['thumbnail'].scaled(
                192, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            thumb_label.setPixmap(thumb)

        badge = QLabel(self.format_time(record['editing_time']))
        badge.setAlignment(Qt.AlignTop | Qt.AlignRight)
        badge.setStyleSheet("""
            background: rgba(0, 0, 0, 160);
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            border: none;
        """)

        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.addWidget(thumb_label)
        stack.addWidget(badge)

        name_label = QLabel(record['name'])
        name_label.setWordWrap(True)
        name_label.setStyleSheet("font-size: 11px; color: #333; border: none;")

        ctime_str = (record['created_time'].strftime('%Y-%m-%d %H:%M')
                     if record['created_time'] else "")
        mtime_str = (record['modified_time'].strftime('%Y-%m-%d %H:%M')
                     if record['modified_time'] else "")

        ctime_label = QLabel(f"创建: {ctime_str}")
        ctime_label.setStyleSheet("font-size: 11px; color: #888; border: none;")
        mtime_label = QLabel(f"修改: {mtime_str}")
        mtime_label.setStyleSheet("font-size: 11px; color: #888; border: none;")

        layout.addLayout(stack)
        layout.addWidget(name_label)
        layout.addWidget(ctime_label)
        layout.addWidget(mtime_label)

        card.mousePressEvent = lambda e, p=record['path']: (
            self.open_document_info(p))

        return card

    def open_document_info(self, filepath):
        try:
            doc = Krita.instance().openDocument(filepath)
            if doc:
                action = Krita.instance().action('document_info')
                if action:
                    action.trigger()
        except Exception as e:
            QMessageBox.warning(
                self, "打开失败", f"无法打开文档信息:\n{filepath}\n\n{e}")

    def refresh_data(self):
        self.stats_total_count.setText("扫描中...")
        QApplication.processEvents()

        print(f"[Krita统计] 扫描路径: {self.scan_path}")
        kra_files = self.scan_kra_files(self.scan_path)
        print(f"[Krita统计] 找到 .kra 文件: {len(kra_files)} 个")

        records = []
        for fp in kra_files:
            rec = self.parse_kra_file(fp)
            records.append(rec)

        sort_by = ('created' if self.sort_combo.currentIndex() == 0
                   else 'modified')
        year_groups, month_groups, day_groups, stats = self.process_data(
            records, sort_by)

        self.records = records
        self.year_groups = year_groups
        self.month_groups = month_groups
        self.day_groups = day_groups
        self.stats = stats

        self.render_album(year_groups, month_groups, day_groups, stats)

    def update_stats(self, stats):
        self.stats_total_count.setText(f"文件: {stats['total_count']}")
        self.stats_total_time.setText(
            f"总耗时: {self.format_time(stats['total_time'])}")
        self.stats_earliest.setText(
            f"最早: {stats['earliest_created'].strftime('%Y-%m-%d')}"
            if stats['earliest_created'] else "最早: -")
        self.stats_latest.setText(
            f"最晚: {stats['latest_modified'].strftime('%Y-%m-%d')}"
            if stats['latest_modified'] else "最晚: -")
        self.stats_month.setText(
            f"本月: {self.format_time(stats['month_time'])}")
        self.stats_year.setText(
            f"本年: {self.format_time(stats['year_time'])}")


class AlbumScrollArea(QScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize_callback = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.resize_callback:
            self.resize_callback()


instance = Krita.instance()
dock_widget_factory = DockWidgetFactory(
    DOCKER_ID,
    DockWidgetFactoryBase.DockPosition.DockRight,
    Krita统计插件
)
instance.addDockWidgetFactory(dock_widget_factory)
