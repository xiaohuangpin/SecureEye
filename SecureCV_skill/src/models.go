package securecv

import "math"

// NormMax 为模型输出的归一化坐标上限（0~1000）。
const NormMax = 1000

// DetectionItem 为单条隐患检测结果。
type DetectionItem struct {
	BBox2d [4]int `json:"bbox_2d"`
	Label  string `json:"label"`
}

// normalize 裁剪到 [0, NormMax] 并纠正 x1>x2 / y1>y2 的非法顺序。
func (d DetectionItem) normalize() DetectionItem {
	var box [4]int
	for i, v := range d.BBox2d {
		if v < 0 {
			v = 0
		}
		if v > NormMax {
			v = NormMax
		}
		box[i] = v
	}
	if box[0] > box[2] {
		box[0], box[2] = box[2], box[0]
	}
	if box[1] > box[3] {
		box[1], box[3] = box[3], box[1]
	}
	return DetectionItem{BBox2d: box, Label: d.Label}
}

// PixelBox 将归一化坐标转换为像素坐标。
func (d DetectionItem) PixelBox(width, height int) [4]int {
	return ReverseNormalizeBox(d.BBox2d, width, height)
}

// DetectionResult 为一次解析的完整结果：有效条目 + 被丢弃条目数。
type DetectionResult struct {
	Detections []DetectionItem `json:"detections"`
	Dropped    int             `json:"dropped"`
}

// DetectionResponse 为结构化输出（json_schema）模式下的根对象。
type DetectionResponse struct {
	Detections []DetectionItem `json:"detections"`
}

// normalizeAll 批量归一化，保持切片顺序。
func normalizeAll(items []DetectionItem) []DetectionItem {
	out := make([]DetectionItem, len(items))
	for i, it := range items {
		out[i] = it.normalize()
	}
	return out
}

// clampInt 限制 v 落在 [lo, hi]。
func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

// toInt 将浮点坐标取整，非法值返回 false。
func toInt(v float64) (int, bool) {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, false
	}
	return int(math.Round(v)), true
}
