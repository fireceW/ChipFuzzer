import os 
import re

def parse_from_llm_output(text):
    """
    从 LLM 输出中提取 ```assembly ... ``` 代码块并解析。

    支持两种输入形式：
    1) text 是完整的 LLM 输出字符串
    2) text 是一个文件路径（会从文件中读取内容再解析）
    """
    # 如果 text 是一个存在的文件路径，则先从文件中读入内容
    if isinstance(text, str) and os.path.isfile(text):
        try:
            print(f"[parse_from_llm_output] 从文件读取 LLM 输出: {text}")
            with open(text, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"⚠️ 读取文件失败: {e}")
            return False

    code_match = re.search(r"```assembly\s*\n(.*?)\n```", text, re.DOTALL)
    
    # 如果没找到，尝试匹配单引号格式 '''assembly ... '''
    if not code_match:
        code_match = re.search(r"'''assembly\s*\n(.*?)\n'''", text, re.DOTALL)
    if not code_match:
        print("⚠️ 未在文本中找到 ```assembly 代码块")
        return False
    
    # 提取代码块内容
    assembly_code = code_match.group(1)
    print("✅ 成功提取汇编代码：")
    print(assembly_code)
    return assembly_code

# 测试
path = " /root/ChipFuzzer/llm_result_fpsqrt_vector_r16_1764137261.txt"
result = parse_from_llm_output(path)