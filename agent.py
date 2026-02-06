import base64,io,logging,json
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class MultClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        example: list[str] = [],
        font_path: str = "simhei.ttf",
        font_size: int = 14
    ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model:str = model_name
        self.font = self._load_font(font_path, font_size)
        self.system_prompt:str = f"""
        **角色**：
        你是一名工地驻场安全员。

        **目标（一步一步执行）**：
        1. 识别图像中所有安全隐患
        2. 为每个安全隐患标注其2D边界框坐标
        3. 用中文描述这些安全隐患,{"如"+"、".join(example)}

        **要求**：
        1. 坐标格式为 [x1, y1, x2, y2]
        2. 输出格式：JSON

        **json格式案列**：
        [
            {{
                "bbox_2d": [120, 85, 340, 290],
                "label": 对应的隐患描述
            }},
            {{
                "bbox_2d": [450, 210, 620, 500],
                "label": 对应的隐患描述
            }}
        ]
    """

    @staticmethod
    def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
        
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            logging.warning(f"字体加载失败: {e}，使用默认字体")
            return ImageFont.load_default()

    @staticmethod
    def _encode_image_data(image_data: str|Image.Image) -> str:
       
        if isinstance(image_data, str):
            with open(image_data, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        elif isinstance(image_data, Image.Image):
            buffered = io.BytesIO()
            image_data.convert("RGB").save(buffered, format="JPEG", quality=95)
            return base64.b64encode(buffered.getvalue()).decode("utf-8")
        else:
            raise TypeError("image_data 必须是图像路径 (str) 或 PIL Image 对象")

    def secure_check(self, image_data: str | Image.Image) -> list[dict[str, list[int]|str]]:
        try:
            image_base64 = self._encode_image_data(image_data)
            response = self.client.chat.completions.create(
                model = self.model,
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "请找出图片中涉及的安全隐患"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"}
            )
            content:str = response.choices[0].message.content
            
            logging.info(f"模型输出：{content}")
            return json.loads(content)
        except Exception as e:
            logging.error(f"模型推理失败: {e}")
            raise

    @staticmethod
    def _reverse_normalize_box(box: list[int], img_width: int, img_height: int) -> list[int]:
        """将 [0,999] 归一化坐标转换为像素坐标"""
        x1, y1, x2, y2 = [max(0, min(1000.0, v)) for v in box]
        return [
            int((x1 / 1000.0) * img_width),
            int((y1 / 1000.0) * img_height),
            int((x2 / 1000.0) * img_width),
            int((y2 / 1000.0) * img_height)
        ]

    def visualize_boxes(
        self,
        image: Image.Image,
        boxes: list[list[int]],
        labels: list[str] | None = None,
        renormalize: bool = False,
        return_b64: bool = False,
    ) -> Image.Image:
        """在图像上绘制边界框和标签"""
        img = image.copy().convert("RGB")
        draw = ImageDraw.Draw(img, "RGBA")
        labels = labels or [""] * len(boxes)

        for box, label in zip(boxes, labels):
            if renormalize:
                box = self._reverse_normalize_box(box, img.width, img.height)
            draw.rectangle([(box[0], box[1]), (box[2], box[3])], outline=(255, 0, 0, 255), width=2, fill=(255, 0, 0, 30))
            if label:
                text_bbox = draw.textbbox((0, 0), label, font=self.font)
                text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
                text_x = max(0, min(box[0], img.width - text_w - 10))
                text_y = max(0, box[1] - text_h - 10)
                draw.text((text_x, text_y), label, font=self.font, fill=(255, 0, 0, 255))
        
        if return_b64:
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=95)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        return img
    

    def infer(self, image_path: str, is_label: bool = False) -> dict[str, Image.Image|str]:
        image = Image.open(image_path).convert("RGB")
        results = self.secure_check(image)

        boxes = [r["bbox_2d"] for r in results]
        labels = [r["label"] for r in results]

        output_image = self.visualize_boxes(image, boxes, labels, renormalize=True) if is_label else image
        label_text = "\n".join(f"{i}.{lbl}" for i, lbl in enumerate(labels, start=1))

        return {"image": output_image, "label": label_text}

    def batch_infer(self, img_paths: list[str], is_label: bool = False) -> list[dict[str, Image.Image | str]]:
        return [self.infer(path, is_label) for path in img_paths]


if __name__ == "__main__":
    api_key="51717266bdda4a83be510e425fab2767.j0m9tLNUzONDBl9H"
    base_url="https://open.bigmodel.cn/api/paas/v4/"
    model_name = "glm-4.6v-flash"
    example = ["未固定的高空作业平台","裸露的带电电缆"]
    image_path = "image/9.jpg"
    ima_list = ['image/9.jpg','image/7.jpg']
    api = MultClient(
        api_key,
        base_url,
        model_name,
        example,
    )
    a = api.batch_infer(ima_list,True)
    print(a)