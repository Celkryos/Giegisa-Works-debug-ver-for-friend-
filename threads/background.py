import os
import json
import random
import re
import time
import base64
import urllib.request
from PyQt6.QtCore import QThread, pyqtSignal
from config import BASE_DIR, save_config
from api import gemini_rest_generate, openai_chat

class TriviaThread(QThread):
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            topics = [
                "宇宙与天文", "奇妙生物圈", "人体与生理", 
                "世界各地的奇葩风俗与冷门地理", "鲜为人知的古代历史边角料或名人怪癖", 
                "日常食物起源与生活常识背后的科学", "早期计算机与互联网发展史的趣事", 
                "各类科学技术与专业领域名词解释", "经典电影、艺术或流行文化背后的冷知识", 
                "任何有趣的冷热门领域知识"
            ]
            selected_topic = random.choice(topics)
            prompt = f"【系统随机种子：{random.randint(1, 999999)}】请提供一个关于“{selected_topic}”的真实、有趣且极度罕见的冷知识。请规避大模型偷懒现象，抛弃常见的烂梗。字数严格控制在50到100字之间。只需输出冷知识的正文内容，绝不要有任何多余的开场白或结尾。"
            
            api_type = self.config.get("api_type", "gemini")
            if api_type == "gemini":
                reply = gemini_rest_generate(self.config, prompt, timeout=30)
            else:
                reply = openai_chat(self.config,
                                    [{"role": "user", "content": prompt}],
                                    temperature=0.9, timeout=45)
            self.result_ready.emit(reply.strip())
        except Exception as e:
            self.error_occurred.emit(str(e))

class IdleChatThread(QThread):
    result_ready = pyqtSignal(str)
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        
    def run(self):
        try:
            prompt = "你的用户已经有一段时间没有进行任何操作了。请结合你高冷/s属性/微傲娇的系统人设，生成一句简短的闲聊或关心的话（20字以内，无需任何开场白，直接输出正文）。"
            sys_p = self.config.get("system_prompt", "")
            api_type = self.config.get("api_type", "gemini")
            if api_type == "gemini":
                reply = gemini_rest_generate(self.config, prompt, system_instruction=sys_p, timeout=30)
            else:
                reply = openai_chat(self.config,
                                    [{"role": "system", "content": sys_p},
                                     {"role": "user", "content": prompt}],
                                    temperature=0.8, timeout=45)
            self.result_ready.emit(reply.strip())
        except Exception:
            pass

class RandomEventThread(QThread):
    result_ready = pyqtSignal(dict)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            prompt = (
                f"【系统随机种子：{random.randint(1, 999999)}】请生成一个给用户的随机遭遇小剧场事件（日常或异世界均可，规避大模型偷懒现象）。\n"
                "事件需要有不可预测性，两个选项不要有明显的“对错”或“好坏”之分，可增加道德困境、黑色幽默或两难的硬核抉择。\n"
                "选项的结果（coin代表数据碎片，mood代表好感度）必须打破常规搭配，有概率出现“扣碎片但加好感”或“加碎片但扣好感”的情况。\n"
                "严格按照以下JSON格式返回（数值在-30到30之间随机，直接输出大括号，禁止附带```json等任何额外标记）：\n"
                '{"scenario": "场景描述(50字内)", "optA": "选项A的动作", "optB": "选项B的动作", "resA_text": "选A的结果描述", "resA_coin": 15, "resA_mood": -5, "resB_text": "选B的结果描述", "resB_coin": -10, "resB_mood": 8}'
            )
            api_type = self.config.get("api_type", "gemini")
            if api_type == "gemini":
                reply = gemini_rest_generate(self.config, prompt, timeout=30)
            else:
                reply = openai_chat(self.config,
                                    [{"role": "user", "content": prompt}],
                                    temperature=0.9, timeout=45)
            
            match = re.search(r'\{.*\}', reply, re.DOTALL)
            if match:
                reply = match.group(0)
            data = json.loads(reply)
            self.result_ready.emit(data)
        except Exception as e:
            print("小剧场生成失败:", str(e))

class DataRetrievalThread(QThread):
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            prompt_content = ""
            txt_path = os.path.join(BASE_DIR, "prompt.txt")
            file_path = os.path.join(BASE_DIR, "prompt")
            
            if os.path.exists(txt_path):
                with open(txt_path, 'r', encoding='utf-8') as f:
                    prompt_content = f.read()
            elif os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    prompt_content = f.read()
            else:
                prompt_content = "（未能找到本地的 prompt 设定文档，请结合自身设定发挥。）\n" + self.config.get("system_prompt", "")
                
            task_prompt = (
                f"【系统随机数：{random.randint(1, 999999)}】\n以下是设定的背景和档案资料：\n{prompt_content}\n\n"
                "请严格结合上述文档内容和你的基础人设，生成一段200字左右的文字。请极力避免同质化，发挥极大的文学创造力。\n"
                "内容必须是以下6种形式之一（请自行随机选择一种）：\n"
                "1. 一个简短小故事，可以急剧反转\n"
                "2. 和伴侣“20”之间的关系展现或发生过的事件\n"
                "3. 你自己的某段“经历和观点”\n"
                "4. 你“在某个平行异世界”看到、经历过或收集到的见闻\n"
                "5. 像趣味科普一样，对某种虚构的异世界事物、名词或风土人情进行介绍和解释\n"
                "6. 其他任何不违背人设的随机内容生成。\n\n"
                "【重要限制】：直接以giegisa的高冷口吻输出正文内容，绝不能有任何开场白（如“好的”“这是一段见闻”等）、也不要结尾分析，直接开始正文内容的描写或陈述。"
            )
            
            api_type = self.config.get("api_type", "gemini")
            if api_type == "gemini":
                reply = gemini_rest_generate(self.config, task_prompt, timeout=30)
            else:
                reply = openai_chat(self.config,
                                    [{"role": "user", "content": task_prompt}],
                                    temperature=0.9, timeout=45)
            self.result_ready.emit(reply.strip())
        except Exception as e:
            self.error_occurred.emit(str(e))

class ItemRetrievalThread(QThread):
    result_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            prompt = f"【系统随机种子：{random.randint(1, 999999)}】请发挥极其天马行空的想象力，随机生成一个在异世界或现实中拾取到的奇异物品。请避开大模型偷懒现象，从各个领域汲取灵感。格式严格为“【物品名称】50字以内的物品介绍”。可以是现实存在的，也可以是完全虚构的。直接输出结果，不要有任何多余的开头或结尾。"
            api_type = self.config.get("api_type", "gemini")
            if api_type == "gemini":
                reply = gemini_rest_generate(self.config, prompt, timeout=30)
            else:
                reply = openai_chat(self.config,
                                    [{"role": "user", "content": prompt}],
                                    temperature=0.9, timeout=45)
            self.result_ready.emit(reply.strip())
        except Exception as e:
            self.error_occurred.emit(str(e))

class ImageFetchThread(QThread):
    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            req = urllib.request.Request(self.url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                data = response.read()
                self.finished.emit(data)
        except Exception as e:
            self.error.emit(str(e))
