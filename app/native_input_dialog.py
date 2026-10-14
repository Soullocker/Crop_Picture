from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from scripts.crop_picture import IMAGE_EXTENSIONS


@dataclass(frozen=True)
class InputSelection:
    """原生窗口的选择结果：一个目录，或明确选择的一组图片。"""

    folder: Path | None = None
    files: tuple[Path, ...] = ()


def resolve_selection(folder: Path, selected_paths: list[Path]) -> InputSelection:
    """选中图片时只处理这些图片；未选图片时选择当前目录或单独选中的子目录。"""
    files = tuple(dict.fromkeys(
        path.resolve() for path in selected_paths
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ))
    if files:
        return InputSelection(files=files)
    directories = [path for path in selected_paths if path.is_dir()]
    target = directories[0] if len(directories) == 1 else folder
    if not target.is_dir():
        raise ValueError("请进入一个实际存在的文件夹后再选择。")
    return InputSelection(folder=target.resolve())


class GUID(ctypes.Structure):
    """Windows COM 接口标识，使用标准小端内存布局。"""

    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value: str) -> GUID:
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


# 仅调用 Windows 自带的文件浏览和窗口接口，不需要额外 COM 包或外部程序。
HRESULT = ctypes.c_int32
POINTER = ctypes.c_void_p
ULONG = ctypes.c_uint32
CALLBACK = ctypes.WINFUNCTYPE
CLSID_FILE_OPEN = GUID.parse("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
IID_FILE_OPEN = GUID.parse("D57C7288-D4AD-4768-BE02-9D969532D960")
IID_EVENTS = GUID.parse("973510DB-7D7F-452B-8975-74A85828D354")
IID_UNKNOWN = GUID.parse("00000000-0000-0000-C000-000000000046")
IID_OLE_WINDOW = GUID.parse("00000114-0000-0000-C000-000000000046")
SIGDN_FILESYSPATH = 0x80058000
CANCELLED_HRESULT = ctypes.c_int32(0x800704C7).value
BUTTON_ID = 0x7001
SUBCLASS_ID = 0x7002


class FilterSpec(ctypes.Structure):
    _fields_ = [("name", wintypes.LPCWSTR), ("pattern", wintypes.LPCWSTR)]


class EventSink(ctypes.Structure):
    _fields_ = [("vtable", ctypes.POINTER(POINTER))]


def invoke(pointer: POINTER, index: int, result_type, arg_types: tuple, *args):
    """按 Windows SDK 的接口顺序调用 COM 方法。"""
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(POINTER))).contents
    function = CALLBACK(result_type, POINTER, *arg_types)(table[index])
    return function(pointer, *args)


def checked(pointer: POINTER, index: int, arg_types: tuple, *args) -> int:
    result = invoke(pointer, index, HRESULT, arg_types, *args)
    if result < 0:
        raise OSError(f"Windows 文件浏览接口失败：0x{result & 0xffffffff:08X}")
    return result


def release(pointer: POINTER) -> None:
    """释放本模块取得的 COM 引用。"""
    if pointer:
        invoke(pointer, 2, ULONG, ())


class NativeInputDialog:
    """保留资源管理器和缩略图，在右下角统一选择目录或多张图片。"""

    def __init__(self, parent_handle: int, initial_folder: Path) -> None:
        self.parent_handle = parent_handle
        self.initial_folder = initial_folder
        self.dialog = POINTER()
        self.window = None
        self.accept_button = None
        self.native_accept = None
        self.result: InputSelection | None = None
        self.error: BaseException | None = None
        self.ref_count = 1
        self.ole = ctypes.OleDLL("ole32")
        self.shell = ctypes.WinDLL("shell32")
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.controls = ctypes.WinDLL("comctl32", use_last_error=True)
        self.configure_api()
        self.create_event_sink()

    def configure_api(self) -> None:
        """声明 64 位句柄和指针类型，避免默认整型截断窗口地址。"""
        self.ole.CoInitializeEx.argtypes = [POINTER, ULONG]
        self.ole.CoInitializeEx.restype = HRESULT
        self.ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), POINTER, ULONG,
                                            ctypes.POINTER(GUID), ctypes.POINTER(POINTER)]
        self.ole.CoCreateInstance.restype = HRESULT
        self.ole.CoTaskMemFree.argtypes = [POINTER]
        self.ole.CoUninitialize.argtypes = []
        self.shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, POINTER,
                                                          ctypes.POINTER(GUID), ctypes.POINTER(POINTER)]
        self.shell.SHCreateItemFromParsingName.restype = HRESULT
        declarations = {
            "GetDlgItem": ([wintypes.HWND, ctypes.c_int], wintypes.HWND),
            "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
            "MapWindowPoints": ([wintypes.HWND, wintypes.HWND, POINTER, ULONG], ctypes.c_int),
            "CreateWindowExW": ([ULONG, wintypes.LPCWSTR, wintypes.LPCWSTR, ULONG,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, POINTER], wintypes.HWND),
            "SendMessageW": ([wintypes.HWND, ULONG, ctypes.c_size_t, ctypes.c_ssize_t], ctypes.c_ssize_t),
            "PostMessageW": ([wintypes.HWND, ULONG, ctypes.c_size_t, ctypes.c_ssize_t], wintypes.BOOL),
            "ShowWindow": ([wintypes.HWND, ctypes.c_int], wintypes.BOOL),
            "EnableWindow": ([wintypes.HWND, wintypes.BOOL], wintypes.BOOL),
            "SetWindowTextW": ([wintypes.HWND, wintypes.LPCWSTR], wintypes.BOOL),
            "MoveWindow": ([wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             wintypes.BOOL], wintypes.BOOL),
            "GetDpiForWindow": ([wintypes.HWND], ULONG),
        }
        for name, (arguments, result) in declarations.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = arguments, result
        self.subclass_type = CALLBACK(ctypes.c_ssize_t, wintypes.HWND, ULONG,
                                      ctypes.c_size_t, ctypes.c_ssize_t, ctypes.c_size_t, ctypes.c_size_t)
        self.subclass_callback = self.subclass_type(self.window_message)
        self.controls.SetWindowSubclass.argtypes = [wintypes.HWND, self.subclass_type,
                                                    ctypes.c_size_t, ctypes.c_size_t]
        self.controls.SetWindowSubclass.restype = wintypes.BOOL
        self.controls.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.subclass_type, ctypes.c_size_t]
        self.controls.RemoveWindowSubclass.restype = wintypes.BOOL
        self.controls.DefSubclassProc.argtypes = [wintypes.HWND, ULONG, ctypes.c_size_t, ctypes.c_ssize_t]
        self.controls.DefSubclassProc.restype = ctypes.c_ssize_t

    def create_event_sink(self) -> None:
        """保持事件回调的强引用，原生模态窗口期间不得释放回调地址。"""
        self.callbacks = [
            CALLBACK(HRESULT, POINTER, ctypes.POINTER(GUID), ctypes.POINTER(POINTER))(self.query_interface),
            CALLBACK(ULONG, POINTER)(self.add_ref),
            CALLBACK(ULONG, POINTER)(self.release_ref),
            CALLBACK(HRESULT, POINTER, POINTER)(self.file_ok),
            CALLBACK(HRESULT, POINTER, POINTER, POINTER)(lambda *_: 0),
            CALLBACK(HRESULT, POINTER, POINTER)(self.selection_changed),
            CALLBACK(HRESULT, POINTER, POINTER)(self.selection_changed),
            CALLBACK(HRESULT, POINTER, POINTER, POINTER, ctypes.POINTER(ULONG))(self.default_response),
            CALLBACK(HRESULT, POINTER, POINTER)(lambda *_: 0),
            CALLBACK(HRESULT, POINTER, POINTER, POINTER, ctypes.POINTER(ULONG))(self.default_response),
        ]
        self.event_table = (POINTER * len(self.callbacks))(
            *(ctypes.cast(callback, POINTER).value for callback in self.callbacks)
        )
        self.sink = EventSink(self.event_table)

    def query_interface(self, this, iid, output) -> int:
        identifier = bytes(iid.contents)
        if identifier in (bytes(IID_UNKNOWN), bytes(IID_EVENTS)):
            output[0] = ctypes.cast(ctypes.pointer(self.sink), POINTER)
            self.ref_count += 1
            return 0
        output[0] = None
        return ctypes.c_int32(0x80004002).value

    def add_ref(self, *_args) -> int:
        self.ref_count += 1
        return self.ref_count

    def release_ref(self, *_args) -> int:
        self.ref_count -= 1
        return self.ref_count

    def default_response(self, _this, _dialog, _item, response) -> int:
        response[0] = 0
        return 0

    def item_path(self, item: POINTER) -> Path:
        """Shell 字符串由 COM 分配，读取后及时归还内存。"""
        text = POINTER()
        checked(item, 5, (ULONG, ctypes.POINTER(POINTER)), SIGDN_FILESYSPATH, ctypes.byref(text))
        try:
            return Path(ctypes.wstring_at(text))
        finally:
            self.ole.CoTaskMemFree(text)

    def selected_paths(self, method_index: int = 28) -> list[Path]:
        """读取当前多选项目，尚未确认时使用 GetSelectedItems。"""
        items = POINTER()
        result = invoke(self.dialog, method_index, HRESULT, (ctypes.POINTER(POINTER),), ctypes.byref(items))
        if result < 0 or not items:
            return []
        paths = []
        try:
            count = ULONG()
            checked(items, 7, (ctypes.POINTER(ULONG),), ctypes.byref(count))
            for index in range(count.value):
                item = POINTER()
                checked(items, 8, (ULONG, ctypes.POINTER(POINTER)), index, ctypes.byref(item))
                try:
                    # “此电脑”等虚拟项目没有文件路径，忽略它们仍允许继续导航。
                    try:
                        paths.append(self.item_path(item))
                    except OSError:
                        pass
                finally:
                    release(item)
        finally:
            release(items)
        return paths

    def current_folder(self) -> Path:
        item = POINTER()
        checked(self.dialog, 13, (ctypes.POINTER(POINTER),), ctypes.byref(item))
        try:
            return self.item_path(item)
        finally:
            release(item)

    def selection_result(self) -> InputSelection:
        """搜索或虚拟视图中选中真实图片时，不要求视图本身有文件系统路径。"""
        paths = self.selected_paths()
        if any(path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS for path in paths):
            return resolve_selection(self.initial_folder, paths)
        directories = [path for path in paths if path.is_dir()]
        folder = directories[0] if len(directories) == 1 else self.current_folder()
        return resolve_selection(folder, paths)

    def install_accept_button(self) -> None:
        """替换原生确认控件，解决原生打开按钮在未选文件时无法选择当前目录的问题。"""
        if self.accept_button:
            return
        ole_window = POINTER()
        checked(self.dialog, 0, (ctypes.POINTER(GUID), ctypes.POINTER(POINTER)),
                ctypes.byref(IID_OLE_WINDOW), ctypes.byref(ole_window))
        try:
            handle = wintypes.HWND()
            checked(ole_window, 3, (ctypes.POINTER(wintypes.HWND),), ctypes.byref(handle))
            self.window = handle.value
        finally:
            release(ole_window)
        self.native_accept = self.user.GetDlgItem(self.window, 1)
        if not self.native_accept:
            raise OSError("无法取得原生文件窗口的确认按钮。")
        # 原生文件区域、导航、搜索和缩略图保持原样，只统一右下角确认按钮的行为。
        self.accept_button = self.user.CreateWindowExW(
            0, "BUTTON", "选择该文件夹", 0x50010001,
            0, 0, 140, 30, self.window, BUTTON_ID, None, None,
        )
        if not self.accept_button:
            raise ctypes.WinError(ctypes.get_last_error())
        font = self.user.SendMessageW(self.native_accept, 0x0031, 0, 0)
        self.user.SendMessageW(self.accept_button, 0x0030, font, 1)
        if not self.controls.SetWindowSubclass(self.window, self.subclass_callback, SUBCLASS_ID, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        self.user.SendMessageW(self.window, 0x0401, BUTTON_ID, 0)
        self.position_accept_button()

    def position_accept_button(self) -> None:
        """沿用原生按钮的位置和 DPI，窗口缩放时同步调整，不覆盖取消按钮。"""
        if not self.accept_button:
            return
        rectangle = wintypes.RECT()
        if not self.user.GetWindowRect(self.native_accept, ctypes.byref(rectangle)):
            return
        self.user.MapWindowPoints(None, self.window, ctypes.byref(rectangle), 2)
        dpi = self.user.GetDpiForWindow(self.window) or 96
        width = max(rectangle.right - rectangle.left, round(140 * dpi / 96))
        self.user.MoveWindow(self.accept_button, rectangle.right - width, rectangle.top,
                             width, rectangle.bottom - rectangle.top, True)
        self.user.ShowWindow(self.native_accept, 0)

    def fail(self, error: BaseException) -> None:
        """回调异常转换成可报告的错误，避免异常越过原生回调边界。"""
        self.error = error
        if self.window:
            self.user.PostMessageW(self.window, 0x0010, 0, 0)
        else:
            invoke(self.dialog, 23, HRESULT, (HRESULT,), ctypes.c_int32(0x80004005).value)

    def selection_changed(self, *_args) -> int:
        try:
            self.install_accept_button()
            files = [path for path in self.selected_paths()
                     if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
            self.user.SetWindowTextW(self.accept_button, "处理所选图片" if files else "选择该文件夹")
            # 虚拟根视图允许浏览，但不能作为输出或整批输入目录。
            try:
                self.selection_result()
                valid = True
            except (OSError, ValueError):
                valid = False
            self.user.EnableWindow(self.accept_button, valid)
            self.position_accept_button()
        except BaseException as error:
            self.fail(error)
        return 0

    def file_ok(self, *_args) -> int:
        """双击图片及键盘确认同样返回明确选中的图片，不扩展成整个目录。"""
        try:
            # 原生确认也支持文件名输入框中的名称，GetResults 返回系统解析后的真实文件。
            paths = self.selected_paths(27)
            self.result = resolve_selection(self.initial_folder, paths) if paths else self.selection_result()
            return 0
        except BaseException as error:
            self.fail(error)
            return 1

    def window_message(self, handle, message, wparam, lparam, subclass_id, reference) -> int:
        try:
            if message == 0x0111 and (wparam & 0xffff) in (BUTTON_ID, 1) and (wparam >> 16) == 0:
                self.result = self.selection_result()
                # 先捕获选择，再异步关闭原生模态窗口，避免在控件通知回调中关闭导致界面滞留。
                self.user.PostMessageW(handle, 0x0010, 0, 0)
                return 0
            result = self.controls.DefSubclassProc(handle, message, wparam, lparam)
            if message in (0x0005, 0x0047):
                self.position_accept_button()
            elif message == 0x0082:
                self.controls.RemoveWindowSubclass(handle, self.subclass_callback, SUBCLASS_ID)
                self.accept_button = None
                self.window = None
            return result
        except BaseException as error:
            self.fail(error)
            return 0

    def show(self) -> InputSelection | None:
        """使用 STA 模态窗口，取消时不改变 APP 现有的输入范围。"""
        initialized = self.ole.CoInitializeEx(None, 0x6)
        if initialized < 0:
            raise OSError(f"Windows 文件浏览初始化失败：0x{initialized & 0xffffffff:08X}")
        cookie = ULONG()
        advised = False
        try:
            result = self.ole.CoCreateInstance(ctypes.byref(CLSID_FILE_OPEN), None, 1,
                                               ctypes.byref(IID_FILE_OPEN), ctypes.byref(self.dialog))
            if result < 0:
                raise OSError(f"无法创建 Windows 文件浏览窗口：0x{result & 0xffffffff:08X}")
            # 保留多选、真实文件路径和原生图片过滤，不启用会隐藏图片的目录模式。
            checked(self.dialog, 9, (ULONG,), 0x40 | 0x200 | 0x800 | 0x1000 | 0x02000000)
            checked(self.dialog, 17, (wintypes.LPCWSTR,), "选择图片或文件夹")
            specs = (FilterSpec * 1)(FilterSpec("图片文件", ";".join("*" + ext for ext in sorted(IMAGE_EXTENSIONS))))
            checked(self.dialog, 4, (ULONG, ctypes.POINTER(FilterSpec)), 1, specs)
            if self.initial_folder.is_dir():
                item = POINTER()
                iid_item = GUID.parse("43826D1E-E718-42EE-BC55-A1E261C37BFE")
                self.shell.SHCreateItemFromParsingName(str(self.initial_folder), None,
                                                       ctypes.byref(iid_item), ctypes.byref(item))
                try:
                    if item:
                        checked(self.dialog, 12, (POINTER,), item)
                finally:
                    release(item)
            checked(self.dialog, 7, (POINTER, ctypes.POINTER(ULONG)),
                    ctypes.cast(ctypes.pointer(self.sink), POINTER), ctypes.byref(cookie))
            advised = True
            result = invoke(self.dialog, 3, HRESULT, (wintypes.HWND,), self.parent_handle)
            if self.error is not None:
                raise self.error
            if result == CANCELLED_HRESULT:
                # 自定义确认使用正常关闭流程退出；真正点击取消时没有捕获结果。
                return self.result
            if result < 0:
                raise OSError(f"文件浏览窗口失败：0x{result & 0xffffffff:08X}")
            return self.result
        finally:
            if advised:
                invoke(self.dialog, 8, HRESULT, (ULONG,), cookie)
            release(self.dialog)
            self.ole.CoUninitialize()


def choose_input(parent_handle: int, initial_folder: Path) -> InputSelection | None:
    """统一的图片与文件夹选择入口。"""
    if os.name != "nt":
        raise RuntimeError("此 APP 的原生选择窗口需要 Windows。")
    return NativeInputDialog(parent_handle, initial_folder).show()
