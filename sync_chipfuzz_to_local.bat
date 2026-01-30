@echo off
REM 从服务器同步 chipfuzz 目录到本地桌面
REM 使用方法：双击此文件，或在命令行执行

echo 正在从服务器同步 chipfuzz 目录...
scp -r root@js1.blockelite.cn:/root/ChipFuzzer_cursor/chipfuzz C:\Users\Lenovo\Desktop\

if %errorlevel% == 0 (
    echo.
    echo ✅ 同步成功！
    echo 文件已更新到: C:\Users\Lenovo\Desktop\chipfuzz
) else (
    echo.
    echo ❌ 同步失败，请检查：
    echo   1. 网络连接是否正常
    echo   2. SSH 密钥是否已配置
    echo   3. 服务器地址是否正确
)

pause
