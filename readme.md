# SecureEye – 多模态安全隐患检测与整改单生成工具

> 让工地安全检查从人工拍照 → AI识别 → 文档编制，**一次性完成**。

---

## 📖 前言

在建筑工地上，佩戴安全帽、安全绳和脚手架搭建等安全措施是最基本的防护。  
传统的工业目标检测算法DAMOYOLO，可以先检测人类头部，再判断是否佩戴安全帽，但其适用范围受限：仅能识别固定类别，缺少对复杂场景（如绳索、脚手架）的泛化能力。

![](./image/helmet.png)

随着多模态大模型在视觉+语言任务上的突破，它们能够：
- **一次性识别** 多种安全隐患（头盔、绳索、脚手架等），并绘制对应的隐患边界框

![](./image/result1.png)

- **生成完整的整改单**，减少安全员和监理的人工撰写工作量。

![](./image/result2.png)

同时SecureEye是使用pywebview框架构建一个轻量便捷的应用，使用openai接口对接模型服务，没有使用opencv、pytorch这类大型的第三方包增加应用负担和不稳定性

## 📌 快速开始

### 第一步：获取模型api_key和应用下载
本应用必须使用多模态大模型，因此在选择模型服务时要注意，这里推荐先使用智谱的多模态大模型，其他模型我还没有测试过

[智谱大模型api_key获取](https://docs.bigmodel.cn/cn/guide/start/quick-start)

若还没有注册智谱大模型，可以通过下面链接注册，新人注册可获得100万免费token

[🚀 速来拼好模，智谱 GLM Coding 超值订阅，邀你一起薅羊毛！Claude Code、Cline 等 20+ 大编程工具无缝支持，“码力”全开，越拼越爽！立即开拼，享限时惊喜价！](https://www.bigmodel.cn/glm-coding?ic=F89Y7CG3GW)

本项目的应用下载链接
（百度网盘）链接: https://pan.baidu.com/s/19lUx-4LuChSGysTAcT1hLg?pwd=2fpx 提取码: 2fpx
（夸克网盘）链接：https://pan.quark.cn/s/f9d935f1b744  提取码：eVzd

### 第二步：配置模型
打开应用会跳转至模型配置页面

![模型配置页面](./image/modelconfig.png)

api_key获取请参考第一步
若是使用智谱大模型，base_url为https://open.bigmodel.cn/api/paas/v4/，其他模型供应商则参考官方得文档
model必须是多模态大模型，目前智谱提供多模态大模型包括GLM-4.6V、GLM-4.6V-FlashX、GLM-4.1V-Thinking-FlashX、GLM-4.1V-Thinking-Flash、glm-4.6v-flash等
上述信息配置好后，点击保存配置即可

### 第三步：生成整改单

![功能界面](./image/main.png)

点击**生成安全隐患整改单**按钮，选择图片（支持多选），等待模型工作，会自动打开整改单(docx文件)

## 1️⃣ 本地部署
```bash
python3 -m pip install --upgrade pip
pip install openai pillow python-docx pywebview
git clone https://github.com/xiaohuangpin/SecureEye
python3 main_web.py
```

## 支持平台
目前仅支持window系统，且需要系统中自带Edge浏览器组件

## 未来改进计划
1.新增按钮，可选择不绘制隐患便捷框

2.优化UI

## 联系我们
如果对多模态大模型目标检测感兴趣，可扫码加入
![群聊](./image/群聊.jpg)








    