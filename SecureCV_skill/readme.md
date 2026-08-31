# SecureCV Skill

基于多模态大模型的**施工现场安全隐患检测**技能，Go 语言实现，纯 Go 依赖，可离线构建。

输入一张或多张工地图片，识别工人的不安全行为与违章作业，输出边界框坐标、中文隐患描述，并在原图上绘制红色标注框与中文标签。

能力来源于原 Python 实现 `core/agent.py` / `core/models.py` / `core/utils.py`，本目录为其 Go 重写版本，行为逐条对齐，本期不包含视频抽帧、docx/excel 导出与界面部分。

## 目录结构

```
SecureCV_skill/
├── skill.yml                  # 技能描述：名称、版本、作者、输入输出参数、入口
├── readme.md                  # 本文档
├── SKILL.md                   # CodeBuddy 技能发现用的元数据与流程指引
└── src/
    ├── go.mod / go.sum        # 模块声明与依赖校验
    ├── vendor/                # go mod vendor 产物，离线可构建
    ├── assets/simhei.ttf      # 中文标注字体
    ├── config.go              # 环境变量加载、校验、日志与字体探测
    ├── models.go              # 数据结构与坐标归一化
    ├── utils.go               # 坐标反归一化、JSON 提取、正则兜底解析
    ├── image.go               # 图片输入抽象、缩放、编码、保存
    ├── visualize.go           # 字体加载、边界框与中文标签绘制
    ├── prompts.go             # 两套中文提示词
    ├── api_client.go          # openai-go 封装：结构化输出 / JSON 双模式
    ├── handler.go             # 检测降级链、单图与批量推理编排
    └── cmd/securecv/main.go   # 命令行入口
```

## 环境要求

- Go 1.25 及以上（依赖 `openai-go/v3` 与 `x/image` 的 go.mod 要求）
- 依赖已通过 `go mod vendor` 落地到 `src/vendor`，无需联网即可构建

## 环境变量

必填（模型参数，不硬编码在代码中）：

| 变量 | 说明 | 兼容别名 |
| --- | --- | --- |
| `api_key` | 模型服务密钥 | `API_KEY`、`OPENAI_API_KEY` |
| `base_url` | OpenAI 兼容端点 | `BASE_URL`、`OPENAI_BASE_URL` |
| `model` | 多模态视觉模型名 | `MODEL`、`OPENAI_MODEL` |

可选：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `SECURECV_FONT_PATH` | 中文标注字体路径 | 自动探测 `assets/simhei.ttf` |
| `SECURECV_FONT_SIZE` | 标注字号 | `14` |
| `SECURECV_MAX_SIZE` | 上传图片最大边长，超出等比缩小 | `2048` |
| `SECURECV_CONCURRENCY` | 批量推理并发度 | `4` |
| `SECURECV_TIMEOUT` | 单次请求超时，支持 `90s`/`2m` | `120s` |
| `SECURECV_HTTP_TIMEOUT` | 网络图片下载超时 | `10s` |
| `SECURECV_DEBUG` | 开启调试日志（会打印模型原始输出） | 关闭 |

## 构建

```bash
cd src
go build -o ../bin/securecv ./cmd/securecv     # Windows 下产物为 securecv.exe
```

离线构建（使用 vendor 目录）：

```bash
cd src && go build -mod=vendor -o ../bin/securecv ./cmd/securecv
```

## 命令行用法

```
securecv [flags] <image> [image ...]
```

常用参数：

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `-label` | 是否绘制标注框与标签 | `true` |
| `-concurrency` | 批量并发度，覆盖环境变量 | 环境变量值 |
| `-timeout` | 单次请求超时，覆盖环境变量 | 环境变量值 |
| `-save <dir>` | 将标注图保存到指定目录 | 不保存 |
| `-no-image` | 输出不含 base64 图片，仅保留标签与坐标 | `false` |
| `-pretty` | 格式化输出 JSON | `false` |
| `-check` | 仅校验模型连通性后退出 | - |

示例（PowerShell）：

```powershell
$env:api_key="sk-xxxx"
$env:base_url="https://open.bigmodel.cn/api/paas/v4/"
$env:model="glm-4.6v-flash"

# 单图检测，结果 JSON 输出到 stdout
.\bin\securecv.exe -pretty ..\image\159.jpg

# 多图批量检测并保存标注图
.\bin\securecv.exe -save out -concurrency 4 ..\image\5.jpg ..\image\6.jpg

# 仅校验连通性
.\bin\securecv.exe -check
```

输出约定：

- **stdout** 只有一份 JSON 结果数组，可被安全管道解析
- **stderr** 承载全部日志，不污染结果
- 图片以 `data:image/jpeg;base64,...` 形式返回，与 `app_main.py` 的现有约定一致

输出示例：

```json
[
  {
    "image": "data:image/jpeg;base64,/9j/4AAQ...",
    "label": "1.工人临边作业未正确佩戴或挂扣安全带",
    "detections": [
      { "bbox_2d": [120, 85, 340, 290], "label": "工人临边作业未正确佩戴或挂扣安全带" }
    ]
  }
]
```

## 作为库使用

```go
package main

import (
	"context"
	"encoding/json"
	"os"

	"securecv"
)

func main() {
	cfg, err := securecv.LoadConfig() // 从环境变量读取 api_key / base_url / model
	if err != nil {
		panic(err)
	}
	securecv.SetupLogger(cfg.Debug)

	client, err := securecv.NewClient(cfg)
	if err != nil {
		panic(err)
	}

	// 单图：支持本地路径、http(s) 链接
	res, err := client.InferPath(context.Background(), "image/159.jpg", true)
	if err != nil {
		panic(err)
	}

	// 批量：并发受限流控制，单图失败写入 error 字段而不中断整批
	results := client.BatchInferPaths(context.Background(), []string{"image/5.jpg", "image/6.jpg"}, true)

	json.NewEncoder(os.Stdout).Encode(results)
}
```

常用 API：

| 方法 | 说明 |
| --- | --- |
| `LoadConfig()` | 从环境变量加载并校验配置 |
| `NewClient(cfg)` | 创建客户端，顺带加载字体（失败自动降级） |
| `client.TestAPI(ctx)` | 连通性自检 |
| `client.InferPath(ctx, path, isLabel)` | 单图推理，自动识别本地路径/URL |
| `client.BatchInferPaths(ctx, paths, isLabel)` | 批量推理，按输入顺序返回 |
| `client.Detect(ctx, src)` | 只做检测，不绘制 |
| `securecv.ParseDetections(content)` | 解析模型输出文本（含容错兜底） |
| `securecv.VisualizeBoxes(img, boxes, labels, face, renormalize)` | 独立绘制标注 |

## 关键实现说明

- **结构化输出优先，自动降级**：先以 `json_schema` 严格模式请求；服务端不支持时静默降级为 `json_object` 通用模式；解析仍失败则走正则逐条兜底。
- **坐标体系**：模型返回 `[0,1000]` 归一化坐标，`detections` 原样保留归一化值；绘制时按图片宽高还原为像素坐标，并自动纠正 `x1>x2`、`y1>y2` 的非法顺序。
- **图片预处理**：边长超过 `SECURECV_MAX_SIZE` 时等比缩小；未超限时走快速路径直接上传原始字节，省去一次解码与重编码。
- **并发与容错**：批量推理用带缓冲 channel 限流，结果按索引归位保证顺序；单图失败只写入该条目的 `error` 字段。
- **字体降级**：字体缺失或解析失败时仅跳过标签绘制，边界框照常输出，不阻断主流程。

## 常见问题

**提示缺少 `api_key` / `base_url` / `model`** — 这三个变量为必填项，确认已设置且值非空。PowerShell 用 `$env:api_key="..."`，CMD 用 `set api_key=...`。

**模型返回 400，但结果仍正常** — 说明服务端不支持 `json_schema` 严格模式，已自动降级为 `json_object`，属预期行为，日志中会有一条 Warning。

**标签没有中文，只画了红框** — 未找到 `simhei.ttf`。设置 `SECURECV_FONT_PATH` 指向字体文件，或把字体放到可执行文件同级的 `assets/` 目录。

**输出 JSON 很大** — 加 `-no-image` 去掉 base64 图片，只保留标签与坐标。
