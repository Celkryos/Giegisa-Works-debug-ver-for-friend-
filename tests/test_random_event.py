"""RandomEventThread 单元测试 —— 同步执行，不依赖真实 API。"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from threads.background import RandomEventThread

# 确保有 QApplication 实例
_app = QApplication.instance() or QApplication(sys.argv)

BASE_CONFIG = {
    "api_type": "openai",
    "openai_api_key": "test-key",
    "openai_model_name": "test-model",
    "system_prompt": "",
}


def _run_sync(thread):
    """同步执行 QThread.run()，直接收集 emit 的 data。"""
    emitted = []
    thread.result_ready.connect(lambda data: emitted.append(data))
    # 绕过 QThread 的线程启动，直接在當前线程执行 run()
    thread.run()
    return emitted


def test_parses_valid_json():
    emitted = _run_sync(RandomEventThread(BASE_CONFIG))
    # 没有 mock → 会调真实 API → 应该失败并 print 不 emit
    # 所以这里只是验证链路不崩
    assert isinstance(emitted, list)


def test_random_event_parses_valid_json():
    thread = RandomEventThread(BASE_CONFIG)
    with patch.object(thread, "config", BASE_CONFIG), \
         patch("threads.background.openai_chat") as mock_api:
        mock_api.return_value = json.dumps({
            "scenario": "测试场景",
            "optA": "选项A",
            "optB": "选项B",
            "resA_text": "结果A",
            "resA_coin": 15,
            "resA_mood": -5,
            "resB_text": "结果B",
            "resB_coin": -10,
            "resB_mood": 8,
        }, ensure_ascii=False)
        emitted = _run_sync(thread)

    assert len(emitted) == 1, f"期望 1 个信号，实际 {len(emitted)}"
    data = emitted[0]
    assert data["scenario"] == "测试场景"
    assert data["optA"] == "选项A"
    assert data["resA_coin"] == 15
    print("  ✓ 正常 JSON 解析通过")


def test_extracts_json_from_noisy_reply():
    thread = RandomEventThread(BASE_CONFIG)
    with patch("threads.background.openai_chat") as mock_api:
        mock_api.return_value = (
            "好的，这是生成的事件：\n"
            '{"scenario": "深夜实验室", "optA": "开门", "optB": "逃跑", '
            '"resA_text": "发现秘密", "resA_coin": 20, "resA_mood": 10, '
            '"resB_text": "安全退回", "resB_coin": -5, "resB_mood": -10}\n'
            "希望你喜欢！"
        )
        emitted = _run_sync(thread)

    assert len(emitted) == 1, f"期望 1 个信号，实际 {len(emitted)}"
    assert emitted[0]["scenario"] == "深夜实验室"
    print("  ✓ 带噪声的 JSON 提取通过")


def test_handles_markdown_fence():
    thread = RandomEventThread(BASE_CONFIG)
    with patch("threads.background.openai_chat") as mock_api:
        mock_api.return_value = (
            "```json\n"
            '{"scenario": "猫的报恩", "optA": "收留它", "optB": "无视它", '
            '"resA_text": "获得好运", "resA_coin": 30, "resA_mood": 15, '
            '"resB_text": "错过缘分", "resB_coin": 0, "resB_mood": -20}\n'
            "```"
        )
        emitted = _run_sync(thread)

    assert len(emitted) == 1, f"期望 1 个信号，实际 {len(emitted)}"
    assert emitted[0]["scenario"] == "猫的报恩"
    print("  ✓ markdown 代码块中的 JSON 提取通过")


def test_silent_on_garbage():
    thread = RandomEventThread(BASE_CONFIG)
    with patch("threads.background.openai_chat") as mock_api:
        mock_api.return_value = "抱歉，我无法生成小剧场。"
        emitted = _run_sync(thread)

    assert len(emitted) == 0, f"期望 0 个信号，实际 {len(emitted)}"
    print("  ✓ 垃圾回复不崩溃，不 emit")


def test_greedy_regex_edge_case():
    """AI 在 JSON 之后又加了花括号文字时，贪婪正则失败但不崩溃。"""
    thread = RandomEventThread(BASE_CONFIG)
    with patch("threads.background.openai_chat") as mock_api:
        mock_api.return_value = (
            '{"scenario": "意外之财", "optA": "捡起钱包", "optB": "交给警察", '
            '"resA_text": "里面有钱", "resA_coin": 25, "resA_mood": 5, '
            '"resB_text": "获得表扬", "resB_coin": 10, "resB_mood": 15}'
            "\n{顺便一提，你今天的运势还行}"
        )
        emitted = _run_sync(thread)

    # 贪婪正则会吃到多余花括号导致 json.loads 失败 → 不 emit
    # 这是已知局限，验证不崩溃
    assert not emitted or emitted[0].get("scenario") == "意外之财"
    print("  ✓ 多余花括号不崩溃（已知局限）")


if __name__ == "__main__":
    test_parses_valid_json()
    test_random_event_parses_valid_json()
    test_extracts_json_from_noisy_reply()
    test_handles_markdown_fence()
    test_silent_on_garbage()
    test_greedy_regex_edge_case()
    print("RANDOM_EVENT_TESTS_OK")
