#!/usr/bin/env python3
"""快速测试 LLM API 是否可用（与 fuzzing 使用同一套调用）"""
import sys
import time

def test_kjy():
    """测试 KJY 接口（qwen3:235b / deepseek-r1:671b）"""
    print("测试 LLM_API_KJY（qwen3:235b）...")
    try:
        from LLM_API_KJY import callOpenAI_KJY
        t0 = time.time()
        # 短 prompt，30 秒超时足够
        out = callOpenAI_KJY("只回复一个词：OK", "qwen3:235b")
        elapsed = time.time() - t0
        print(f"  ✅ 成功 ({elapsed:.1f}s): {repr(out[:200])}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def test_openai():
    """测试 OpenAI 接口（gpt-5.1）"""
    print("测试 LLM_API（gpt-5.1）...")
    try:
        from LLM_API import callOpenAI
        t0 = time.time()
        out = callOpenAI("只回复一个词：OK")
        elapsed = time.time() - t0
        print(f"  ✅ 成功 ({elapsed:.1f}s): {repr(out[:200])}")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

if __name__ == "__main__":
    which = (sys.argv[1:1] or ["kjy"])[0].lower()
    ok = False
    if which in ("kjy", "qwen", "all"):
        ok = test_kjy() or ok
    if which in ("openai", "gpt", "all"):
        ok = test_openai() or ok
    if which not in ("kjy", "qwen", "openai", "gpt", "all"):
        ok = test_kjy()
    sys.exit(0 if ok else 1)
