package securecv

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
)

var (
	// bboxArrayPat 用于修复 bbox_2d 数组中缺失的逗号
	bboxArrayPat = regexp.MustCompile(`"bbox_2d"\s*:\s*\[([^\[\]]*)\]`)
	// jsonArrayPat / jsonObjectPat 用于从 Markdown 或脏文本中截取 JSON 片段
	jsonArrayPat  = regexp.MustCompile(`(?s)\[.*\]`)
	jsonObjectPat = regexp.MustCompile(`(?s)\{.*\}`)
	// boxPat / labelPat 用于正则兜底逐条抽取
	boxPat   = regexp.MustCompile(`"bbox_2d"\s*:\s*\[\s*([\d.\-]+)[\s,]+([\d.\-]+)[\s,]+([\d.\-]+)[\s,]+([\d.\-]+)\s*\]`)
	labelPat = regexp.MustCompile(`"label"\s*:\s*"((?:[^"\\]|\\.)*)"`)
)

// dictKeys 为从对象中提取检测数组时的优先键名。
var dictKeys = []string{"detections", "results", "data", "items", "list", "boxes"}

// ReverseNormalizeBox 将 [0, NormMax] 归一化坐标转换为像素坐标。
func ReverseNormalizeBox(box [4]int, imgWidth, imgHeight int) [4]int {
	dims := [4]int{imgWidth, imgHeight, imgWidth, imgHeight}
	var out [4]int
	for i, v := range box {
		clamped := clampInt(v, 0, NormMax)
		out[i] = int(float64(clamped) / NormMax * float64(dims[i]))
	}
	return out
}

// repairBBoxCommas 修复 bbox_2d 数组中数字间缺失的逗号，如 [470 345 536 449] -> [470, 345, 536, 449]。
func repairBBoxCommas(text string) string {
	return bboxArrayPat.ReplaceAllStringFunc(text, func(m string) string {
		sub := bboxArrayPat.FindStringSubmatch(m)
		if len(sub) != 2 {
			return m
		}
		parts := strings.FieldsFunc(sub[1], func(r rune) bool {
			return r == ',' || unicode.IsSpace(r)
		})
		if len(parts) == 0 {
			return m
		}
		return `"bbox_2d": [` + strings.Join(parts, ", ") + `]`
	})
}

// ParseDetections 把模型输出文本解析为检测结果：先做 JSON 解析，失败再正则兜底。
func ParseDetections(content string) DetectionResult {
	text := strings.TrimSpace(content)
	if text == "" {
		return DetectionResult{Detections: []DetectionItem{}}
	}
	text = repairBBoxCommas(text)

	items, err := validateItems(extractJSONArray(text))
	if err == nil {
		return DetectionResult{Detections: normalizeAll(items)}
	}
	slog.Debug("结构化校验失败，启用正则兜底", "error", err)

	dropped, items := regexFallback(text)
	if dropped > 0 {
		slog.Warn("正则兜底丢弃了非法检测条目", "dropped", dropped)
	}
	return DetectionResult{Detections: normalizeAll(items), Dropped: dropped}
}

// extractJSONArray 从文本中尽力取出检测条目数组。
func extractJSONArray(text string) []any {
	if text == "" {
		return nil
	}
	if raw, ok := decodeAny(text); ok {
		if list, ok := raw.([]any); ok {
			return list
		}
		if obj, ok := raw.(map[string]any); ok {
			if list := firstList(obj); list != nil {
				return list
			}
			return nil
		}
	}

	if m := jsonArrayPat.FindString(text); m != "" {
		if raw, ok := decodeAny(m); ok {
			if list, ok := raw.([]any); ok {
				return list
			}
		}
	}
	if m := jsonObjectPat.FindString(text); m != "" {
		if raw, ok := decodeAny(m); ok {
			if obj, ok := raw.(map[string]any); ok {
				return firstList(obj)
			}
		}
	}
	slog.Warn("无法从模型输出中解析出 JSON 数组")
	return nil
}

// decodeAny 解析 JSON 片段，失败返回 false。
func decodeAny(text string) (any, bool) {
	var v any
	if err := json.Unmarshal([]byte(text), &v); err != nil {
		return nil, false
	}
	return v, true
}

// firstList 按优先键名取数组，否则按键名排序取第一个数组值，保证结果确定。
func firstList(obj map[string]any) []any {
	for _, key := range dictKeys {
		if list, ok := obj[key].([]any); ok {
			return list
		}
	}
	keys := make([]string, 0, len(obj))
	for k := range obj {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		if list, ok := obj[k].([]any); ok {
			return list
		}
	}
	return nil
}

// validateItems 校验并转换条目，任一条目非法即整体失败（交由兜底逻辑处理）。
func validateItems(raw []any) ([]DetectionItem, error) {
	if len(raw) == 0 {
		return []DetectionItem{}, nil
	}
	items := make([]DetectionItem, 0, len(raw))
	for i, it := range raw {
		obj, ok := it.(map[string]any)
		if !ok {
			return nil, fmt.Errorf("第 %d 条不是对象: %T", i+1, it)
		}
		rawBox, ok := obj["bbox_2d"].([]any)
		if !ok || len(rawBox) != 4 {
			return nil, fmt.Errorf("第 %d 条 bbox_2d 非法，需为 4 个数值", i+1)
		}
		var box [4]int
		for j, n := range rawBox {
			f, ok := n.(float64)
			if !ok {
				return nil, fmt.Errorf("第 %d 条 bbox_2d 第 %d 个值不是数字", i+1, j+1)
			}
			v, ok := toInt(f)
			if !ok {
				return nil, fmt.Errorf("第 %d 条 bbox_2d 第 %d 个值溢出", i+1, j+1)
			}
			box[j] = v
		}
		label, ok := obj["label"].(string)
		if !ok {
			return nil, fmt.Errorf("第 %d 条 label 缺失或不是字符串", i+1)
		}
		items = append(items, DetectionItem{BBox2d: box, Label: label})
	}
	return items, nil
}

// regexFallback 从残缺文本中逐条抽取 bbox 与 label，能救一条是一条。
func regexFallback(text string) (int, []DetectionItem) {
	var items []DetectionItem
	dropped := 0

	boxes := boxPat.FindAllStringSubmatch(text, -1)
	labels := labelPat.FindAllStringSubmatch(text, -1)

	appendBox := func(box [4]int, label string) {
		items = append(items, DetectionItem{BBox2d: box, Label: label})
	}

	for i, b := range boxes {
		box, ok := parseBox(b[1:])
		if !ok {
			dropped++
			continue
		}
		label := ""
		if i < len(labels) {
			label = unescapeLabel(labels[i][1])
		}
		appendBox(box, label)
	}
	return dropped, items
}

// parseBox 将正则捕获的 4 个数字字符串转为坐标。
func parseBox(parts []string) ([4]int, bool) {
	if len(parts) != 4 {
		return [4]int{}, false
	}
	var box [4]int
	for i, p := range parts {
		f, err := strconv.ParseFloat(strings.TrimSpace(p), 64)
		if err != nil {
			return [4]int{}, false
		}
		v, ok := toInt(f)
		if !ok {
			return [4]int{}, false
		}
		box[i] = v
	}
	return box, true
}

// unescapeLabel 还原标签中的转义字符，失败时返回原文。
func unescapeLabel(s string) string {
	if unquoted, err := strconv.Unquote(`"` + s + `"`); err == nil {
		return unquoted
	}
	return s
}
