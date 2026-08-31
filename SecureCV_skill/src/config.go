package securecv

import (
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// 默认值
const (
	DefaultFontSize    = 14
	DefaultMaxSize     = 2048
	DefaultConcurrency = 4
	DefaultTimeout     = 120 * time.Second
	DefaultHTTPTimeout = 10 * time.Second
	DefaultFontName    = "simhei.ttf"
)

// Config 为 SecureCV 的运行配置，全部字段均可通过环境变量注入。
type Config struct {
	APIKey      string        // 必填，模型服务密钥
	BaseURL     string        // 必填，模型服务地址（OpenAI 兼容端点）
	Model       string        // 必填，多模态模型名称
	FontPath    string        // 可选，中文标注字体，留空则自动探测
	FontSize    int           // 可选，标注字号
	MaxSize     int           // 可选，上传图片的最大边长，超出等比缩小
	Concurrency int           // 可选，批量推理并发度
	Timeout     time.Duration // 可选，单次模型请求超时
	HTTPTimeout time.Duration // 可选，下载网络图片的超时
	Debug       bool          // 可选，输出调试日志（含模型原始输出）
}

// LoadConfig 从环境变量加载配置并做合法性校验。
// 必填项优先读取小写 api_key / base_url / model，兼容大写与 OPENAI_ 前缀变体。
func LoadConfig() (Config, error) {
	cfg := Config{
		APIKey:      lookupEnv("api_key", "API_KEY", "OPENAI_API_KEY"),
		BaseURL:     lookupEnv("base_url", "BASE_URL", "OPENAI_BASE_URL"),
		Model:       lookupEnv("model", "MODEL", "OPENAI_MODEL"),
		FontPath:    envString("SECURECV_FONT_PATH", ""),
		FontSize:    envInt("SECURECV_FONT_SIZE", DefaultFontSize),
		MaxSize:     envInt("SECURECV_MAX_SIZE", DefaultMaxSize),
		Concurrency: envInt("SECURECV_CONCURRENCY", DefaultConcurrency),
		Timeout:     envDuration("SECURECV_TIMEOUT", DefaultTimeout),
		HTTPTimeout: envDuration("SECURECV_HTTP_TIMEOUT", DefaultHTTPTimeout),
		Debug:       envBool("SECURECV_DEBUG"),
	}
	return cfg, cfg.Validate()
}

// Validate 校验必填项与取值范围，并补齐字体路径。
func (c *Config) Validate() error {
	if strings.TrimSpace(c.APIKey) == "" {
		return errors.New("缺少环境变量 api_key（或 OPENAI_API_KEY）")
	}
	if strings.TrimSpace(c.BaseURL) == "" {
		return errors.New("缺少环境变量 base_url（或 OPENAI_BASE_URL）")
	}
	if strings.TrimSpace(c.Model) == "" {
		return errors.New("缺少环境变量 model（或 OPENAI_MODEL）")
	}
	if c.FontSize <= 0 {
		c.FontSize = DefaultFontSize
	}
	if c.MaxSize <= 0 {
		c.MaxSize = DefaultMaxSize
	}
	if c.Concurrency <= 0 {
		c.Concurrency = DefaultConcurrency
	}
	if c.Timeout <= 0 {
		c.Timeout = DefaultTimeout
	}
	if c.HTTPTimeout <= 0 {
		c.HTTPTimeout = DefaultHTTPTimeout
	}
	if strings.TrimSpace(c.FontPath) == "" {
		c.FontPath = FindFont()
	}
	return nil
}

// FindFont 按可执行文件目录、工作目录、源码目录的顺序探测中文字体，找不到返回空串。
func FindFont() string {
	var dirs []string
	if exe, err := os.Executable(); err == nil {
		dirs = append(dirs, filepath.Dir(exe))
	}
	if wd, err := os.Getwd(); err == nil {
		dirs = append(dirs, wd)
	}
	if _, file, _, ok := runtime.Caller(0); ok {
		root := filepath.Dir(file)
		dirs = append(dirs, root, filepath.Dir(root))
	}

	seen := make(map[string]struct{}, len(dirs))
	for _, dir := range dirs {
		for _, candidate := range []string{
			filepath.Join(dir, "assets", DefaultFontName),
			filepath.Join(dir, DefaultFontName),
		} {
			if _, ok := seen[candidate]; ok {
				continue
			}
			seen[candidate] = struct{}{}
			if fileExists(candidate) {
				return candidate
			}
		}
	}
	return ""
}

// SetupLogger 将日志统一输出到 stderr，保证 stdout 只承载结果数据。
func SetupLogger(debug bool) {
	level := slog.LevelInfo
	if debug {
		level = slog.LevelDebug
	}
	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: level})))
}

func lookupEnv(keys ...string) string {
	for _, key := range keys {
		if v := strings.TrimSpace(os.Getenv(key)); v != "" {
			return v
		}
	}
	return ""
}

func envString(key, fallback string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return fallback
}

func envInt(key string, fallback int) int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil || n <= 0 {
		return fallback
	}
	return n
}

func envDuration(key string, fallback time.Duration) time.Duration {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return fallback
	}
	if d, err := time.ParseDuration(v); err == nil && d > 0 {
		return d
	}
	if n, err := strconv.Atoi(v); err == nil && n > 0 {
		return time.Duration(n) * time.Second
	}
	return fallback
}

func envBool(key string) bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv(key))) {
	case "1", "true", "yes", "on":
		return true
	default:
		return false
	}
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

// Redact 用于日志脱敏，避免密钥泄漏。
func Redact(key string) string {
	if len(key) <= 8 {
		return "****"
	}
	return fmt.Sprintf("%s****%s", key[:4], key[len(key)-4:])
}
