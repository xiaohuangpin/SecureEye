package securecv

import (
	"fmt"
	"image"
	"image/color"
	"log/slog"
	"os"

	"golang.org/x/image/draw"
	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

// 标注样式常量
const (
	BoxLineWidth = 2   // 边框线宽（像素）
	LabelGap     = 10  // 标签与边框的间距（像素）
	Padding      = 2   // 标签背景内边距（像素）
	MinFontSize  = 1.0 // 最小字号，防止字体创建失败
)

var (
	boxColor  = color.RGBA{R: 255, G: 0, B: 0, A: 255} // 边框红色
	fillColor = color.RGBA{R: 255, G: 0, B: 0, A: 30}  // 半透明填充
	textColor = color.RGBA{R: 255, G: 255, B: 255, A: 255}
	labelBG   = color.RGBA{R: 255, G: 0, B: 0, A: 200} // 标签底色
)

// LoadFace 加载 TrueType 字体，字体缺失或解析失败时返回 nil（标注降级为只画框）。
func LoadFace(fontPath string, size int) (font.Face, error) {
	if fontPath == "" {
		return nil, fmt.Errorf("未指定字体路径")
	}
	raw, err := os.ReadFile(fontPath)
	if err != nil {
		return nil, fmt.Errorf("字体文件读取失败: %w", err)
	}
	parsed, err := opentype.Parse(raw)
	if err != nil {
		return nil, fmt.Errorf("字体解析失败: %w", err)
	}
	faceSize := float64(size)
	if faceSize < MinFontSize {
		faceSize = MinFontSize
	}
	face, err := opentype.NewFace(parsed, &opentype.FaceOptions{
		Size:    faceSize,
		DPI:     72,
		Hinting: font.HintingFull,
	})
	if err != nil {
		return nil, fmt.Errorf("创建字体失败: %w", err)
	}
	return face, nil
}

// VisualizeBoxes 在图像上绘制边界框与中文标签。
// boxes 为归一化坐标（0~NormMax），labels 与 boxes 一一对应，renormalize 为 false 时按像素坐标处理。
func VisualizeBoxes(img image.Image, boxes [][4]int, labels []string, face font.Face, renormalize bool) (image.Image, error) {
	if img == nil {
		return nil, fmt.Errorf("待标注图像为空")
	}
	dst := toRGBA(img)
	bounds := dst.Bounds()

	for i, box := range boxes {
		pixel := box
		if renormalize {
			pixel = ReverseNormalizeBox(box, bounds.Dx(), bounds.Dy())
		}
		rect := image.Rect(pixel[0], pixel[1], pixel[2], pixel[3]).Intersect(bounds)
		if rect.Empty() {
			continue
		}
		draw.Draw(dst, rect, image.NewUniform(fillColor), image.Point{}, draw.Over)
		drawBorder(dst, rect, boxColor, BoxLineWidth)

		var label string
		if i < len(labels) {
			label = labels[i]
		}
		if label == "" {
			continue
		}
		if face == nil {
			slog.Warn("字体不可用，跳过标签绘制", "label", label)
			continue
		}
		drawLabel(dst, rect, label, face)
	}
	return dst, nil
}

// drawBorder 用四次矩形填充绘制等宽边框，避免逐像素循环。
func drawBorder(dst *image.RGBA, rect image.Rectangle, c color.Color, width int) {
	src := image.NewUniform(c)
	top := image.Rect(rect.Min.X, rect.Min.Y, rect.Max.X, rect.Min.Y+width)
	bottom := image.Rect(rect.Min.X, rect.Max.Y-width, rect.Max.X, rect.Max.Y)
	left := image.Rect(rect.Min.X, rect.Min.Y+width, rect.Min.X+width, rect.Max.Y-width)
	right := image.Rect(rect.Max.X-width, rect.Min.Y+width, rect.Max.X, rect.Max.Y-width)
	for _, r := range []image.Rectangle{top, bottom, left, right} {
		if !r.Empty() {
			draw.Draw(dst, r, src, image.Point{}, draw.Src)
		}
	}
}

// drawLabel 在边框上方绘制带底色的标签，越界时回退到边框内部顶端。
func drawLabel(dst *image.RGBA, rect image.Rectangle, label string, face font.Face) {
	drawer := &font.Drawer{Face: face}
	advance := drawer.MeasureString(label).Ceil()
	metrics := face.Metrics()
	ascent := metrics.Ascent.Ceil()
	textH := ascent + metrics.Descent.Ceil()

	bounds := dst.Bounds()
	width := advance + Padding*2
	if width > bounds.Dx() {
		width = bounds.Dx()
	}

	x := clampInt(rect.Min.X, 0, bounds.Dx()-width)
	y := rect.Min.Y - textH - LabelGap
	if y < 0 {
		y = clampInt(rect.Min.Y, 0, bounds.Dy()-textH)
	}

	bg := image.Rect(x, y, x+width, y+textH).Intersect(bounds)
	if !bg.Empty() {
		draw.Draw(dst, bg, image.NewUniform(labelBG), image.Point{}, draw.Over)
	}

	drawer.Dst = dst
	drawer.Src = image.NewUniform(textColor)
	drawer.Dot = fixed.P(x+Padding, y+ascent)
	drawer.DrawString(label)
}
