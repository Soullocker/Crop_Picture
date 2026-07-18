from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from PIL import Image


# 常用类型别名：让 Pylance 更容易判断 tuple 的固定长度。
Color = tuple[int, int, int]
RgbaPixel = tuple[int, int, int, int]
BBox = tuple[int, int, int, int]
SvgViewBox = tuple[float, float, float, float]
CornerColors = tuple[Color, Color, Color, Color]

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
) -> BBox | None:
    """检测图片内容边界，返回可直接传给 Pillow crop 的边界框。"""
    rgba = image.convert("RGBA")
    width, height = rgba.size
    pixels = rgba.load()
    background = detect_background(rgba, alpha_threshold)
    corner_backgrounds = detect_corner_backgrounds(rgba, alpha_threshold, background)
    use_gradient_background = has_gradient_background(corner_backgrounds, tolerance)

    min_x, min_y = width, height
    max_x, max_y = -1, -1

    for y in range(height):
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
) -> str:
    """裁剪普通位图文件，并把结果保存到目标路径。"""
    with Image.open(source) as image:
        if image.format == "GIF" and getattr(image, "is_animated", False):
            raise RuntimeError("Animated GIF is not supported. Please export a single-frame image such as PNG.")
        if image.format == "TIFF" and getattr(image, "n_frames", 1) > 1:
            raise RuntimeError("Multi-page TIFF is not supported. Please split it into single-page images first.")

        bbox = find_content_bbox(image, tolerance, alpha_threshold, padding)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if bbox is None:
            image.save(destination)
            return "kept"

        cropped = image.crop(bbox)
        cropped.save(destination)

        if cropped.size == image.size:
            return "kept"
        return f"{image.size[0]}x{image.size[1]} -> {cropped.size[0]}x{cropped.size[1]}"


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


def render_svg_to_png(source: Path, output: Path, width: int, height: int) -> None:
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
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            command[1] = "--headless"
            completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"SVG rendering failed: {message}")


def crop_svg_file(
    source: Path,
    destination: Path,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    render_pixels: int,
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
        render_svg_to_png(source, rendered, render_w, render_h)
        with Image.open(rendered) as image:
            bbox = find_content_bbox(image, tolerance, alpha_threshold, padding)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if bbox is None:
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
    tree.write(destination, encoding="utf-8", xml_declaration=True)

    old_box = f"{format_number(old_x)} {format_number(old_y)} {format_number(old_w)} {format_number(old_h)}"
    new_box = f"{format_number(new_x)} {format_number(new_y)} {format_number(new_w)} {format_number(new_h)}"
    if old_box == new_box:
        return "kept"
    return f"viewBox {old_box} -> {new_box}"


def process_file(
    source: Path,
    destination: Path,
    tolerance: int,
    alpha_threshold: int,
    padding: int,
    svg_render_pixels: int,
) -> str:
    """根据扩展名分发到位图裁剪或 SVG 裁剪。"""
    if source.suffix.lower() in SVG_EXTENSIONS:
        return crop_svg_file(source, destination, tolerance, alpha_threshold, padding, svg_render_pixels)
    return crop_file(source, destination, tolerance, alpha_threshold, padding)


def collect_images(input_path: Path, names: list[str]) -> list[Path]:
    """收集待处理图片；只处理当前文件夹，不递归进入子文件夹。"""
    if input_path.is_file():
        if input_path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise SystemExit(f"Unsupported image type: {input_path}")
        if names:
            raise SystemExit("--name can only be used when --input is a folder.")
        return [input_path]

    if not input_path.is_dir():
        raise SystemExit(f"Input path does not exist: {input_path}")

    if names:
        files = [input_path / name for name in names]
        missing = [path.name for path in files if not path.exists()]
        if missing:
            raise SystemExit("These named image files were not found: " + ", ".join(missing))
        unsupported = [path.name for path in files if path.suffix.lower() not in IMAGE_EXTENSIONS]
        if unsupported:
            raise SystemExit("These named files are not supported images: " + ", ".join(unsupported))
        return files

    return [
        path
        for path in sorted(input_path.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
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


def main() -> int:
    """命令行入口。"""
    reconfigure_stdout = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure_stdout):
        reconfigure_stdout(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Crop white or transparent margins from exported raster images and SVG files."
    )
    parser.add_argument("--input", required=True, help="Input image file or folder.")
    parser.add_argument("--output", required=True, help="Output folder.")
    parser.add_argument(
        "--name",
        action="append",
        default=[],
        help="Image filename inside the input folder. Repeat this option for multiple files.",
    )
    parser.add_argument("--tolerance", type=int, default=12, help="Background color tolerance. Default: 12")
    parser.add_argument("--padding", type=int, default=5, help="Padding kept around content. Default: 5")
    parser.add_argument("--alpha-threshold", type=int, default=8, help="Transparent pixel threshold. Default: 8")
    parser.add_argument(
        "--svg-render-pixels",
        type=int,
        default=2400,
        help="Temporary render size used to detect SVG visible content. Default: 2400",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    image_files = collect_images(input_path, args.name)

    if not image_files:
        raise SystemExit(f"No supported image files found in: {input_path}")

    changed = 0
    kept = 0
    skipped: list[tuple[str, str]] = []
    for source in image_files:
        destination = build_destination(source, input_path, output_dir)
        try:
            result = process_file(
                source,
                destination,
                args.tolerance,
                args.alpha_threshold,
                args.padding,
                args.svg_render_pixels,
            )
        except Exception as error:
            skipped.append((source.name, str(error)))
            print(f"WARNING: {source.name}: skipped because {error}")
            continue

        if "->" in result:
            changed += 1
        else:
            kept += 1
        print(f"{source.name}: {result}")

    print(
        f"Done. Processed {len(image_files)} image(s); "
        f"cropped {changed}; kept {kept}; skipped {len(skipped)}; output: {output_dir}"
    )
    if skipped:
        print("Skipped files:")
        for filename, reason in skipped:
            print(f"- {filename}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
