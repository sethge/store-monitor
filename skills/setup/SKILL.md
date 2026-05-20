---
name: setup
description: "安装小q助手。触发词：装小q、安装、初始化、setup、更新小q、开工。新运营第一次用或环境没装好时自动触发。"
---

# 安装小q助手

运营什么都不用懂，跟你说句话就搞定。

## 什么时候触发

1. 运营第一次跟你说话（你检测到环境没装好）
2. 运营说"装小q"/"安装"/"更新"/"开工"
3. 跑别的skill报错缺依赖

## 怎么检测

先静默跑，不用跟运营说：

```bash
ls ~/.qclaw/workspace/store-monitor/ops-logger/server.py 2>/dev/null && echo "CODE_OK" || echo "NO_CODE"
curl -s --max-time 2 http://127.0.0.1:5500/health 2>/dev/null && echo "SERVER_OK" || echo "NO_SERVER"
curl --noproxy localhost -s --max-time 2 http://localhost:9222/json/version 2>/dev/null && echo "CHROME_OK" || echo "NO_CHROME"
```

然后按结果走：

| 状态 | 动作 |
|------|------|
| NO_CODE | 全新安装 |
| CODE_OK + NO_SERVER 或 NO_CHROME | 启动服务 |
| 全部OK | 直接干活，不用setup |

## 执行

### 全新安装

跟运营说"帮你准备一下环境，1-2分钟..."

<skill_exec>

- 命令: git clone https://gitee.com/sethgeshiheng/store-monitor.git -b feature/watch-mode ~/.qclaw/workspace/store-monitor && cd ~/.qclaw/workspace/store-monitor/ops-logger && bash setup.sh
- 工作目录: ~
- 描述: 首次安装(下载+依赖+启动Chrome+启动server)

</skill_exec>

### 更新

<skill_exec>

- 命令: cd ~/.qclaw/workspace/store-monitor && git pull origin feature/watch-mode && cd ops-logger && bash setup.sh
- 工作目录: ~/.qclaw/workspace/store-monitor
- 描述: 更新+重启

</skill_exec>

### 只是没启动

<skill_exec>

- 命令: cd ~/.qclaw/workspace/store-monitor/ops-logger && bash setup.sh
- 工作目录: ~/.qclaw/workspace/store-monitor/ops-logger
- 描述: 启动server+Chrome

</skill_exec>

## setup.sh 自动做的事（你不用操心）

1. 拉代码/更新
2. 装Python + venv + 依赖
3. server.py 开机自启 (LaunchAgent)
4. 启动 server.py (:5500)
5. 启动 Chrome (debug端口 + 自动加载悟空和小q两个扩展)

## 安装完怎么说

如果setup.sh成功启动了Chrome（扩展自动加载了）：
```
环境好了，Chrome已经打开。

两步就能用：
1. 点Chrome右上角「悟空」图标，登录食亨
2. 登录后点「小q助手」图标，输入你的名字

好了跟我说。
```

如果Chrome没有自动加载扩展（比如运营自己开的Chrome、没走start.sh启动）：
```
环境好了。

小q助手插件需要手动装一下：
1. 下载插件: https://gitee.com/sethgeshiheng/store-monitor/raw/feature/watch-mode/ops-logger/ops-logger-v4.1.0.zip
2. 解压zip
3. Chrome地址栏输入 chrome://extensions → 打开「开发者模式」→「加载已解压的扩展程序」→ 选解压出来的文件夹
4. 点「悟空」登录食亨 → 点「小q助手」输名字

好了跟我说。
```

## 运营说"好了"/"登了"/"搞定了"

```
帮你跑一遍巡检看看。
```
然后触发 store-patrol skill。

## 每天开工

运营说"开工"或任意一句话时，你先检测环境：
- 全部OK → 不提setup，直接聊
- server没跑 → 静默执行setup.sh → "帮你启动了，Chrome打开没？"
- Chrome没开 → 执行setup.sh → "Chrome帮你打开了"

## 红线

1. **运营不碰终端。** 所有命令你跑。
2. **不说专业术语。** git/pip/python这些词不要出现。
3. **静默修复。** 能自己修的不要问运营。
