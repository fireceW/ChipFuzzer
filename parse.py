import os 
import re

def parse_from_llm_output(text):
    """
    Extract ```assembly ... ``` code blocks from the LLM output and parse them.

    Two input forms are supported:
    1) text is the complete LLM output string
    2) text is a file path (the content will be read from the file and then parsed)
    """
    # If text is an existing file path, read the content from the file first
    if isinstance(text, str) and os.path.isfile(text):
        try:
            print(f"[parse_from_llm_output] 从文件读取 LLM 输出: {text}")
            with open(text, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            print(f"⚠️ 读取文件失败: {e}")
            return False

    code_match = re.search(r"```assembly\s*\n(.*?)\n```", text, re.DOTALL)
    
    # If not found, try to match the single quote format '''assembly ... '''
    if not code_match:
        code_match = re.search(r"'''assembly\s*\n(.*?)\n'''", text, re.DOTALL)
    if not code_match:
        print("⚠️ 未在文本中找到 ```assembly 代码块")
        return False
    
    # Extract code block content
    assembly_code = code_match.group(1)
    print("✅ 成功提取汇编代码：")
    print(assembly_code)
    return assembly_code

# test
path = " /root/ChipFuzzer/llm_result_fpsqrt_vector_r16_1764137261.txt"
result = parse_from_llm_output(path)