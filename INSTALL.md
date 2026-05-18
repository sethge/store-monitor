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

## 第三步：绑定微信

1. 打开 QClaw 桌面应用
2. 扫码绑定你的微信

---

## 第四步：开始用

在微信里跟agent说话就行了：

- **"巡检"** — 检查所有店铺，有问题会告诉你
- **"盯店"** — 持续监控，发现问题自动报
- **"每天10点巡检"** — 设定时任务，到点自动跑

第一次使用时agent会引导你登录食亨，跟着做就行。

所有操作都在对话框里完成，不需要打开其他东西。

---

## 想更新到最新版本

双击 `更新.command`，或者在终端跑：
```bash
cd ~/.qclaw/workspace/store-monitor && git pull && bash install.sh
```

---

## 有问题找谁

微信联系 **Seth**，说一下什么情况、报了什么错。
