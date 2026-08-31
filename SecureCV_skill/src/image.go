package securecv

import (
	"bytes"
	"context"
	"encoding/base64"
	"fmt"
	"image"
	_ "image/gif" // 注册 gif 解码器
	"image/jpeg"
	_ "image/png" // 注册 png 解码器
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"golang.org/x/image/draw"
	_ "golang.org/x/image/webp" // 注册 webp 解码器
)

// JPEGQuality 为上传与输出图片的编码质量。
const JPEGQuality = 95

// ImageSource 抽象图片输入，替代 Python 版的 str | Image.Image 联合类型。
type ImageSource interface {
	// Load 按 maxSize 产出可直接上传的编码结果。
	Load(maxSize int) (*LoadedImage, error)
	// Name 返回便于日志定位的来源标识。
	Name() string
}

// LoadedImage 保存编码结果与惰性解码的原图。
type LoadedImage struct {
	Base64 string // 按上传要求编码后的 base64
	MIME   string // 与 Base64 对应的 MIME 类型
	Width  int    // 编码后图片的宽
	Height int    // 编码后图片的高

	img  image.Image
	raw  []byte
	once sync.Once
	err  error
}

// DataURI 返回可直接内联的 data URI。
func (l *LoadedImage) DataURI() string {
	if l == nil || l.Base64 == "" {
		return ""
	}
	return "data:" + l.MIME + ";base64," + l.Base64
}

// Image 惰性解码并返回与上传内容一致的原图（已按需缩放）。
func (l *LoadedImage) Image() (image.Image, error) {
	if l == nil {
		return nil, fmt.Errorf("LoadedImage 为空")
	}
	l.once.Do(func() {
		if l.img != nil {
			return
		}
		if len(l.raw) == 0 {
			l.err = fmt.Errorf("没有可用于解码的图像数据")
			return
		}
		l.img, _, l.err = image.Decode(bytes.NewReader(l.raw))
	})
	return l.img, l.err
}

// ---------------------------------------------------------------- 输入源

type pathSource struct{ path string }

// FromPath 以本地文件路径作为输入。
func FromPath(path string) ImageSource { return pathSource{path: path} }

func (s pathSource) Name() string { return s.path }

func (s pathSource) Load(maxSize int) (*LoadedImage, error) {
	raw, err := os.ReadFile(s.path)
	if err != nil {
		return nil, fmt.Errorf("读取图片失败: %w", err)
	}
	cfg, format, err := image.DecodeConfig(bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("解析图片失败: %w", err)
	}
	// 快速路径：尺寸合规时直接上传原始字节，避免一次解码 + 重编码
	if cfg.Width <= maxSize && cfg.Height <= maxSize {
		return &LoadedImage{
			Base64: base64.StdEncoding.EncodeToString(raw),
			MIME:   mimeOf(format),
			Width:  cfg.Width,
			Height: cfg.Height,
			raw:    raw,
		}, nil
	}
	img, err := decodeBytes(raw)
	if err != nil {
		return nil, err
	}
	return encodeUpload(resizeImage(img, maxSize))
}

type urlSource struct {
	url     string
	timeout time.Duration
}

// FromURL 以 http(s) 图片链接作为输入，timeout 为下载超时（<=0 时用默认值）。
func FromURL(url string, timeout time.Duration) ImageSource {
	if timeout <= 0 {
		timeout = DefaultHTTPTimeout
	}
	return urlSource{url: url, timeout: timeout}
}

func (s urlSource) Name() string { return s.url }

func (s urlSource) Load(maxSize int) (*LoadedImage, error) {
	raw, err := s.download()
	if err != nil {
		return nil, err
	}
	img, err := decodeBytes(raw)
	if err != nil {
		return nil, err
	}
	return encodeUpload(resizeImage(img, maxSize))
}

func (s urlSource) download() ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), s.timeout)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.url, nil)
	if err != nil {
		return nil, fmt.Errorf("构造下载请求失败: %w", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("下载图片失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("下载图片失败: HTTP %d", resp.StatusCode)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 32<<20))
}

type imageSource struct{ img image.Image }

// FromImage 以内存中的 image.Image 作为输入。
func FromImage(img image.Image) ImageSource { return imageSource{img: img} }

func (s imageSource) Name() string { return "image.Image" }

func (s imageSource) Load(maxSize int) (*LoadedImage, error) {
	if s.img == nil {
		return nil, fmt.Errorf("image.Image 为空")
	}
	return encodeUpload(resizeImage(s.img, maxSize))
}

// ---------------------------------------------------------------- 编解码

// decodeBytes 解码任意受支持格式的图片字节。
func decodeBytes(raw []byte) (image.Image, error) {
	img, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return nil, fmt.Errorf("图片解码失败: %w", err)
	}
	return img, nil
}

// resizeImage 等比缩小到最大边长不超过 maxSize。
func resizeImage(img image.Image, maxSize int) image.Image {
	b := img.Bounds()
	w, h := b.Dx(), b.Dy()
	if w <= maxSize && h <= maxSize {
		return img
	}
	scale := float64(maxSize) / float64(max(w, h))
	nw, nh := int(float64(w)*scale), int(float64(h)*scale)
	if nw < 1 {
		nw = 1
	}
	if nh < 1 {
		nh = 1
	}
	dst := image.NewRGBA(image.Rect(0, 0, nw, nh))
	draw.CatmullRom.Scale(dst, dst.Bounds(), img, b, draw.Over, nil)
	return dst
}

// encodeJPEG 统一编码为 JPEG 并返回字节。
func encodeJPEG(img image.Image) ([]byte, error) {
	var buf bytes.Buffer
	if err := jpeg.Encode(&buf, toRGBA(img), &jpeg.Options{Quality: JPEGQuality}); err != nil {
		return nil, fmt.Errorf("JPEG 编码失败: %w", err)
	}
	return buf.Bytes(), nil
}

// toRGBA 将任意图像统一为 RGBA，保证编码与绘制行为一致。
func toRGBA(img image.Image) *image.RGBA {
	if rgba, ok := img.(*image.RGBA); ok {
		return rgba
	}
	b := img.Bounds()
	rgba := image.NewRGBA(image.Rect(0, 0, b.Dx(), b.Dy()))
	draw.Draw(rgba, rgba.Bounds(), img, b.Min, draw.Src)
	return rgba
}

// encodeUpload 编码上传用的 JPEG 结果。
func encodeUpload(img image.Image) (*LoadedImage, error) {
	data, err := encodeJPEG(img)
	if err != nil {
		return nil, err
	}
	b := img.Bounds()
	return &LoadedImage{
		Base64: base64.StdEncoding.EncodeToString(data),
		MIME:   "image/jpeg",
		Width:  b.Dx(),
		Height: b.Dy(),
		img:    img,
	}, nil
}

// mimeOf 将解码得到的格式名转为 MIME。
func mimeOf(format string) string {
	switch strings.ToLower(format) {
	case "jpeg":
		return "image/jpeg"
	case "png":
		return "image/png"
	case "gif":
		return "image/gif"
	case "webp":
		return "image/webp"
	default:
		return "image/jpeg"
	}
}

// ---------------------------------------------------------------- 输出

// EncodeImage 将图像编码为 JPEG base64。
func EncodeImage(img image.Image) (string, error) {
	data, err := encodeJPEG(img)
	if err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(data), nil
}

// SaveImage 将图像保存为 JPEG 文件，目录不存在时自动创建。
func SaveImage(path string, img image.Image, quality int) error {
	if quality <= 0 || quality > 100 {
		quality = JPEGQuality
	}
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("创建目录失败: %w", err)
		}
	}
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("创建文件失败: %w", err)
	}
	defer f.Close()

	if err := jpeg.Encode(f, toRGBA(img), &jpeg.Options{Quality: quality}); err != nil {
		return fmt.Errorf("写入图片失败: %w", err)
	}
	return nil
}

// DecodeBase64 解码 base64 图片（允许携带 data URI 前缀）。
func DecodeBase64(s string) (image.Image, error) {
	if idx := strings.Index(s, ","); idx != -1 && strings.HasPrefix(strings.TrimSpace(s), "data:") {
		s = s[idx+1:]
	}
	raw, err := base64.StdEncoding.DecodeString(strings.TrimSpace(s))
	if err != nil {
		return nil, fmt.Errorf("base64 解码失败: %w", err)
	}
	return decodeBytes(raw)
}
