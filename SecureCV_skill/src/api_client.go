package securecv

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/openai/openai-go/v3/shared"
	"golang.org/x/image/font"
)

// ResponseFormatUnion 为响应格式的联合类型别名，简化调用方书写。
type ResponseFormatUnion = openai.ChatCompletionNewParamsResponseFormatUnion

// Client 封装多模态大模型调用。
type Client struct {
	client openai.Client
	cfg    Config
	face   font.Face
}

// NewClient 依据配置创建客户端。
func NewClient(cfg Config) (*Client, error) {
	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	client := openai.NewClient(
		option.WithAPIKey(cfg.APIKey),
		option.WithBaseURL(cfg.BaseURL),
		option.WithRequestTimeout(cfg.Timeout),
	)
	c := &Client{client: client, cfg: cfg}
	if cfg.FontPath != "" {
		face, err := LoadFace(cfg.FontPath, cfg.FontSize)
		if err != nil {
			slog.Warn("字体加载失败，标注将只绘制边界框", "path", cfg.FontPath, "error", err)
		} else {
			c.face = face
		}
	}
	slog.Debug("客户端已就绪",
		"base_url", cfg.BaseURL,
		"model", cfg.Model,
		"api_key", Redact(cfg.APIKey),
		"font", cfg.FontPath,
	)
	return c, nil
}

// TestAPI 校验密钥与地址连通性。
func (c *Client) TestAPI(ctx context.Context) bool {
	if _, err := c.client.Models.List(ctx); err != nil {
		slog.Debug("模型连通性检查失败", "error", err)
		return false
	}
	return true
}

// Detect 优先使用结构化输出，失败自动降级为通用 JSON 模式。
func (c *Client) Detect(ctx context.Context, src ImageSource) ([]DetectionItem, error) {
	loaded, err := src.Load(c.cfg.MaxSize)
	if err != nil {
		return nil, err
	}
	items, err := c.SecureCheckParse(ctx, loaded)
	if err == nil {
		return items, nil
	}
	slog.Warn("结构化输出不可用，降级为 JSON 模式", "error", err)

	items, err = c.SecureCheck(ctx, loaded)
	if err != nil {
		return nil, err
	}
	return items, nil
}

// SecureCheckParse 使用 json_schema 严格模式请求模型，返回结构化检测结果。
func (c *Client) SecureCheckParse(ctx context.Context, loaded *LoadedImage) ([]DetectionItem, error) {
	content, err := c.complete(ctx, ParsePrompt, loaded, ResponseFormatUnion{
		OfJSONSchema: &shared.ResponseFormatJSONSchemaParam{
			JSONSchema: shared.ResponseFormatJSONSchemaJSONSchemaParam{
				Name:   SchemaName,
				Strict: openai.Bool(true),
				Schema: detectionSchema(),
			},
		},
	})
	if err != nil {
		return nil, err
	}
	result := ParseDetections(content)
	if len(result.Detections) == 0 {
		slog.Warn("结构化输出为空，可能触发了拒绝或安全策略")
	}
	return result.Detections, nil
}

// SecureCheck 使用 json_object 模式请求模型，返回检测结果。
func (c *Client) SecureCheck(ctx context.Context, loaded *LoadedImage) ([]DetectionItem, error) {
	content, err := c.complete(ctx, SystemPrompt, loaded, ResponseFormatUnion{
		OfJSONObject: &shared.ResponseFormatJSONObjectParam{},
	})
	if err != nil {
		return nil, err
	}
	return ParseDetections(content).Detections, nil
}

// complete 发起一次带图对话并返回原始文本。
func (c *Client) complete(ctx context.Context, sysPrompt string, loaded *LoadedImage, format ResponseFormatUnion) (string, error) {
	if loaded == nil || loaded.Base64 == "" {
		return "", fmt.Errorf("图片内容为空")
	}
	ctx, cancel := context.WithTimeout(ctx, c.cfg.Timeout)
	defer cancel()

	resp, err := c.client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
		Model: c.cfg.Model,
		Messages: []openai.ChatCompletionMessageParamUnion{
			openai.SystemMessage(sysPrompt),
			openai.UserMessage([]openai.ChatCompletionContentPartUnionParam{
				openai.ImageContentPart(openai.ChatCompletionContentPartImageImageURLParam{
					URL:    loaded.DataURI(),
					Detail: "high",
				}),
				openai.TextContentPart(UserPrompt),
			}),
		},
		ResponseFormat: format,
	})
	if err != nil {
		return "", fmt.Errorf("模型推理失败: %w", err)
	}
	if len(resp.Choices) == 0 {
		return "", fmt.Errorf("模型未返回任何结果")
	}
	content := resp.Choices[0].Message.Content
	slog.Debug("模型原始输出", "content", content)
	return content, nil
}

// detectionSchema 构造结构化输出的 JSON Schema。
func detectionSchema() map[string]any {
	item := map[string]any{
		"type":     "object",
		"required": []string{"bbox_2d", "label"},
		"properties": map[string]any{
			"bbox_2d": map[string]any{
				"type":        "array",
				"items":       map[string]any{"type": "integer"},
				"description": "边界框坐标 [x1, y1, x2, y2]，整数像素坐标",
			},
			"label": map[string]any{
				"type":        "string",
				"description": "违规标签，例如：工人临边作业未正确佩戴或挂扣安全带",
			},
		},
		"additionalProperties": false,
	}
	return map[string]any{
		"type":     "object",
		"required": []string{"detections"},
		"properties": map[string]any{
			"detections": map[string]any{
				"type":        "array",
				"items":       item,
				"description": "检测到的所有工人不安全行为条目",
			},
		},
		"additionalProperties": false,
	}
}
