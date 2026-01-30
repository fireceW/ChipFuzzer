#!/bin/bash
# 从服务器同步 chipfuzz 目录到本地（Linux/Mac 版本）
# 使用方法：chmod +x sync_chipfuzz_to_local.sh && ./sync_chipfuzz_to_local.sh

echo "正在从服务器同步 chipfuzz 目录..."
scp -r root@js1.blockelite.cn:/root/ChipFuzzer_cursor/chipfuzz ~/Desktop/

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ 同步成功！"
    echo "文件已更新到: ~/Desktop/chipfuzz"
else
    echo ""
    echo "❌ 同步失败，请检查："
    echo "  1. 网络连接是否正常"
    echo "  2. SSH 密钥是否已配置"
    echo "  3. 服务器地址是否正确"
fi
