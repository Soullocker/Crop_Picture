from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

from PIL import Image


# 常用类型别名：让 Pylance 更容易判断 tuple 的固定长度。
Color = tuple[int, int, int]
RgbaPixel = tuple[int, int, int, int]
BBox = tuple[int, int, int, int]
SvgViewBox = tuple[float, float, float, float]
CornerColors = tuple[Color, Color, Color, Color]
CancelCheck = Callable[[], bool] | None

RASTER_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
    ".gif",
    ".ppm",
    ".pgm",
    ".pbm",
    ".pnm",
}
SVG_EXTENSIONS = {".svg"}
IMAGE_EXTENSIONS = RASTER_EXTENSIONS | SVG_EXTENSIONS
SVG_NAMESPACE = "http://www.w3.org/2000/svg"


class CropCancelled(Exception):
    """用户主动取消任务，不作为图片处理失败计数。"""


def check_cancelled(cancel_requested: CancelCheck) -> None:
    """在可安全中断的步骤检查取消请求。"""
    if cancel_requested is not None and cancel_requested():
        raise CropCancelled("任务已取消。")


def validate_static_image(image: Image.Image) -> None:
    """预览和正式处理使用相同的多帧图片限制。"""
    if image.format == "GIF" and getattr(image, "is_animated", False):
        raise RuntimeError("暂不支持动画 GIF，请先导出单帧 PNG 等图片。")
    if image.format == "TIFF" and getattr(image, "n_frames", 1) > 1:
        raise RuntimeError("暂不支持多页 TIFF，请先拆分成单页图片。")


def format_number(value: float) -> str:
    """把 SVG viewBox 数值格式化得短一些，避免输出过长的小数。"""
    if abs(value) < 1e-9:
        value = 0
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def border_pixels(width: int, height: int) -> Iterator[tuple[int, int]]:
    """依次返回图片最外圈像素坐标，用于估计背景颜色。"""
    for x in range(width):
        yield x, 0
        yield x, height - 1
    for y in range(1, height - 1):
        yield 0, y
        yield width - 1, y


def median(values: list[int]) -> int:
    """返回整数列表的中位数；调用方会传入可修改的临时列表。"""
    values.sort()
    return values[len(values) // 2]


def rgba_pixel(pixels: Any, x: int, y: int) -> RgbaPixel:
    """从 Pillow PixelAccess 中读取一个 RGBA 像素，并告诉类型检查器其固定结构。"""
    return cast(RgbaPixel, pixels[x, y])


def color_distance(left: Color, right: Color) -> int:
    """用 RGB 三通道最大差值衡量颜色距离，适合白边/浅色背景判断。"""
    return max(abs(left[0] - right[0]), abs(left[1] - right[1]), abs(left[2] - right[2]))


def lerp_color(
    start: Color,
    end: Color,
    amount: float,
) -> Color:
    """在两个 RGB 颜色之间线性插值，用于估计平滑渐变背景。"""
    return (
        round(start[0] + (end[0] - start[0]) * amount),
        round(start[1] + (end[1] - start[1]) * amount),
        round(start[2] + (end[2] - start[2]) * amount),
    )


def detect_background(image: Image.Image, alpha_threshold: int) -> Color:
    """从图片四周边框像素估计全局背景色。"""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    channels: list[list[int]] = [[], [], []]

    for x, y in border_pixels(width, height):
        r, g, b, a = rgba_pixel(pixels, x, y)
        if a > alpha_threshold:
            channels[0].append(r)
            channels[1].append(g)
            channels[2].append(b)

    if not channels[0]:
        return 255, 255, 255

    return median(channels[0]), median(channels[1]), median(channels[2])


def detect_corner_backgrounds(
    image: Image.Image,
    alpha_threshold: int,
    fallback: Color,
) -> CornerColors:
    """分别估计四个角的背景色，帮助处理科研图常见的浅色渐变背景。"""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    sample = min(24, width, height, max(2, max(width, height) // 20))
    corners = (
        (range(0, sample), range(0, sample)),
        (range(max(0, width - sample), width), range(0, sample)),
        (range(0, sample), range(max(0, height - sample), height)),
        (range(max(0, width - sample), width), range(max(0, height - sample), height)),
    )
    colors: list[Color] = []

    for xs, ys in corners:
        channels: list[list[int]] = [[], [], []]
        for y in ys:
            for x in xs:
                r, g, b, a = rgba_pixel(pixels, x, y)
                if a > alpha_threshold:
                    channels[0].append(r)
                    channels[1].append(g)
                    channels[2].append(b)

        if channels[0]:
            colors.append((median(channels[0]), median(channels[1]), median(channels[2])))
        else:
            colors.append(fallback)

    return colors[0], colors[1], colors[2], colors[3]


def estimate_gradient_background(
    x: int,
    y: int,
    width: int,
    height: int,
    corners: CornerColors,
) -> Color:
    """用四角颜色做双线性插值，估算指定像素位置的渐变背景色。"""
    top_left, top_right, bottom_left, bottom_right = corners
    x_amount = 0.0 if width <= 1 else x / (width - 1)
    y_amount = 0.0 if height <= 1 else y / (height - 1)
    top = lerp_color(top_left, top_right, x_amount)
    bottom = lerp_color(bottom_left, bottom_right, x_amount)
    return lerp_color(top, bottom, y_amount)


def has_gradient_background(
    corners: CornerColors,
    tolerance: int,
) -> bool:
    """判断四角背景色差是否足以认为这是平滑渐变背景。"""
    max_distance = 0
    for left in corners:
        for right in corners:
            max_distance = max(max_distance, color_distance(left, right))
    return max_distance > tolerance


def find_content_bbox(
    image: Image.Image,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    cancel_requested: CancelCheck = None,
) -> BBox | None:
    """检测图片内容边界，返回可直接传给 Pillow crop 的边界框。"""
    check_cancelled(cancel_requested)
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    background = detect_background(rgba, alpha_threshold)
    corner_backgrounds = detect_corner_backgrounds(rgba, alpha_threshold, background)
    use_gradient_background = has_gradient_background(corner_backgrounds, tolerance)

    min_x, min_y = width, height
    max_x, max_y = -1, -1

    for y in range(height):
        # 逐行响应取消，避免大图必须扫描完毕才能停止。
        check_cancelled(cancel_requested)
        for x in range(width):
            r, g, b, a = rgba_pixel(pixels, x, y)
            if a <= alpha_threshold:
                continue

            # 纯色背景使用全局背景色；渐变背景按像素位置估计局部背景色。
            color: Color = (r, g, b)
            if use_gradient_background:
                pixel_background = estimate_gradient_background(x, y, width, height, corner_backgrounds)
            else:
                pixel_background = background

            distance = color_distance(color, pixel_background)
            if distance > tolerance:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        return None

    return (
        max(0, min_x - padding),
        max(0, min_y - padding),
        min(width, max_x + padding + 1),
        min(height, max_y + padding + 1),
    )


def crop_file(
    source: Path,
    destination: Path,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    cancel_requested: CancelCheck = None,
) -> str:
    """裁剪普通位图文件，并把结果保存到目标路径。"""
    check_cancelled(cancel_requested)
    with Image.open(source) as image:
        validate_static_image(image)
        bbox = find_content_bbox(image, tolerance, alpha_threshold, padding, cancel_requested)
        check_cancelled(cancel_requested)
        unchanged = bbox is None or bbox == (0, 0, image.width, image.height)
        if not unchanged:
            assert bbox is not None
            cropped = image.crop(bbox)
            destination.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(destination)
            return f"{image.size[0]}x{image.size[1]} -> {cropped.size[0]}x{cropped.size[1]}"

    # 关闭输入文件后直接复制字节，完整保留 JPEG 编码、EXIF、DPI 和其他元数据。
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return "kept"


def parse_svg_length(value: str | None, fallback: float) -> float:
    """解析 SVG width/height 长度，尽量换算为像素单位。"""
    if not value:
        return fallback

    text = value.strip()
    if not text:
        return fallback

    if text.endswith("%"):
        return fallback

    units = {
        "px": 1.0,
        "pt": 96.0 / 72.0,
        "pc": 16.0,
        "in": 96.0,
        "cm": 96.0 / 2.54,
        "mm": 96.0 / 25.4,
    }
    for suffix, scale in units.items():
        if text.lower().endswith(suffix):
            return float(text[: -len(suffix)]) * scale

    return float(text)


def parse_svg_viewbox(root: ET.Element) -> SvgViewBox:
    """读取 SVG 根节点 viewBox；缺失时用 width/height 构造默认画布。"""
    viewbox = root.get("viewBox") or root.get("viewbox")
    if viewbox:
        parts = viewbox.replace(",", " ").split()
        if len(parts) == 4:
            return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])

    width = parse_svg_length(root.get("width"), 1000.0)
    height = parse_svg_length(root.get("height"), 1000.0)
    return 0.0, 0.0, width, height


def find_browser() -> str | None:
    """查找可用于无头渲染 SVG 的 Edge 或 Chrome。"""
    for command in ("msedge", "chrome"):
        path = shutil.which(command)
        if path:
            return path

    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def file_uri(path: Path) -> str:
    """把本地路径转换为浏览器可以打开的 file:// URI。"""
    return path.resolve().as_uri()


def render_svg_to_png(
    source: Path, output: Path, width: int, height: int, cancel_requested: CancelCheck = None
) -> None:
    """用浏览器临时渲染 SVG，得到一张用于检测边界的 PNG。"""
    import html

    browser = find_browser()
    if browser is None:
        raise RuntimeError("Microsoft Edge or Google Chrome was not found for SVG rendering.")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
  margin: 0;
  padding: 0;
  width: {width}px;
  height: {height}px;
  overflow: hidden;
  background: white;
}}
img {{
  display: block;
  width: {width}px;
  height: {height}px;
}}
</style>
</head>
<body>
<img src="{html.escape(file_uri(source), quote=True)}">
</body>
</html>
"""
    with tempfile.TemporaryDirectory(prefix="crop-picture-svg-") as temp_dir:
        html_path = Path(temp_dir) / "render.html"
        user_data_dir = Path(temp_dir) / "browser-profile"
        html_path.write_text(html, encoding="utf-8")
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--user-data-dir={user_data_dir}",
            f"--window-size={width},{height}",
            f"--screenshot={output}",
            file_uri(html_path),
        ]
        for headless_mode in ("--headless=new", "--headless"):
            check_cancelled(cancel_requested)
            command[1] = headless_mode
            # 轮询浏览器进程，使 SVG 渲染也能响应取消；同时避免无限等待。
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 60
            try:
                while True:
                    check_cancelled(cancel_requested)
                    if time.monotonic() >= deadline:
                        raise RuntimeError("SVG 渲染超时，请检查图片或降低 SVG 检测尺寸。")
                    try:
                        stdout, stderr = process.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                raise
            if process.returncode == 0 and output.exists():
                return
        message = stderr.strip() or stdout.strip() or "浏览器未生成检测图。"
        raise RuntimeError(f"SVG 渲染失败：{message}")


def crop_svg_file(
    source: Path,
    destination: Path,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    render_pixels: int,
    cancel_requested: CancelCheck = None,
) -> str:
    """裁剪 SVG：通过临时渲染检测内容，再收紧根节点 viewBox。"""
    ET.register_namespace("", SVG_NAMESPACE)
    tree = ET.parse(source)
    root = tree.getroot()
    old_x, old_y, old_w, old_h = parse_svg_viewbox(root)

    if old_w <= 0 or old_h <= 0:
        raise RuntimeError(f"Invalid SVG viewBox or size: {source}")

    scale = render_pixels / max(old_w, old_h)
    render_w = max(64, int(math.ceil(old_w * scale)))
    render_h = max(64, int(math.ceil(old_h * scale)))

    with tempfile.TemporaryDirectory(prefix="crop-picture-svg-") as temp_dir:
        rendered = Path(temp_dir) / "render.png"
        render_svg_to_png(source, rendered, render_w, render_h, cancel_requested)
        with Image.open(rendered) as image:
            bbox = find_content_bbox(image, tolerance, alpha_threshold, padding, cancel_requested)

    check_cancelled(cancel_requested)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if bbox is None or bbox == (0, 0, render_w, render_h):
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return "kept"

    left, top, right, bottom = bbox
    new_x = old_x + (left / render_w) * old_w
    new_y = old_y + (top / render_h) * old_h
    new_w = ((right - left) / render_w) * old_w
    new_h = ((bottom - top) / render_h) * old_h

    root.set(
        "viewBox",
        " ".join(format_number(value) for value in (new_x, new_y, new_w, new_h)),
    )
    old_box = f"{format_number(old_x)} {format_number(old_y)} {format_number(old_w)} {format_number(old_h)}"
    new_box = f"{format_number(new_x)} {format_number(new_y)} {format_number(new_w)} {format_number(new_h)}"
    if old_box == new_box:
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        return "kept"
    tree.write(destination, encoding="utf-8", xml_declaration=True)
    return f"viewBox {old_box} -> {new_box}"


def process_file(
    source: Path,
    destination: Path,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    svg_render_pixels: int,
    cancel_requested: CancelCheck = None,
) -> str:
    """根据扩展名分发到位图裁剪或 SVG 裁剪。"""
    if source.suffix.lower() in SVG_EXTENSIONS:
        return crop_svg_file(source, destination, tolerance, alpha_threshold, padding, svg_render_pixels, cancel_requested)
    return crop_file(source, destination, tolerance, alpha_threshold, padding, cancel_requested)


def load_preview_image(
    source: Path,
    svg_render_pixels: int, cancel_requested: CancelCheck = None,
) -> Image.Image:
    """读取独立的预览图像；SVG 只在临时目录渲染。"""
    check_cancelled(cancel_requested)
    is_svg = source.suffix.lower() in SVG_EXTENSIONS
    if is_svg:
        _, _, width, height = parse_svg_viewbox(ET.parse(source).getroot())
        if width <= 0 or height <= 0:
            raise RuntimeError("SVG 的画布尺寸无效。")
        scale = svg_render_pixels / max(width, height)
        render_w, render_h = max(64, math.ceil(width * scale)), max(64, math.ceil(height * scale))
        with tempfile.TemporaryDirectory(prefix="crop-picture-preview-") as temp_dir:
            rendered = Path(temp_dir) / "preview.png"
            render_svg_to_png(source, rendered, render_w, render_h, cancel_requested)
            with Image.open(rendered) as image:
                before = image.convert("RGBA")
    else:
        with Image.open(source) as image:
            validate_static_image(image)
            before = image.convert("RGBA")
    check_cancelled(cancel_requested)
    return before


def preview_file(
    source: Path, tolerance: int, alpha_threshold: int, padding: int,
    svg_render_pixels: int, cancel_requested: CancelCheck = None,
) -> tuple[Image.Image, Image.Image, str]:
    """使用正式裁剪算法生成前后预览，不写入输出文件夹。"""
    before = load_preview_image(source, svg_render_pixels, cancel_requested)
    is_svg = source.suffix.lower() in SVG_EXTENSIONS

    bbox = find_content_bbox(before, tolerance, alpha_threshold, padding, cancel_requested)
    check_cancelled(cancel_requested)
    unchanged = bbox is None or bbox == (0, 0, before.width, before.height)
    after = before.copy() if unchanged else before.crop(cast(BBox, bbox))
    description = f"{before.width} × {before.height} → {after.width} × {after.height}"
    if is_svg:
        description = "SVG 检测图：" + description
    description += "；无需裁剪，将原样复制" if unchanged else "；预览未保存"
    # 边界按完整检测图计算，缩小显示图只用于控制界面内存占用。
    before.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    after.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return before, after, description


def collect_images(input_path: Path) -> list[Path]:
    """收集待处理图片；批量扫描跳过裁剪结果，单独指定的图片仍可处理。"""
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise SystemExit(f"Unsupported image type: {input_path}")
        return [input_path]

    if not input_path.is_dir():
        raise SystemExit(f"Input path does not exist: {input_path}")

    # 批量处理只收集原图，避免已有结果再次生成“裁剪_裁剪_”文件。
    return [
        path
        for path in sorted(input_path.iterdir())
        if path.is_file()
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and not path.name.startswith("裁剪_")
    ]


def build_destination(source: Path, input_path: Path, output_dir: Path) -> Path:
    """生成输出路径；同目录输出时自动添加“裁剪_”前缀避免覆盖原图。"""
    if input_path.is_dir():
        input_dir = input_path
    else:
        input_dir = input_path.parent

    if output_dir == input_dir:
        return output_dir / f"裁剪_{source.name}"
    return output_dir / source.name
