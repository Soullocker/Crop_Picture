---
name: crop-picture
description: Crop white or transparent margins from exported raster images and SVG vector graphics. Use when the user asks to remove blank borders, crop a folder of images, crop a named image, or crop SVG files while keeping vector output.
---

# Crop Picture

Use this skill to crop blank margins from exported images and SVG vector graphics.

## Tool Location

The reusable script is bundled with this skill:

```text
scripts/crop_picture.py
```

Use the Python environment available on the machine, or create a local `.venv` from `requirements.txt`.

From this skill folder:

```powershell
python .\scripts\crop_picture.py --input "<input file or folder>" --output "<output folder>"
```

On Windows after creating `.venv`:

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py --input "<input file or folder>" --output "<output folder>"
```

## Supported Requests

- Crop every supported file in the current folder, without recursing into subfolders.
- Crop a single raster image or SVG file.
- Crop one or more named files inside a folder.
- Save results to a user-specified output folder.
- If the output folder is the same as the input folder, save cropped files with the `裁剪` prefix.
- Skip files that fail to crop and print a warning, then continue with the remaining files.

Supported formats: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`, `.webp`, `.gif`, `.ppm`, `.pgm`, `.pbm`, `.pnm`, `.svg`.

The script preserves original files. It writes cropped copies to the output folder.

For raster files, the output is a cropped raster image. For SVG files, the output remains SVG and the script tightens the root `viewBox`.

The raster cropper is tuned for scientific figures with plain white, transparent, light solid-color, or smooth gradient backgrounds. It is not intended for general photo subject detection.

## Usage

Batch folder:

```powershell
python .\scripts\crop_picture.py --input "D:\path\images" --output "D:\path\images_cropped"
```

Single file:

```powershell
python .\scripts\crop_picture.py --input "D:\path\figure.svg" --output "D:\path\cropped"
```

Named file inside a folder:

```powershell
python .\scripts\crop_picture.py --input "D:\path\images" --output "D:\path\cropped" --name "figure.svg"
```

## Parameters

- `--padding`: Extra pixels retained around detected content. Default: `5`.
- `--tolerance`: Background color tolerance. Default: `12`.
- `--alpha-threshold`: Transparent pixel threshold. Default: `8`.
- `--svg-render-pixels`: Temporary render size for SVG boundary detection. Default: `2400`.

If a crop looks too tight, rerun with a larger `--padding`, such as `--padding 20`.

## SVG Notes

SVG cropping keeps vector output by temporarily rendering the SVG in Microsoft Edge or Google Chrome to detect the visible content boundary, then updating the root `viewBox`.

If SVG cropping fails, confirm that Microsoft Edge or Google Chrome is installed. Raster image cropping only requires Pillow.

## Assistant Behavior

When the user provides input and output paths, run the bundled script. Do not overwrite the original files. If the user names a single file inside a folder, pass it with `--name`.
