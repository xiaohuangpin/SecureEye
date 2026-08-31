import re,httpx

async def _download_image(url: str) -> bytes:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content


def _repair_bbox_commas(text: str) -> str:
        """修复 bbox_2d 数组中数字间缺失的逗号：如 [470 345 536 449] -> [470, 345, 536, 449]"""
        return re.sub(
            r'"bbox_2d"\s*:\s*\[[\d.\-]+(?:\s*[,\s]+\s*[\d.\-]+)+\]',
            lambda m: re.sub(r'(?<=[\d.\-])\s+(?=[\d.\-])', ', ', m.group(0)),
            text,
        )


def _reverse_normalize_box(box: list[int], img_width: int, img_height: int) -> list[int]:
        """将 [0,999] 归一化坐标转换为像素坐标"""
        x1, y1, x2, y2 = [max(0, min(1000.0, v)) for v in box]
        return [
            int((x1 / 1000.0) * img_width),
            int((y1 / 1000.0) * img_height),
            int((x2 / 1000.0) * img_width),
            int((y2 / 1000.0) * img_height)
        ]



