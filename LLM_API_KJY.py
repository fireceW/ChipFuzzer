import unicodedata

from openai import OpenAI

client = OpenAI(
    api_key="f7c165690e63515a7a3904c7f7dc159c72ff4350684ed000e8b27f2860c4890a",
    base_url="https://uni-api.cstcloud.cn/v1"
)

def callOpenAI_KJY(prompt: str, modelname) -> str:
    completion = client.chat.completions.create(
        messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
      ],
        #model="deepseek-r1:671b",
        model=modelname,
        #model= "gpt-4o-2024-08-06",
        #model="gpt-4-1106-preview",
        #model="gpt-4-0314",
    )

    message = completion.choices[0].message
    content = unicodedata.normalize('NFKC', message.content)

    return content
