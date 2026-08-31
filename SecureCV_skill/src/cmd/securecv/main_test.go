package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"image"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"securecv"
)

// 真实测试配置与测试图，go test -short 时跳过联网用例。
const (
	testAPIKey  = "sk-live-FwvUaHKfDD_immjRYXa719dzIy9fxmNHzh5pq1Lmzf4"
	testBaseURL = "https://api.modelbest.cn/v1"
	testModel   = "MiniCPM-V-4.5"
	testImage   = `C:\Users\admin\Desktop\SecureEye\image\159.jpg`
)

// ------------------------------------------------------------------ 测试脚手架

// prepareOutDir 清空并返回项目内的输出目录，便于直接查看结果。
// 位于 testdata 下，Go 工具链会跳过该目录，不会参与构建。
func prepareOutDir(t *testing.T) string {
	t.Helper()
	dir := filepath.Join("testdata", "out")
	if err := os.RemoveAll(dir); err != nil {
		t.Fatalf("清空输出目录失败: %v", err)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("创建输出目录失败: %v", err)
	}
	abs, err := filepath.Abs(dir)
	if err != nil {
		t.Fatalf("解析输出目录失败: %v", err)
	}
	t.Logf("输出目录: %s", abs)
	return dir
}

// setupEnv 注入真实模型配置。
func setupEnv(t *testing.T) {
	t.Helper()
	t.Setenv("api_key", testAPIKey)
	t.Setenv("base_url", testBaseURL)
	t.Setenv("model", testModel)
}

// requireOnline 在 -short 模式下跳过联网用例。
func requireOnline(t *testing.T) {
	t.Helper()
	if testing.Short() {
		t.Skip("跳过真实 API 用例")
	}
	setupEnv(t)
}

// requireImage 校验真实测试图可用。
func requireImage(t *testing.T) string {
	t.Helper()
	if _, err := os.Stat(testImage); err != nil {
		t.Fatalf("测试图不可用: %v", err)
	}
	return testImage
}

// capture 把 file 临时换成管道，返回期间写入的全部内容。
func capture(t *testing.T, file **os.File, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatalf("创建管道失败: %v", err)
	}
	old := *file
	*file = w
	defer func() { *file = old }()

	done := make(chan string, 1)
	go func() {
		var buf bytes.Buffer
		_, _ = io.Copy(&buf, r)
		done <- buf.String()
	}()

	fn()
	_ = w.Close()
	out := <-done
	_ = r.Close()
	return out
}

// runCLI 重置全局 flag 后执行 run，返回 stdout 内容与错误。
func runCLI(t *testing.T, args ...string) (string, error) {
	t.Helper()
	oldFlags, oldArgs := flag.CommandLine, os.Args
	t.Cleanup(func() { flag.CommandLine, os.Args = oldFlags, oldArgs })

	flag.CommandLine = flag.NewFlagSet("securecv", flag.ContinueOnError)
	flag.CommandLine.SetOutput(io.Discard)
	flag.CommandLine.Usage = usage
	os.Args = append([]string{"securecv"}, args...)

	var err error
	out := capture(t, &os.Stdout, func() { err = run() })
	return out, err
}

// decodeResults 校验 stdout 是合法的 JSON 结果数组。
func decodeResults(t *testing.T, out string) []securecv.InferResult {
	t.Helper()
	var results []securecv.InferResult
	if err := json.Unmarshal([]byte(out), &results); err != nil {
		t.Fatalf("输出不是合法 JSON: %v\n%.512s", err, out)
	}
	return results
}

// ------------------------------------------------------------------ 联网用例

func TestRunCheck(t *testing.T) {
	requireOnline(t)

	out, err := runCLI(t, "-check")
	if err != nil {
		t.Fatalf("连通性检查失败: %v", err)
	}
	if !strings.Contains(out, "模型连通性正常") {
		t.Fatalf("输出缺少成功提示: %q", out)
	}
}

func TestRunInfer(t *testing.T) {
	requireOnline(t)

	out, err := runCLI(t, requireImage(t))
	if err != nil {
		t.Fatalf("推理失败: %v", err)
	}
	results := decodeResults(t, out)
	if len(results) != 1 {
		t.Fatalf("期望 1 条结果，实际 %d 条", len(results))
	}
	res := results[0]
	if res.Error != "" {
		t.Fatalf("单图处理出错: %s", res.Error)
	}
	if !strings.HasPrefix(res.Image, "data:image/jpeg;base64,") {
		t.Fatalf("标注图缺失或格式错误: %.64q", res.Image)
	}
	t.Logf("检测结果 %d 条: %s", len(res.Detections), res.Label)
}

func TestRunInferWithFlags(t *testing.T) {
	requireOnline(t)
	saveDir := prepareOutDir(t)

	out, err := runCLI(t, "-no-image", "-pretty", "-save", saveDir, "-concurrency", "2", requireImage(t))
	if err != nil {
		t.Fatalf("推理失败: %v", err)
	}
	results := decodeResults(t, out)
	if results[0].Error != "" {
		t.Fatalf("单图处理出错: %s", results[0].Error)
	}
	if results[0].Image != "" {
		t.Fatalf("-no-image 应清空图片字段: %.64q", results[0].Image)
	}
	if !strings.Contains(out, "\n  ") {
		t.Fatalf("-pretty 应缩进输出")
	}
	if _, err := os.Stat(filepath.Join(saveDir, "securecv_001.jpg")); err != nil {
		t.Fatalf("-save 未生成标注图: %v", err)
	}
}

func TestRunInferBadPath(t *testing.T) {
	setupEnv(t)

	out, err := runCLI(t, filepath.Join(t.TempDir(), "missing.jpg"))
	if err != nil {
		t.Fatalf("单图失败不应中断整批: %v", err)
	}
	if res := decodeResults(t, out); res[0].Error == "" {
		t.Fatalf("结果中应记录错误信息: %s", out)
	}
}

// ------------------------------------------------------------------ 离线用例

func TestWriteJSON(t *testing.T) {
	results := []securecv.InferResult{{Label: "1.a<b>&c"}}
	path := filepath.Join(t.TempDir(), "out.json")

	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("创建文件失败: %v", err)
	}
	if err := writeJSON(f, results, false); err != nil {
		t.Fatalf("writeJSON 失败: %v", err)
	}
	_ = f.Close()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("读取输出失败: %v", err)
	}
	if !strings.Contains(string(data), "a<b>&c") {
		t.Fatalf("应关闭 HTML 转义: %s", data)
	}
	if strings.Contains(string(data), "\n  ") {
		t.Fatalf("紧凑模式不应缩进: %s", data)
	}
}

func TestSaveResults(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	b64, err := securecv.EncodeImage(image.NewRGBA(image.Rect(0, 0, 8, 8)))
	if err != nil {
		t.Fatalf("编码测试图失败: %v", err)
	}

	saveResults([]securecv.InferResult{
		{Image: "data:image/jpeg;base64," + b64},
		{Image: "not-base64"},
		{Error: "推理失败"},
		{Image: ""},
	}, dir)

	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatalf("读取保存目录失败: %v", err)
	}
	if len(entries) != 1 || entries[0].Name() != "securecv_001.jpg" {
		t.Fatalf("应只保存 1 张有效图，实际: %v", entries)
	}
}

func TestUsage(t *testing.T) {
	out := capture(t, &os.Stderr, usage)
	for _, want := range []string{"securecv -", "[flags] <image>", "SECURECV_DEBUG"} {
		if !strings.Contains(out, want) {
			t.Fatalf("用法输出缺少 %q", want)
		}
	}
}
