"""Gemini API 调用 —— 通过 Google Gen AI SDK。"""

import httpx
from google import genai


def gemini_rest_generate(config, prompt, system_instruction=None, history=None,
                         image_b64=None, image_mime="image/png", timeout=30):
    """调用 Gemini 模型生成回复。

    Args:
        config: 配置字典，需包含 gemini_api_key、gemini_model_name
        prompt: 当前用户提示词
        system_instruction: 系统指令（可选）
        history: 历史对话列表 [{"role": "user"/"assistant", "content": "..."}]
        image_b64: base64 编码的图片数据（可选）
        image_mime: 图片 MIME 类型，默认 "image/png"
        timeout: 请求超时秒数，默认 30

    Returns:
        模型生成的回复文本

    Raises:
        ValueError: API Key 未填写或返回空内容
    """
    api_key = config.get("gemini_api_key", "").strip()
    if not api_key:
        raise ValueError("尚未填写 Gemini API Key。")

    model_name = (config.get("gemini_model_name") or "gemini-3.5-flash").strip()
    proxy = (config.get("gemini_proxy") or "").strip()

    # ---- 构建对话内容 ----
    contents = []
    if history:
        for m in history:
            role = "user" if m.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

    user_parts = []
    if prompt:
        user_parts.append({"text": prompt})
    if image_b64:
        user_parts.append({
            "inline_data": {"mime_type": image_mime, "data": image_b64},
        })
    if not user_parts:
        user_parts.append({"text": " "})
    contents.append({"role": "user", "parts": user_parts})

    # ---- 创建客户端（代理只影响 Gemini，不污染全局环境变量）----
    http_options = {"timeout": timeout * 1000}
    if proxy:
        http_options["transport"] = httpx.HTTPTransport(proxy=proxy)

    client = genai.Client(api_key=api_key, http_options=http_options)

    # ---- 构建生成配置 ----
    generate_config = {}
    if system_instruction:
        generate_config["system_instruction"] = {
            "parts": [{"text": system_instruction}],
        }

    # ---- 发起请求 ----
    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=generate_config,
    )

    # ---- 解析响应 ----
    candidates = response.candidates
    if not candidates:
        feedback = getattr(response, "prompt_feedback", None) or "Gemini 未返回任何内容"
        raise ValueError(str(feedback))

    text = "".join(
        part.text
        for candidate in candidates
        if candidate.content
        for part in candidate.content.parts
        if part.text
    )
    if not text.strip():
        raise ValueError("Gemini 返回了空内容。")

    return text.strip()
