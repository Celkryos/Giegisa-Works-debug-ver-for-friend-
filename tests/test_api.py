"""API 模块冒烟测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.openai_compat import _is_text_only_model, _join_url
import threads.chat as chat_module
from threads.chat import ChatThread


# ── _is_text_only_model ──────────────────────────────

def test_text_only_detection():
    """DeepSeek 和 GLM 系列被正确识别为纯文本模型。"""
    text_only = [
        "deepseek-chat", "deepseek-v4-pro", "deepseek-v4-flash",
        "deepseek-ai/DeepSeek-V3",
        "glm-4", "glm-4-flash", "glm-4.5", "glm-4.7",
        "glm-5", "glm-5.2",
        "chatglm3-6b",
    ]
    for name in text_only:
        assert _is_text_only_model(name), f"{name} should be text-only"


def test_vision_models_not_detected():
    """多模态模型不会被误判为纯文本。"""
    vision_models = [
        "gpt-4o", "gpt-4-vision-preview",
        "qwen-vl-max", "Qwen/Qwen3-VL-30B-A3B-Thinking",
        "glm-4v", "GLM-4V",
        "claude-sonnet-5",
    ]
    for name in vision_models:
        assert not _is_text_only_model(name), f"{name} should NOT be text-only"


# ── _join_url ────────────────────────────────────────

def test_join_url():
    assert _join_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
    assert _join_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert _join_url("https://api.siliconflow.cn/v1") == "https://api.siliconflow.cn/v1"
    # 用户手误填了完整端点 URL，应裁掉 /chat/completions
    assert _join_url("https://api.x.com/v1/chat/completions") == "https://api.x.com/v1"
    # 空值 → 默认 OpenAI v1 地址
    assert _join_url("") == "https://api.openai.com/v1"


def test_chat_thread_reaches_model_api():
    """阅读器交谈最终会走 ChatThread 的真实 OpenAI 兼容调用分支。"""
    called = {}
    old_openai_chat = chat_module.openai_chat
    try:
        def fake_openai(config, messages, **kwargs):
            called["config"] = config
            called["messages"] = messages
            return "模型回复"

        chat_module.openai_chat = fake_openai
        thread = ChatThread({
            "api_type": "openai",
            "openai_api_key": "test-key",
            "openai_model_name": "test-model",
            "system_prompt": "system",
            "history_limit": 50,
        })
        thread.history = []
        thread.current_msg = "我正在读一本书，请分析这段文字。"
        thread._record_and_emit = lambda reply: called.update(reply=reply)
        thread._run_openai()
        assert called["reply"] == "模型回复"
        assert called["messages"][-1]["content"] == thread.current_msg
    finally:
        chat_module.openai_chat = old_openai_chat


if __name__ == "__main__":
    test_text_only_detection()
    test_vision_models_not_detected()
    test_join_url()
    test_chat_thread_reaches_model_api()
    print("API_SMOKE_OK")
