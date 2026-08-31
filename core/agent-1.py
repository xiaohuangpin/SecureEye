import base64,io,logging,json,asyncio,re
from PIL import Image, ImageDraw, ImageFont
from openai import AsyncOpenAI

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

    async def secure_check(self, image_data: str | Image.Image) -> dict[str,list[int]]:
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
            return self._parse_content(content)
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
    
    async def infer(self, image_path: str | Image.Image,is_label:bool) -> dict[str, Image.Image|str]:
        #image = Image.open(image_path).convert("RGB")
        image = Image.open(image_path).convert("RGB") if isinstance(image_path, str) else image_path.convert("RGB")
        results = await self.secure_check(image)
        boxes,labels = [r["bbox_2d"] for r in results],[r["label"] for r in results]

        output_image = self.visualize_boxes(image, boxes, labels, renormalize=True) if is_label else self._encode_image_data(image)
        label_text = "\n".join(f"{i}.{lbl}" for i, lbl in enumerate(labels, start=1))

        return {"image": output_image, "label": label_text}

    async def batch_infer(self, img_paths: list[str | Image.Image],is_label:bool) -> list[dict[str, Image.Image | str]]:

        #return [self.infer(path, is_label) for path in img_paths]
        tasks = [self.infer(path,is_label) for path in img_paths]
        return await asyncio.gather(*tasks)
        #return results



if __name__ == "__main__":
    import asyncio
    import asyncio
    from dotenv import load_dotenv
    import os

    async def secure_cv(
            api_key:str,
            base_url:str,
            model_name:str,
            example:str,
            ima_path:list[str],
            ) -> list[dict[str,str]]:
        clinet = MultClient(
                api_key,
                base_url,
                model_name,
                example,
            )
        results:list[dict[str,str]] = await clinet.batch_infer(ima_path,True)
        print(results['label'])
        logging.info(f"处理了 {len(results)} 张图片")
        return results

    load_dotenv()
    api_key:str = os.getenv("api_key")
    base_url:str = os.getenv("base_url")
    model_name:str = os.getenv("model")
    example:list[str] = ["未固定的高空作业平台","裸露的带电电缆"]
    image_path:str = "image/6.jpg"
    ima_list:list[str] = ['image/9.jpg']
    asyncio.run(secure_cv(api_key,base_url,model_name,example,ima_list))
    
    """
    a = api.batch_infer(ima_list,True)
    print(a)
    """