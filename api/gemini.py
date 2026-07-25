"""Gemini REST ??????????? Gemini ???"""

import json
import urllib.request

def gemini_rest_generate(config, prompt, system_instruction=None, history=None,
                         image_b64=None, image_mime="image/png", timeout=30):
    api_key = config.get("gemini_api_key", "").strip()
    if not api_key:
        raise ValueError("尚未填写 Gemini API Key。")
    model_name = (config.get("gemini_model_name") or "gemini-3.5-flash").strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"

    contents = []
    if history:
        for m in history:
            role = "user" if m.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

    user_parts = []
    if prompt:
        user_parts.append({"text": prompt})
    if image_b64:
        user_parts.append({"inline_data": {"mime_type": image_mime, "data": image_b64}})
    if not user_parts:  # 兜底，避免发空请求
        user_parts.append({"text": " "})
    contents.append({"role": "user", "parts": user_parts})

    body = {"contents": contents}
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # “Gemini 代理”只应该影响 Gemini 请求。旧代码把它写进全局
    # HTTP_PROXY/HTTPS_PROXY，导致硅基流动等 OpenAI 兼容接口也被迫走
    # 127.0.0.1 本地代理；代理软件没启动时就会报 WinError 10061。
    proxy = (config.get("gemini_proxy") or "").strip()
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        response_context = opener.open(req, timeout=timeout)
    else:
        response_context = urllib.request.urlopen(req, timeout=timeout)

    with response_context as response:
        result = json.loads(response.read().decode("utf-8"))

    candidates = result.get("candidates") or []
    if not candidates:
        # 常见于内容被安全策略拦截，或 key/模型名错误
        feedback = result.get("promptFeedback") or result.get("error") or "Gemini 未返回任何内容"
        raise ValueError(str(feedback))
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if not text.strip():
        raise ValueError("Gemini 返回了空内容。")
    return text.strip()
