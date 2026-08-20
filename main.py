import gradio as gr
from core.agent import MultClient
from dotenv import load_dotenv
import os
from PIL import Image
from typing import Tuple, Union
load_dotenv()

api_key:str = os.getenv("api_key")
base_url:str = os.getenv("base_url")
model_name:str = os.getenv("model")
example:list[str] = ["未固定的高空作业平台","裸露的带电电缆"]

client = MultClient(
    api_key,
    base_url,
    model_name,
    example)

async def infer_cv(image_input: Union[str, Image.Image]) -> Tuple[Image.Image, str]:
    # 如果用户没有上传图片或输入为空
    if image_input is None:
        return None, "请先上传图片"
    
    try:
        
        output: dict[str, Image.Image | str] = await client.infer(image_input, True)
        
        # 获取返回的图片和文本
        result_image = output['image']
        result_text = output['label']
        
        return result_image, result_text
        
    except Exception as e:
        #print(f"推理出错: {e}")
        # 返回原始图片（或None）并显示错误信息
        return image_input, f"❌ 检测失败：{str(e)}"


def create_ui():
    with gr.Blocks(theme=gr.themes.Soft(), title="智能目标检测系统") as demo:
        gr.Markdown("# 🛡️ 智能安全隐患检测系统")
        gr.Markdown("上传图片（支持本地上传或URL），点击**开始检测**识别安全风险。")
        
        with gr.Row():
            # === 左侧：输入区域 ===
            with gr.Column(scale=1):
                gr.Markdown("### 📷 原始图片")
                # 允许上传文件或者输入图片链接
                input_image = gr.Image(
                    label="上传图片",
                    type="pil",  # 直接接收 PIL 图片对象
                    sources=["upload", "clipboard", "webcam"], # 丰富输入来源
                    elem_id="input_img"
                )
            
            # === 右侧：输出区域 ===
            with gr.Column(scale=1):
                gr.Markdown("### 📊 检测结果")
                output_image = gr.Image(
                    label="标注结果",
                    type="pil",
                    interactive=False,
                    elem_id="output_img"
                )
        
        # === 底部：控制与状态栏 ===
        with gr.Row():
            # 按钮居中放置
            with gr.Column(scale=1):
                submit_btn = gr.Button("🚀 开始检测", variant="primary", size="lg")
            
            # 状态显示区域
            with gr.Column(scale=2):
                status_text = gr.Textbox(
                    label="系统状态",
                    placeholder="等待操作...",
                    interactive=False,
                    lines=2,
                    max_lines=5
                )

        # ================= 事件绑定 =================
        # 点击按钮 -> 触发推理 -> 更新右边图片和下方文字
        submit_btn.click(
            fn=infer_cv,
            inputs=input_image,
            outputs=[output_image, status_text]
        )
        
        gr.Examples(
            examples=[["image/8.jpg"], ["image/9.jpg"]], # 替换为实际示例路径
            inputs=input_image,
            label="点击加载示例"
        )

    return demo

if __name__ == "__main__":
    # 创建界面
    ui = create_ui()
    # 启动，注意：Gradio 默认运行在同步环境，内部会自动处理 asyncio loop
    ui.launch()



    


