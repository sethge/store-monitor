# 食亨智慧运营 — 安装指南

## 你需要准备什么

- 一台 Mac 或 Windows 电脑
- 微信（用来跟agent说话）
- 食亨账号（你平时登的那个）

全程大概10分钟，不需要懂技术。

---

## 第一步：安装 QClaw

QClaw 是agent的运行环境，装一次就行。

**Mac：**
1. 打开"终端"（在 启动台 → 其他 → 终端，或者 Spotlight 搜"终端"）
2. 复制粘贴下面这行，按回车：
```bash
curl -fsSL https://qclaw.ai/install.sh | bash
```
3. 等它跑完，看到 `✅ QClaw已安装` 就行

**Windows：**
1. 打开 PowerShell（右键开始菜单 → Windows PowerShell）
2. 复制粘贴下面这行，按回车：
```powershell
irm https://qclaw.ai/install.ps1 | iex
```

---

## 第二步：安装盯店Agent

在终端里依次执行（每行复制粘贴后按回车）：

```bash
cd ~/.qclaw/workspace
git clone https://gitee.com/sethgeshiheng/store-monitor.git
cd store-monitor
git checkout feature/watch-mode
bash install.sh
```

看到 `✅ 安装完成！` 就OK了。

> 如果提示输入Gitee用户名密码，找Seth要。

---

## 第三步：登录食亨

1. 安装完会自动打开一个浏览器窗口（Chrome或Chromium）
2. 在这个浏览器里打开 **bi.shihengtech.com**
3. 用你的食亨账号登录
4. 登录成功后，**不要关这个浏览器**

> 这个浏览器是agent专用的，跟你平时用的Chrome互不影响。

---

## 第四步：绑定微信

1. 打开 QClaw 桌面应用
2. 扫码绑定你的微信
3. 绑定成功后，在微信里找到 QClaw 的对话

---

## 第五步：试一下

在微信里跟agent说：

> 巡检

它会自动检查你所有店铺，几十秒后给你汇报结果。

其他你可以说的：
- **"盯店"** — 持续监控，有问题自动报
- **"每天10点巡检"** — 设定时任务
- **"港翠有什么问题"** — 查指定品牌

---

## 常见问题

### agent说"浏览器连不上"
把那个专用浏览器关掉重开，或者在终端里跑：
```bash
cd ~/.qclaw/workspace/store-monitor
python3 -c "from browser import launch; import asyncio; from playwright.async_api import async_playwright; asyncio.run(async_playwright().start())"
```

### agent说"插件未就绪"
在专用浏览器里重新登录一次 bi.shihengtech.com。

### agent说"品牌未找到"
确认你的食亨账号下有这个品牌的授权。

### 想更新到最新版本
```bash
cd ~/.qclaw/workspace/store-monitor
git pull
bash install.sh
```

---

## 有问题找谁

微信联系 **Seth**，说一下什么情况、报了什么错。
