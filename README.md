# Crop Picture 图片白边裁剪 Skill

当前版本：`v1.0.0`

`Crop Picture` 是一个用于自动裁剪图片白边的 Codex Skill，同时也可以作为本地 Windows 小工具独立使用。

它主要面向 MATLAB、Origin、Python/Matplotlib、Excel、仿真软件等导出的论文插图，能够批量去除图片四周多余的白色或透明边距，减少在 Word、PowerPoint 中手动裁剪图片的工作量。

本 Skill 同时支持：

- 位图图片：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`
- SVG 矢量图：`.svg`

对于位图，程序会输出裁剪后的位图副本。  
对于 SVG，程序会保留矢量格式，不转换成 PNG，而是通过收紧根节点 `viewBox` 的方式裁剪画布边距。

## 适用场景

适合：

- 批量裁剪 MATLAB 导出图片的白边。
- 批量裁剪 Origin、Python、Excel、仿真软件导出的白底图表。
- 裁剪单张图片，并把结果保存到指定文件夹。
- 裁剪文件夹内指定名称的图片。
- 裁剪 SVG 矢量图，同时保留 `.svg` 矢量格式。
- 将处理后的图片插入 Word、PowerPoint 或论文文档。

不适合：

- 对照片进行主体识别式裁剪。
- 对复杂背景、渐变背景或纹理背景图片做精确抠图。
- 替代专业图片编辑软件进行美化、标注、调色或内容修改。
- 对所有 SVG 结构做完美几何解析；本工具采用临时渲染检测可见边界，再修改 `viewBox`。

## 核心原则

- 不覆盖原始文件。
- 所有裁剪结果写入用户指定的输出文件夹。
- 文件名保持不变。
- 位图输出仍为原格式图片。
- SVG 输出仍为 SVG 矢量文件。
- 如果裁剪过紧，可以通过 `--padding` 增大保留边距。

## 仓库结构

```text
.
├─ README.md
├─ SKILL.md
├─ requirements.txt
├─ agents/
│  └─ openai.yaml
├─ scripts/
│  └─ crop_picture.py
└─ tools/
   ├─ crop_folder.bat
   ├─ crop_folder.ps1
   ├─ crop_single.bat
   ├─ crop_single.ps1
   ├─ install_dependencies.bat
   └─ install_dependencies.ps1
```

文件说明：

- `SKILL.md`：Codex Skill 主入口，描述何时触发以及如何调用裁剪脚本。
- `agents/openai.yaml`：Codex UI 元数据。
- `requirements.txt`：Python 依赖，目前主要是 `Pillow`。
- `scripts/crop_picture.py`：核心裁剪程序，支持位图和 SVG。
- `tools/crop_folder.bat`：双击批量裁剪整个文件夹。
- `tools/crop_single.bat`：双击裁剪单张图片，支持完整路径或“文件夹 + 文件名”。
- `tools/install_dependencies.bat`：双击创建或修复本地 `.venv` 虚拟环境。

## 环境要求

推荐环境：

- Windows 10/11
- Python 3.10 或更高版本
- PowerShell
- Microsoft Edge 或 Google Chrome
- Codex Desktop 或支持本地 Skill 的 Codex 环境

说明：

- 位图裁剪依赖 Python 包 `Pillow`。
- SVG 裁剪会临时调用 Microsoft Edge 或 Google Chrome 进行无头渲染，用于检测可见内容边界。
- SVG 最终不会被保存为 PNG，输出仍然是 `.svg`。
- 如果只处理 PNG/JPG/TIF 等位图，不需要浏览器参与。

## 安装方式

### 方式一：作为 Codex Skill 安装

将本仓库克隆或复制到 Codex skills 目录。

Windows 示例：

```powershell
git clone https://github.com/Soullocker/Crop_Picture.git "$env:USERPROFILE\.codex\skills\crop-picture"
```

安装 Python 依赖：

```powershell
cd "$env:USERPROFILE\.codex\skills\crop-picture"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

也可以双击：

```text
tools\install_dependencies.bat
```

安装后，重启 Codex 或开启新会话，使 Skill 被重新发现。

### 方式二：作为普通本地工具使用

克隆仓库到任意目录，例如：

```powershell
git clone https://github.com/Soullocker/Crop_Picture.git D:\Tools\Crop_Picture
```

进入目录并安装依赖：

```powershell
cd D:\Tools\Crop_Picture
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

之后可以双击使用：

```text
tools\crop_folder.bat
tools\crop_single.bat
```

## 推荐使用方式

### 在 Codex 中使用

示例请求：

```text
裁剪 D:\论文\图片 文件夹下的所有图片和 SVG，输出到 D:\论文\图片_裁剪后。
```

```text
只裁剪 D:\论文\图片 文件夹里的 figure.svg，输出到 D:\论文\裁剪后。
```

```text
帮我把这个文件夹里的 MATLAB 导出图去掉白边，原图不要覆盖。
```

### 双击批量裁剪

双击：

```text
tools\crop_folder.bat
```

按提示输入：

```text
Input image folder path:
输出前图片所在文件夹

Output folder path:
裁剪后图片保存文件夹

Padding pixels, press Enter for 8:
保留边距，直接回车使用默认值
```

### 双击裁剪单张图片

双击：

```text
tools\crop_single.bat
```

可以输入单张图片完整路径：

```text
D:\论文\图片\figure.png
```

也可以先输入图片所在文件夹，再输入文件名：

```text
D:\论文\图片
figure.svg
```

## 命令行用法

### 批量裁剪文件夹

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py `
  --input "D:\path\images" `
  --output "D:\path\images_cropped"
```

### 裁剪单张图片

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py `
  --input "D:\path\images\figure.png" `
  --output "D:\path\cropped"
```

### 裁剪文件夹内指定图片

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py `
  --input "D:\path\images" `
  --output "D:\path\cropped" `
  --name "figure.svg"
```

### 裁剪多个指定文件

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py `
  --input "D:\path\images" `
  --output "D:\path\cropped" `
  --name "figure1.png" `
  --name "figure2.svg"
```

## 参数说明

常用参数：

- `--input`：输入文件或文件夹路径。
- `--output`：输出文件夹路径。
- `--name`：当 `--input` 是文件夹时，指定只处理某个文件名；可以重复使用。
- `--padding`：裁剪后额外保留的边距，默认 `5` 像素。
- `--tolerance`：背景颜色容差，默认 `12`。
- `--alpha-threshold`：透明像素判断阈值，默认 `8`。
- `--svg-render-pixels`：SVG 临时渲染检测尺寸，默认 `2400`。

示例：如果裁剪太紧，可以增大边距：

```powershell
.\.venv\Scripts\python.exe .\scripts\crop_picture.py `
  --input "D:\path\images" `
  --output "D:\path\images_cropped" `
  --padding 20
```

## SVG 裁剪说明

SVG 是矢量图，不适合直接用位图裁剪方式保存。

本工具对 SVG 的处理流程是：

1. 使用 Edge 或 Chrome 临时把 SVG 渲染成检测图。
2. 根据检测图识别白色或透明边距。
3. 将检测到的内容边界映射回 SVG 坐标。
4. 修改 SVG 根节点的 `viewBox`。
5. 保存为新的 `.svg` 文件。

因此，SVG 输出仍然是矢量图，适合插入 Word、PowerPoint 或论文文档。

## 验收标准

一个合格的裁剪结果应满足：

- 原始文件未被覆盖。
- 输出文件数量与待处理文件数量一致。
- 位图白边明显减少。
- 坐标轴、图例、标题、文字没有被裁掉。
- SVG 文件仍然是 `.svg` 格式。
- SVG 的 `viewBox` 被收紧，而不是转成 PNG。
- 中文路径和中文文件名可以正常处理。

## 常见问题

### 裁剪太紧怎么办？

增大 `--padding`，例如：

```powershell
--padding 20
```

### 浅灰色背景没有裁干净怎么办？

适当增大 `--tolerance`，例如：

```powershell
--tolerance 20
```

### 浅色坐标轴或文字被裁掉怎么办？

降低 `--tolerance`，或增大 `--padding`。

### SVG 裁剪失败怎么办？

请确认已安装 Microsoft Edge 或 Google Chrome。

### 可以处理照片吗？

不推荐。本工具主要面向图表、示意图、白底导出图和 SVG 矢量图。

## Version History

### v1.0.0 - Initial usable version

- 支持 PNG/JPG/JPEG/BMP/TIF/TIFF 位图白边裁剪。
- 支持 SVG 矢量图裁剪，并保留 SVG 格式。
- 支持批量文件夹处理。
- 支持单张图片处理。
- 支持通过文件夹路径和文件名指定单个或多个文件。
- 提供 Windows 双击工具。
- 提供 Codex Skill 入口。
