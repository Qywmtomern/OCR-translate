"""
翻译器 — 通过 DeepSeek API 将任意语言翻译为简体中文
每次调用创建独立客户端，线程安全
"""

from openai import OpenAI

import config


class Translator:
    """DeepSeek API 翻译客户端（线程安全，每次调用创建独立客户端）"""

    def __init__(self):
        self._model_name = config.DEEPSEEK_MODEL
        self._fallback_models = ["deepseek-chat", "deepSeek-V4-pro"]

    # ------------------------------------------------------------------
    # 翻译
    # ------------------------------------------------------------------
    def translate(self, text: str) -> str:
        """将文本翻译为简体中文"""
        if not text or not text.strip():
            return ""

        client = OpenAI(
            base_url=config.DEEPSEEK_BASE_URL,
            api_key=config.DEEPSEEK_API_KEY,
            timeout=30.0,
        )

        last_error = None
        models_to_try = [self._model_name] + [
            m for m in self._fallback_models if m != self._model_name
        ]

        for model in models_to_try:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": config.TRANSLATE_SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                result = resp.choices[0].message.content.strip()
                self._model_name = model
                return result
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(
            f"翻译失败 (尝试了 {len(models_to_try)} 个模型名: {models_to_try}): {last_error}"
        )
