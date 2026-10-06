import base64,io,logging,json,asyncio,re
from functools import lru_cache
from typing import List
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI
from pydantic import TypeAdapter
from core.models import DetectionResponse, DetectionResult, DetectionItem
from core.utils import _download_image,_repair_bbox_commas,_reverse_normalize_box

logger = logging.getLogger(__name__)

class MultClient:
    MAX_SIZE = 2048        # 输入图像最长边限制
    JPEG_QUALITY = 85      # 全局 JPEG 质量（发模型 / 展示 / 导出共用）：相比 95 体积约减 1/3
    MIN_FONT_SIZE = 8      # 标注字体大小可调范围（模型配置页）
    MAX_FONT_SIZE = 72
    DEFAULT_FONT_SIZE = 14

    # 固定段：结构化解析（DetectionResponse）依赖此输出模板，界面只读展示、用户不可修改
    JSON_TEMPLATE: str = """**输出要求**
1. 每个不安全行为单独输出一条检测项，放入 detections 数组。
2. 边界框 bbox_2d 为 [x1, y1, x2, y2]，整数像素坐标，且必须恰好 4 个数值。
3. 边界框应紧密包围涉事工人及其危险动作范围。
4. label 简明描述工人的具体不安全行为。
5. 只标注明确可见、可判断的违章行为；不确定、模糊、遮挡严重导致无法判断的情况不要输出。
6. 如果没有发现工人不安全行为，detections 返回空数组。
7. 直接返回结构化对象，不要输出任何解释、Markdown 或额外文字。

**JSON格式**
{
    "detections": [
        {
            "bbox_2d": [x1, y1, x2, y2],
            "label": "工人临边作业未正确佩戴或挂扣安全绳"
        }
    ]
}"""

    # 可编辑段默认值：角色与识别重点，用户可在“系统提示词”页面修改
    DEFAULT_PROMPT_BODY: str = """**角色**
你是一名专业的施工现场安全巡查员，负责识别图像中工人的不安全行为和违章作业行为。

请只关注“工人自身的不安全行为”，不要重点检查设备、材料、环境或管理问题。只有当某个物体或环境与工人的危险行为直接相关时，才可以一并纳入边界框。

**重点识别行为**
- 高处作业、临边作业、洞口作业未佩戴安全带或未正确挂扣安全绳。
- 高处作业安全绳未高挂低用，或安全带悬挂方式明显错误。
- 工人站在脚手架、平台、梯子、设备边缘、护栏、临边位置进行冒险作业。
- 工人攀爬、跨越、倚靠、坐卧在护栏、脚手架杆件、洞口边缘或不稳定位置。
- 工人在升降平台、剪叉车、曲臂车等设备上探身、跨越、站立在护栏上或超出安全作业范围。
- 工人未戴安全帽，或未正确系紧安全帽下颚带。
- 工人在施工区域未穿反光背心或未佩戴明显必要个人防护用品。
- 其他明显违反安全操作规程的工人行为。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        prompt: str | None = None,
        font_path: str = "simhei.ttf",
        font_size: int = DEFAULT_FONT_SIZE
    ):
        self.client:AsyncOpenAI = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model:str = model_name
        self.font_size:int = self.clamp_font_size(font_size)
        self.font:ImageFont = self._load_font(font_path, self.font_size)
        # 唯一提示词 = 用户可编辑段 + 固定 JSON 输出模板（两种调用方式共用）
        self.prompt_body: str = (prompt or self.DEFAULT_PROMPT_BODY).strip()
        self.system_prompt:str = f"{self.prompt_body}\n\n{self.JSON_TEMPLATE}"

    @classmethod
    def clamp_font_size(cls, size: int | str | None) -> int:
        """字体大小限幅，兼容配置中缺失/非法值"""
        try:
            return max(cls.MIN_FONT_SIZE, min(cls.MAX_FONT_SIZE, int(size)))
        except (TypeError, ValueError):
            return cls.DEFAULT_FONT_SIZE
        
    async def test_api(self) -> bool:
        try:
            await self.client.models.list()
            return True
        except:
            return False
    

    @staticmethod
    @lru_cache(maxsize=16)  # 缓存字号 TTF：重建客户端（改提示词/字体）时不重复解析大字体文件
    def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception as e:
            logger.warning(f"字体加载失败: {e}，使用默认字体")
            return ImageFont.load_default()


    async def _encode_image_data(self, image_data: str | Image.Image) -> str:
        """图像 → JPEG base64；解码/缩放/编码等 CPU 活均放工作线程，不占用事件循环"""
        if isinstance(image_data, Image.Image):
            return await asyncio.to_thread(self._encode_sync, image_data)
        if isinstance(image_data, str):
            if image_data.startswith(("http://", "https://")):
                raw = await _download_image(image_data)
                return await asyncio.to_thread(self._encode_sync, Image.open(io.BytesIO(raw)))
            return await asyncio.to_thread(self._encode_file, image_data)
        raise TypeError("image_data 必须是图像路径 (str) 或 PIL Image 对象")

    def _encode_file(self, path: str) -> str:
        """本地文件：无需缩放时直接透传原始字节（保留原格式，性能最优）"""
        with Image.open(path) as img:
            if max(img.size) > self.MAX_SIZE:
                return self._encode_sync(img)
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _encode_sync(self, img: Image.Image) -> str:
        """等比缩放（取宽高方向上更严格的比例）后编 JPEG"""
        limit: int = self.MAX_SIZE
        w, h = img.size
        if w > limit or h > limit:
            scale = min(limit / w, limit / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        buffered = io.BytesIO()
        img.convert("RGB").save(buffered, format="JPEG", quality=self.JPEG_QUALITY)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    @staticmethod
    def _open_rgb(path: str) -> Image.Image:
        """在线程里完成解码（convert 才真正读入像素）"""
        with Image.open(path) as img:
            return img.convert("RGB")

    async def secure_check(self, image_base64: str) -> list[dict]:
        try:
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
            logger.info(f"模型输出：{content}")
            #time.sleep(1.5)
            result: DetectionResult = self._parse_content(content)
            return [d.model_dump() for d in result.detections]
        except Exception as e:
            logger.error(f"模型推理失败: {e}")
            raise

    async def secure_check_parse(self, image_base64: str) -> list[dict]:
        try:
            response = await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
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
                response_format=DetectionResponse,
            )
            parsed: DetectionResponse = response.choices[0].message.parsed
            if parsed is None:
                logger.warning("结构化解析返回为空（可能触发了拒绝/安全策略）")
                return []
            return [d.normalize().model_dump() for d in parsed.detections]
        except Exception as e:
            logger.error(f"结构化模型推理失败: {e}")
            raise

    @staticmethod
    def _extract_json_array(text: str) -> list:
        if text is None:
            return []
        text = text.strip()
        if not text:
            return []
        text = _repair_bbox_commas(text)

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

        logger.warning("无法从模型输出中解析出 JSON 数组")
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
            logger.warning(f"第一轮 Pydantic 校验失败，启用正则兜底: {e}")

        # 兜底：用正则从脏文本中逐条抽取 {bbox_2d:[..], label:".."}
        dropped, detections = cls._regex_fallback(content)
        if dropped:
            logger.warning(f"正则兜底共丢弃 {dropped} 条非法检测条目")
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
                box = _reverse_normalize_box(box, img.width, img.height)
            draw.rectangle([(box[0], box[1]), (box[2], box[3])], outline=(255, 0, 0, 255), width=2, fill=(255, 0, 0, 30))
            if label:
                text_bbox:tuple[float,float,float,float] = draw.textbbox((0, 0), label, font=self.font)
                text_w, text_h = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
                text_x = max(0, min(box[0], img.width - text_w - 10))
                text_y:float = max(0, box[1] - text_h - 10)
                draw.text((text_x, text_y), label, font=self.font, fill=(255, 0, 0, 255))
        
        if return_b64:
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=self.JPEG_QUALITY)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')
        return img
    
    async def _detect(self, image_data: str | Image.Image) -> tuple[list[dict], str]:
        """只编码一次并复用；优先结构化解析，失败自动降级到通用 JSON 解析"""
        image_base64 = await self._encode_image_data(image_data)
        try:
            return await self.secure_check_parse(image_base64), image_base64
        except Exception as e:
            logger.warning(f"secure_check_parse 失败，降级 secure_check: {e}")
            return await self.secure_check(image_base64), image_base64

    async def infer(self, image_data: str | Image.Image, is_label: bool) -> dict[str, Image.Image | str]:
        """检测→（可选）画框；仅标注模式才解码原图，否则直接用原文件字节"""
        results, image_base64 = await self._detect(image_data)
        boxes, labels = [r["bbox_2d"] for r in results], [r["label"] for r in results]

        if is_label:
            image = (await asyncio.to_thread(self._open_rgb, image_data)
                     if isinstance(image_data, str) else image_data)
            output_image = await asyncio.to_thread(self.visualize_boxes, image, boxes, labels)
        else:
            output_image = image_base64  # 复用发给模型的编码，不再二次编码

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
    logger.info(f"处理了 {len(results)} 张图片")

    # 测试 secure_check_parse：结构化输出，成功则打印数据类 JSON
    #async def test_parse(img_path: str):
        #res = await client.secure_check_parse(img_path)
        #print(json.dumps(res, ensure_ascii=False, indent=2))
        #logging.info(f"secure_check_parse 返回 {len(res)} 条检测")

    #asyncio.run(test_parse(ima_list[0]))