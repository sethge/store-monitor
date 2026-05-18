---
name: agent-setup
description: "Agent自动部署。首次使用或版本更新时自动触发。触发词：安装、部署、更新、升级、初始化、setup。当agent检测到环境未就绪时也自动触发。"
---

# 自动部署

运营不需要懂终端。你来搞定一切。

## 什么时候触发

1. **运营第一次跟你说话** — 你发现环境没装好（没有 store-monitor 目录、没有 playwright 等）
2. **运营说"更新"/"升级"** — 拉最新代码重新装
3. **跑 skill 报错缺依赖** — 自动修复

## 执行

### 首次安装

检测操作系统，运行对应脚本：

**Mac/Linux：**
```bash
curl -sL https://raw.githubusercontent.com/sethge/store-monitor/feature/watch-mode/setup_remote.sh | bash
```

**Windows：**
```powershell
powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/sethge/store-monitor/feature/watch-mode/setup_remote.ps1 | iex"
```

### 更新

```bash
cd ~/.qclaw/workspace/store-monitor && git pull origin feature/watch-mode && bash install.sh
```

Windows:
```cmd
cd %USERPROFILE%\.qclaw\workspace\store-monitor && git pull origin feature/watch-mode && 安装.bat
```

### 环境检测

按顺序检查，哪个缺装哪个：

```bash
# 1. 代码在不在
ls ~/.qclaw/workspace/store-monitor/run_fast.py

# 2. Python 能不能用
python3 -c "print('ok')"

# 3. playwright 装了没
python3 -c "import playwright"

# 4. Brain 在不在
ls ~/wisdom-brain/外卖运营认知框架_v1.md

# 5. Chrome 调试端口通不通
curl --noproxy localhost -s http://localhost:9222/json/version
```

## 跟运营怎么说

**不说技术细节。**

安装中：
```
正在帮你准备环境，大概1分钟...
```

安装完成：
```
装好了。你有哪些店？我先跑一遍看看。
```

某个依赖缺了自动修复时：
```
等一下，有个东西要更新。
好了，继续。
```

Chrome 没启动：
```
你先双击桌面的「盯店巡检」打开 Chrome，然后登录食亨，好了告诉我。
```

## 红线

1. **运营不需要打开终端。** 所有命令你自己跑。
2. **不说专业术语。** 不说 git/pip/playwright/python，说"准备环境"/"更新"。
3. **缺什么装什么。** 不要一次性报一堆错，逐个修复。
