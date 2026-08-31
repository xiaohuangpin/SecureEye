package securecv

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"
)

// InferResult 为单张图片的推理结果，同时作为 CLI 的 JSON 输出单元。
type InferResult struct {
	Image      string          `json:"image"`           // data URI，与 app_main.py 的约定一致
	Label      string          `json:"label"`           // "1.描述\n2.描述"
	Detections []DetectionItem `json:"detections"`      // 归一化坐标的检测条目
	Error      string          `json:"error,omitempty"` // 单图错误信息，不影响整批
}

// Infer 对单张图片执行检测，isLabel 为 true 时返回带标注的图片。
func (c *Client) Infer(ctx context.Context, src ImageSource, isLabel bool) (InferResult, error) {
	loaded, err := src.Load(c.cfg.MaxSize)
	if err != nil {
		return InferResult{}, err
	}
	detections, err := c.DetectWith(ctx, loaded)
	if err != nil {
		return InferResult{}, err
	}
	return c.buildResult(loaded, detections, isLabel)
}

// InferPath 便捷入口：直接传入本地路径或图片 URL。
func (c *Client) InferPath(ctx context.Context, path string, isLabel bool) (InferResult, error) {
	return c.Infer(ctx, SourceOf(path, c.cfg.HTTPTimeout), isLabel)
}

// BatchInfer 并发处理多张图片，按输入顺序返回结果，单图失败不影响其他图片。
func (c *Client) BatchInfer(ctx context.Context, srcs []ImageSource, isLabel bool) []InferResult {
	results := make([]InferResult, len(srcs))
	if len(srcs) == 0 {
		return results
	}

	limit := c.cfg.Concurrency
	if limit > len(srcs) {
		limit = len(srcs)
	}
	sem := make(chan struct{}, limit)
	var wg sync.WaitGroup

	for i, src := range srcs {
		wg.Add(1)
		go func(idx int, s ImageSource) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			res, err := c.Infer(ctx, s, isLabel)
			if err != nil {
				slog.Error("图片处理失败", "source", s.Name(), "error", err)
				res = InferResult{Error: err.Error(), Detections: []DetectionItem{}}
			}
			results[idx] = res
		}(i, src)
	}
	wg.Wait()
	return results
}

// BatchInferPaths 便捷入口：直接传入本地路径或图片 URL 列表。
func (c *Client) BatchInferPaths(ctx context.Context, paths []string, isLabel bool) []InferResult {
	srcs := make([]ImageSource, len(paths))
	for i, p := range paths {
		srcs[i] = SourceOf(p, c.cfg.HTTPTimeout)
	}
	return c.BatchInfer(ctx, srcs, isLabel)
}

// DetectWith 复用已加载的图片执行检测，避免重复编码。
func (c *Client) DetectWith(ctx context.Context, loaded *LoadedImage) ([]DetectionItem, error) {
	if loaded == nil {
		return nil, fmt.Errorf("图片内容为空")
	}
	items, err := c.SecureCheckParse(ctx, loaded)
	if err == nil {
		return items, nil
	}
	slog.Warn("结构化输出不可用，降级为 JSON 模式", "source", "DetectWith", "error", err)
	return c.SecureCheck(ctx, loaded)
}

// buildResult 汇总检测结果：按需绘制标注并拼装标签文本。
func (c *Client) buildResult(loaded *LoadedImage, detections []DetectionItem, isLabel bool) (InferResult, error) {
	labels := make([]string, len(detections))
	boxes := make([][4]int, len(detections))
	for i, d := range detections {
		labels[i] = d.Label
		boxes[i] = d.BBox2d
	}

	res := InferResult{
		Detections: detections,
		Label:      formatLabels(labels),
	}

	if !isLabel || len(detections) == 0 {
		res.Image = loaded.DataURI()
		return res, nil
	}

	img, err := loaded.Image()
	if err != nil {
		slog.Warn("标注失败，返回原图", "error", err)
		res.Image = loaded.DataURI()
		return res, nil
	}
	marked, err := VisualizeBoxes(img, boxes, labels, c.face, true)
	if err != nil {
		slog.Warn("标注失败，返回原图", "error", err)
		res.Image = loaded.DataURI()
		return res, nil
	}
	encoded, err := EncodeImage(marked)
	if err != nil {
		return res, fmt.Errorf("标注图编码失败: %w", err)
	}
	res.Image = "data:image/jpeg;base64," + encoded
	return res, nil
}

// formatLabels 生成 "1.描述\n2.描述" 形式的标签文本。
func formatLabels(labels []string) string {
	if len(labels) == 0 {
		return ""
	}
	var sb strings.Builder
	for i, l := range labels {
		fmt.Fprintf(&sb, "%d.%s\n", i+1, l)
	}
	return strings.TrimRight(sb.String(), "\n")
}

// SourceOf 自动识别本地路径与 http(s) 链接。
func SourceOf(input string, timeout time.Duration) ImageSource {
	if isHTTPURL(input) {
		return FromURL(input, timeout)
	}
	return FromPath(input)
}

// isHTTPURL 判断字符串是否为 http(s) 链接。
func isHTTPURL(s string) bool {
	return strings.HasPrefix(s, "http://") || strings.HasPrefix(s, "https://")
}
