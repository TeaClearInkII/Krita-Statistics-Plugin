from krita import DockWidget, DockWidgetFactory, DockWidgetFactoryBase, Krita
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
import zipfile
import xml.etree.ElementTree as ET
import os
import datetime
import re
import hashlib
import json
import base64

DOCKER_NAME = 'Krita统计插件'
DOCKER_ID = 'pykrita_krita统计插件'
SETTINGS_GROUP = 'krita统计插件'


def _find_local(parent, local_tag):
    if parent is None:
        return None
    for child in parent.iter():
        tag = child.tag
        if tag is not None and '}' in tag:
            tag = tag.split('}', 1)[1]
        if tag == local_tag:
            return child
    return None


def _parse_iso_duration(text):
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        pass
    m = re.match(r'PT?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', text)
    if m:
        h, mi, s = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + int(s or 0)
    return 0


def _extract_email(root):
    email_elem = _find_local(root, 'email')
    if email_elem is not None and email_elem.text:
        return email_elem.text.strip()
    for child in root.iter():
        tag = child.tag
        if tag is not None and '}' in tag:
            tag = tag.split('}', 1)[1]
        if tag == 'contact' and child.get('type', '').lower() == 'email':
            if child.text:
                return child.text.strip()
    return ''


def _extract_author_contacts(root):
    result = {}
    author = _find_local(root, 'author')
    if author is None:
        return result
    direct_map = {
        'company': '公司', 'position': '职位',
        'author-title': '头衔', 'initial': '缩写',
        'creator-first-name': '名', 'creator-last-name': '姓',
    }
    for tag_name, label in direct_map.items():
        elem = _find_local(author, tag_name)
        if elem is not None and elem.text:
            result[label] = elem.text.strip()

    contact_label_map = {
        'homepage': '主页', 'telephone': '电话',
        'telephone-work': '工作电话', 'fax': '传真',
        'country': '国家', 'city': '城市',
        'street': '街道', 'postal-code': '邮政编码',
        'email': '邮箱',
    }
    for child in author.iter():
        tag = child.tag
        if tag is not None and '}' in tag:
            tag = tag.split('}', 1)[1]
        if tag == 'contact':
            ctype = child.get('type', '').lower()
            if ctype in contact_label_map:
                if child.text and child.text.strip():
                    result[contact_label_map[ctype]] = child.text.strip()

    return result


def _gamma_correct_qimage(qimage, gamma=2.2):
    if qimage.isNull():
        return qimage
    img = qimage.convertToFormat(QImage.Format_ARGB32)
    if img.isNull():
        return qimage
    w, h = img.width(), img.height()
    table = [int(255.0 * (i / 255.0) ** (1.0 / gamma) + 0.5)
             for i in range(256)]
    for y in range(h):
        for x in range(w):
            c = img.pixel(x, y)
            r, g, b, a = qRed(c), qGreen(c), qBlue(c), qAlpha(c)
            img.setPixel(x, y, qRgba(table[r], table[g], table[b], a))
    return img


class ScanWorker(QObject):
    finished = pyqtSignal(object)
    progress = pyqtSignal(int, int)

    def __init__(self, scan_path):
        super().__init__()
        self.scan_path = scan_path

    def run(self):
        kra_files = []
        for root, dirs, files in os.walk(self.scan_path):
            for f in files:
                if f.lower().endswith('.kra'):
                    kra_files.append(os.path.join(root, f))

        records = []
        total = len(kra_files)
        for i, fp in enumerate(kra_files):
            if QThread.currentThread().isInterruptionRequested():
                break
            rec = self._parse_kra_file(fp)
            records.append(rec)
            self.progress.emit(i + 1, total)

        self.finished.emit(records)

    @staticmethod
    def _parse_kra_file(filepath):
        result = {
            'path': filepath,
            'name': os.path.basename(filepath),
            'editing_time': 0,
            'editing_cycles': 0,
            'created_time': None,
            'modified_time': None,
            'thumbnail_bytes': None,
            'title': '',
            'creator': '',
            'author_name': '',
            'author_email': '',
            'author_contact': {},
            'canvas_width': 0,
            'canvas_height': 0,
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
                names = zf.namelist()

                if 'documentinfo.xml' in names:
                    xml_data = zf.read('documentinfo.xml')
                    root = ET.fromstring(xml_data)

                    time_elem = _find_local(root, 'editing-time')
                    if time_elem is not None and time_elem.text:
                        result['editing_time'] = _parse_iso_duration(
                            time_elem.text.strip())

                    cycles_elem = _find_local(root, 'editing-cycles')
                    if cycles_elem is not None and cycles_elem.text:
                        result['editing_cycles'] = int(
                            cycles_elem.text.strip())

                    title_elem = _find_local(root, 'title')
                    if title_elem is not None and title_elem.text:
                        result['title'] = title_elem.text.strip()

                    creator_elem = _find_local(root, 'initial-creator')
                    if creator_elem is not None and creator_elem.text:
                        result['creator'] = creator_elem.text.strip()

                    name_elem = _find_local(root, 'full-name')
                    if name_elem is not None and name_elem.text:
                        result['author_name'] = name_elem.text.strip()

                    result['author_email'] = _extract_email(root)
                    result['author_contact'] = _extract_author_contacts(root)

                if 'maindoc.xml' in names:
                    xml_data = zf.read('maindoc.xml')
                    root = ET.fromstring(xml_data)
                    img = _find_local(root, 'IMAGE')
                    if img is not None:
                        w = img.get('width', '0')
                        h = img.get('height', '0')
                        result['canvas_width'] = int(w) if w.isdigit() else 0
                        result['canvas_height'] = int(h) if h.isdigit() else 0

                for thumb_name in ['preview.png', 'mergedimage.png']:
                    if thumb_name in names:
                        raw = zf.read(thumb_name)
                        qimage = QImage()
                        qimage.loadFromData(raw)
                        qimage = _gamma_correct_qimage(qimage)
                        ba = QByteArray()
                        buf = QBuffer(ba)
                        buf.open(QIODevice.WriteOnly)
                        qimage.save(buf, 'PNG')
                        buf.close()
                        result['thumbnail_bytes'] = bytes(ba)
                        break
        except Exception as e:
            print(f"解析失败: {filepath} - {e}")

        return result


class Krita统计插件(DockWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self._tr('Krita统计插件', 'Krita Statistics'))
        self.records = []
        self.year_groups = {}
        self.month_groups = {}
        self.day_groups = {}
        self.stats = {}
        self._rendering = False
        self._collapsed_years = set()
        self._collapsed_months = set()
        self._thread = None
        self._worker = None
        self._current_search = ''
        self._all_records = []
        self._cache = {}
        locale = Krita.instance().readSetting('', 'locale', '')
        self._lang = 'zh' if locale and locale.startswith('zh') else 'en'
        self._load_settings()
        self._cache_init()
        self._build_ui()
        QTimer.singleShot(100, self.refresh_data)

    def canvasChanged(self, canvas):
        pass

    def _tr(self, zh, en):
        return zh if self._lang == 'zh' else en

    def _get_default_scan_path(self):
        return QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)

    def _update_path_display(self):
        text = self.scan_path
        if len(text) > 40:
            text = "..." + text[-37:]
        self.path_label.setText(text)
        self.path_label.setToolTip(self.scan_path)

    def _browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(
            self, self._tr("选择 .kra 文件目录", "Select .kra folder"), self.scan_path)
        if dir_path:
            self.scan_path = dir_path
            self._update_path_display()
            self._save_settings()
            self.refresh_data()

    @staticmethod
    def _scale_thumb(pixmap, target_w, target_h):
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            target_w, target_h,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation)

    @staticmethod
    def _gamma_correct_pixmap(pixmap, gamma=2.2):
        if pixmap.isNull():
            return pixmap
        img = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
        if img.isNull():
            return pixmap
        img = _gamma_correct_qimage(img, gamma)
        return QPixmap.fromImage(img)

    def scan_kra_files(self, root_dir):
        kra_files = []
        try:
            for root, dirs, files in os.walk(root_dir):
                for f in files:
                    if f.lower().endswith('.kra'):
                        kra_files.append(os.path.join(root, f))
        except PermissionError:
            print(f"[Krita统计] 权限不足，无法访问: {root_dir}")
        except OSError as e:
            print(f"[Krita统计] 扫描路径失败: {e}")
        return kra_files

    def parse_kra_file(self, filepath):
        result = {
            'path': filepath,
            'name': os.path.basename(filepath),
            'editing_time': 0,
            'editing_cycles': 0,
            'created_time': None,
            'modified_time': None,
            'thumbnail': None,
            'title': '',
            'creator': '',
            'author_name': '',
            'author_email': '',
            'author_contact': {},
            'canvas_width': 0,
            'canvas_height': 0,
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
                names = zf.namelist()

                if 'documentinfo.xml' in names:
                    xml_data = zf.read('documentinfo.xml')
                    root = ET.fromstring(xml_data)

                    time_elem = _find_local(root, 'editing-time')
                    if time_elem is not None and time_elem.text:
                        result['editing_time'] = _parse_iso_duration(
                            time_elem.text.strip())

                    cycles_elem = _find_local(root, 'editing-cycles')
                    if cycles_elem is not None and cycles_elem.text:
                        result['editing_cycles'] = int(
                            cycles_elem.text.strip())

                    title_elem = _find_local(root, 'title')
                    if title_elem is not None and title_elem.text:
                        result['title'] = title_elem.text.strip()

                    creator_elem = _find_local(root, 'initial-creator')
                    if creator_elem is not None and creator_elem.text:
                        result['creator'] = creator_elem.text.strip()

                    name_elem = _find_local(root, 'full-name')
                    if name_elem is not None and name_elem.text:
                        result['author_name'] = name_elem.text.strip()

                    result['author_email'] = _extract_email(root)
                    result['author_contact'] = _extract_author_contacts(root)

                if 'maindoc.xml' in names:
                    xml_data = zf.read('maindoc.xml')
                    root = ET.fromstring(xml_data)
                    img = _find_local(root, 'IMAGE')
                    if img is not None:
                        w = img.get('width', '0')
                        h = img.get('height', '0')
                        result['canvas_width'] = int(w) if w.isdigit() else 0
                        result['canvas_height'] = int(h) if h.isdigit() else 0

                for thumb_name in ['preview.png', 'mergedimage.png']:
                    if thumb_name in names:
                        img_data = zf.read(thumb_name)
                        pixmap = QPixmap()
                        pixmap.loadFromData(img_data)
                        result['thumbnail'] = self._gamma_correct_pixmap(
                            pixmap)
                        break
        except Exception as e:
            print(f"解析失败: {filepath} - {e}")

        return result

    def process_data(self, records, sort_by='created', sort_order='desc'):
        key = 'created_time' if sort_by == 'created' else 'modified_time'
        records.sort(key=lambda r: r[key] or datetime.datetime.min,
                     reverse=(sort_order == 'desc'))

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

    def _save_settings(self):
        ks = Krita.instance()
        ks.writeSetting(SETTINGS_GROUP, 'scanPath', self.scan_path)
        ks.writeSetting(
            SETTINGS_GROUP, 'sortIndex',
            str(self.sort_combo.currentIndex()))
        ks.writeSetting(
            SETTINGS_GROUP, 'collapsedYears',
            ','.join(sorted(self._collapsed_years)))
        ks.writeSetting(
            SETTINGS_GROUP, 'collapsedMonths',
            ','.join(sorted(self._collapsed_months)))

    def _load_settings(self):
        ks = Krita.instance()
        saved_path = ks.readSetting(SETTINGS_GROUP, 'scanPath', '')
        self.scan_path = saved_path if saved_path else \
            self._get_default_scan_path()

        saved_sort = ks.readSetting(SETTINGS_GROUP, 'sortIndex', '')
        self._saved_sort_index = int(saved_sort) if saved_sort.isdigit() else 0

        saved_years = ks.readSetting(SETTINGS_GROUP, 'collapsedYears', '')
        self._collapsed_years = set(
            y for y in saved_years.split(',') if y)

        saved_months = ks.readSetting(SETTINGS_GROUP, 'collapsedMonths', '')
        self._collapsed_months = set(
            m for m in saved_months.split(',') if m)

    def _cache_init(self):
        self._cache_dir = os.path.join(
            os.path.expanduser('~'), '.krita_stats_cache')
        os.makedirs(os.path.join(self._cache_dir, 'thumbnails'), exist_ok=True)
        self._cache_index_path = os.path.join(self._cache_dir, 'index.json')
        self._cache_index = {}
        if os.path.isfile(self._cache_index_path):
            try:
                with open(self._cache_index_path, 'r', encoding='utf-8') as f:
                    self._cache_index = json.load(f)
            except Exception:
                self._cache_index = {}
        self._cache_lru = []

    def _cache_key(self, filepath):
        return hashlib.md5(filepath.encode('utf-8')).hexdigest()

    def _cache_thumb_path(self, filepath):
        return os.path.join(
            self._cache_dir, 'thumbnails', self._cache_key(filepath) + '.png')

    def _load_from_cache(self, filepath, mtime):
        try:
            norm = os.path.normpath(filepath)
            ck = self._cache_key(norm)
            entry = self._cache_index.get(ck)
            if entry is None:
                return None
            if abs(entry['mtime'] - mtime) > 0.001:
                return None
            thumb_path = self._cache_thumb_path(norm)
            thumb = None
            if os.path.isfile(thumb_path):
                pix = QPixmap()
                if pix.load(thumb_path):
                    thumb = pix
            rec = {
                'path': norm,
                'name': os.path.basename(norm),
                'editing_time': entry.get('editing_time', 0),
                'editing_cycles': entry.get('editing_cycles', 0),
                'created_time': (datetime.datetime.fromtimestamp(
                    entry['created_ts'])
                    if entry.get('created_ts') else None),
                'modified_time': (datetime.datetime.fromtimestamp(
                    entry['modified_ts'])
                    if entry.get('modified_ts') else None),
                'thumbnail': thumb,
                'title': entry.get('title', ''),
                'creator': entry.get('creator', ''),
                'author_name': entry.get('author_name', ''),
                'author_email': entry.get('author_email', ''),
                'author_contact': entry.get('author_contact', {}),
                'canvas_width': entry.get('canvas_width', 0),
                'canvas_height': entry.get('canvas_height', 0),
            }
            return rec
        except Exception:
            return None

    def _save_to_cache(self, records):
        for rec in records:
            try:
                norm = os.path.normpath(rec['path'])
                mtime = os.path.getmtime(norm)
                ck = self._cache_key(norm)
                thumb = rec.get('thumbnail')
                if thumb and not thumb.isNull():
                    thumb.save(self._cache_thumb_path(norm), 'PNG')
                self._cache_index[ck] = {
                    'path': norm,
                    'mtime': mtime,
                    'editing_time': rec['editing_time'],
                    'editing_cycles': rec['editing_cycles'],
                    'created_ts': rec['created_time'].timestamp()
                    if rec['created_time'] else 0,
                    'modified_ts': rec['modified_time'].timestamp()
                    if rec['modified_time'] else 0,
                    'title': rec.get('title', ''),
                    'creator': rec.get('creator', ''),
                    'author_name': rec.get('author_name', ''),
                    'author_email': rec.get('author_email', ''),
                    'author_contact': rec.get('author_contact', {}),
                    'canvas_width': rec.get('canvas_width', 0),
                    'canvas_height': rec.get('canvas_height', 0),
                }
            except Exception:
                pass
        try:
            with open(self._cache_index_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache_index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _build_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        top_container = QVBoxLayout()
        top_container.setSpacing(2)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            self._tr('创建时间 ↓', 'Created ↓'), self._tr('创建时间 ↑', 'Created ↑'),
            self._tr('修改时间 ↓', 'Modified ↓'), self._tr('修改时间 ↑', 'Modified ↑'),
        ])
        self.sort_combo.setCurrentIndex(self._saved_sort_index)
        browse_btn = QPushButton(self._tr('\U0001F4C1 浏览', '\U0001F4C1 Browse'))
        browse_btn.clicked.connect(self._browse_directory)
        self.path_label = QLabel('')
        self.path_label.setStyleSheet("font-size: 10px; color: #ccc; min-width: 0;")
        refresh_btn = QPushButton(self._tr('刷新', 'Refresh'))
        refresh_btn.clicked.connect(self.refresh_data)

        row1 = QHBoxLayout()
        row1.setSpacing(4)
        row1.addWidget(QLabel(self._tr('排序:', 'Sort:')))
        row1.addWidget(self.sort_combo)
        row1.addWidget(browse_btn)
        row1.addStretch()
        row1.addWidget(refresh_btn)

        row2 = QHBoxLayout()
        row2.setSpacing(0)
        row2.addWidget(self.path_label)
        row2.addStretch()

        top_container.addLayout(row1)
        top_container.addLayout(row2)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self._tr('搜索文件名...', 'Search filename...'))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)

        row3 = QHBoxLayout()
        row3.addWidget(self.search_input)
        top_container.addLayout(row3)

        self.scroll_area = AlbumScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_content = QWidget()
        self.album_layout = QVBoxLayout(scroll_content)
        self.album_layout.setSpacing(2)
        self.album_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll_area.setWidget(scroll_content)
        self.scroll_area.resize_callback = self._on_album_resize

        bottom_container = QVBoxLayout()
        bottom_container.setSpacing(2)

        self.stats_total_count = QLabel(self._tr('文件: 0', 'Files: 0'))
        self.stats_total_time = QLabel(self._tr('总耗时: 0s', 'Total: 0s'))
        self.stats_month = QLabel(self._tr('本月: 0s', 'Month: 0s'))
        self.stats_year = QLabel(self._tr('本年: 0s', 'Year: 0s'))
        self.stats_earliest = QLabel(self._tr('最早: -', 'Earliest: -'))
        self.stats_latest = QLabel(self._tr('最晚: -', 'Latest: -'))

        label_style = "font-size: 13px; color: #ddd;"
        for w in [self.stats_total_count, self.stats_total_time,
                  self.stats_month, self.stats_year,
                  self.stats_earliest, self.stats_latest]:
            w.setStyleSheet(label_style)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        for w in [self.stats_total_count, self.stats_total_time,
                  self.stats_month, self.stats_year]:
            row1.addWidget(w)
        row1.addStretch()

        chart_btn = QPushButton(self._tr('\U0001F4CA 图表', '\U0001F4CA Chart'))
        chart_btn.clicked.connect(self._show_chart_dialog)
        export_btn = QPushButton(self._tr('\U0001F4E4 导出', '\U0001F4E4 Export'))
        export_btn.clicked.connect(self._export_html_report)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        for w in [self.stats_earliest, self.stats_latest]:
            row2.addWidget(w)
        row2.addStretch()

        row3 = QHBoxLayout()
        row3.addWidget(chart_btn)
        row3.addStretch()
        about_btn = QPushButton(self._tr('\u2139\uFE0F 关于', '\u2139\uFE0F About'))
        about_btn.clicked.connect(self._show_about_dialog)
        row3.addWidget(about_btn)
        row3.addStretch()
        row3.addWidget(export_btn)

        bottom_container.addLayout(row1)
        bottom_container.addLayout(row2)
        bottom_container.addLayout(row3)

        main_layout.addLayout(top_container)
        main_layout.addWidget(self.scroll_area)
        main_layout.addLayout(bottom_container)
        self.setWidget(main_widget)

        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._update_path_display()

    def _on_album_resize(self):
        if self._rendering:
            return
        if self.records and self.stats:
            self.render_album(
                self.year_groups, self.month_groups,
                self.day_groups, self.stats)

    def _on_search_changed(self, text):
        self._current_search = text.strip().lower()
        if not self._all_records:
            return
        self._apply_search_filter()

    def _apply_search_filter(self):
        if self._current_search:
            filtered = [r for r in self._all_records
                        if self._current_search in r['name'].lower()]
        else:
            filtered = list(self._all_records)

        if not filtered:
            self._show_empty_state(self._tr('未找到匹配的文件', 'No matching files'))
            return

        idx = self.sort_combo.currentIndex()
        sort_map = {
            0: ('created', 'desc'),
            1: ('created', 'asc'),
            2: ('modified', 'desc'),
            3: ('modified', 'asc'),
        }
        sort_by, sort_order = sort_map.get(idx, ('created', 'desc'))
        year_groups, month_groups, day_groups, stats = self.process_data(
            filtered, sort_by, sort_order)
        self.records = filtered
        self.year_groups = year_groups
        self.month_groups = month_groups
        self.day_groups = day_groups
        self.stats = stats
        self.render_album(year_groups, month_groups, day_groups, stats)

    def _show_empty_state(self, message=None):
        if message is None:
            message = self._tr('未找到 .kra 文件', 'No .kra files found')
        self._clear_layout(self.album_layout)
        label = QLabel(f"\U0001F4C2  {message}\n{self._tr('点击 浏览 选择其他目录', 'Click Browse to choose another folder')}")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 14px; color: #aaa; padding: 40px;")
        self.album_layout.addWidget(label)
        self.album_layout.addStretch()

    def _make_collapsible_header(self, text, key, is_year=True):
        btn = QToolButton()
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setArrowType(Qt.DownArrow)
        btn.setText(text)
        btn.setCheckable(True)
        btn.setChecked(True)

        if is_year:
            btn.setStyleSheet("""
                QToolButton {
                    font-weight: bold; font-size: 17px;
                    padding: 8px 4px 4px 4px;
                    color: #ffffff; border: none; text-align: left;
                }
                QToolButton:hover { color: #4a9eff; }
            """)
        else:
            btn.setStyleSheet("""
                QToolButton {
                    font-weight: bold; font-size: 15px;
                    padding: 4px 4px 2px 16px;
                    color: #e0e0e0; border: none; text-align: left;
                }
                QToolButton:hover { color: #4a9eff; }
            """)

        def on_toggled(checked):
            btn.setArrowType(
                Qt.DownArrow if checked else Qt.RightArrow)
            self._toggle_section(key, is_year, checked)

        btn.toggled.connect(on_toggled)
        return btn

    def _toggle_section(self, key, is_year, checked):
        if is_year:
            if checked:
                self._collapsed_years.discard(key)
            else:
                self._collapsed_years.add(key)
        else:
            if checked:
                self._collapsed_months.discard(key)
            else:
                self._collapsed_months.add(key)
        self._save_settings()
        self.render_album(self.year_groups, self.month_groups,
                          self.day_groups, self.stats)

    def render_album(self, year_groups, month_groups, day_groups, stats):
        if self._rendering:
            return
        self._rendering = True
        try:
            self._do_render(year_groups, month_groups, day_groups, stats)
        finally:
            self._rendering = False

    def _do_render(self, year_groups, month_groups, day_groups, stats):
        content = self.scroll_area.widget()
        saved_callback = self.scroll_area.resize_callback
        self.scroll_area.resize_callback = None
        if content:
            content.setUpdatesEnabled(False)
        try:
            self._clear_layout(self.album_layout)

            cols = self._calc_columns()

            for year_key in sorted(year_groups.keys(), reverse=True):
                year_records = year_groups[year_key]
                year_total = sum(r['editing_time'] for r in year_records)
                year_btn = self._make_collapsible_header(
                    f"\U0001F4C5 {year_key}  {self._tr('年总耗时', 'Year total')}: {self.format_time(year_total)}",
                    year_key, is_year=True)
                year_btn.setChecked(year_key not in self._collapsed_years)
                self.album_layout.addWidget(year_btn)

                year_expanded = year_key not in self._collapsed_years
                year_container = QWidget()
                year_container.setVisible(year_expanded)
                year_container_layout = QVBoxLayout(year_container)
                year_container_layout.setContentsMargins(0, 0, 0, 0)
                year_container_layout.setSpacing(1)

                for month_key in sorted(month_groups.keys(), reverse=True):
                    if not month_key.startswith(year_key):
                        continue
                    month_records = month_groups[month_key]
                    month_total = sum(r['editing_time'] for r in month_records)
                    month_btn = self._make_collapsible_header(
                        f"\U0001F4C1 {month_key}  {self._tr('月总耗时', 'Month total')}: {self.format_time(month_total)}",
                        month_key, is_year=False)
                    month_btn.setChecked(month_key not in self._collapsed_months)
                    year_container_layout.addWidget(month_btn)

                    month_expanded = month_key not in self._collapsed_months
                    month_container = QWidget()
                    month_container.setVisible(month_expanded)
                    month_container_layout = QVBoxLayout(month_container)
                    month_container_layout.setContentsMargins(12, 0, 0, 0)
                    month_container_layout.setSpacing(1)

                    for day_key in sorted(day_groups.keys(), reverse=True):
                        if not day_key.startswith(month_key):
                            continue
                        day_records = day_groups[day_key]
                        day_total = sum(r['editing_time'] for r in day_records)
                        day_label = QLabel(
                            f"\U0001F4C4 {day_key}  {self._tr('日总耗时', 'Day total')}: {self.format_time(day_total)}")
                        day_label.setStyleSheet(
                            "font-size: 13px; font-weight: bold; "
                            "color: #ccc; "
                            "padding: 2px 4px 2px 4px;")
                        month_container_layout.addWidget(day_label)

                        if not day_records:
                            continue
                        grid = QGridLayout()
                        grid.setSpacing(6)
                        for i, rec in enumerate(day_records):
                            card = self.create_card(rec)
                            grid.addWidget(card, i // cols, i % cols)
                        month_container_layout.addLayout(grid)

                    year_container_layout.addWidget(month_container)

                self.album_layout.addWidget(year_container)

            self.album_layout.addStretch()
            self.update_stats(stats)
        finally:
            if content:
                content.setUpdatesEnabled(True)
            self.scroll_area.resize_callback = saved_callback
            self.scroll_area.cancel_debounce()

    def _calc_columns(self):
        scroll_width = self.scroll_area.viewport().width()
        card_width = 148
        spacing = 6
        effective = scroll_width + spacing
        cols = max(1, effective // (card_width + spacing))
        return min(cols, 6)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                w = item.widget()
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                Krita统计插件._clear_layout(item.layout())

    def create_card(self, record):
        card = QWidget()
        card.setFixedSize(140, 210)
        card.setStyleSheet("""
            QWidget {
                border: 1px solid #555;
                border-radius: 4px;
                background: #3c3c3c;
            }
            QWidget:hover {
                border-color: #4a9eff;
                background: #4a4a4a;
            }
        """)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        thumb_grid = QGridLayout()
        thumb_grid.setContentsMargins(0, 0, 0, 0)
        thumb_grid.setSpacing(0)

        thumb_label = QLabel()
        thumb_label.setFixedSize(132, 132)
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("border: none; background: #555;")
        if record['thumbnail'] and not record['thumbnail'].isNull():
            thumb = self._scale_thumb(record['thumbnail'], 132, 132)
            thumb_label.setPixmap(thumb)

        badge = QLabel(self.format_time(record['editing_time']))
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("""
            background: rgba(0, 0, 0, 160);
            color: white;
            padding: 1px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: bold;
            border: none;
        """)

        thumb_grid.addWidget(thumb_label, 0, 0)
        thumb_grid.addWidget(badge, 0, 0, Qt.AlignTop | Qt.AlignRight)
        layout.addLayout(thumb_grid)

        name_label = QLabel(record['name'])
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet(
            "font-size: 12px; color: #f0f0f0; border: none;")

        ctime_str = (record['created_time'].strftime('%Y-%m-%d %H:%M')
                     if record['created_time'] else "")
        mtime_str = (record['modified_time'].strftime('%Y-%m-%d %H:%M')
                     if record['modified_time'] else "")

        ctime_label = QLabel(f"{self._tr('创建', 'Created')}: {ctime_str}")
        ctime_label.setAlignment(Qt.AlignCenter)
        ctime_label.setStyleSheet(
            "font-size: 11px; color: #aaa; border: none;")
        mtime_label = QLabel(f"{self._tr('修改', 'Modified')}: {mtime_str}")
        mtime_label.setAlignment(Qt.AlignCenter)
        mtime_label.setStyleSheet(
            "font-size: 11px; color: #aaa; border: none;")

        layout.addWidget(name_label)
        layout.addWidget(ctime_label)
        layout.addWidget(mtime_label)

        card.mousePressEvent = lambda e, rec=record: (
            self._show_document_info(rec))

        return card

    def _show_document_info(self, record):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self._tr('图像信息', 'Image Info')} - {record['name']}")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        if record['thumbnail'] and not record['thumbnail'].isNull():
            thumb = record['thumbnail'].scaled(
                300, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            thumb_label = QLabel()
            thumb_label.setPixmap(thumb)
            thumb_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(thumb_label)

        grid = QGridLayout()
        grid.setVerticalSpacing(6)
        grid.setHorizontalSpacing(12)

        info = [
            (self._tr('文件名', 'File'), record['name']),
            (self._tr('路径', 'Path'), record['path']),
            (self._tr('编辑时间', 'Edit time'), self.format_time(record['editing_time'])),
            (self._tr('编辑次数', 'Edit cycles'), str(record['editing_cycles'])),
            (self._tr('创建时间', 'Created'), record['created_time'].strftime('%Y-%m-%d %H:%M:%S')
             if record['created_time'] else '-'),
            (self._tr('修改时间', 'Modified'), record['modified_time'].strftime('%Y-%m-%d %H:%M:%S')
             if record['modified_time'] else '-'),
            (self._tr('画布尺寸', 'Canvas'), f"{record['canvas_width']} x {record['canvas_height']} px"
             if record['canvas_width'] > 0 else '-'),
            (self._tr('标题', 'Title'), record['title'] or '-'),
            (self._tr('创建者', 'Creator'), record['creator'] or '-'),
            (self._tr('图像作者', 'Author'), record['author_name'] or '-'),
            (self._tr('作者邮箱', 'Email'), record['author_email'] or '-'),
        ]

        row = 0
        for label, value in info:
            lbl = QLabel(f"<b>{label}:</b>")
            lbl.setStyleSheet("font-size: 12px;")
            val = QLabel(value)
            val.setStyleSheet("font-size: 12px; color: #ccc;")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(lbl, row, 0, Qt.AlignTop)
            grid.addWidget(val, row, 1)
            row += 1

        sep = QLabel(f'<b>\u2500 {self._tr("作者联系方式", "Author Contacts")} \u2500</b>')
        sep.setStyleSheet("font-size: 12px; color: #aaa; padding: 4px 0;")
        grid.addWidget(sep, row, 0, 1, 2)
        row += 1

        shown_labels = set()
        for label_text, value in self._get_krita_contact_fields():
            shown_labels.add(label_text)
            lbl = QLabel(f"<b>{label_text}:</b>")
            lbl.setStyleSheet("font-size: 12px; color: #ddd;")
            val = QLabel(value)
            val.setStyleSheet("font-size: 12px; color: #ccc;")
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(lbl, row, 0, Qt.AlignTop)
            grid.addWidget(val, row, 1)
            row += 1

        for label_text, value in record.get('author_contact', {}).items():
            if label_text not in shown_labels:
                shown_labels.add(label_text)
                lbl = QLabel(f"<b>{label_text}:</b>")
                lbl.setStyleSheet("font-size: 12px; color: #ddd;")
                val = QLabel(value)
                val.setStyleSheet("font-size: 12px; color: #ccc;")
                val.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(lbl, row, 0, Qt.AlignTop)
                grid.addWidget(val, row, 1)
                row += 1

        layout.addLayout(grid)

        btn_box = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_box.addStretch()
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

        dialog.exec_()

    def _on_sort_changed(self):
        if not self._all_records:
            return
        self._apply_search_filter()
        self._save_settings()

    def refresh_data(self):
        if self._thread is not None and self._thread.isRunning():
            self._thread.requestInterruption()
            self._thread.quit()
            self._thread.wait(3000)

        self._thread = None
        self._worker = None

        self.stats_total_count.setText(self._tr("扫描中...", "Scanning..."))

        print(f"[Krita统计] 扫描路径: {self.scan_path}")

        all_files = self.scan_kra_files(self.scan_path)
        self._cache_records = []
        to_scan = []
        for fp in all_files:
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                to_scan.append(fp)
                continue
            cached = self._load_from_cache(fp, mtime)
            if cached:
                self._cache_records.append(cached)
            else:
                to_scan.append(fp)

        if to_scan:
            self._worker = ScanWorker(self.scan_path)
            self._thread = QThread(self)
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)
            self._worker.finished.connect(self._on_scan_finished)
            self._worker.finished.connect(self._thread.quit)
            self._worker.progress.connect(self._on_scan_progress)
            self._thread.finished.connect(self._cleanup_scan)
            self._thread.start()
        else:
            self._on_scan_finished([])

    def _on_scan_progress(self, current, total):
        self.stats_total_count.setText(f"{self._tr('扫描中', 'Scanning')}... {current}/{total}")

    def _on_scan_finished(self, raw_records):
        records = list(self._cache_records)
        self._cache_records = []

        for raw in raw_records:
            rec = {
                'path': raw['path'],
                'name': raw['name'],
                'editing_time': raw['editing_time'],
                'editing_cycles': raw['editing_cycles'],
                'created_time': raw['created_time'],
                'modified_time': raw['modified_time'],
                'title': raw['title'],
                'creator': raw['creator'],
                'author_name': raw['author_name'],
                'author_email': raw['author_email'],
                'author_contact': raw.get('author_contact', {}),
                'canvas_width': raw['canvas_width'],
                'canvas_height': raw['canvas_height'],
                'thumbnail': None,
            }
            thumb_bytes = raw['thumbnail_bytes']
            if thumb_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(thumb_bytes)
                rec['thumbnail'] = pixmap
            records.append(rec)

        if raw_records:
            self._save_to_cache(records)

        self._all_records = records

        if not records:
            self._show_empty_state()
            return

        idx = self.sort_combo.currentIndex()
        sort_map = {
            0: ('created', 'desc'),
            1: ('created', 'asc'),
            2: ('modified', 'desc'),
            3: ('modified', 'asc'),
        }
        sort_by, sort_order = sort_map.get(idx, ('created', 'desc'))
        year_groups, month_groups, day_groups, stats = self.process_data(
            records, sort_by, sort_order)

        self.records = records
        self.year_groups = year_groups
        self.month_groups = month_groups
        self.day_groups = day_groups
        self.stats = stats

        self.render_album(year_groups, month_groups, day_groups, stats)

    def _cleanup_scan(self):
        self._worker = None
        self._thread = None

    def update_stats(self, stats):
        self.stats_total_count.setText(
            f"{self._tr('文件', 'Files')}: {stats['total_count']}")
        self.stats_total_time.setText(
            f"{self._tr('总耗时', 'Total')}: {self.format_time(stats['total_time'])}")
        self.stats_earliest.setText(
            f"{self._tr('最早', 'Earliest')}: {stats['earliest_created'].strftime('%Y-%m-%d')}"
            if stats['earliest_created'] else f"{self._tr('最早', 'Earliest')}: -")
        self.stats_latest.setText(
            f"{self._tr('最晚', 'Latest')}: {stats['latest_modified'].strftime('%Y-%m-%d')}"
            if stats['latest_modified'] else f"{self._tr('最晚', 'Latest')}: -")
        self.stats_month.setText(
            f"{self._tr('本月', 'Month')}: {self.format_time(stats['month_time'])}")
        self.stats_year.setText(
            f"{self._tr('本年', 'Year')}: {self.format_time(stats['year_time'])}")

    def _get_krita_author_name(self):
        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.GenericConfigLocation)
        kritarc = os.path.join(config_dir, 'kritarc')
        if os.path.isfile(kritarc):
            s = QSettings(kritarc, QSettings.IniFormat)
            for key in ['Author/name', 'author/name', 'Author/full-name']:
                val = s.value(key, '')
                if val and val != 'Unknown':
                    return val
        ks = Krita.instance()
        for group, key in [('Author', 'name'), ('author', 'name'),
                           ('Author', 'full-name'), ('author', 'full-name')]:
            val = ks.readSetting(group, key, '')
            if val and val != 'Unknown':
                return val
        if self._all_records:
            for rec in self._all_records:
                n = rec.get('author_name')
                if n and n not in ('', 'Unknown'):
                    return n
        return ''

    def _get_krita_contact_fields(self):
        result = []
        seen_keys = set()
        authors = {}

        config_dir = QStandardPaths.writableLocation(
            QStandardPaths.GenericConfigLocation)
        kritarc = os.path.join(config_dir, 'kritarc')
        if os.path.isfile(kritarc):
            s = QSettings(kritarc, QSettings.IniFormat)
            for section in ['Author', 'author', 'AuthorProfile']:
                s.beginGroup(section)
                for key in s.childKeys():
                    val = s.value(key, '')
                    if val and val != 'Unknown':
                        authors[key] = val
                s.endGroup()

        if not authors:
            ks = Krita.instance()
            for group in ['Author', 'author']:
                for key in ['name', 'email', 'telephone', 'telephone-work',
                            'fax', 'company', 'country', 'city', 'street',
                            'postal-code']:
                    val = ks.readSetting(group, key, '')
                    if val and val != 'Unknown':
                        authors[key] = val

        label_map = {
            'name': '姓名', 'full-name': '姓名',
            'email': '邮箱', 'telephone': '电话',
            'telephone-work': '工作电话', 'fax': '传真',
            'company': '公司', 'country': '国家',
            'city': '城市', 'street': '街道',
            'postal-code': '邮政编码',
        }
        for key, label in label_map.items():
            if key in authors and key not in seen_keys:
                seen_keys.add(key)
                result.append((label, authors[key]))

        if not result and self._all_records:
            for rec in self._all_records:
                ac = rec.get('author_contact', {})
                for label_text, val in ac.items():
                    if label_text not in [r[0] for r in result]:
                        result.append((label_text, val))
                if '姓名' not in [r[0] for r in result]:
                    n = rec.get('author_name')
                    if n and n not in ('', 'Unknown'):
                        result.append(('姓名', n))
                if '邮箱' not in [r[0] for r in result]:
                    e = rec.get('author_email')
                    if e:
                        result.append(('邮箱', e))
                if result:
                    break

        return result

    def _pixmap_to_base64(self, pixmap, max_size=(80, 80)):
        if not pixmap or pixmap.isNull():
            return ''
        thumb = pixmap.scaled(
            max_size[0], max_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        thumb.save(buf, 'PNG')
        buf.close()
        return base64.b64encode(bytes(ba)).decode()

    def _chart_data_for_range(self, range_idx):
        from datetime import timedelta
        now = datetime.datetime.now()
        records = self._all_records

        if range_idx == 0:
            start = now - timedelta(days=7)
            filtered = [r for r in records if r['created_time'] and r['created_time'] >= start]
            groups = {}
            for r in filtered:
                k = r['created_time'].strftime('%m-%d')
                groups[k] = groups.get(k, 0) + r['editing_time']
            labels = [(now - timedelta(days=6 - i)).strftime('%m-%d') for i in range(7)]
            values = [groups.get(l, 0) for l in labels]
        elif range_idx == 1:
            start = now - timedelta(days=30)
            filtered = [r for r in records if r['created_time'] and r['created_time'] >= start]
            groups = {}
            for r in filtered:
                k = r['created_time'].strftime('%m-%d')
                groups[k] = groups.get(k, 0) + r['editing_time']
            labels = [(now - timedelta(days=29 - i)).strftime('%m-%d') for i in range(30)]
            values = [groups.get(l, 0) for l in labels]
        elif range_idx == 2:
            start = now - timedelta(days=365)
            filtered = [r for r in records if r['created_time'] and r['created_time'] >= start]
            groups = {}
            for r in filtered:
                k = r['created_time'].strftime('%y-%m')
                groups[k] = groups.get(k, 0) + r['editing_time']
            labels = []
            for i in range(11, -1, -1):
                m = now.month - i
                y = now.year
                while m <= 0:
                    m += 12
                    y -= 1
                labels.append(f'{y % 100:02d}-{m:02d}')
            values = [groups.get(l, 0) for l in labels]
            total_time = sum(values)
            return labels, values, total_time, len(filtered)
        else:
            groups = {}
            for r in records:
                if r['created_time']:
                    k = r['created_time'].strftime('%Y')
                    groups[k] = groups.get(k, 0) + r['editing_time']
            labels = sorted(groups.keys())
            values = [groups[k] for k in labels]
            total_time = sum(values)
            return labels, values, total_time, len(records)

        total_time = sum(values)
        return labels, values, total_time, len(filtered)

    def _render_chart_pixmap(self, labels, values, width=600, height=300, chart_type=0):
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.white)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        ml, mr, mt, mb = 55, 16, 20, 50
        cw, ch = width - ml - mr, height - mt - mb
        max_val = max(values) or 1

        p.setPen(QPen(QColor('#ccc'), 1))
        p.drawLine(ml, mt, ml, mt + ch)
        p.drawLine(ml, mt + ch, ml + cw, mt + ch)

        for i in range(5):
            val = max_val * i // 4
            yy = mt + ch - int(ch * i / 4)
            p.setPen(QPen(QColor('#eee'), 1))
            p.drawLine(ml + 1, yy, ml + cw, yy)
            p.setPen(QColor('#999'))
            f = p.font()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(0, yy - 8, ml - 8, 16), Qt.AlignRight | Qt.AlignVCenter, str(val))

        n = len(labels)
        bw = max(6, min(36, cw // n - 4))
        gap = (cw - bw * n) // (n + 1) if n > 1 else cw // 3

        if chart_type == 0:
            for i, val in enumerate(values):
                x = ml + gap + i * (bw + gap)
                bh = int((val / max_val) * ch) if max_val else 0
                y = mt + ch - bh
                p.setBrush(QColor('#4a9eff'))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(x, y, bw, bh, 2, 2)
                p.setPen(QColor('#999'))
                f.setPointSize(7)
                p.setFont(f)
                p.drawText(QRectF(x, y - 16, bw, 14), Qt.AlignCenter, str(val))
        else:
            pts = [QPointF(ml + gap + i * (bw + gap) + bw / 2, mt + ch) for i in range(len(values))]
            for i, val in enumerate(values):
                bh = int((val / max_val) * ch) if max_val else 0
                pts[i].setY(mt + ch - bh)

            path = QPainterPath()
            path.moveTo(pts[0].x(), mt + ch)
            path.lineTo(pts[0])
            if chart_type == 2 and len(pts) > 2:
                for i in range(len(pts) - 1):
                    cpx = (pts[i].x() + pts[i + 1].x()) / 2
                    path.cubicTo(cpx, pts[i].y(), cpx, pts[i + 1].y(), pts[i + 1].x(), pts[i + 1].y())
            else:
                for i in range(1, len(pts)):
                    path.lineTo(pts[i])
            path.lineTo(pts[-1].x(), mt + ch)
            path.closeSubpath()

            p.setBrush(QColor(74, 158, 255, 30))
            p.setPen(QPen(QColor('#4a9eff'), 2))
            p.drawPath(path)

            p.setBrush(QColor('#4a9eff'))
            for pt in pts:
                p.drawEllipse(pt, 3, 3)

            for i, val in enumerate(values):
                p.setPen(QColor('#999'))
                f.setPointSize(7)
                p.setFont(f)
                p.drawText(QRectF(pts[i].x() - bw / 2, pts[i].y() - 16, bw, 14), Qt.AlignCenter, str(val))

        for i, label in enumerate(labels):
            x = ml + gap + i * (bw + gap)
            p.setPen(QColor('#999'))
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(x - 4, mt + ch + 4, bw + 8, 40), Qt.AlignCenter | Qt.TextWordWrap, label)

        p.end()
        return pixmap

    def _show_chart_dialog(self):
        if not self._all_records:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr('统计图表', 'Statistics Chart'))
        dialog.resize(1800, 1000)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(8)

        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        author_name = self._get_krita_author_name()

        top = QHBoxLayout()
        top.addWidget(QLabel(self._tr('时间范围:', 'Range:')))
        combo = QComboBox()
        combo.addItems([self._tr('最近7天', 'Last 7 days'), self._tr('最近30天', 'Last 30 days'),
                        self._tr('最近12个月', 'Last 12 months'), self._tr('全部', 'All')])
        top.addWidget(combo)
        top.addSpacing(20)
        top.addWidget(QLabel(self._tr('图表样式:', 'Style:')))
        style_combo = QComboBox()
        style_combo.addItems([self._tr('\U0001F4CA 柱状图', '\U0001F4CA Bar'),
                              self._tr('\U0001F4C8 折线图', '\U0001F4C8 Line'),
                              self._tr('\U0001F4C8 曲线图', '\U0001F4C8 Curve')])
        top.addWidget(style_combo)
        top.addStretch()
        layout.addLayout(top)

        chart_container = QWidget()
        clayout = QVBoxLayout(chart_container)
        clayout.setContentsMargins(0, 0, 0, 0)
        clayout.setSpacing(4)

        chart = ChartWidget()
        clayout.addWidget(chart, 1)

        today_label = QLabel(f'\U0001F4C5  {author_name}  {today_str}' if author_name else f'\U0001F4C5  {today_str}')
        today_label.setAlignment(Qt.AlignCenter)
        today_label.setStyleSheet('font-size: 13px; color: #fff; padding: 4px;')
        clayout.addWidget(today_label)

        self._chart_summary = QLabel('')
        self._chart_summary.setAlignment(Qt.AlignCenter)
        self._chart_summary.setStyleSheet('font-size: 13px; color: #fff; padding: 2px;')
        clayout.addWidget(self._chart_summary)

        layout.addWidget(chart_container, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        export_png = QPushButton(self._tr('导出图表为PNG', 'Export Chart as PNG'))
        close_btn = QPushButton(self._tr('关闭', 'Close'))
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(export_png)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        def update():
            idx = combo.currentIndex()
            st = style_combo.currentIndex()
            labels, values, total_time, count = self._chart_data_for_range(idx)
            chart.set_data(labels, values, st)
            self._chart_summary.setText(
                f"{self._tr('总耗时', 'Total')}: {self.format_time(total_time)}  |  "
                f"{self._tr('作品', 'Works')}: {count}")
            self._chart_data_cache = (labels, values)

        self._chart_data_cache = None
        combo.currentIndexChanged.connect(update)
        style_combo.currentIndexChanged.connect(update)
        export_png.clicked.connect(lambda: self._save_chart_png(chart_container))
        update()
        dialog.exec_()

    def _save_chart_png(self, container):
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        default_name = f'{self._tr("Krita统计图表", "KritaChart")}_{today_str}.png'
        saved_dir = Krita.instance().readSetting(SETTINGS_GROUP, 'exportPath', '')
        default_path = os.path.join(saved_dir, default_name) if saved_dir else default_name
        path, _ = QFileDialog.getSaveFileName(
            self, self._tr('保存图表', 'Save Chart'), default_path,
            f'{self._tr("PNG图片", "PNG Image")} (*.png)')
        if not path:
            return
        Krita.instance().writeSetting(SETTINGS_GROUP, 'exportPath', os.path.dirname(path))
        pixmap = container.grab()
        pixmap.save(path, 'PNG')

    def _show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr('关于', 'About'))
        dialog.resize(360, 230)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        title = QLabel(f'\u2764 {self._tr("Krita统计插件", "Krita Statistics Plugin")}')
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #4a9eff;')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        author = QLabel(f'{self._tr("插件作者", "Author")}\uFF1A\u8336\u6E05\u58A8\u5202')
        author.setAlignment(Qt.AlignCenter)
        author.setStyleSheet('font-size: 13px; color: #ccc;')
        layout.addWidget(author)

        bilibili_btn = QPushButton('\u54D4\u54E9\u54D4\u54E9')
        bilibili_btn.setStyleSheet('''
            QPushButton {
                font-size: 14px; color: #fff; background: #fb7299;
                border: none; border-radius: 4px; padding: 8px 24px;
            }
            QPushButton:hover { background: #fc8fac; }
        ''')
        bilibili_btn.setCursor(QCursor(Qt.PointingHandCursor))
        bilibili_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl('https://space.bilibili.com/388428308')))
        btn_container = QHBoxLayout()
        btn_container.addStretch()
        btn_container.addWidget(bilibili_btn)
        btn_container.addStretch()
        layout.addLayout(btn_container)

        sponsor = QLabel(f'{self._tr("赞助", "Sponsor")}\uFF1A<a href="https://space.bilibili.com/388428308/charge" style="color:#fb7299;">B\u7AD9\u5145\u7535</a>')
        sponsor.setOpenExternalLinks(True)
        sponsor.setAlignment(Qt.AlignCenter)
        sponsor.setStyleSheet('font-size: 12px; color: #999;')
        layout.addWidget(sponsor)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton(self._tr('关闭', 'Close'))
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        dialog.exec_()

    def _export_html_report(self):
        if not self._all_records:
            return
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        default_name = f'{self._tr("Krita统计报告", "KritaReport")}_{today_str}.html'
        saved_dir = Krita.instance().readSetting(SETTINGS_GROUP, 'exportPath', '')
        default_path = os.path.join(saved_dir, default_name) if saved_dir else default_name
        path, _ = QFileDialog.getSaveFileName(
            self, self._tr('保存报告', 'Save Report'), default_path,
            f'{self._tr("HTML文件", "HTML File")} (*.html)')
        if not path:
            return
        Krita.instance().writeSetting(SETTINGS_GROUP, 'exportPath', os.path.dirname(path))

        chart_names = [self._tr('最近7天', 'Last 7 days'),
                       self._tr('最近30天', 'Last 30 days'),
                       self._tr('最近12个月', 'Last 12 months'),
                       self._tr('全部', 'All')]
        chart_b64s = []
        for i in range(4):
            labels, values, _, _ = self._chart_data_for_range(i)
            n = len(labels)
            cw = max(800, n * 65 + 100)
            ch = max(300, 200 + n * 4)
            pixmap = self._render_chart_pixmap(labels, values, width=cw, height=ch)
            chart_b64s.append(self._pixmap_to_base64(pixmap, (cw, ch)))

        stats = self.stats or {}
        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')

        sorted_records = sorted(self._all_records, key=lambda r: r['editing_time'], reverse=True)
        rows = ''
        for rec in sorted_records:
            thumb_b64 = self._pixmap_to_base64(rec.get('thumbnail'), (80, 80))
            thumb_html = f'<img src="data:image/png;base64,{thumb_b64}" alt="">' if thumb_b64 else ''
            canvas = f"{rec['canvas_width']}\u00d7{rec['canvas_height']}" if rec['canvas_width'] > 0 else '-'
            ctime = rec['created_time'].strftime('%Y-%m-%d %H:%M') if rec['created_time'] else '-'
            mtime = rec['modified_time'].strftime('%Y-%m-%d %H:%M') if rec['modified_time'] else '-'
            etime = self.format_time(rec['editing_time'])
            etime_val = rec['editing_time']
            cv = rec['canvas_width'] * rec['canvas_height'] if rec['canvas_width'] > 0 else 0
            rows += f'''<tr>
            <td class="thumb">{thumb_html}</td>
            <td data-value="{rec['name'].lower()}">{rec['name']}</td>
            <td data-value="{etime_val}">{etime}</td>
            <td data-value="{ctime}">{ctime}</td>
            <td data-value="{mtime}">{mtime}</td>
            <td data-value="{cv}">{canvas}</td>
        </tr>
'''

        total_time = self.format_time(stats.get('total_time', 0))
        earliest = stats['earliest_created'].strftime('%Y-%m-%d') if stats.get('earliest_created') else '-'
        latest = stats['latest_modified'].strftime('%Y-%m-%d') if stats.get('latest_modified') else '-'
        author_name = self._get_krita_author_name()
        contact_result = self._get_krita_contact_fields()
        contact_parts = [f'<strong>{label}:</strong> {val}' for label, val in contact_result]
        contact_html = ' | '.join(contact_parts) if contact_parts else ''
        up_arrow = '\u2191'
        down_arrow = '\u2193'
        tr_report_title = self._tr('Krita 绘画统计报告', 'Krita Painting Statistics Report')
        tr_export_pdf = self._tr('导出为 PDF', 'Export as PDF')
        tr_total_files = self._tr('文件总数', 'Total Files')
        tr_total_time_label = self._tr('总编辑时间', 'Total Editing Time')
        tr_author_contacts = self._tr('作者联系方式', 'Author Contacts')
        tr_earliest = self._tr('最早作品', 'Earliest')
        tr_latest = self._tr('最近作品', 'Latest')
        tr_month = self._tr('本月', 'Month')
        tr_year = self._tr('本年', 'Year')
        tr_thumbnail = self._tr('缩略图', 'Preview')
        tr_filename = self._tr('文件名', 'Filename')
        tr_edit_time = self._tr('编辑时间', 'Edit Time')
        tr_created = self._tr('创建时间', 'Created')
        tr_modified = self._tr('修改时间', 'Modified')
        tr_canvas = self._tr('画布大小', 'Canvas Size')
        tr_generated = self._tr('由 Krita统计插件 生成', 'Generated by Krita Statistics Plugin')

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Krita 绘画统计报告{f' - {author_name}' if author_name else ''}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 20px auto; padding: 0 16px; color: #333; }}
h1 {{ color: #2c3e50; border-bottom: 2px solid #4a9eff; padding-bottom: 8px; }}
.summary {{ background: #f8f9fa; padding: 16px; border-radius: 8px; margin: 16px 0; line-height: 1.8; }}
.btn-print {{ background: #4a9eff; color: #fff; border: none; padding: 10px 24px; border-radius: 4px; font-size: 14px; cursor: pointer; float: right; }}
.btn-print:hover {{ background: #357abd; }}
.chart {{ text-align: center; margin: 16px 0; }}
.chart h3 {{ margin: 16px 0 4px; color: #555; font-size: 14px; }}
.chart img {{ max-width: 100%; border: 1px solid #dee2e6; border-radius: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
th, td {{ border: 1px solid #dee2e6; padding: 8px; text-align: left; font-size: 13px; }}
th {{ background: #4a9eff; color: white; cursor: pointer; }}
th:hover {{ background: #357abd; }}
th .arrow {{ font-size: 11px; margin-left: 4px; }}
tr:nth-child(even) {{ background: #f8f9fa; }}
tr:nth-child(even) {{ background: #f8f9fa; }}
.thumb img {{ width: 80px; height: 80px; object-fit: cover; border-radius: 4px; }}
@media print {{ .btn-print {{ display: none; }} body {{ margin: 0; padding: 8px; }} }}
</style>
</head>
<body>
<button class="btn-print" onclick="window.print()">{tr_export_pdf}</button>
<h1>{tr_report_title}{f' - {author_name}' if author_name else ''}</h1>
<div class="summary">
<p><strong>{tr_total_files}:</strong> {stats.get('total_count', 0)} | <strong>{tr_total_time_label}:</strong> {total_time}</p>
<p><strong>{tr_author_contacts}:</strong></p>
<p>{contact_html}</p>
<p><strong>{tr_earliest}:</strong> {earliest} | <strong>{tr_latest}:</strong> {latest}</p>
<p><strong>{tr_month}:</strong> {self.format_time(stats.get('month_time', 0))} | <strong>{tr_year}:</strong> {self.format_time(stats.get('year_time', 0))}</p>
</div>
<div class="chart">
{''.join(f'<h3>{chart_names[i]}</h3><img src="data:image/png;base64,{chart_b64s[i]}" alt="{chart_names[i]}">' for i in range(4))}
</div>
<table id="sort-table">
<tr><th>{tr_thumbnail}</th><th onclick="sortTable(1)">{tr_filename} <span class="arrow"></span></th><th onclick="sortTable(2)">{tr_edit_time} <span class="arrow"></span></th><th onclick="sortTable(3)">{tr_created} <span class="arrow"></span></th><th onclick="sortTable(4)">{tr_modified} <span class="arrow"></span></th><th onclick="sortTable(5)">{tr_canvas} <span class="arrow"></span></th></tr>
{rows}
</table>
<script>
let sortDir = [0,0,0,0,0,0];
function sortTable(col) {{
  const table = document.getElementById('sort-table');
  const tbody = table.querySelector('tbody') || table;
  const rows = Array.from(tbody.querySelectorAll('tr'));
  if (rows.length === 0) return;
  const header = rows.shift();
  sortDir[col] = sortDir[col] === 1 ? -1 : 1;
  const dir = sortDir[col];
  rows.sort((a, b) => {{
    let va = (a.cells[col].getAttribute('data-value') || a.cells[col].textContent).trim();
    let vb = (b.cells[col].getAttribute('data-value') || b.cells[col].textContent).trim();
    let na = parseFloat(va), nb = parseFloat(vb);
    if (!isNaN(na) && !isNaN(nb)) return (na - nb) * dir;
    return va.localeCompare(vb) * dir;
  }});
  tbody.innerHTML = '';
  tbody.appendChild(header);
  rows.forEach(r => tbody.appendChild(r));
  document.querySelectorAll('#sort-table th .arrow').forEach((el, i) => {{
    el.textContent = i+1 === col ? (dir === 1 ? '{up_arrow}' : '{down_arrow}') : '';
  }});
}}
</script>
<p style="text-align:center;color:#999;margin-top:32px;">{tr_generated} | {now_str}</p>
<p style="text-align:center;color:#999;font-size:12px;">\u63D2\u4EF6\u4F5C\u8005\uFF1A\u8336\u6E05\u58A8\u5202 | \u4E3B\u9875\uFF1A<a href="https://space.bilibili.com/388428308" style="color:#fb7299;">\u54D4\u54E9\u54D4\u54E9</a> | \u8D5E\u52A9\uFF1A<a href="https://space.bilibili.com/388428308/charge" style="color:#fb7299;">B\u7AD9\u5145\u7535</a></p>
</body>
</html>'''

        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            from PyQt5.QtCore import QUrl
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, self._tr('导出失败', 'Export Failed'), str(e))


class AlbumScrollArea(QScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize_callback = None
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._emit_resize)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._debounce.start(100)

    def _emit_resize(self):
        if self.resize_callback:
            self.resize_callback()

    def cancel_debounce(self):
        self._debounce.stop()


class ChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.labels = []
        self.values = []
        self.chart_type = 0
        self.setMinimumSize(500, 260)

    def set_data(self, labels, values, chart_type=0):
        self.labels = labels
        self.values = values
        self.chart_type = chart_type
        self.update()

    def _get_points(self, ml, mt, cw, ch, max_val):
        n = len(self.labels)
        bw = max(6, min(36, cw // n - 4))
        gap = (cw - bw * n) // (n + 1) if n > 1 else cw // 3
        pts = []
        for i, val in enumerate(self.values):
            x = ml + gap + i * (bw + gap) + bw / 2
            bh = int((val / max_val) * ch) if max_val else 0
            y = mt + ch - bh
            pts.append(QPointF(x, y))
        return pts, bw, gap

    def paintEvent(self, event):
        if not self.labels:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        ml, mr, mt, mb = 55, 16, 20, 50
        cw, ch = w - ml - mr, h - mt - mb
        max_val = max(self.values) or 1

        p.setPen(QPen(QColor('#ccc'), 1))
        p.drawLine(ml, mt, ml, mt + ch)
        p.drawLine(ml, mt + ch, ml + cw, mt + ch)

        y_ticks = 4
        for i in range(y_ticks + 1):
            val = max_val * i // y_ticks
            yy = mt + ch - int(ch * i / y_ticks)
            p.setPen(QPen(QColor('#eee'), 1))
            p.drawLine(ml + 1, yy, ml + cw, yy)
            p.setPen(QColor('#999'))
            f = p.font()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(0, yy - 8, ml - 8, 16), Qt.AlignRight | Qt.AlignVCenter, self._fmt_val(val))

        n = len(self.labels)
        bw = max(6, min(36, cw // n - 4))
        gap = (cw - bw * n) // (n + 1) if n > 1 else cw // 3

        if self.chart_type == 0:
            self._draw_bars(p, ml, mt, cw, ch, max_val, bw, gap)
        elif self.chart_type == 1:
            self._draw_line(p, ml, mt, cw, ch, max_val, bw, gap, False)
        else:
            self._draw_line(p, ml, mt, cw, ch, max_val, bw, gap, True)

        for i, label in enumerate(self.labels):
            x = ml + gap + i * (bw + gap)
            p.setPen(QColor('#999'))
            f = p.font()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(x - 4, mt + ch + 4, bw + 8, 40), Qt.AlignCenter | Qt.TextWordWrap, label)

    def _draw_bars(self, p, ml, mt, cw, ch, max_val, bw, gap):
        for i, val in enumerate(self.values):
            x = ml + gap + i * (bw + gap)
            bh = int((val / max_val) * ch) if max_val else 0
            y = mt + ch - bh
            p.setBrush(QColor('#4a9eff'))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, y, bw, bh, 2, 2)
            p.setPen(QColor('#999'))
            f = p.font()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(x, y - 16, bw, 14), Qt.AlignCenter, self._fmt_val(val))

    def _draw_line(self, p, ml, mt, cw, ch, max_val, bw, gap, smooth):
        pts = [QPointF(ml + gap + i * (bw + gap) + bw / 2, mt + ch) for i in range(len(self.values))]
        for i, val in enumerate(self.values):
            bh = int((val / max_val) * ch) if max_val else 0
            pts[i].setY(mt + ch - bh)

        path = QPainterPath()
        path.moveTo(pts[0].x(), mt + ch)
        path.lineTo(pts[0])
        if smooth and len(pts) > 2:
            for i in range(len(pts) - 1):
                cpx = (pts[i].x() + pts[i + 1].x()) / 2
                path.cubicTo(cpx, pts[i].y(), cpx, pts[i + 1].y(), pts[i + 1].x(), pts[i + 1].y())
        else:
            for i in range(1, len(pts)):
                path.lineTo(pts[i])
        path.lineTo(pts[-1].x(), mt + ch)
        path.closeSubpath()

        p.setBrush(QColor(74, 158, 255, 30))
        p.setPen(QPen(QColor('#4a9eff'), 2))
        p.drawPath(path)

        p.setBrush(QColor('#4a9eff'))
        for pt in pts:
            p.drawEllipse(pt, 3, 3)

        for i, val in enumerate(self.values):
            p.setPen(QColor('#999'))
            f = p.font()
            f.setPointSize(7)
            p.setFont(f)
            p.drawText(QRectF(pts[i].x() - bw / 2, pts[i].y() - 16, bw, 14), Qt.AlignCenter, self._fmt_val(val))

    @staticmethod
    def _fmt_val(val):
        if val < 60:
            return f'{val}s'
        if val < 3600:
            return f'{val // 60}m'
        return f'{val // 3600}h'


instance = Krita.instance()
dock_widget_factory = DockWidgetFactory(
    DOCKER_ID,
    DockWidgetFactoryBase.DockPosition.DockRight,
    Krita统计插件
)
instance.addDockWidgetFactory(dock_widget_factory)