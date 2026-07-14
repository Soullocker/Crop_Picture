# Crop Picture

Crop Picture is a Codex skill and local utility for removing white or transparent margins from exported figures.

It supports raster images and SVG vector graphics:

- Raster: `.png`, `.jpg`, `.jpeg`, `.bmp`, `.tif`, `.tiff`
- Vector: `.svg`

Raster files are cropped as images. SVG files keep their vector format; the tool tightens the root `viewBox` instead of converting them to PNG.

## Requirements

- Python 3.10 or newer
- Microsoft Edge or Google Chrome for SVG cropping
- Python package: `Pillow`

## Setup

From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Or double-click:

```text
tools\install_dependencies.bat
```

## Double-click Tools

- `tools\crop_folder.bat`: crop every supported file in a folder.
- `tools\crop_single.bat`: crop one file by full path, or by folder plus filename.
- `tools\install_dependencies.bat`: create or repair the local `.venv`.

The `.bat` files launch small PowerShell prompts so Chinese paths and filenames are handled reliably on Windows.

The original files are not modified. Cropped files are written to the output folder you choose.

## Command Examples

Batch folder:

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py --input "D:\path\images" --output "D:\path\images_cropped"
```

Single SVG:

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py --input "D:\path\figure.svg" --output "D:\path\cropped"
```

Named file in a folder:

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py --input "D:\path\images" --output "D:\path\cropped" --name "figure.svg"
```

If the crop is too tight, add a larger padding value:

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py --input "D:\path\images" --output "D:\path\images_cropped" --padding 20
```

## Install As A Codex Skill

Copy or link this folder into your Codex skills directory, for example:

```text
C:\Users\<you>\.codex\skills\crop-picture
```

Keep `SKILL.md` at the root of the skill folder.
