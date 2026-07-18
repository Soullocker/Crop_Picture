# Crop Picture 图片白边裁剪 Skill

当前版本：`v2.1.0`

`Crop Picture` 是一个用于自动裁剪图片白边的 Codex Skill，同时也包含可独立运行的 Windows 图形界面 APP。

如果你想体验图形界面版本，请切换到 `app-version` 分支。  
本 `main` 分支保留 Skill / 核心裁剪代码，便于继续维护和同步源码。

它主要面向 MATLAB、Origin、Python/Matplotlib、Excel、仿真软件等导出的论文插图，能够批量去除图片四周多余的白色、透明、浅色纯色或平滑渐变边距，减少在 Word、PowerPoint 中手动裁剪图片的工作量。

本 Skill 同时支持：

- 位图图片：`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`、`.webp`、`.gif`、`.ppm`、`.pgm`、`.pbm`、`.pnm`
- SVG 矢量图：`.svg`

对于位图，程序会输出裁剪后的位图副本。  
对于 SVG，程序会保留矢量格式，不转换成 PNG，而是通过收紧根节点 `viewBox` 的方式裁剪画布边距。

## 适用场景

适合：

- 批量裁剪 MATLAB 导出图片的白边。
- 批量裁剪 Origin、Python、Excel、仿真软件导出的白底、透明底、浅色纯色背景或平滑渐变背景图表。
- 裁剪单张图片，并把结果保存到指定文件夹。
- 裁剪文件夹内指定名称的图片。
- 裁剪 SVG 矢量图，同时保留 `.svg` 矢量格式。
- 将处理后的图片插入 Word、PowerPoint 或论文文档。

不适合：

- 对照片进行主体识别式裁剪。
- 对复杂背景、纹理背景或照片做精确主体抠图。
- 替代专业图片编辑软件进行美化、标注、调色或内容修改。
- 对所有 SVG 结构做完美几何解析；本工具采用临时渲染检测可见边界，再修改 `viewBox`。

## 核心原则

- 不覆盖原始文件。
- 所有裁剪结果写入用户指定的输出文件夹。
- 当输出文件夹与输入文件夹不同，文件名保持不变。
- 当输出文件夹与输入文件夹相同，输出文件名自动添加 `裁剪_` 前缀，避免覆盖原图。
- 批量处理时，单张图片失败会被跳过，并在终端输出警告和失败汇总。
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
- `scripts/crop_picture.py`：核心裁剪程序，支持位图和 SVG，支持科研图常见纯色与平滑渐变背景。
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
- 动画 GIF 和多页 TIFF 不会被静默截取第一帧或第一页；程序会跳过并给出提示。

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

如果 `--output` 与 `--input` 指向同一个文件夹，输出文件会自动命名为 `裁剪_原文件名`，例如 `figure.png` 会输出为 `裁剪_figure.png`。

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
- 输出文件数量与成功处理的文件数量一致；失败文件会在终端提示并汇总。
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

### 浅灰色或平滑渐变背景没有裁干净怎么办？

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

## 打包与发布

### 打包成独立程序

在项目根目录运行：

```powershell
.\tools\build_app.bat
```

打包完成后，`dist/` 里会生成独立的 Windows 程序。

### 上传到 GitHub

1. 把源码改动提交到当前分支。
2. 推送到 GitHub 仓库。
3. 如果要发布给别人下载，去 GitHub 新建一个 Release。
4. 把 `dist/` 里的程序压缩后上传到 Release 附件。

这样可以保留之前版本。每次发布一个新版本时，新建一个 Release 就行，旧的 Release 仍然保留。

## 图形界面 APP

这是 `Crop Picture` 的桌面版，面向科研绘图场景，用来批量裁剪图片白边、透明边和浅色背景边距。

### 主要功能

- 选择单张图片或整个文件夹
- 裁剪后可保存到其他文件夹
- 也可以直接保存到原文件夹，并自动加上 `裁剪_` 前缀，避免覆盖原图
- 支持批量处理，单张失败不会中断后续图片
- 支持重复裁剪提醒，避免反复处理同一批文件

### 支持格式

`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`、`.webp`、`.gif`、`.ppm`、`.pgm`、`.pbm`、`.pnm`、`.svg`

### 运行方式

在项目根目录双击：

```text
tools\run_app.bat
```

也可以直接运行：

```text
.\.venv\Scripts\python.exe .\app\main.py
```

### 打包方式

在项目根目录运行：

```text
tools\build_app.bat
```

打包完成后，独立程序会生成在 `dist/` 目录中。

### 使用建议

- 科研绘图、论文插图、白底图、透明底图、纯色背景图都比较适合
- 如果是 `SVG`，请确保电脑上有 `Microsoft Edge` 或 `Google Chrome`
- 如果裁剪太紧，可以适当增大保留边距

## Version History

### v2.1.0 - Skill 与 APP 合并版本

- 将图形界面 APP 合并进同一仓库。
- APP 支持单张图片和文件夹批量裁剪。
- APP 支持输出到原文件夹时自动添加 `裁剪_` 前缀。
- APP 支持重复裁剪提醒、失败跳过和中文界面说明。
- README 统一整理为 Skill 与 APP 两部分说明。

### v1.0.0 - Initial usable version

- 支持 PNG/JPG/JPEG/BMP/TIF/TIFF 位图白边裁剪。
- 支持 SVG 矢量图裁剪，并保留 SVG 格式。
- 支持批量文件夹处理。
- 支持单张图片处理。
- 支持通过文件夹路径和文件名指定单个或多个文件。
- 提供 Windows 双击工具。
- 提供 Codex Skill 入口。

### v1.1.0 - Scientific figure workflow improvements

- 增加 `.webp`、`.gif`、`.ppm`、`.pgm`、`.pbm`、`.pnm` 格式识别。
- 增强浅色纯色和平滑渐变背景的裁剪判断。
- 当输入和输出为同一文件夹时，输出文件自动添加 `裁剪_` 前缀。
- 批量处理时单张失败不再中断后续文件，会输出警告和失败汇总。
