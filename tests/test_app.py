from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# 自动验证不弹出窗口，也不使用或修改用户的实际配置。
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main import MainWindow
from app.native_input_dialog import InputSelection, resolve_selection
from scripts.crop_picture import (
    CropCancelled, collect_images, crop_svg_file, preview_file, process_file, render_svg_to_png,
)


def make_image(path: Path, size: tuple[int, int] = (100, 100), margin: int = 30) -> None:
    """生成带白边的确定性测试图，不依赖真实科研图片。"""
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).rectangle(
        (margin, margin, size[0] - margin - 1, size[1] - margin - 1), fill="black"
    )
    image.save(path)


class CoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="crop-app-test-")
        self.folder = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_app_startup_self_test_exits_successfully(self) -> None:
        """启动独立进程，验证供打包脚本使用的真实 APP 启动检查。"""
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve().parents[1] / "app/main.py"), "--self-test"],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unchanged_jpeg_is_byte_identical_with_metadata(self) -> None:
        """纯白图片和边距导致全画布保留的图片都必须原样复制。"""
        for margin in (None, 2):
            with self.subTest(margin=margin):
                source = self.folder / "original.jpg"
                destination = self.folder / "裁剪_original.jpg"
                image = Image.new("RGB", (40, 40), "white")
                if margin is not None:
                    ImageDraw.Draw(image).rectangle((2, 2, 37, 37), fill="black")
                exif = Image.Exif()
                exif[270] = "metadata must be retained"
                image.save(source, quality=97, dpi=(300, 300), exif=exif, icc_profile=b"test-profile")
                original_bytes = source.read_bytes()
                self.assertEqual(process_file(source, destination, 12, 8, 5, 2400), "kept")
                self.assertEqual(destination.read_bytes(), original_bytes)
                self.assertEqual(source.read_bytes(), original_bytes)
                with Image.open(destination) as copied:
                    self.assertEqual(copied.getexif()[270], exif[270])
                    self.assertEqual(copied.info["dpi"], (300, 300))

    def test_batch_skips_results_and_updates_existing_output(self) -> None:
        source = self.folder / "ansys.png"
        destination = self.folder / "裁剪_ansys.png"
        make_image(source)
        process_file(source, destination, 12, 8, 5, 2400)
        self.assertEqual(collect_images(self.folder), [source])
        make_image(source, (160, 120), 30)
        original_bytes = source.read_bytes()
        process_file(source, destination, 12, 8, 5, 2400)
        with Image.open(destination) as cropped:
            self.assertEqual(cropped.size, (110, 70))
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertFalse((self.folder / "裁剪_裁剪_ansys.png").exists())
        self.assertEqual(collect_images(destination), [destination])

    def test_preview_matches_crop_and_creates_no_files(self) -> None:
        source = self.folder / "ansys.png"
        make_image(source)
        before, after, description = preview_file(source, 12, 8, 5, 2400)
        self.assertEqual(before.size, (100, 100))
        self.assertEqual(after.size, (50, 50))
        self.assertIn("预览未保存", description)
        self.assertEqual(list(self.folder.iterdir()), [source])

    def test_cancel_during_scan_does_not_overwrite_result(self) -> None:
        source = self.folder / "large.png"
        destination = self.folder / "裁剪_large.png"
        make_image(source, (200, 200), 50)
        destination.write_bytes(b"previous output")
        checks = 0

        def cancel_after_a_few_rows() -> bool:
            nonlocal checks
            checks += 1
            return checks > 8

        with self.assertRaises(CropCancelled):
            process_file(source, destination, 12, 8, 5, 2400, cancel_after_a_few_rows)
        self.assertEqual(destination.read_bytes(), b"previous output")

    def test_unchanged_svg_is_byte_identical(self) -> None:
        source = self.folder / "diagram.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><!--保留--></svg>', encoding="utf-8")
        destination = self.folder / "裁剪_diagram.svg"

        def render_blank(source: Path, output: Path, width: int, height: int, cancel=None) -> None:
            Image.new("RGB", (width, height), "white").save(output)

        with patch("scripts.crop_picture.render_svg_to_png", side_effect=render_blank):
            self.assertEqual(crop_svg_file(source, destination, 12, 8, 5, 100), "kept")
        self.assertEqual(source.read_bytes(), destination.read_bytes())

    def test_svg_cancel_terminates_browser(self) -> None:
        source = self.folder / "diagram.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        browser = Mock()
        browser.communicate.side_effect = [subprocess.TimeoutExpired("browser", 0.1), ("", "")]
        checks = 0

        def cancel_while_rendering() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        with patch("scripts.crop_picture.find_browser", return_value="browser"), patch(
            "scripts.crop_picture.subprocess.Popen", return_value=browser
        ):
            with self.assertRaises(CropCancelled):
                render_svg_to_png(source, self.folder / "render.png", 100, 100, cancel_while_rendering)
        browser.terminate.assert_called_once()


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="crop-window-test-")
        self.folder = Path(self.temp.name)
        self.source = self.folder / "ansys.png"
        make_image(self.source)
        self.settings_path = self.folder / "settings.ini"
        self.windows: list[MainWindow] = []
        self.window = self.new_window()

    def new_window(self) -> MainWindow:
        settings = QSettings(str(self.settings_path), QSettings.Format.IniFormat)
        window = MainWindow(settings)
        window.show_message_box = Mock(return_value=QMessageBox.StandardButton.No)
        self.windows.append(window)
        return window

    def wait_for_idle(self, window: MainWindow) -> None:
        """通过事件循环等待真实后台线程完成，同时检查是否超时。"""
        deadline = time.monotonic() + 10
        while window.worker is not None or window.preview_worker is not None:
            self.application.processEvents()
            if time.monotonic() > deadline:
                window.cancel_task()
                self.fail("后台任务未在限定时间内结束")
            time.sleep(0.01)
        self.application.processEvents()

    def tearDown(self) -> None:
        for window in self.windows:
            if window.worker is not None or window.preview_worker is not None:
                window.cancel_task()
                self.wait_for_idle(window)
            window.close()
        self.application.processEvents()
        self.temp.cleanup()

    def select_source(self) -> None:
        self.window.input_edit.setText(str(self.source))
        self.window.same_folder_check.setChecked(True)

    def test_preview_is_background_only_and_controls_recover(self) -> None:
        self.select_source()
        self.window.start_preview()
        self.assertFalse(self.window.start_button.isEnabled())
        self.assertTrue(self.window.cancel_button.isEnabled())
        self.wait_for_idle(self.window)
        self.assertFalse(self.window.before_preview.original_pixmap.isNull())
        self.assertFalse(self.window.after_preview.original_pixmap.isNull())
        self.assertFalse((self.folder / "裁剪_ansys.png").exists())
        self.assertTrue(self.window.start_button.isEnabled())
        self.assertFalse(self.window.cancel_button.isEnabled())
        self.window.padding_spin.setValue(10)
        self.assertTrue(self.window.after_preview.original_pixmap.isNull())

    def test_parameters_paths_and_records_survive_restart(self) -> None:
        self.select_source()
        self.window.padding_spin.setValue(7)
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.window.close()
        restarted = self.new_window()
        self.assertEqual(restarted.padding_spin.value(), 7)
        self.assertEqual(restarted.input_edit.text(), str(self.source))
        self.assertTrue(restarted.same_folder_check.isChecked())
        signature = restarted.build_input_signature(self.source)
        self.assertFalse(restarted.confirm_repeated_crop(self.source, self.folder, signature))
        restarted.show_message_box.assert_called_once()
        restarted.show_message_box.reset_mock()
        restarted.padding_spin.setValue(8)
        self.assertTrue(restarted.confirm_repeated_crop(self.source, self.folder, signature))
        restarted.show_message_box.assert_not_called()

    def test_source_replacement_and_deleted_result_allow_retry(self) -> None:
        self.select_source()
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.window.show_message_box.reset_mock()
        make_image(self.source, (160, 120), 30)
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.assertEqual(self.window.show_message_box.call_count, 1)
        with Image.open(self.folder / "裁剪_ansys.png") as result:
            self.assertEqual(result.size, (110, 70))
        self.assertIn("实际输出", self.window.preview_status.text())
        self.assertFalse((self.folder / "裁剪_裁剪_ansys.png").exists())
        (self.folder / "裁剪_ansys.png").unlink()
        signature = self.window.build_input_signature(self.source)
        self.window.show_message_box.reset_mock()
        self.assertTrue(self.window.confirm_repeated_crop(self.source, self.folder, signature))
        self.window.show_message_box.assert_not_called()

    def test_partial_failure_is_not_recorded_as_success(self) -> None:
        (self.folder / "broken.png").write_bytes(b"invalid image")
        self.window.input_edit.setText(str(self.folder))
        self.window.same_folder_check.setChecked(True)
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.assertEqual(self.window.crop_records, {})
        self.assertIn("处理失败 1 张", self.window.log.toPlainText())
        self.assertTrue((self.folder / "裁剪_ansys.png").exists())

    def test_cancel_keeps_completed_files_and_stops_remaining_batch(self) -> None:
        make_image(self.folder / "second.png")
        self.window.input_edit.setText(str(self.folder))
        self.window.same_folder_check.setChecked(True)

        def crop_first_then_cancel(*args):
            result = process_file(*args)
            self.window.worker.requestInterruption()
            return result

        with patch("app.main.process_file", side_effect=crop_first_then_cancel):
            self.window.start_crop()
            self.wait_for_idle(self.window)
        self.assertTrue((self.folder / "裁剪_ansys.png").exists())
        self.assertFalse((self.folder / "裁剪_second.png").exists())
        self.assertEqual(self.window.crop_records, {})
        self.assertIn("已取消", self.window.progress_status.text())
        self.assertEqual(self.window.progress.value(), 50)

    def test_close_during_preview_requests_safe_stop(self) -> None:
        self.select_source()
        started = threading.Event()

        def slow_preview(source, tolerance, alpha, padding, svg_pixels, cancel):
            started.set()
            while not cancel():
                time.sleep(0.01)
            raise CropCancelled()

        with patch("app.main.preview_file", side_effect=slow_preview):
            self.window.show()
            self.window.start_preview()
            self.assertTrue(started.wait(2))
            self.window.close()
            self.assertTrue(self.window.close_pending)
            self.wait_for_idle(self.window)
            self.assertFalse(self.window.isVisible())

    def test_invalid_saved_records_do_not_prevent_startup(self) -> None:
        self.window.settings.setValue("crop_records", '{"bad": "broken"}')
        self.window.settings.sync()
        restarted = self.new_window()
        self.assertEqual(restarted.crop_records, {})

    def test_multi_selection_processes_only_selected_files_and_survives_restart(self) -> None:
        """目录中有三张图，但明确多选的两张才进入预览、处理和持久化记录。"""
        second = self.folder / "second.png"
        unselected = self.folder / "unselected.png"
        make_image(second)
        make_image(unselected)
        self.window.apply_input_selection(InputSelection(files=(self.source, second)))
        self.window.same_folder_check.setChecked(True)
        self.assertEqual(self.window.preview_combo.count(), 2)
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.assertTrue((self.folder / "裁剪_ansys.png").exists())
        self.assertTrue((self.folder / "裁剪_second.png").exists())
        self.assertFalse((self.folder / "裁剪_unselected.png").exists())
        self.window.close()
        restarted = self.new_window()
        self.assertEqual(restarted.selected_input_files, (self.source.resolve(), second.resolve()))
        self.assertEqual(restarted.preview_combo.count(), 2)
        signature = restarted.build_input_signature(self.folder)
        self.assertFalse(restarted.confirm_repeated_crop(self.folder, self.folder, signature))

    def test_folder_selection_and_explicit_cropped_image_have_different_scope(self) -> None:
        """目录仍跳过已有结果，明确选择该结果时允许处理。"""
        result = self.folder / "裁剪_ansys.png"
        make_image(result)
        selection = resolve_selection(self.folder, [])
        self.window.apply_input_selection(selection)
        self.assertEqual(self.window.get_input_files(self.folder), [self.source])
        self.window.apply_input_selection(resolve_selection(self.folder, [result]))
        self.assertEqual(self.window.get_input_files(result), [result.resolve()])

    def test_cross_folder_selection_outputs_to_each_original_folder(self) -> None:
        """搜索结果中跨目录多选时，原目录输出分别保存，不互相覆盖同名图片。"""
        second_folder = self.folder / "other"
        second_folder.mkdir()
        second = second_folder / "ansys.png"
        make_image(second)
        self.window.apply_input_selection(InputSelection(files=(self.source, second)))
        self.window.same_folder_check.setChecked(True)
        self.window.start_crop()
        self.wait_for_idle(self.window)
        self.assertTrue((self.folder / "裁剪_ansys.png").exists())
        self.assertTrue((second_folder / "裁剪_ansys.png").exists())

    def test_duplicate_output_names_are_rejected_before_processing(self) -> None:
        """跨目录同名图片输出到单一目录时，提前阻止结果互相覆盖。"""
        second_folder = self.folder / "other"
        second_folder.mkdir()
        second = second_folder / "ansys.png"
        make_image(second)
        output = self.folder / "output"
        self.window.apply_input_selection(InputSelection(files=(self.source, second)))
        self.window.output_edit.setText(str(output))
        self.window.start_crop()
        self.assertIsNone(self.window.worker)
        self.assertFalse(output.exists())
        self.window.show_message_box.assert_called_once()

    def test_selected_source_is_not_overwritten_by_another_result(self) -> None:
        """同时选中原图及其旧裁剪结果时，禁止覆盖本次输入再继续读取它。"""
        old_result = self.folder / "裁剪_ansys.png"
        make_image(old_result)
        original_bytes = old_result.read_bytes()
        self.window.apply_input_selection(InputSelection(files=(self.source, old_result)))
        self.window.same_folder_check.setChecked(True)
        self.window.start_crop()
        self.assertIsNone(self.window.worker)
        self.assertEqual(old_result.read_bytes(), original_bytes)
        self.window.show_message_box.assert_called_once()


if __name__ == "__main__":
    unittest.main()
