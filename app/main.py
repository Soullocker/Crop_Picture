from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QRectF, QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QSpinBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.crop_picture import (  # noqa: E402
    IMAGE_EXTENSIONS, CropCancelled, build_destination, collect_images, load_preview_image, preview_file, process_file,
)
from app.native_input_dialog import InputSelection, choose_input  # noqa: E402


InputSignature = tuple[tuple[str, int, int], ...]
APP_VERSION = "2.2.0"
CropParameters = tuple[int, int, int, int]
CropRecord = tuple[InputSignature, str, CropParameters]


def resource_path(*parts: str) -> Path:
    """兼容源码运行和 PyInstaller 打包后的资源路径。"""
    bundle_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return bundle_root.joinpath(*parts)


ASSET_ICON_CANDIDATES = (
    resource_path("assets", "app_icon.ico"),
    resource_path("assets", "app_icon.png"),
    resource_path("assets", "app_icon.jpg"),
    resource_path("assets", "app_icon.jpeg"),
)


def load_app_icon() -> QIcon:
    """优先加载自定义窗口图标，找不到时回退到默认图标。"""
    for icon_path in ASSET_ICON_CANDIDATES:
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                return icon
    return QIcon()


class CropWorker(QThread):
    """在后台线程中执行裁剪，避免界面卡住。"""

    log_message = Signal(str)
    progress_changed = Signal(int, int)
    finished_summary = Signal(int, int, int)
    cancelled_summary = Signal(int, int, int)
    file_processed = Signal(str, str)
    failed = Signal(str)

    def __init__(
        self,
        input_path: Path,
        output_dir: Path,
        padding: int,
        tolerance: int,
        alpha_threshold: int,
        svg_render_pixels: int,
        image_files: list[Path] | None = None,
        same_folder_output: bool = False,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.padding = padding
        self.tolerance = tolerance
        self.alpha_threshold = alpha_threshold
        self.svg_render_pixels = svg_render_pixels
        self.image_files = image_files
        self.same_folder_output = same_folder_output

    def run(self) -> None:
        """收集并裁剪图片，把过程通过信号传回界面。"""
        try:
            image_files = self.image_files if self.image_files is not None else collect_images(self.input_path)
        except SystemExit as error:
            self.failed.emit(str(error))
            return
        except Exception as error:
            self.failed.emit(f"读取输入路径失败：{error}")
            return

        if not image_files:
            self.failed.emit("没有找到可裁剪的图片。")
            return

        changed = 0
        kept = 0
        skipped = 0
        total = len(image_files)
        self.log_message.emit(f"共找到 {total} 张可处理图片。")

        for index, source in enumerate(image_files, start=1):
            if self.isInterruptionRequested():
                self.cancelled_summary.emit(changed, kept, skipped)
                return
            try:
                output_dir = source.parent if self.same_folder_output else self.output_dir
                destination = build_destination(source, source, output_dir)
                result = process_file(
                    source,
                    destination,
                    self.tolerance,
                    self.alpha_threshold,
                    self.padding,
                    self.svg_render_pixels,
                    self.isInterruptionRequested,
                )
            except CropCancelled:
                self.cancelled_summary.emit(changed, kept, skipped)
                return
            except Exception as error:
                skipped += 1
                self.log_message.emit(f"跳过 {source.name}：{error}")
                self.progress_changed.emit(index, total)
                continue

            if "->" in result:
                changed += 1
            else:
                kept += 1
            self.log_message.emit(f"{source.name}: {result}")
            self.file_processed.emit(str(source), str(destination))
            self.progress_changed.emit(index, total)

        self.finished_summary.emit(changed, kept, skipped)


class PreviewWorker(QThread):
    """在后台生成裁剪预览，不创建或覆盖任何输出图片。"""

    preview_ready = Signal(object, object, str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, source: Path, parameters: CropParameters, destination: Path | None = None) -> None:
        super().__init__()
        self.source = source
        self.parameters = parameters
        self.destination = destination

    def run(self) -> None:
        padding, tolerance, alpha_threshold, svg_pixels = self.parameters
        try:
            if self.destination is None:
                before, after, description = preview_file(
                    self.source, tolerance, alpha_threshold, padding, svg_pixels, self.isInterruptionRequested
                )
            else:
                # 实际输出预览也在后台读取，避免大图和 SVG 渲染阻塞界面。
                before = load_preview_image(self.source, svg_pixels, self.isInterruptionRequested)
                after = load_preview_image(self.destination, svg_pixels, self.isInterruptionRequested)
                description = f"实际输出：{before.width} × {before.height} → {after.width} × {after.height}"
                if self.source.suffix.lower() == ".svg":
                    description = "SVG 实际输出（检测图预览）"
                before.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                after.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        except CropCancelled:
            self.cancelled.emit()
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.preview_ready.emit(before, after, description)


class PreviewLabel(QLabel):
    """随窗口缩放预览图，保持比例，透明区域显示为浅灰底。"""

    def __init__(self) -> None:
        super().__init__("尚未预览")
        self.original_pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet("background: #f0f2f5; border: 1px solid #d8dce2; border-radius: 4px;")

    def set_preview_image(self, image: Image.Image | None) -> None:
        """Pillow 图像转为独立 Qt 图像，避免后台图像对象释放后仍引用其内存。"""
        self.original_pixmap = QPixmap.fromImage(ImageQt(image).copy()) if image is not None else QPixmap()
        self.refresh_pixmap()

    def refresh_pixmap(self) -> None:
        if self.original_pixmap.isNull():
            self.clear()
            self.setText("尚未预览")
        else:
            self.setPixmap(self.original_pixmap.scaled(
                self.contentsRect().size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refresh_pixmap()


class MainWindow(QMainWindow):
    """支持预览、取消和持久化设置的裁剪界面。"""

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.worker: CropWorker | None = None
        self.preview_worker: PreviewWorker | None = None
        self.close_pending = False
        self.settings = settings if settings is not None else QSettings("Soullocker", "CropPicture")
        self.current_input_path: Path | None = None
        self.selected_input_files: tuple[Path, ...] = ()
        self.current_output_path: Path | None = None
        self.current_input_signature: InputSignature = ()
        self.current_parameters: CropParameters = (5, 12, 8, 2400)
        self.crop_records: dict[str, CropRecord] = {}
        self.preview_results: dict[str, Path] = {}
        self.crop_summary: tuple[int, int, int] | None = None
        self.setWindowTitle(f"科研图片裁剪 v{APP_VERSION}")
        self.resize(1280, 820)
        self.setFont(QFont("Microsoft YaHei UI", 11))
        app_icon = load_app_icon()
        self.setWindowIcon(app_icon if not app_icon.isNull() else self.build_message_icon("app"))
        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei UI";
                font-size: 11pt;
            }
            QLabel#TitleLabel {
                color: #1f2933;
                font-size: 18pt;
                font-weight: 700;
            }
            QLabel#SubtitleLabel {
                color: #555555;
                font-size: 10.5pt;
            }
            QGroupBox {
                border: 1px solid #d8dce2;
                border-radius: 6px;
                color: #1f2933;
                margin-top: 12px;
                padding: 16px 16px 14px 16px;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                min-height: 30px;
                padding: 4px 10px;
            }
            QPushButton#StartButton {
                background-color: #1769e0;
                border: 1px solid #155bc1;
                border-radius: 5px;
                color: white;
                font-weight: 700;
                min-width: 112px;
            }
            QPushButton#StartButton:disabled {
                background-color: #9bbbea;
                border-color: #8aa8d4;
            }
            QLineEdit, QSpinBox {
                min-height: 28px;
            }
            QSpinBox, QProgressBar {
                font-family: "Times New Roman";
            }
            QProgressBar {
                border: 1px solid #c8cdd4;
                border-radius: 4px;
                height: 18px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #1769e0;
                border-radius: 3px;
            }
            QPlainTextEdit, QTextBrowser {
                font-family: "Microsoft YaHei UI";
                font-size: 10.5pt;
            }
            QFrame#HelpPanel {
                border: 1px solid #d8dce2;
                border-radius: 6px;
                background: #ffffff;
            }
            """
        )

        self.input_edit = QLineEdit()
        self.input_selection_status = QLabel("请选择图片或文件夹。")
        self.input_selection_status.setWordWrap(True)
        self.output_edit = QLineEdit()
        self.same_folder_check = QCheckBox("输出到原文件夹（裁剪后的文件自动添加“裁剪_”前缀）")
        self.padding_spin = self.create_spin_box(0, 200, 5)
        self.tolerance_spin = self.create_spin_box(0, 255, 12)
        self.alpha_spin = self.create_spin_box(0, 255, 8)
        self.svg_pixels_spin = self.create_spin_box(64, 8000, 2400)

        self.start_button = QPushButton("开始裁剪")
        self.start_button.setObjectName("StartButton")
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setEnabled(False)
        self.preview_button = QPushButton("预览裁剪")
        self.preview_combo = QComboBox()
        self.preview_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preview_combo.setMinimumContentsLength(12)
        self.preview_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.before_preview = PreviewLabel()
        self.after_preview = PreviewLabel()
        self.preview_status = QLabel("选择图片后点击预览，确认效果再开始裁剪。")
        self.preview_status.setWordWrap(True)
        self.open_output_button = QPushButton("打开输出文件夹")
        self.open_output_button.setEnabled(False)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_status = QLabel("进度：尚未开始")
        self.progress_status.setObjectName("SubtitleLabel")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("裁剪日志会显示在这里。")
        self.log.setMinimumHeight(230)

        self.build_ui()
        self.restore_settings()
        self.connect_signals()
        self.refresh_preview_sources()

    def create_spin_box(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin_box = QSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        spin_box.setFixedWidth(128)
        return spin_box

    def build_ui(self) -> None:
        """创建窗口布局。"""
        self.input_button = QPushButton("选择图片或文件夹")
        self.input_button.setToolTip("不选图片时选择当前文件夹；选中一张或多张图片时仅处理所选图片。")
        self.output_folder_button = QPushButton("选择输出文件夹")
        self.input_button.clicked.connect(self.choose_input)
        self.output_folder_button.clicked.connect(self.choose_output_folder)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_edit)
        input_row.addWidget(self.input_button)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit)
        output_row.addWidget(self.output_folder_button)

        input_form = QFormLayout()
        input_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        input_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        input_form.setContentsMargins(16, 10, 16, 10)
        input_form.setHorizontalSpacing(16)
        input_form.setVerticalSpacing(12)
        input_form.addRow("输入图片或文件夹", input_row)
        input_form.addRow("处理范围", self.input_selection_status)
        input_form.addRow("输出文件夹", output_row)
        input_form.addRow("", self.same_folder_check)

        parameter_grid = QGridLayout()
        parameter_grid.setContentsMargins(16, 10, 16, 10)
        parameter_grid.setHorizontalSpacing(10)
        parameter_grid.setVerticalSpacing(12)
        parameter_grid.addLayout(self.make_parameter_row("保留边距", self.padding_spin), 0, 0)
        parameter_grid.addLayout(self.make_parameter_row("背景容差", self.tolerance_spin), 0, 1)
        parameter_grid.addLayout(self.make_parameter_row("透明判断阈值", self.alpha_spin), 1, 0)
        parameter_grid.addLayout(self.make_parameter_row("SVG 检测尺寸", self.svg_pixels_spin), 1, 1)
        parameter_grid.setColumnStretch(0, 1)
        parameter_grid.setColumnStretch(1, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(16, 10, 16, 10)
        actions.setSpacing(18)
        actions.addStretch()
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.open_output_button)
        actions.addStretch()

        title = QLabel("科研图片裁剪工具")
        title.setObjectName("TitleLabel")
        subtitle = QLabel("去除科研绘图、论文插图中的白边、透明边距和浅色背景边距")
        subtitle.setObjectName("SubtitleLabel")

        log_title = QLabel("处理日志")
        log_title.setObjectName("SubtitleLabel")

        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        left_layout.addWidget(title)
        left_layout.addWidget(subtitle)
        left_layout.addWidget(self.make_group_box("输入与输出", input_form))
        left_layout.addWidget(self.make_group_box("裁剪参数", parameter_grid))
        left_layout.addWidget(self.make_group_box("操作", actions))
        left_layout.addWidget(self.progress_status)
        left_layout.addWidget(self.progress)
        left_layout.addWidget(log_title)
        left_layout.addWidget(self.log, stretch=1)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(14)
        main_layout.addLayout(left_layout, stretch=3)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_layout.addWidget(self.build_preview_panel(), stretch=1)
        right_layout.addWidget(self.build_help_panel(), stretch=1)
        main_layout.addLayout(right_layout, stretch=2)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def make_group_box(self, title: str, layout: QFormLayout | QGridLayout | QHBoxLayout) -> QGroupBox:
        """把相关控件放进带标题的分组区域。"""
        group_box = QGroupBox(title)
        group_box.setLayout(layout)
        return group_box

    def build_message_icon(self, state: str, size: int = 48) -> QIcon:
        """生成统一风格的提示图标。"""
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        colors = {
            "app": QColor("#1769e0"),
            "question": QColor("#1769e0"),
            "success": QColor("#1f9d55"),
            "warning": QColor("#d9822b"),
        }
        background = colors.get(state, QColor("#1769e0"))
        accent = QColor("#ffffff")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))

        corner_pen = QPen(accent)
        corner_pen.setWidth(max(2, size // 9))
        corner_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(corner_pen)

        margin = size * 0.27
        corner = size * 0.14
        left = margin
        top = margin
        right = size - margin
        bottom = size - margin

        painter.drawLine(int(left), int(top), int(left + corner), int(top))
        painter.drawLine(int(left), int(top), int(left), int(top + corner))

        painter.drawLine(int(right - corner), int(top), int(right), int(top))
        painter.drawLine(int(right), int(top), int(right), int(top + corner))

        painter.drawLine(int(left), int(bottom - corner), int(left), int(bottom))
        painter.drawLine(int(left), int(bottom), int(left + corner), int(bottom))

        painter.drawLine(int(right - corner), int(bottom), int(right), int(bottom))
        painter.drawLine(int(right), int(bottom - corner), int(right), int(bottom))

        if state == "success":
            check_pen = QPen(accent)
            check_pen.setWidth(max(2, size // 10))
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.drawLine(int(size * 0.30), int(size * 0.54), int(size * 0.43), int(size * 0.68))
            painter.drawLine(int(size * 0.43), int(size * 0.68), int(size * 0.70), int(size * 0.36))
        elif state == "warning":
            exclamation_pen = QPen(accent)
            exclamation_pen.setWidth(max(2, size // 10))
            exclamation_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(exclamation_pen)
            painter.drawLine(int(size * 0.50), int(size * 0.30), int(size * 0.50), int(size * 0.58))
            painter.drawPoint(int(size * 0.50), int(size * 0.70))

        painter.end()
        return QIcon(pixmap)

    def show_message_box(
        self,
        title: str,
        text: str,
        informative_text: str = "",
        state: str = "question",
        buttons: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        default_button: QMessageBox.StandardButton = QMessageBox.StandardButton.Ok,
        preferred_width: int = 640,
        button_spacing: int = 24,
        main_text_wrap: bool = True,
        informative_text_wrap: bool = True,
    ) -> QMessageBox.StandardButton:
        """显示统一样式的提示框。"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        if informative_text:
            box.setInformativeText(informative_text)
        box.setStandardButtons(buttons)
        box.setDefaultButton(default_button)
        box.setIcon(QMessageBox.Icon.NoIcon)
        box.setIconPixmap(self.build_message_icon(state).pixmap(48, 48))
        box.setMinimumWidth(preferred_width)
        box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        main_label = box.findChild(QLabel, "qt_msgbox_label")
        if main_label is not None:
            main_label.setWordWrap(main_text_wrap)
            main_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )

        info_label = box.findChild(QLabel, "qt_msgbox_informativelabel")
        if info_label is not None:
            info_label.setWordWrap(informative_text_wrap)
            info_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )

        button_box = box.findChild(QDialogButtonBox)
        if button_box is not None:
            button_layout = button_box.layout()
            if button_layout is not None:
                button_layout.setSpacing(button_spacing)
                button_layout.setContentsMargins(0, 0, 0, 0)

            for button in button_box.findChildren(QPushButton):
                button.setMinimumWidth(104)
                button.setMinimumHeight(32)

        return QMessageBox.StandardButton(box.exec())

    def make_parameter_row(self, label_text: str, spin_box: QSpinBox) -> QHBoxLayout:
        """创建参数标签与数值框靠近排列的一组控件。"""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        label = QLabel(label_text)
        label.setMinimumWidth(96)
        layout.addWidget(label)
        layout.addWidget(spin_box)
        layout.addStretch()
        return layout

    def build_preview_panel(self) -> QWidget:
        """并排展示原图和裁剪效果，文件夹输入可选择其中任意原图。"""
        selection = QHBoxLayout()
        selection.addWidget(self.preview_combo, stretch=1)
        selection.addWidget(self.preview_button)
        images = QHBoxLayout()
        for title, preview in (("裁剪前", self.before_preview), ("裁剪后", self.after_preview)):
            column = QVBoxLayout()
            label = QLabel(title)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
            column.addWidget(preview, stretch=1)
            images.addLayout(column, stretch=1)
        layout = QVBoxLayout()
        layout.addLayout(selection)
        layout.addLayout(images, stretch=1)
        layout.addWidget(self.preview_status)
        panel = QGroupBox("裁剪效果预览")
        panel.setLayout(layout)
        return panel

    def get_parameters(self) -> CropParameters:
        """参数顺序在后台任务和持久化记录中保持一致。"""
        return (
            self.padding_spin.value(), self.tolerance_spin.value(),
            self.alpha_spin.value(), self.svg_pixels_spin.value(),
        )

    def restore_settings(self) -> None:
        """启动时恢复参数、路径和上次成功任务记录；损坏记录不阻止软件启动。"""
        for key, spin in (
            ("padding", self.padding_spin), ("tolerance", self.tolerance_spin),
            ("alpha_threshold", self.alpha_spin), ("svg_render_pixels", self.svg_pixels_spin),
        ):
            try:
                spin.setValue(int(self.settings.value(key, spin.value())))
            except (TypeError, ValueError):
                continue
        self.input_edit.setText(str(self.settings.value("input_path", "")))
        try:
            selected = json.loads(str(self.settings.value("input_files", "[]")))
            if isinstance(selected, list) and all(isinstance(path, str) for path in selected):
                self.selected_input_files = tuple(Path(path) for path in selected)
        except (TypeError, ValueError):
            pass
        self.update_selection_status()
        self.output_edit.setText(str(self.settings.value("output_path", "")))
        self.same_folder_check.setChecked(self.settings.value("same_folder", False, type=bool))
        self.toggle_same_folder_output(self.same_folder_check.isChecked())
        try:
            records = json.loads(str(self.settings.value("crop_records", "{}")))
            if not isinstance(records, dict):
                return
            for key, record in records.items():
                try:
                    signature, output, parameters = record
                    if not isinstance(output, str) or len(parameters) != 4:
                        continue
                    entries = tuple((str(name), int(size), int(mtime)) for name, size, mtime in signature)
                    values = tuple(int(value) for value in parameters)
                    self.crop_records[key] = (entries, output, (values[0], values[1], values[2], values[3]))
                except (TypeError, ValueError):
                    continue
        except (TypeError, ValueError):
            self.log_message("历史裁剪记录无法读取，将从新的任务开始记录。")

    def save_settings(self) -> None:
        """保存在当前用户配置中，源码运行和打包运行共用同一份设置。"""
        for key, value in zip(
            ("padding", "tolerance", "alpha_threshold", "svg_render_pixels"), self.get_parameters()
        ):
            self.settings.setValue(key, value)
        self.settings.setValue("input_path", self.input_edit.text().strip())
        self.settings.setValue("input_files", json.dumps([str(path) for path in self.selected_input_files], ensure_ascii=False))
        self.settings.setValue("output_path", self.output_edit.text().strip())
        self.settings.setValue("same_folder", self.same_folder_check.isChecked())
        # 限制历史输入位置数量，避免长期使用后无限增长。
        self.crop_records = dict(list(self.crop_records.items())[-100:])
        self.settings.setValue("crop_records", json.dumps(self.crop_records, ensure_ascii=False))
        self.settings.sync()
        if self.settings.status() != QSettings.Status.NoError:
            self.log_message("设置保存失败，请检查当前用户配置的写入权限。")

    def refresh_preview_sources(self) -> None:
        """更新预览列表；手工输入路径尚未完成时不弹出错误提示。"""
        previous_source = self.preview_combo.currentData()
        self.preview_results.clear()
        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        try:
            text = self.input_edit.text().strip()
            images = self.get_input_files(Path(text).expanduser().resolve()) if text else []
        except (SystemExit, OSError, ValueError):
            images = []
        for image in images:
            self.preview_combo.addItem(image.name, str(image))
        previous_index = self.preview_combo.findData(previous_source) if previous_source else -1
        if previous_index >= 0:
            self.preview_combo.setCurrentIndex(previous_index)
        self.preview_combo.blockSignals(False)
        self.preview_button.setEnabled(bool(images) and self.worker is None and self.preview_worker is None)
        self.clear_preview()

    def clear_preview(self) -> None:
        """切换输入或参数时清空旧预览，避免把旧效果误认为当前结果。"""
        self.before_preview.set_preview_image(None)
        self.after_preview.set_preview_image(None)
        self.preview_status.setText("点击“预览裁剪”查看当前参数效果，预览不会保存文件。")

    def start_preview(self) -> None:
        """输出路径未选择时也可预览，先判断参数是否合适。"""
        if self.worker is not None or self.preview_worker is not None:
            return
        source_text = self.preview_combo.currentData()
        if not source_text:
            self.show_message_box("缺少图片", "请先选择图片或包含原图的文件夹。", state="warning")
            return
        self.begin_preview(Path(source_text))

    def begin_preview(self, source: Path, destination: Path | None = None) -> None:
        """预览当前参数效果或已经保存的实际输出，共用后台线程生命周期。"""
        if self.worker is not None or self.preview_worker is not None:
            return
        self.save_settings()
        self.preview_status.setText("正在计算预览，可点击“取消任务”停止。")
        self.preview_worker = PreviewWorker(source, self.get_parameters(), destination)
        self.preview_worker.preview_ready.connect(self.show_preview)
        self.preview_worker.failed.connect(self.fail_preview)
        self.preview_worker.cancelled.connect(self.cancel_preview_finished)
        self.preview_worker.finished.connect(self.preview_thread_finished)
        self.set_running_state(True)
        self.preview_worker.start()

    def show_preview(self, before: Image.Image, after: Image.Image, description: str) -> None:
        """仅在界面线程创建并展示 Qt 位图。"""
        self.before_preview.set_preview_image(before)
        self.after_preview.set_preview_image(after)
        self.preview_status.setText(description)

    def fail_preview(self, message: str) -> None:
        """预览失败不影响已有输出，也不记录为成功任务。"""
        self.preview_status.setText(f"预览失败：{message}")
        self.log_message(f"预览失败：{message}")

    def cancel_preview_finished(self) -> None:
        """取消预览后保留此前的裁剪任务状态。"""
        self.preview_status.setText("预览已取消，未保存任何输出文件。")

    def preview_thread_finished(self) -> None:
        """等待线程真正结束后才能恢复按钮和释放线程对象。"""
        if self.preview_worker is not None:
            self.preview_worker.deleteLater()
            self.preview_worker = None
        self.set_running_state(False)
        if self.close_pending:
            QTimer.singleShot(0, self.close)

    def remember_preview_result(self, source: str, destination: str) -> None:
        """记录正式输出路径，批量处理后可按原图名称查看实际保存结果。"""
        self.preview_results[source] = Path(destination)

    def preview_selection_changed(self) -> None:
        """已有正式输出时显示它，否则等待用户计算预览。"""
        self.clear_preview()
        source = self.preview_combo.currentData()
        destination = self.preview_results.get(source)
        if not source or destination is None or not destination.exists():
            return
        self.begin_preview(Path(source), destination)

    def build_help_panel(self) -> QWidget:
        """创建右侧中文说明栏。"""
        panel = QFrame()
        panel.setObjectName("HelpPanel")
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        panel.setMinimumWidth(320)

        text = QTextBrowser()
        text.setOpenExternalLinks(False)
        text.setHtml(
            """
            <style>
              body { font-family: "Microsoft YaHei UI"; font-size: 13pt; line-height: 1.75; }
              h2 { color: #1f2933; font-size: 16pt; margin: 6px 0 10px 0; }
              h3 { color: #1f2933; font-size: 14pt; margin: 20px 0 10px 0; }
              b { color: #1f2933; }
              p { margin: 8px 0; }
              li { margin: 9px 0; }
            </style>
            <h2>说明</h2>

            <h3>基础用法</h3>
            <ol>
              <li>点击 <b>选择图片或文件夹</b>。没有选中图片时，点击 <b>选择该文件夹</b> 批量处理目录中的原图；选中一张或多张图片后，点击 <b>处理所选图片</b>，只处理这些图片。可以按住 Ctrl 或 Shift 多选。</li>
              <li>按文件夹批量处理时会跳过文件名以“裁剪_”开头的图片；明确选择的图片仍可单独处理。</li>
              <li>选择输出文件夹；如果勾选 <b>输出到原文件夹</b>，结果会自动添加“裁剪_”前缀，避免覆盖原图。重新裁剪原图时，会覆盖更新同名裁剪结果。</li>
              <li>可先在右上方选择图片，点击 <b>预览裁剪</b> 查看前后效果；预览不会保存文件。满意后点击 <b>开始裁剪</b>。</li>
              <li>计算预览或裁剪时可以点击 <b>取消任务</b>。已经完成的输出会保留，尚未处理的图片不再继续。</li>
              <li>软件会自动记住参数和路径。成功任务的重复裁剪记录在关闭软件后仍保留；原图或参数变化后允许重新处理。</li>
            </ol>

            <h3>参数说明</h3>
            <ol>
              <li><b>保留边距：</b>裁剪后额外留下的空白边，数值越大，结果越不容易裁得过紧。</li>
              <li><b>背景容差：</b>判断背景和内容的颜色差异。白底、浅灰底通常用默认值即可；如果浅色背景裁不干净，可以适当增大；如果浅色文字或坐标轴被裁掉，可以适当减小。</li>
              <li><b>透明判断阈值：</b>用于处理透明背景图片。数值越大，越多接近透明的像素会被当作空白。</li>
              <li><b>SVG 检测尺寸：</b>只影响 SVG 矢量图。程序会临时把 SVG 渲染成一张检测图来判断边界，这个数值就是检测图最长边的大致像素数。数值越大，检测越细，但速度会慢一些。普通 PNG、JPG、WebP 等位图不受这个参数影响。</li>
              <li><b>无需裁剪：</b>程序已经检测过图片，判断当前内容不需要去边时，会把原图原样复制到输出文件夹，不会改动图片内容。</li>
              <li><b>裁剪失败：</b>图片损坏、格式异常或边界检测出错时，会跳过当前图片并在日志里提示原因，后面的图片会继续处理。</li>
            </ol>

            <h3>适用范围</h3>
            <ol>
              <li>.png/.jpg/.jpeg/.bmp/.tif/.tiff/.webp/.gif/.ppm/.pgm/.pbm/.pnm/.svg等格式均可裁剪</li>
              <li><b>适合</b>科研绘图中的插图、白底图、透明底图、浅色纯色背景和平滑渐变背景。</li>
              <li><b>不适合</b>作为通用照片主体裁剪工具。</li>
            </ol>
            """
        )

        layout = QVBoxLayout()
        layout.addWidget(text)
        panel.setLayout(layout)
        return panel

    def connect_signals(self) -> None:
        self.same_folder_check.toggled.connect(self.toggle_same_folder_output)
        self.start_button.clicked.connect(self.start_crop)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.preview_button.clicked.connect(self.start_preview)
        self.cancel_button.clicked.connect(self.cancel_task)
        self.input_edit.textChanged.connect(self.input_text_changed)
        self.preview_combo.currentIndexChanged.connect(self.preview_selection_changed)
        for spin in (self.padding_spin, self.tolerance_spin, self.alpha_spin, self.svg_pixels_spin):
            spin.valueChanged.connect(self.parameters_changed)

    def parameters_changed(self) -> None:
        """参数变化立即保存，并使旧预览失效。"""
        self.preview_results.clear()
        self.clear_preview()
        self.save_settings()

    def choose_input(self) -> None:
        """一个原生入口同时支持目录、单图和多图，取消时保持原输入。"""
        current_text = self.input_edit.text().strip()
        current_path = Path(current_text).expanduser() if current_text else Path.home()
        if current_path.is_file():
            current_path = current_path.parent
        try:
            selection = choose_input(int(self.winId()), current_path)
        except Exception as error:
            self.show_message_box("选择失败", "无法打开图片和文件夹选择窗口。", str(error), state="warning")
            return
        if selection is not None:
            self.apply_input_selection(selection)

    def apply_input_selection(self, selection: InputSelection) -> None:
        """保存明确的文件清单，避免多选后意外扩展成整个目录。"""
        files = tuple(dict.fromkeys(path.resolve() for path in selection.files))
        if not files and selection.folder is None:
            return
        text = str(files[0] if len(files) == 1 else files[0].parent) if files else str(selection.folder)
        self.input_edit.blockSignals(True)
        self.input_edit.setText(text)
        self.input_edit.blockSignals(False)
        self.selected_input_files = files
        self.update_selection_status()
        self.refresh_preview_sources()
        if self.same_folder_check.isChecked():
            self.toggle_same_folder_output(True)
        self.save_settings()

    def update_selection_status(self) -> None:
        """明确展示当前处理范围，多图时防止手工编辑目录而丢失选择含义。"""
        self.input_edit.setReadOnly(len(self.selected_input_files) > 1)
        if self.selected_input_files:
            count = len(self.selected_input_files)
            text = f"已选择 {count} 张图片，仅处理所选图片。"
            if len({path.parent for path in self.selected_input_files}) > 1:
                text += "原目录输出时，各结果保存到各自图片所在目录。"
        elif self.input_edit.text().strip():
            path = Path(self.input_edit.text().strip()).expanduser()
            text = "处理此文件夹中的原图，跳过“裁剪_”图片。" if path.is_dir() else "处理此单张图片。"
        else:
            text = "请选择图片或文件夹。"
        self.input_selection_status.setText(text)

    def input_text_changed(self) -> None:
        """手工修改输入路径后恢复按路径处理，不沿用此前明确选择的文件清单。"""
        self.selected_input_files = ()
        self.update_selection_status()
        self.refresh_preview_sources()

    def get_input_files(self, input_path: Path) -> list[Path]:
        """明确选择不应用目录前缀过滤；目录模式继续排除已有裁剪结果。"""
        if not self.selected_input_files:
            return collect_images(input_path)
        for path in self.selected_input_files:
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError(f"所选图片不存在或格式不支持：{path}")
        return list(self.selected_input_files)

    def record_key(self, input_path: Path) -> str:
        """不同的多图选择分别保存历史，不能用其所在目录替代选择范围。"""
        if len(self.selected_input_files) <= 1:
            return self.normalize_path_key(input_path)
        paths = sorted(self.normalize_path_key(path) for path in self.selected_input_files)
        return "files:" + hashlib.sha256(json.dumps(paths, ensure_ascii=False).encode("utf-8")).hexdigest()

    def destination_for_source(self, source: Path, output_dir: Path) -> Path:
        """原目录输出按每张图片的实际位置生成目标，兼容搜索结果中的跨目录多选。"""
        target_dir = source.parent if self.same_folder_check.isChecked() else output_dir
        return build_destination(source, source, target_dir)

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.output_edit.setText(folder)

    def toggle_same_folder_output(self, checked: bool) -> None:
        self.output_edit.setEnabled(not checked)
        self.output_folder_button.setEnabled(not checked)
        if checked and self.input_edit.text().strip():
            input_path = Path(self.input_edit.text().strip()).expanduser()
            if input_path.is_file():
                self.output_edit.setText(str(input_path.parent))
            else:
                self.output_edit.setText(str(input_path))

    def start_crop(self) -> None:
        if self.worker is not None or self.preview_worker is not None:
            return
        input_text = self.input_edit.text().strip()
        output_text = self.output_edit.text().strip()

        if not input_text:
            self.show_message_box("缺少输入", "请先选择图片或文件夹。", state="warning")
            return

        if self.same_folder_check.isChecked():
            input_path_for_output = Path(input_text).expanduser()
            if input_path_for_output.is_file():
                output_text = str(input_path_for_output.parent)
            else:
                output_text = input_text
            self.output_edit.setText(output_text)

        if not output_text:
            self.show_message_box("缺少输出文件夹", "请先选择输出文件夹。", state="warning")
            return

        input_path = Path(input_text).expanduser().resolve()
        output_dir = Path(output_text).expanduser().resolve()
        if not input_path.exists():
            self.show_message_box("输入无效", "输入路径必须是图片或文件夹。", state="warning")
            return

        try:
            image_files = self.get_input_files(input_path)
            current_signature = self.build_input_signature(input_path)
            destinations = [self.normalize_path_key(self.destination_for_source(source, output_dir))
                            for source in image_files]
            if len(destinations) != len(set(destinations)):
                raise ValueError("所选图片中有同名文件会写入同一个结果，请使用原文件夹输出或先调整文件名。")
            # 跨目录多选或同时选择原图与旧结果时，不能把另一张输入图片当作输出覆盖。
            source_paths = {self.normalize_path_key(source) for source in image_files}
            if any(destination in source_paths for destination in destinations):
                raise ValueError("部分裁剪结果会覆盖本次所选的另一张输入图片，请调整所选图片或输出文件夹。")
        except SystemExit as error:
            self.show_message_box("输入无效", str(error), state="warning")
            return
        except Exception as error:
            self.show_message_box("读取失败", f"读取输入内容失败：{error}", state="warning")
            return

        if not current_signature:
            self.show_message_box("没有图片", "没有找到可裁剪的图片。", state="warning")
            return

        if not self.confirm_repeated_crop(input_path, output_dir, current_signature):
            return

        self.refresh_preview_sources()
        self.save_settings()
        self.crop_summary = None
        self.log.clear()
        self.progress.setValue(0)
        self.progress_status.setText("进度：准备开始")
        self.set_running_state(True)
        self.current_input_path = input_path
        self.current_output_path = output_dir
        self.current_input_signature = current_signature
        self.current_parameters = self.get_parameters()
        self.log_message(f"输入：{input_path}")
        self.log_message(self.input_selection_status.text())
        self.log_message(f"输出文件夹：{output_dir}")

        self.worker = CropWorker(
            input_path=input_path,
            output_dir=output_dir,
            padding=self.padding_spin.value(),
            tolerance=self.tolerance_spin.value(),
            alpha_threshold=self.alpha_spin.value(),
            svg_render_pixels=self.svg_pixels_spin.value(),
            image_files=image_files,
            same_folder_output=self.same_folder_check.isChecked(),
        )
        self.worker.log_message.connect(self.log_message)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.finished_summary.connect(self.finish_crop)
        self.worker.cancelled_summary.connect(self.cancel_crop_finished)
        self.worker.file_processed.connect(self.remember_preview_result)
        self.worker.failed.connect(self.fail_crop)
        self.worker.finished.connect(self.crop_thread_finished)
        self.worker.start()

    def set_running_state(self, running: bool) -> None:
        """任务期间锁定路径和参数，取消仍可操作，避免结果与界面设置不一致。"""
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.preview_button.setEnabled(not running and self.preview_combo.count() > 0)
        for widget in (
            self.input_edit, self.input_button,
            self.same_folder_check, self.padding_spin, self.tolerance_spin,
            self.alpha_spin, self.svg_pixels_spin, self.preview_combo,
        ):
            widget.setEnabled(not running)
        self.output_edit.setEnabled(not running and not self.same_folder_check.isChecked())
        self.output_folder_button.setEnabled(not running and not self.same_folder_check.isChecked())
        self.open_output_button.setEnabled(not running and bool(self.output_edit.text().strip()))

    def cancel_task(self) -> None:
        """请求安全中断，不强制终止线程，保留已经保存完成的结果。"""
        for thread in (self.worker, self.preview_worker):
            if thread is not None:
                thread.requestInterruption()
        self.cancel_button.setEnabled(False)
        if self.worker is not None:
            self.progress_status.setText("进度：正在取消，请等待当前安全步骤结束")
        if self.preview_worker is not None:
            self.preview_status.setText("正在取消预览，请稍候。")

    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭窗口时先安全停止任务，避免运行中的 QThread 被销毁。"""
        self.save_settings()
        if self.worker is not None or self.preview_worker is not None:
            self.close_pending = True
            self.cancel_task()
            event.ignore()
        else:
            event.accept()

    def build_input_signature(self, input_path: Path) -> InputSignature:
        """记录当前输入位置的图片状态，用于判断是否重复裁剪。"""
        image_files = self.get_input_files(input_path)
        entries: list[tuple[str, int, int]] = []
        for image_file in image_files:
            stat = image_file.stat()
            name = self.normalize_path_key(image_file) if self.selected_input_files else image_file.name
            entries.append((name, stat.st_size, stat.st_mtime_ns))
        return tuple(sorted(entries))

    def normalize_path_key(self, path: Path) -> str:
        """把路径转成稳定字符串，便于对比。"""
        return os.path.normcase(str(path.resolve()))

    def confirm_repeated_crop(self, input_path: Path, output_dir: Path, current_signature: InputSignature) -> bool:
        """成功记录跨启动保留；输入、参数、输出路径和输出存在状态都相同时才提醒。"""
        previous_state = self.crop_records.get(self.record_key(input_path))
        if previous_state is None:
            return True

        previous_signature, previous_output, previous_parameters = previous_state
        current_output = "@original" if self.same_folder_check.isChecked() else self.normalize_path_key(output_dir)
        if (
            previous_signature != current_signature or previous_output != current_output
            or previous_parameters != self.get_parameters()
        ):
            return True

        # 结果被用户删除后允许重新生成，历史成功记录不能代替当前文件检查。
        if any(not self.destination_for_source(source, output_dir).is_file()
               for source in self.get_input_files(input_path)):
            return True

        reply = self.show_message_box(
            "可能重复裁剪",
            "这些原图已经按相同参数裁剪过，且输入图片没有变化。是否仍然继续裁剪并覆盖已有结果？",
            f"输入路径：\n{input_path}\n\n输出路径：\n{output_dir}",
            state="question",
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No,
            preferred_width=760,
            button_spacing=34,
            main_text_wrap=False,
            informative_text_wrap=True,
        )
        return reply == QMessageBox.StandardButton.Yes

    def remember_current_crop_state(self) -> None:
        """裁剪完成后记录当前输入位置的图片状态。"""
        if self.current_input_path is None or self.current_output_path is None:
            return

        try:
            key = self.record_key(self.current_input_path)
            self.crop_records.pop(key, None)
            self.crop_records[key] = (
                self.current_input_signature,
                "@original" if self.same_folder_check.isChecked() else self.normalize_path_key(self.current_output_path),
                self.current_parameters,
            )
            self.save_settings()
        except Exception as error:
            self.log_message(f"记录裁剪状态失败：{error}")

    def log_message(self, message: str) -> None:
        self.log.appendPlainText(message)

    def update_progress(self, current: int, total: int) -> None:
        self.progress.setValue(round((current / total) * 100))
        if self.worker is None or not self.worker.isInterruptionRequested():
            self.progress_status.setText(f"进度：{current} / {total}")

    def finish_crop(self, changed: int, kept: int, skipped: int) -> None:
        self.progress.setValue(100)
        self.progress_status.setText("进度：已完成")
        # 失败或取消的任务不记录为整批成功，重试时不会被误提醒。
        if skipped == 0:
            self.remember_current_crop_state()
        self.log_message("")
        self.log_message(f"完成：裁剪 {changed} 张，无需裁剪 {kept} 张，处理失败 {skipped} 张。")
        self.crop_summary = (changed, kept, skipped)

    def cancel_crop_finished(self, changed: int, kept: int, skipped: int) -> None:
        self.progress_status.setText("进度：已取消")
        self.log_message(f"已取消：裁剪 {changed} 张，无需裁剪 {kept} 张，失败 {skipped} 张；已完成的输出保留。")

    def crop_thread_finished(self) -> None:
        """在线程退出后恢复操作，再展示本次完成的正式输出。"""
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self.set_running_state(False)
        if self.close_pending:
            QTimer.singleShot(0, self.close)
            return
        self.preview_selection_changed()
        if self.crop_summary is not None:
            changed, kept, skipped = self.crop_summary
            self.show_message_box(
                "裁剪完成", "图片裁剪完成。",
                f"裁剪 {changed} 张，无需裁剪 {kept} 张，处理失败 {skipped} 张。",
                state="warning" if skipped else "success", preferred_width=660,
                main_text_wrap=False, informative_text_wrap=False,
            )

    def fail_crop(self, message: str) -> None:
        self.progress_status.setText("进度：任务失败")
        self.log_message(f"任务失败：{message}")
        self.show_message_box("任务失败", "裁剪过程中出现了问题。", message, state="warning", preferred_width=660)

    def open_output_folder(self) -> None:
        output_text = self.output_edit.text().strip()
        if not output_text:
            return
        output_dir = Path(output_text).expanduser().resolve()
        if output_dir.exists():
            QDesktopServices.openUrl(output_dir.as_uri())
        else:
            self.show_message_box("文件夹不存在", "输出文件夹不存在。", str(output_dir), state="warning", preferred_width=660)


def main() -> int:
    # 让 Qt 在高分屏下自动使用合适的缩放。
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    self_test = "--self-test" in sys.argv
    if self_test:
        # 打包后检查真实 Qt 导入和窗口初始化，不弹出界面或修改用户配置。
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(sys.argv)
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    if self_test:
        with tempfile.TemporaryDirectory(prefix="crop-app-self-test-") as settings_dir:
            settings = QSettings(str(Path(settings_dir) / "settings.ini"), QSettings.Format.IniFormat)
            window = MainWindow(settings)
            window.show()
            QTimer.singleShot(100, app.quit)
            return app.exec()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
