from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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
    QVBoxLayout,
    QWidget,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.crop_picture import build_destination, collect_images, process_file  # noqa: E402


IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif *.ppm *.pgm *.pbm *.pnm *.svg)"
InputSignature = tuple[tuple[str, int, int], ...]


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
    failed = Signal(str)

    def __init__(
        self,
        input_path: Path,
        output_dir: Path,
        padding: int,
        tolerance: int,
        alpha_threshold: int,
        svg_render_pixels: int,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.padding = padding
        self.tolerance = tolerance
        self.alpha_threshold = alpha_threshold
        self.svg_render_pixels = svg_render_pixels

    def run(self) -> None:
        """收集并裁剪图片，把过程通过信号传回界面。"""
        try:
            image_files = collect_images(self.input_path, [])
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
            destination = build_destination(source, self.input_path, self.output_dir)
            try:
                result = process_file(
                    source,
                    destination,
                    self.tolerance,
                    self.alpha_threshold,
                    self.padding,
                    self.svg_render_pixels,
                )
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
            self.progress_changed.emit(index, total)

        self.finished_summary.emit(changed, kept, skipped)


class MainWindow(QMainWindow):
    """最小可用桌面界面。"""

    def __init__(self) -> None:
        super().__init__()
        self.worker: CropWorker | None = None
        self.current_input_path: Path | None = None
        self.current_output_path: Path | None = None
        self.crop_records: dict[str, tuple[InputSignature, str]] = {}
        self.setWindowTitle("科研图片裁剪")
        self.resize(1120, 760)
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
        self.output_edit = QLineEdit()
        self.same_folder_check = QCheckBox("输出到原文件夹（裁剪后的文件自动添加“裁剪_”前缀）")
        self.padding_spin = self.create_spin_box(0, 200, 5)
        self.tolerance_spin = self.create_spin_box(0, 255, 12)
        self.alpha_spin = self.create_spin_box(0, 255, 8)
        self.svg_pixels_spin = self.create_spin_box(64, 8000, 2400)

        self.start_button = QPushButton("开始裁剪")
        self.start_button.setObjectName("StartButton")
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
        self.connect_signals()

    def create_spin_box(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin_box = QSpinBox()
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(value)
        spin_box.setFixedWidth(128)
        return spin_box

    def build_ui(self) -> None:
        """创建窗口布局。"""
        input_file_button = QPushButton("选择图片")
        input_folder_button = QPushButton("选择文件夹")
        output_button = QPushButton("选择输出文件夹")
        input_file_button.clicked.connect(self.choose_input_file)
        input_folder_button.clicked.connect(self.choose_input_folder)
        output_button.clicked.connect(self.choose_output_folder)

        input_row = QHBoxLayout()
        input_row.addWidget(self.input_edit)
        input_row.addWidget(input_file_button)
        input_row.addWidget(input_folder_button)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit)
        output_row.addWidget(output_button)

        input_form = QFormLayout()
        input_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        input_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft)
        input_form.setContentsMargins(16, 10, 16, 10)
        input_form.setHorizontalSpacing(16)
        input_form.setVerticalSpacing(12)
        input_form.addRow("输入图片或文件夹", input_row)
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
        actions.setSpacing(100)
        actions.addStretch()
        actions.addWidget(self.start_button)
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
        main_layout.addWidget(self.build_help_panel(), stretch=2)

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
              <li>点击 <b>选择图片</b> 处理单张图片，或点击 <b>选择文件夹</b> 批量处理当前文件夹中的图片。</li>
               <li>选择输出文件夹；如果勾选 <b>输出到原文件夹</b>，结果会自动添加“裁剪_”前缀，避免覆盖原图。</li>
              <li>一般保持默认参数即可，然后点击 <b>开始裁剪</b>。</li>
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

    def choose_input_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输入文件夹")
        if not folder:
            return
        self.input_edit.setText(folder)
        if self.same_folder_check.isChecked():
            self.output_edit.setText(folder)

    def choose_input_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", IMAGE_FILTER)
        if not file_path:
            return
        self.input_edit.setText(file_path)
        if self.same_folder_check.isChecked():
            self.output_edit.setText(str(Path(file_path).parent))

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.output_edit.setText(folder)

    def toggle_same_folder_output(self, checked: bool) -> None:
        self.output_edit.setEnabled(not checked)
        if checked and self.input_edit.text().strip():
            input_path = Path(self.input_edit.text().strip()).expanduser()
            if input_path.is_file():
                self.output_edit.setText(str(input_path.parent))
            else:
                self.output_edit.setText(str(input_path))

    def start_crop(self) -> None:
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
            current_signature = self.build_input_signature(input_path)
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

        self.log.clear()
        self.progress.setValue(0)
        self.progress_status.setText("进度：准备开始")
        self.set_running_state(True)
        self.current_input_path = input_path
        self.current_output_path = output_dir
        self.log_message(f"输入：{input_path}")
        self.log_message(f"输出文件夹：{output_dir}")

        self.worker = CropWorker(
            input_path=input_path,
            output_dir=output_dir,
            padding=self.padding_spin.value(),
            tolerance=self.tolerance_spin.value(),
            alpha_threshold=self.alpha_spin.value(),
            svg_render_pixels=self.svg_pixels_spin.value(),
        )
        self.worker.log_message.connect(self.log_message)
        self.worker.progress_changed.connect(self.update_progress)
        self.worker.finished_summary.connect(self.finish_crop)
        self.worker.failed.connect(self.fail_crop)
        self.worker.start()

    def set_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.open_output_button.setEnabled(not running and bool(self.output_edit.text().strip()))

    def build_input_signature(self, input_path: Path) -> InputSignature:
        """记录当前输入位置的图片状态，用于判断是否重复裁剪。"""
        image_files = collect_images(input_path, [])
        entries: list[tuple[str, int, int]] = []
        for image_file in image_files:
            stat = image_file.stat()
            entries.append((image_file.name, stat.st_size, stat.st_mtime_ns))
        return tuple(sorted(entries))

    def normalize_path_key(self, path: Path) -> str:
        """把路径转成稳定字符串，便于对比。"""
        return str(path.resolve())

    def confirm_repeated_crop(self, input_path: Path, output_dir: Path, current_signature: InputSignature) -> bool:
        """只有在输入内容和输出路径都没变时，才提醒用户可能重复裁剪。"""
        previous_state = self.crop_records.get(self.normalize_path_key(input_path))
        if previous_state is None:
            return True

        previous_signature, previous_output = previous_state
        current_output = self.normalize_path_key(output_dir)
        if previous_signature != current_signature or previous_output != current_output:
            return True

        reply = self.show_message_box(
            "可能重复裁剪",
            "这个输入路径下的文件在本次打开软件后已经裁剪过，且当前图片内容没有变化。是否仍然继续裁剪？",
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
            self.crop_records[self.normalize_path_key(self.current_input_path)] = (
                self.build_input_signature(self.current_input_path),
                self.normalize_path_key(self.current_output_path),
            )
        except Exception as error:
            self.log_message(f"记录裁剪状态失败：{error}")

    def log_message(self, message: str) -> None:
        self.log.appendPlainText(message)

    def update_progress(self, current: int, total: int) -> None:
        self.progress.setValue(round((current / total) * 100))
        self.progress_status.setText(f"进度：{current} / {total}")

    def finish_crop(self, changed: int, kept: int, skipped: int) -> None:
        self.set_running_state(False)
        self.progress.setValue(100)
        self.progress_status.setText("进度：已完成")
        self.remember_current_crop_state()
        self.log_message("")
        self.log_message(f"完成：裁剪 {changed} 张，无需裁剪 {kept} 张，处理失败 {skipped} 张。")
        self.show_message_box(
            "裁剪完成",
            "图片裁剪完成。",
            f"裁剪 {changed} 张，无需裁剪 {kept} 张，处理失败 {skipped} 张。",
            state="success",
            preferred_width=660,
            main_text_wrap=False,
            informative_text_wrap=False,
        )

    def fail_crop(self, message: str) -> None:
        self.set_running_state(False)
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
    app = QApplication(sys.argv)
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
