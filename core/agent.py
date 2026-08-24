import base64,io,logging,json,asyncio,re
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI
from pydantic import BaseModel, Field, TypeAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

class DetectionItem(BaseModel):
    
    bbox_2d: Tuple[int, int, int, int] = Field(
        description="边界框坐标 [x1, y1, x2, y2]，整数像素坐标"
    )
    label: str = Field(
        description="违规标签，例如：工人临边作业未正确佩戴或挂扣安全带"
    )

    def normalize(self) -> "DetectionItem":
        """裁剪到 [0, NORM_MAX] 并修正 x1>x2 / y1>y2 的非法顺序"""
        x1, y1, x2, y2 = (max(0, min(1000, int(round(v)))) for v in self.bbox_2d)
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        return DetectionItem(bbox_2d=(x1, y1, x2, y2), label=self.label)


class DetectionResult(BaseModel):
    """模型整体输出：检测列表 + 校验统计"""
    detections: list[DetectionItem] = Field(default_factory=list)
    dropped: int = 0  


class DetectionResponse(BaseModel):
    """beta parse 结构化输出根对象（SDK 要求 response_format 为单一对象）"""
    detections: list[DetectionItem] = Field(
        default_factory=list,
        description="检测到的所有工人不安全行为条目",
    )


class MultClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        font_path: str = "simhei.ttf",
        font_size: int = 14
    ):
        self.client:AsyncOpenAI = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model:str = model_name
        self.font:ImageFont = self._load_font(font_path, font_size)
        self.MAX_SIZE = 2048
        self.system_prompt:str = f"""
        **角色**
        你是一名专业的施工现场安全巡查员，负责识别图像中工人的不安全行为和违章作业行为。

        请只关注“工人自身的不安全行为”，不要重点检查设备、材料、环境或管理问题。只有当某个物体或环境与工人的危险行为直接相关时，才可以一并纳入边界框

        **重点识别行为**
        - 高处作业、临边作业、洞口作业未佩戴安全带或未正确挂扣安全带。
        - 高处作业安全带未高挂低用，或安全带悬挂方式明显错误。
        - 工人站在脚手架、平台、梯子、设备边缘、护栏、临边位置进行冒险作业。
        - 工人攀爬、跨越、倚靠、坐卧在护栏、脚手架杆件、洞口边缘或不稳定位置。
        - 工人在升降平台、剪叉车、曲臂车等设备上探身、跨越、站立在护栏上或超出安全作业范围。
        - 工人未戴安全帽，或未正确系紧安全帽下颚带。
        - 工人在施工区域未穿反光背心或未佩戴明显必要个人防护用品。
        - 其他明显违反安全操作规程的工人行为。

        **输出要求**
        1. 每个不安全行为单独输出一条 JSON 对象。
        2. 边界框格式为 bbox_2d: [x1, y1, x2, y2]，使用整数像素坐标。
        3. 边界框应紧密包围涉事工人及其危险动作范围。
        4. label简明描述工人的具体不安全行为。
        5. 只标注明确可见、可判断的违章行为；不确定、模糊、遮挡严重导致无法判断的情况不要输出。
        6. 只输出 JSON 数组，不要输出任何解释、Markdown 或额外文字。
        7. 如果没有发现工人不安全行为，输出[]。

        **JSON格式**
        [
            {{
                "bbox_2d": [x1, y1, x2, y2],
                "label": "工人临边作业未正确佩戴或挂扣安全带"
            }}
            ...
        ]
    """

        self.parse_prompt: str = f"""
        **角色**
        你是一名专业的施工现场安全巡查员，负责识别图像中工人的不安全行为和违章作业行为。

        请只关注“工人自身的不安全行为”，不要重点检查设备、材料、环境或管理问题。只有当某个物体或环境与工人的危险行为直接相关时，才可以一并纳入边界框。

        **重点识别行为**
        - 高处作业、临边作业、洞口作业未佩戴安全带或未正确挂扣安全带。
        - 高处作业安全带未高挂低用，或安全带悬挂方式明显错误。
        - 工人站在脚手架、平台、梯子、设备边缘、护栏、临边位置进行冒险作业。
        - 工人攀爬、跨越、倚靠、坐卧在护栏、脚手架杆件、洞口边缘或不稳定位置。
        - 工人在升降平台、剪叉车、曲臂车等设备上探身、跨越、站立在护栏上或超出安全作业范围。
        - 工人未戴安全帽，或未正确系紧安全帽下颚带。
        - 工人在施工区域未穿反光背心或未佩戴明显必要个人防护用品。
        - 其他明显违反安全操作规程的工人行为。

        **输出要求**
        1. 每个不安全行为单独输出一条检测项，放入 detections 数组。
        2. 边界框 bbox_2d 为 [x1, y1, x2, y2]，整数像素坐标，且必须恰好 4 个数值。
        3. 边界框应紧密包围涉事工人及其危险动作范围。
        4. label 简明描述工人的具体不安全行为。
        5. 只标注明确可见、可判断的违章行为；不确定、模糊、遮挡严重导致无法判断的情况不要输出。
        6. 如果没有发现工人不安全行为，detections 返回空数组。
        7. 直接返回结构化对象，不要输出任何解释、Markdown 或额外文字。
    """
        
    async def test_api(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except:
            return False
    

    @staticmethod
    def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:

        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            logging.warning(f"字体加载失败: {e}，使用默认字体")
            return ImageFont.load_default()

    @staticmethod
    def _encode_image_data(image_data: str | Image.Image) -> str:
        if isinstance(image_data, str):
            img = Image.open(image_data)
            w, h = img.size
            # 快速路径：无需缩放时直接读取原始文件（保留原格式，性能最优）
            if w <= 2048 and h <= 2048:
                img.close()
                with open(image_data, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
        elif isinstance(image_data, Image.Image):
            img = image_data
            w, h = img.size
        else:
            raise TypeError("image_data 必须是图像路径 (str) 或 PIL Image 对象")

        # 等比缩放：取宽高方向上更严格的缩放比例
        if w > 2048 or h > 2048:
            scale = min(2048 / w, 2048 / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

        buffered = io.BytesIO()
        img.convert("RGB").save(buffered, format="JPEG", quality=95)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    async def secure_check(self, image_data: str | Image.Image) -> list[dict]:
        try:
            image_base64 = self._encode_image_data(image_data)
            response = await self.client.chat.completions.create(
                model = self.model,
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "find potential safety hazards from images"},
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
            #time.sleep(1.5)
            result: DetectionResult = self._parse_content(content)
            return [d.model_dump() for d in result.detections]
        except Exception as e:
            logging.error(f"模型推理失败: {e}")
            raise

    async def secure_check_parse(self, image_data: str | Image.Image) -> list[dict]:
        try:
            image_base64 = self._encode_image_data(image_data)
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.parse_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "find potential safety hazards from images"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                            }
                        ]
                    }
                ],
                response_format=DetectionResponse,
            )
            parsed: DetectionResponse = response.choices[0].message.parsed
            if parsed is None:
                logging.warning("结构化解析返回为空（可能触发了拒绝/安全策略）")
                return []
            return [d.normalize().model_dump() for d in parsed.detections]
        except Exception as e:
            logging.error(f"结构化模型推理失败: {e}")
            raise

    @staticmethod
    def _repair_bbox_commas(text: str) -> str:
        """修复 bbox_2d 数组中数字间缺失的逗号：如 [470 345 536 449] -> [470, 345, 536, 449]"""
        return re.sub(
            r'"bbox_2d"\s*:\s*\[[\d.\-]+(?:\s*[,\s]+\s*[\d.\-]+)+\]',
            lambda m: re.sub(r'(?<=[\d.\-])\s+(?=[\d.\-])', ', ', m.group(0)),
            text,
        )

    @staticmethod
    def _extract_json_array(text: str) -> list:
        if text is None:
            return []
        text = text.strip()
        if not text:
            return []
        text = MultClient._repair_bbox_commas(text)

        try:
            obj = json.loads(text)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                for key in ("detections", "results", "data", "items", "list", "boxes"):
                    if key in obj and isinstance(obj[key], list):
                        return obj[key]
                # 退而求其次：取第一个 list 类型的值
                for v in obj.values():
                    if isinstance(v, list):
                        return v
                return []
        except json.JSONDecodeError:
            pass

        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, list):
                    return obj
            except json.JSONDecodeError:
                pass

        # 再尝试提取首个 {...} 对象并找其中的数组
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict):
                    for v in obj.values():
                        if isinstance(v, list):
                            return v
            except json.JSONDecodeError:
                pass

        logging.warning("无法从模型输出中解析出 JSON 数组")
        return []

    @classmethod
    def _parse_content(cls, content: str) -> DetectionResult:
        DetectionList = TypeAdapter(List[DetectionItem])
        detections: list[DetectionItem] = []
        dropped = 0

        try:
            raw_list = cls._extract_json_array(content)
            items = DetectionList.validate_python(raw_list)
            return DetectionResult(
                detections=[it.normalize() for it in items], dropped=0
            )
        except Exception as e:
            logging.warning(f"第一轮 Pydantic 校验失败，启用正则兜底: {e}")

        # 兜底：用正则从脏文本中逐条抽取 {bbox_2d:[..], label:".."}
        dropped, detections = cls._regex_fallback(content)
        if dropped:
            logging.warning(f"正则兜底共丢弃 {dropped} 条非法检测条目")
        return DetectionResult(detections=detections, dropped=dropped)

    @staticmethod
    def _regex_fallback(text: str) -> tuple[int, list[DetectionItem]]:
        """从残缺/脏文本中用正则逐条提取 bbox 与 label，能救一条是一条"""
        detections: list[DetectionItem] = []
        dropped = 0
        # 匹配 "bbox_2d": [x1, y1, x2, y2]
        box_pat = re.compile(
            r'"bbox_2d"\s*:\s*\[\s*([\d.\-]+)[\s,]+([\d.\-]+)[\s,]+([\d.\-]+)[\s,]+([\d.\-]+)\s*\]'
        )
        # 匹配 "label": "..."（允许转义引号与跨行）
        label_pat = re.compile(r'"label"\s*:\s*"((?:[^"\\]|\\.)*)"')
        boxes = box_pat.findall(text)
        labels = label_pat.findall(text)
        for i, b in enumerate(boxes):
            try:
                box = tuple(int(round(float(x))) for x in b)
                label = labels[i].encode().decode("unicode_escape") if i < len(labels) else ""
                detections.append(DetectionItem(bbox_2d=box, label=label).normalize())
            except (ValueError, TypeError):
                dropped += 1
       
        for j in range(len(labels), len(boxes)):
            try:
                box = tuple(int(round(float(x))) for x in boxes[j])
                detections.append(DetectionItem(bbox_2d=box, label="").normalize())
            except (ValueError, TypeError):
                dropped += 1
        return dropped, detections

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
        renormalize: bool = True,
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
                text_bbox:tuple[float,float,float,float] = draw.textbbox((0, 0), label, font=self.font)
                text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
                text_x = max(0, min(box[0], img.width - text_w - 10))
                text_y:float = max(0, box[1] - text_h - 10)
                draw.text((text_x, text_y), label, font=self.font, fill=(255, 0, 0, 255))
        
        if return_b64:
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=95)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
        return img
    
    async def _detect(self, image: Image.Image) -> list[dict]:
        """优先用结构化解析，失败自动降级到通用 JSON 解析"""
        try:
            return await self.secure_check_parse(image)
        except Exception as e:
            logging.warning(f"secure_check_parse 失败，降级 secure_check: {e}")
            return await self.secure_check(image)

    async def infer(self, image_path: str | Image.Image, is_label: bool) -> dict[str, Image.Image | str]:
        image = Image.open(image_path).convert("RGB") if isinstance(image_path, str) else image_path.convert("RGB")
        results = await self._detect(image)
        boxes, labels = [r["bbox_2d"] for r in results], [r["label"] for r in results]

        output_image = self.visualize_boxes(image, boxes, labels, renormalize=True) if is_label else self._encode_image_data(image)
        label_text = "\n".join(f"{i}.{lbl}" for i, lbl in enumerate(labels, start=1))

        return {"image": output_image, "label": label_text}

    async def batch_infer(self, img_paths: list[str | Image.Image], is_label: bool) -> list[dict[str, Image.Image | str]]:
        tasks = [self.infer(path, is_label) for path in img_paths]
        return await asyncio.gather(*tasks)



if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv
    import os

    load_dotenv()
    client = MultClient(
        api_key=os.getenv("api_key"),
        base_url=os.getenv("base_url"),
        model_name=os.getenv("model"),
    )
    ima_list: list[str] = ["image/159.jpg"]
    results: list[dict] = asyncio.run(client.batch_infer(ima_list, True))
    for r in results:
        print(r["label"])
    logging.info(f"处理了 {len(results)} 张图片")

    # 测试 secure_check_parse：结构化输出，成功则打印数据类 JSON
    #async def test_parse(img_path: str):
        #res = await client.secure_check_parse(img_path)
        #print(json.dumps(res, ensure_ascii=False, indent=2))
        #logging.info(f"secure_check_parse 返回 {len(res)} 条检测")

    #asyncio.run(test_parse(ima_list[0]))