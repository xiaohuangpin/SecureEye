package securecv

import (
	"encoding/json"
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
	APIKey      string        `json:"api_key"`
	BaseURL     string        `json:"base_url"`
	Model       string        `json:"model"`
	FontPath    string        `json:"font_path"`
	FontSize    int           `json:"font_size"`
	MaxSize     int           `json:"max_size"`
	Concurrency int           `json:"concurrency"`
	Timeout     time.Duration `json:"timeout"`
	HTTPTimeout time.Duration `json:"http_timeout"`
	Debug       bool          `json:"debug"`
	Loaded      bool          // JSON 配置文件是否成功加载；仅内部用于区分来源
}

// LoadConfig 先从可执行文件所在目录加载 model_config.json，再叠加环境变量。
// JSON 中已填入的必填项（api_key/base_url/model）优先；其余可选字段以环境变量覆盖
// JSON 值，并回退到默认值。若 JSON 缺失或为空则视为未配置。
func LoadConfig() (Config, error) {
	file := loadFromJSON()
	return Config{
		APIKey:      file.APIKey,
		BaseURL:     file.BaseURL,
		Model:       file.Model,
		FontPath:    envString("SECURECV_FONT_PATH", file.FontPath),
		FontSize:    envInt("SECURECV_FONT_SIZE", DefaultFontSize),
		MaxSize:     envInt("SECURECV_MAX_SIZE", DefaultMaxSize),
		Concurrency: envInt("SECURECV_CONCURRENCY", DefaultConcurrency),
		Timeout:     envDuration("SECURECV_TIMEOUT", file.Timeout),
		HTTPTimeout: envDuration("SECURECV_HTTP_TIMEOUT", file.HTTPTimeout),
		Debug:       envBool("SECURECV_DEBUG"),
	}, file.Validate()
}

// loadFromJSON 从本配置文件所在目录的上一层（即项目根）读取 model_config.json。
// JSON 缺失、为空或解析失败时返回 Loaded=false 的零值，保证向后兼容。
func loadFromJSON() Config {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		return Config{Loaded: true}
	}
	// config.go -> src; model_config.json 位于其父目录（项目根）。
	// runtime.Caller 在 go test 等场景可能返回相对路径，故先归一化为绝对路径。
	root := filepath.Dir(filepath.Dir(file))
	if !filepath.IsAbs(root) {
		if wd, err := os.Getwd(); err == nil {
			root = filepath.Join(wd, root)
		}
	}
	b, err := os.ReadFile(filepath.Join(root, "model_config.json"))
	if err != nil || len(strings.TrimSpace(string(b))) == 0 {
		return Config{Loaded: true}
	}
	cfg := Config{}
	if json.Unmarshal(b, &cfg) == nil {
		cfg.Loaded = true
	}
	return cfg
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
