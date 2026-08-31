// Command securecv 是 SecureCV 的命令行入口：输入图片，输出 JSON 检测结果。
//
// 用法：
//
//	securecv [flags] <image> [image ...]
//
// 环境变量（必填）：api_key / base_url / model
// 环境变量（可选）：SECURECV_FONT_PATH、SECURECV_FONT_SIZE、SECURECV_MAX_SIZE、
//
//	SECURECV_CONCURRENCY、SECURECV_TIMEOUT、SECURECV_HTTP_TIMEOUT、SECURECV_DEBUG
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"

	"securecv"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "错误:", err)
		os.Exit(1)
	}
}


func run() error {
	var (
		label       = flag.Bool("label", true, "是否绘制标注框与标签")
		concurrency = flag.Int("concurrency", 0, "批量推理并发度，覆盖环境变量")
		timeout     = flag.Duration("timeout", 0, "单次请求超时，如 90s，覆盖环境变量")
		saveDir     = flag.String("save", "", "将标注图保存到指定目录")
		noImage     = flag.Bool("no-image", false, "输出中不包含 base64 图片，仅保留标签与坐标")
		pretty      = flag.Bool("pretty", false, "格式化输出 JSON")
		check       = flag.Bool("check", false, "仅校验模型连通性后退出")
	)
	flag.Usage = usage
	flag.Parse()

	cfg, err := securecv.LoadConfig()  // 加载模型配置
	if err != nil {
		return err
	}
	if *concurrency > 0 {
		cfg.Concurrency = *concurrency
	}
	if *timeout > 0 {
		cfg.Timeout = *timeout
	}
	securecv.SetupLogger(cfg.Debug)  // 初始化日志模块

	client, err := securecv.NewClient(cfg)  //创建openai客户端
	if err != nil {
		return err
	}

	if *check {  
		if !client.TestAPI(context.Background()) {
			return fmt.Errorf("模型连通性检查失败，请检查 api_key 与 base_url")
		}
		fmt.Println("模型连通性正常")
		return nil
	}

	paths := flag.Args()
	if len(paths) == 0 {
		flag.Usage()
		return fmt.Errorf("请至少提供一张图片路径")
	}

	results := client.BatchInferPaths(context.Background(), paths, *label)  //图片安全隐患检测
	if *saveDir != "" {
		saveResults(results, *saveDir)
	}
	if *noImage {
		for i := range results {
			results[i].Image = ""
		}
	}
	return writeJSON(os.Stdout, results, *pretty)
}

// writeJSON 将结果写入输出流。
func writeJSON(w *os.File, results []securecv.InferResult, pretty bool) error {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	if pretty {
		enc.SetIndent("", "  ")
	}
	return enc.Encode(results)
}

// saveResults 将标注图按序号保存为 JPEG。
func saveResults(results []securecv.InferResult, dir string) {
	for i, res := range results {
		if res.Image == "" || res.Error != "" {
			continue
		}
		img, err := securecv.DecodeBase64(res.Image)
		if err != nil {
			slog.Warn("标注图保存失败", "index", i, "error", err)
			continue
		}
		path := filepath.Join(dir, fmt.Sprintf("securecv_%03d.jpg", i+1))
		if err := securecv.SaveImage(path, img, 0); err != nil {
			slog.Warn("标注图保存失败", "path", path, "error", err)
			continue
		}
		slog.Info("标注图已保存", "path", path)
	}
}

func usage() {
	var sb strings.Builder
	sb.WriteString("securecv - 施工现场安全隐患检测\n\n用法:\n  securecv [flags] <image> [image ...]\n\n")
	sb.WriteString("示例:\n  set api_key=xxx&& set base_url=https://...&& set model=glm-4v && securecv image/1.jpg\n\n")
	sb.WriteString("环境变量:\n")
	sb.WriteString("  api_key / base_url / model          必填，模型参数\n")
	sb.WriteString("  SECURECV_FONT_PATH                  中文字体路径（默认自动探测 simhei.ttf）\n")
	sb.WriteString("  SECURECV_FONT_SIZE                  标注字号（默认 14）\n")
	sb.WriteString("  SECURECV_MAX_SIZE                   上传图片最大边长（默认 2048）\n")
	sb.WriteString("  SECURECV_CONCURRENCY                批量并发度（默认 4）\n")
	sb.WriteString("  SECURECV_TIMEOUT                    单次请求超时（默认 120s）\n")
	sb.WriteString("  SECURECV_HTTP_TIMEOUT               网络图片下载超时（默认 10s）\n")
	sb.WriteString("  SECURECV_DEBUG                      开启调试日志（1/true/yes/on）\n\n")
	sb.WriteString("参数:\n")
	fmt.Fprint(os.Stderr, sb.String())
	flag.PrintDefaults()
}
