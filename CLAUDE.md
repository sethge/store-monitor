# 食亨智慧运营

## 启动时

### 第一步：环境自检（静默，不跟运营说）

```bash
# 依赖检查（缺哪个装哪个，不要一次性报错）
python3 -c "import playwright" 2>/dev/null || pip3 install playwright && playwright install chromium
python3 -c "import lzstring" 2>/dev/null || pip3 install lzstring --break-system-packages 2>/dev/null || pip3 install lzstring
python3 -c "from google import genai" 2>/dev/null || pip3 install google-genai --break-system-packages 2>/dev/null || pip3 install google-genai

# Brain（知识库）
if [ ! -d "$HOME/wisdom-brain" ]; then
  git clone https://github.com/sethge/wisdom-brain.git "$HOME/wisdom-brain" 2>/dev/null
fi

# memory 目录
mkdir -p memory/interactions memory/pending_review
```

**Windows 用 `pip install` 和 `python` 替换。** 装依赖时不跟运营说话，装完再打招呼。如果某个依赖装不上，自己排查修复，实在不行才告诉运营"有个东西需要你帮忙"。

### 第二步：加载人格

1. 读 `agent-config/SOUL.md`（你是谁）
2. 读 `agent-config/BRAIN.md`（你的运营认知）— 先 `cd ~/wisdom-brain && git pull --quiet` 拉最新
3. 读 `agent-config/USER.md`（你面对谁）
4. 读 `agent-config/MEMORY.md`（你记住了什么）
5. 读 `agent-config/knowledge/rules.md`（你必须遵守的规则）

---

美团+饿了么外卖店铺自动巡检工具。通过悟空插件切换店铺，自动检查差评、活动到期、推广余额、重要通知。

## 快速开始

```bash
# 指定品牌（跑一次）
NO_PROXY=localhost python3 run_fast.py "品牌1" "品牌2"

# 全量巡检（插件下所有品牌）
NO_PROXY=localhost python3 run_all_fast.py

# 预警模式（只看通知，每10分钟一轮，到18:00结束）
NO_PROXY=localhost python3 run_fast.py --watch "品牌1" "品牌2"
```

## 环境要求
- Python 3 + Playwright (`pip3 install playwright && playwright install chromium`)
- Chrome调试模式 (`--remote-debugging-port=9222`)
- 悟空插件（goku文件夹）+ 食亨账号登录

## 环境问题处理原则

**运营遇到任何环境报错，不能让他自己研究，你直接帮他修。**

处理步骤：
1. 先跑对应skill的 setup.sh：`bash skills/store-diagnosis/setup.sh`
2. setup.sh 会自动检测并安装所有缺的依赖
3. 如果 setup.sh 也失败，给运营一行命令让他复制粘贴执行
4. 装完后自动重新执行刚才失败的操作

常见报错和对应修复：
- `Cannot find package 'sharp'` → `npm install -g sharp`
- `No module named 'xxx'` → `pip3 install xxx`
- `ffmpeg: command not found` → Mac: `brew install ffmpeg` / Linux: `sudo apt install ffmpeg`
- `command not found: brew` → `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`
- `command not found: node` → Mac: `brew install node` / Linux: `curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs`

总安装脚本：`bash install.sh`（装全部skill依赖）

## Skill
输入 `/盯店` 自动执行，支持三种模式：
- **巡检** — `/盯店` 或 `/盯店 品牌名`，跑一次全量检查
- **预警** — `/盯店 预警`，只看通知，每10分钟一轮，到18:00结束
- **诊断** — `/盯店 诊断 视频路径`，视频提帧→Agent读图提取JSON→deploy.py生成公网链接（GitHub Pages）→运营在网页填分析+下载Excel
