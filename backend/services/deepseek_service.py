"""DeepSeek Chat Completions（OpenAI 兼容接口）

官方文档：https://api-docs.deepseek.com/zh-cn/
- base_url: https://api.deepseek.com（亦可使用 https://api.deepseek.com/v1，v1 与模型版本无关）
- 对话接口: POST /chat/completions
- 模型示例: deepseek-chat、deepseek-reasoner
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# 与 curl 示例一致：https://api-docs.deepseek.com/zh-cn/
DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_CHAT_URL = f"{DEEPSEEK_BASE}/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

# 这些异常在 LLM 长响应场景下常因中间代理/网关提前关连接引发，值得自动重试
_RETRYABLE_EXCEPTIONS: tuple = (
    http.client.IncompleteRead,
    http.client.RemoteDisconnected,
    http.client.BadStatusLine,
    ConnectionError,
    TimeoutError,
    socket.timeout,
)


def _do_chat_request(api_key: str, payload: bytes, timeout: int) -> dict:
    req = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # 避免连接被代理复用后半截断导致 IncompleteRead：每次新连接
            "Connection": "close",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def chat_completion(
    api_key: str,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
    temperature: float = 0.3,
    extra_body: dict | None = None,
    max_retries: int = 2,
    retry_backoff: float = 1.5,
) -> str:
    payload_obj: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if extra_body:
        payload_obj.update(extra_body)
    payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")

    data: dict | None = None
    last_err: Exception | None = None
    attempts = max(1, int(max_retries) + 1)
    for i in range(attempts):
        try:
            data = _do_chat_request(api_key, payload, timeout)
            break
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            # 4xx 多为请求/鉴权错误，无需重试；5xx / 429 进入重试分支
            if 400 <= e.code < 500 and e.code != 429:
                raise ValueError(f"DeepSeek HTTP {e.code}: {body[:500]}") from e
            last_err = ValueError(f"DeepSeek HTTP {e.code}: {body[:300]}")
        except urllib.error.URLError as e:
            # URLError 通常包裹 socket.timeout / ConnectionReset / DNS 错误 → 重试
            last_err = e
        except _RETRYABLE_EXCEPTIONS as e:
            last_err = e
        except Exception as e:
            raise ValueError(f"DeepSeek 请求失败: {e}") from e
        if i < attempts - 1:
            wait = retry_backoff * (2 ** i)
            logger.info(
                "DeepSeek 请求失败（第 %d/%d 次），%.1fs 后重试：%s",
                i + 1, attempts, wait, last_err,
            )
            time.sleep(wait)

    if data is None:
        raise ValueError(f"DeepSeek 请求失败（重试 {attempts - 1} 次）: {last_err}")

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise ValueError(f"DeepSeek 响应格式异常: {data}") from e


def chat_completion_json_object(
    api_key: str,
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    timeout: int = 120,
    max_retries: int = 2,
) -> str:
    """
    使用 JSON Output（response_format=json_object）。
    若服务端不支持该参数，将抛出异常，由调用方回退到普通 chat_completion。
    参见 API 指南「JSON Output」: https://api-docs.deepseek.com/zh-cn/
    """
    return chat_completion(
        api_key,
        messages,
        model=model,
        timeout=timeout,
        temperature=0.2,
        extra_body={"response_format": {"type": "json_object"}},
        max_retries=max_retries,
    )


def extract_json_object(text: str) -> dict:
    """从模型输出中解析 JSON 对象（支持 ```json 代码块）"""
    t = (text or "").strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
        if m:
            t = m.group(1).strip()
    # 尝试找首个 { 到最后一个 }
    if "{" in t:
        start = t.index("{")
        end = t.rindex("}") + 1
        t = t[start:end]
    return json.loads(t)
