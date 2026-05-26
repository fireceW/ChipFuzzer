import unicodedata

from openai import OpenAI

client = OpenAI(
    api_key="f7c165690e63515a7a3904c7f7dc159c72ff4350684ed000e8b27f2860c4890a",
    base_url="https://uni-api.cstcloud.cn/v1"
)

# LLM 调用超时（秒），避免 API 挂死时程序一直等待；大模型如 qwen3:235b 可能需数分钟
LLM_TIMEOUT = 600  # 10 分钟

def callOpenAI_KJY(prompt: str, modelname) -> str:
    completion = client.chat.completions.create(
        messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
      ],
        model=modelname,
        timeout=LLM_TIMEOUT,
    )

    message = completion.choices[0].message
    content = unicodedata.normalize('NFKC', message.content)

    return content
