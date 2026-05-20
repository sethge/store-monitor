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
curl -s --max-time 2 http://127.0.0.1:5500/api/setup/status 2>/dev/null
```

返回JSON checklist：
```json
{
  "chrome_debug": true/false,    // Chrome debug端口是否可用
  "developer_mode": true/false,  // 开发者模式（headless需要）
  "goku_login": true/false,      // Goku插件是否已登录
  "operator_set": true/false,    // 运营名是否已设置
  "operator": "宋彬",            // 当前运营名
  "ready": true/false            // 整体就绪
}
```

## 冷启动Checklist（逐步确认）

如果server没跑（curl失败），先装环境：

### Step 0: 安装环境

跟运营说"帮你准备一下环境，1-2分钟..."

<skill_exec>

- 命令: git clone https://gitee.com/sethgeshiheng/store-monitor.git -b feature/watch-mode ~/.qclaw/workspace/store-monitor && cd ~/.qclaw/workspace/store-monitor/ops-logger && bash install.sh
- 工作目录: ~
- 描述: 首次安装(下载+依赖+启动server)

</skill_exec>

装完再查 `/api/setup/status`，然后逐步走下面的checklist。

### Step 1: Chrome debug模式

**检查**: `chrome_debug == true`

如果false，跟运营说：
```
需要用调试模式打开Chrome。
我帮你打开，你等一下。
```

然后执行：
```bash
cd ~/.qclaw/workspace/store-monitor/ops-logger && bash start.sh
```

start.sh会启动Chrome（带debug端口）+ server。

### Step 2: 开发者模式 + 装插件

**检查**: `developer_mode == true`

如果false，跟运营说：
```
Chrome里需要打开开发者模式，一次就好：
1. Chrome地址栏输入 chrome://extensions
2. 右上角打开「开发者模式」开关
3. 回来跟我说一声
```

运营说好了之后，再查一次。如果Goku没装，引导装：
```
现在装两个插件：
1. 在 chrome://extensions 页面点「加载已解压的扩展程序」
2. 第一个选: ~/.qclaw/workspace/store-monitor/goku
3. 第二个选: ~/.qclaw/workspace/store-monitor/ops-logger/extension
装好跟我说。
```

### Step 3: 登录食亨

**检查**: `goku_login == true`

如果false，跟运营说：
```
点Chrome右上角「悟空」图标，登录食亨账号。
登录好了跟我说。
```

### Step 4: 输入名字

**检查**: `operator_set == true`

如果false，跟运营说：
```
最后一步：点Chrome右上角「小q助手」图标，输入你的名字。
```

### 全部完成

所有check都通过后：
```
都好了！帮你跑一遍巡检看看效果。
```
然后触发 store-patrol skill。

## 更新

<skill_exec>

- 命令: cd ~/.qclaw/workspace/store-monitor && git pull origin feature/watch-mode && cd ops-logger && bash install.sh
- 工作目录: ~/.qclaw/workspace/store-monitor
- 描述: 更新+重启

</skill_exec>

## 每天开工

运营说"开工"或任意一句话时，你先检测 `/api/setup/status`：
- `ready == true` → 不提setup，直接聊
- server没跑 → 静默执行start.sh → "帮你启动了"
- Chrome没开 → 执行start.sh → "Chrome帮你打开了"
- 登录过期 → "悟空登录过期了，点Chrome右上角悟空图标重新登录一下"

## 红线

1. **运营不碰终端。** 所有命令你跑。
2. **不说专业术语。** git/pip/python/debug这些词不要出现在跟运营的对话里。
3. **静默修复。** 能自己修的不要问运营。
4. **每步确认。** 需要运营操作的步骤，等运营说"好了"再继续下一步。
