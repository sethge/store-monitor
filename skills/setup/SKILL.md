---
name: setup
description: "安装小q助手。触发词：装小q、安装、初始化、setup、更新小q。新运营第一次用或环境没装好时自动触发。"
---

# 安装小q助手

运营只需要说一句"装小q"，你来搞定一切。

## 什么时候触发

1. 运营第一次跟你说话，你检测到环境没装好
2. 运营说"装小q"/"安装"/"更新"
3. 跑别的skill报错缺依赖

## 怎么检测环境

```bash
ls ~/.qclaw/workspace/store-monitor/ops-logger/server.py 2>/dev/null && echo "已安装" || echo "未安装"
curl -s --max-time 2 http://127.0.0.1:5500/health 2>/dev/null && echo "server运行中" || echo "server未启动"
```

## 执行

### 全新安装（目录不存在）

跟运营说"正在帮你准备环境，大概1-2分钟..."，然后执行：

<skill_exec>

- 命令: git clone https://gitee.com/sethgeshiheng/store-monitor.git -b feature/watch-mode ~/.qclaw/workspace/store-monitor && cd ~/.qclaw/workspace/store-monitor/ops-logger && bash setup.sh
- 工作目录: ~
- 描述: 首次安装

</skill_exec>

### 已安装过（更新或修复）

<skill_exec>

- 命令: cd ~/.qclaw/workspace/store-monitor && git pull origin feature/watch-mode && cd ops-logger && bash setup.sh
- 工作目录: ~/.qclaw/workspace/store-monitor
- 描述: 更新+重启

</skill_exec>

### 只是server没启动

<skill_exec>

- 命令: cd ~/.qclaw/workspace/store-monitor/ops-logger && bash start.sh
- 工作目录: ~/.qclaw/workspace/store-monitor/ops-logger
- 描述: 启动服务+Chrome

</skill_exec>

## setup.sh 自动完成的事

1. 装Python + venv + flask/requests/playwright
2. server.py开机自启(LaunchAgent)
3. 桌面快捷方式「启动小q」
4. 启动server.py(:5500)
5. 启动Chrome(debug端口 + 自动加载悟空+小q两个扩展)

## 安装完怎么说

```
装好了！Chrome已经打开了。

两步就能用：
1. 点Chrome右上角「悟空」图标，登录食亨
2. 点「小q助手」图标，输入你的名字

搞定跟我说，我帮你跑第一次巡检。
```

## 运营说"好了"/"登录了"

触发 store-patrol skill 跑第一次全量巡检。

## 红线

1. **运营不需要打开终端。** 所有命令你来跑。
2. **不说专业术语。** 不说git/pip/python，说"准备环境"/"更新"。
3. **缺什么装什么，逐个修，不一次性报一堆错。**
