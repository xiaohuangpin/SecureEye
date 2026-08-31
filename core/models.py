from typing import Tuple
from pydantic import BaseModel, Field


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
