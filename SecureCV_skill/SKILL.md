---
name: securecv
description: 基于多模态大模型的施工现场安全隐患检测技能，用 Go 实现。用于识别工地图片中工人的不安全行为与违章作业，输出边界框坐标、中文隐患描述与带标注的结果图。当用户提出安全隐患检测、违章行为识别、工地图像标注、PPE 佩戴检查、批量图片安全巡检等需求时，应使用本技能。
---

# SecureCV 安全隐患检测

## 用途

对施工现场图片调用多模态视觉大模型，识别工人的不安全行为（高处/临边作业未挂安全带、未戴安全帽、未穿反光背心、攀爬护栏、探出升降平台等），输出边界框与中文隐患描述，并可绘制红框标注图。

## 前置条件

- 环境变量 `api_key`、`base_url`、`model` 必须已设置；缺失时程序直接报错退出，不要尝试硬编码密钥
- 可执行文件为 `bin/securecv.exe`（Windows）或 `bin/securecv`（Linux/macOS），由 `skill.yml` 的 `binary` 字段定位；编译步骤见 `readme.md`

## 执行流程

1. **先做连通性自检**：`bin\securecv -check`，确认模型可用后再进入检测；不通则提示用户检查 `api_key` / `base_url`。
2. **运行检测**：`securecv [flags] <image> [image ...]`，图片支持本地路径与 http(s) 链接，可接受单张或多张。
3. **解析 stdout**：结果是 JSON 数组；日志在 stderr，不要混用。`-pretty` 仅用于人工阅读、程序消费时不加。
4. **解读结果**：
   - `detections` 为空 → 该图未发现隐患
   - 某条目 `error` 非空 → 该图处理失败，其余图片不受影响

## 参数要点

- `-label=false`：只检测不画框，返回原图
- `-save <dir>`：把标注图写成 JPEG 文件（按序号命名）
- `-pretty`：格式化 JSON，便于人工阅读；程序消费时不加
- `-concurrency N` / `-timeout D`：覆盖环境变量 `SECURECV_CONCURRENCY`、`SECURECV_TIMEOUT`

## 坐标约定

`detections[].bbox_2d` 是 `[0,1000]` 的归一化坐标 `[x1, y1, x2, y2]`，转像素需除以 1000 再乘图片宽高。若要在其他系统中复用结果，注意先做这一步换算。

## 参考

- 完整的环境变量、输入输出契约见 `skill.yml`
- 库调用方式与常见问题见 `readme.md`
- 提示词位于 `src/prompts.go`，调整识别范围时修改该文件
