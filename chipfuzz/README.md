# ChipFuzzer 展示页（静态网页）

这是一个用于展示 **ChipFuzzer（芯片验证框架）** 的静态网页，无需构建工具，直接打开即可。

## 目录结构

- `index.html`：主页
- `assets/style.css`：样式
- `assets/main.js`：主题切换/复制按钮/数字动效

## 打开方式

### 方式 A：直接双击

直接用浏览器打开 `index.html`。

### 方式 B：本地静态服务器（推荐）

在该目录打开终端后运行：

```powershell
python -m http.server 5173
```

然后在浏览器访问：`http://localhost:5173/`

## 如何替换成你的真实内容

- 在 `index.html` 中搜索 **“占位”** 或 **“示例”**，把链接、邮箱、命令行示例替换成真实信息
- 如果你有架构图/结果截图，可以放到 `assets/` 里，然后在 `index.html` 增加 `<img>` 区块

