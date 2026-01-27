import unicodedata

from openai import OpenAI

client = OpenAI(
    api_key="sk-8OQ6Ea0pzN4b6fAxvu26WNBgu4nquIhsVf4uWFZPgi7Uw9n7",
    base_url="http://35.164.11.19:3887/v1"
)

def callOpenAI(prompt: str) -> str:
    completion = client.chat.completions.create(
        messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": prompt}
      ],
        model="gpt-5.1",
        #model= "gpt-4o-2024-08-06",
        #model="gpt-4-1106-preview",
        #model="gpt-4-0314",
    )

    message = completion.choices[0].message
    content = unicodedata.normalize('NFKC', message.content)

    return content





#print(callOpenAI("hello, you are a helpful hardware fuzzing tester."))
