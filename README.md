# 🛡️ SecureEye — AI-Powered Construction Site Safety Inspection

> **In one sentence**: Upload a photo of your construction site, and SecureEye uses AI to automatically detect **unsafe worker behaviors** (e.g., missing harness, no helmet), draws bounding boxes on the image, and generates a rectification report for you — no more manually copying inspection sheets.

📖 **中文文档**: [readme_zh.md](./readme_zh.md)

---

## ✨ The Problem We Solve

On construction sites, most serious accidents are caused by **unsafe human behavior**:

- Working at edges or heights **without a proper safety harness**, or with the harness attached incorrectly;
- **Leaning over or taking risks** from scaffolds or lift-platform guardrails;
- Safety harness not used in the "high anchor, low use" (高挂低用) configuration;
- **Missing hard hats**, or chin straps left loose;
- No reflective vests or required personal protective equipment (PPE) in work zones…

Traditionally, safety officers photograph each scene and handwrite rectification forms — inefficient, error-prone, and inconsistent.

**SecureEye makes this simple**: upload one site photo, and the AI instantly "understands" what workers are doing, precisely boxes every hazardous action, and compiles a standardized rectification report.

---

## 🤖 Why a Multimodal LLM Instead of Traditional Detection Algorithms?

Traditional object detection (e.g., DAMOYOLO) typically recognizes only **a fixed set of object classes** — e.g., locate a head first, then judge whether a hat is present. It struggles to understand **complex human behaviors** such as "a worker leaning over a guardrail," and generalizes poorly to ropes, scaffolding, and other contexts.

![](./image/helmet.png)

A multimodal large language model combines "image perception + semantic understanding," enabling it to:

- 🔍 **Identify multiple unsafe behaviors at once** (missing harness, reckless climbing, no helmet, etc.) and draw precise hazard bounding boxes:

![](./image/result1.png)

- 📝 **Auto-generate complete rectification reports**, dramatically reducing repetitive writing for safety officers and supervisors:

![](./image/app_example.png)

> 💡 **SecureEye's design principle**: Build a lightweight, stable desktop app with `pywebview`, and connect to model services through an OpenAI-compatible interface. **No heavyweight third-party libraries such as OpenCV or PyTorch**, reducing installation burden and runtime instability for out-of-the-box use.

---

## 🚀 Quick Start

### Step 1: Get the App (Download or Build from Source)

This application must call a multimodal LLM. When configuring the model, choose a service that is compatible with the OpenAI interface (locally deployed models are also supported).

**App download:**

- Baidu Netdisk: https://pan.baidu.com/s/19lUx-4LuChSGysTAcT1hLg?pwd=2fpx (extraction code: `2fpx`)
- Quark Netdisk: https://pan.quark.cn/s/f9d935f1b744 (extraction code: `eVzd`)

### Step 2: Configure the Model

Launching the app automatically opens the model configuration page. Most mainstream providers are OpenAI-compatible — fill in the corresponding information.

![Model Configuration Page](./image/modelconfig.png)

Click **Save Configuration** when done.

### Step 3: Generate a Rectification Report

![Rectification Report Demo](./image/app_main.png)

Click the **Safety Hazard Detection** button and select an image (multiple selection supported). After detection, the system displays each unsafe behavior in a table and supports exporting to Word and Excel.

---

## 💻 Build from Source (Local Deployment)

```bash
python3 -m pip install --upgrade pip
pip install openai pillow python-docx pywebview
git clone https://github.com/xiaohuangpin/SecureEye
python3 main.py
```

---

## 🌐 Gradio Online Demo (No Desktop App Required)

If you only want to **quickly try out** the detection without installing the desktop client, run the Gradio demo. It opens a lightweight web page in your browser with the same interaction flow as the desktop version:

- 📷 **Multiple image sources**: local upload, clipboard paste, and live camera capture;
- 🖼️ **One-click sample loading**: built-in example images, click to try;
- 🚀 **Start detection**: original image on the left, auto-annotated hazard bounding boxes on the right, plus a textual description.

Launch (configure `api_key` / `base_url` / `model` in `.env` first):

```bash
pip install gradio
python3 main.py
```

After running, the browser opens the demo page automatically. Upload or load a sample image and click **Start Detection** to view results.

---

## 🖥️ Supported Platforms

Currently supports **Windows** and requires the **Edge browser component** (a runtime dependency of pywebview) to be present in the system.

---

## 🔍 Unsafe Behaviors SecureEye Focuses On

We use specially optimized prompts to focus the model on **workers' own behavior** rather than equipment, materials, or the environment:

| Category | Typical Violations |
| --- | --- |
| Work at height / edge operations | Missing or incorrectly fastened safety harness; harness not used "high anchor, low use" |
| Risky positioning | Standing on scaffolds, platforms, guardrails, edges, or hole rims |
| Climbing & leaning | Climbing, crossing, leaning on, or sitting/lying on guardrails or unstable positions |
| Lift equipment violations | Leaning out, standing on guardrails, or over-reaching on scissor/cherry pickers |
| Personal protective equipment (PPE) | Missing hard hat / loose chin strap; no reflective vest, etc. |

> 📌 The model only labels **clearly visible,judgeable** violations. Blurred or heavily occluded scenes that prevent a confident judgment are not flagged, avoiding false accusations against workers.

---

## 🗺️ Future Roadmap

- [ ] **Develop a corresponding Skill (plugin)**: Package SecureEye's "construction unsafe-behavior detection + rectification report generation" capability into a reusable Skill that integrates seamlessly with skill-extensible AI coding/agent platforms. Goals include:
  - Standardized input/output protocol so other agents can invoke the detection with one click;
  - Built-in professional safety-inspection prompts and violation-type lists, ready to use;
  - Automatic detection triggering and rectification-suggestion generation within agent workflows.

---

## 💬 Contact Us

If you are interested in "multimodal LLM + construction safety behavior detection," scan the QR code to join our community:

![Community](./image/群聊.jpg)
