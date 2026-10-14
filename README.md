# Crop Picture 图片裁剪 APP

当前版本：`v2.1.0`

这是 `Crop Picture` 的图形界面版，面向科研绘图场景，用来批量裁剪图片白边、透明边和浅色背景边距。

## 主要功能

- 支持单张图片或整个文件夹
- 支持批量处理，单张失败不会中断后续图片
- 支持输出到原文件夹时自动加上 `裁剪_` 前缀，避免覆盖原图
- 文件夹批量处理会跳过以 `裁剪_` 开头的图片；重新裁剪原图时，会覆盖更新同名裁剪结果
- 支持重复裁剪提醒
- 支持失败跳过并给出文字提示

## 支持格式

`.png`、`.jpg`、`.jpeg`、`.bmp`、`.tif`、`.tiff`、`.webp`、`.gif`、`.ppm`、`.pgm`、`.pbm`、`.pnm`、`.svg`

## 运行方式

在项目根目录双击：

```text
tools\run_app.bat
```

也可以直接运行：

```text
.\.venv\Scripts\python.exe .\app\main.py
```

## 打包方式

在项目根目录双击：

```text
tools\build_app.bat
```

打包完成后，独立程序会生成在 `dist/` 目录中。

## 文件结构

```text
.
├─ README.md
├─ app/
│  ├─ __init__.py
│  └─ main.py
├─ assets/
│  ├─ README.md
│  └─ app_icon.png
├─ scripts/
│  └─ crop_picture.py
├─ tools/
│  ├─ build_app.bat
│  ├─ build_app.ps1
│  ├─ run_app.bat
│  └─ run_app.ps1
├─ requirements.txt
└─ pyrightconfig.json
```

## 使用建议

- 适合科研绘图、论文插图、白底图、透明底图、纯色背景图
- 如果是 `SVG`，请确保电脑上有 `Microsoft Edge` 或 `Google Chrome`
- 如果裁剪太紧，可以适当增大保留边距

## 作为 Codex Skill 使用

本项目也可以作为 Codex Skill 安装，详见 [Skill 使用说明](README_SKILL.md)。

## 版本说明

### v2.1.0

- 新增科研图片裁剪图形界面 APP
- 支持单张图片和文件夹批量裁剪
- 支持输出到原文件夹时自动添加 `裁剪_` 前缀
- 支持重复裁剪提醒、失败跳过和中文界面说明
