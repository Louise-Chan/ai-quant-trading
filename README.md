# SilentSigma 套利者

基于 **Electron + FastAPI + Gate.io** 的加密货币量化交易桌面应用。集成多因子策略引擎、DeepSeek AI 审核 / 选币 / 因子挖掘、组合回测、Brinson 归因 + 风险模型，面向散户提供「半自动」量化交易方案：策略引擎产出信号 → AI 审核 → 用户人工通过 → 执行下单。

> 完整开发文档见根目录 `开发需求文档.md`（含架构、API 规范、策略引擎、因子工程、归因模型等全部章节）。

---

## 安装方式

### A. 普通用户：一键安装包（推荐）

从 `dist-installer-gui/` 目录下载 **`SilentSigma-Installer-GUI-<version>.exe`**，双击后会打开 Electron 图形安装器（现代 GUI 界面，类似常见热门软件安装程序）。`SilentSigma-Installer-GUI` 内部会静默调用核心安装包完成安装：

1. 选择安装路径（支持自定义）；
2. 自动写入便携 Python 运行时与后端代码（无需自行安装 Python）；
3. 自动创建桌面 / 开始菜单快捷方式；
4. 启动后 Electron 主进程会自动拉起内置后端，等待 `/api/v1/health` 就绪后再显示主窗口；
5. 卸载时默认保留 `%APPDATA%\SilentSigma\data\` 下的数据库与配置（包含已注册账号、API Key 等）。

> GUI 安装器构建命令：`npm run build:gui-installer`。如只需传统 NSIS 向导版，仍可使用 `npm run build:installer`。

### B. 开发者：一键启动（源码态）

双击根目录 **`run.bat`**：

1. 后台最小化启动 `SilentSigma Backend` 窗口（运行 `python main.py`，监听 `:8081`）
2. 自动轮询 `/api/v1/health` 直至后端就绪（最多 60 秒）
3. 自动启动 `SilentSigma Frontend` 窗口（运行 `npm start`，弹出 Electron 主窗口）
4. 启动器窗口 3 秒后自动退出，**关闭它不会停止已启动的服务**

如需停止服务：分别运行 `scripts\stop-backend.bat` 与 `scripts\stop-frontend.bat`。

---

## 手动启动（开发模式）

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
# 主要依赖：fastapi, uvicorn, sqlalchemy, gate-api, numpy, pandas, scikit-learn
# 可选：复制 .env.example 为 .env，默认使用 SQLite
python main.py
# 或 uvicorn main:app --reload --host 0.0.0.0 --port 8081
```

后端端口默认 **8081**（见 `backend/config.py::PORT`）。修改端口后需同步更新 `renderer/js/config.js` 的 `API_BASE`。

### 2. 前端 (Electron)

```bash
npm install
npm start
```

### 3. 数据库

| 模式 | 配置 | 适用场景 |
|------|------|----------|
| **SQLite（默认）** | 无需配置，首次启动自动创建 `backend/ai_quant.db` | 个人 / 开发 |
| **MySQL** | 复制 `backend/.env.example` 为 `backend/.env`，设置 `USE_SQLITE=false` 并填入 MySQL 连接 | 多机 / 生产 |

切换到 MySQL 时执行：`cd backend && python ../scripts/init_mysql.py`。

---

## 启动脚本一览

| 脚本 | 说明 |
|------|------|
| **`run.bat`** | **一键启动器**：自动启动后端 + 等待就绪 + 启动前端 |
| **`打开应用.vbs`** | 双击直接打开 Electron 桌面应用（无黑色窗口体验，需后端已在运行） |
| `scripts/start-backend.bat` | 单独启动后端（自动 kill 占用 :8081 的旧进程） |
| `scripts/stop-backend.bat`  | 停止后端 |
| `scripts/start-frontend.bat`| 单独启动 Electron |
| `scripts/stop-frontend.bat` | 停止 Electron |
| `scripts/diagnose.bat`      | 后端环境/依赖诊断 |

---

## 核心功能模块

| 模块 | 说明 | 主要 API / 文件 |
|------|------|------|
| **登录注册** | 用户注册、JWT 登录 | `/api/v1/auth/*` |
| **交易所绑定** | Gate.io 实盘 + 模拟双模式 | `/api/v1/broker/*`，`utils/gate_client.py` 按 mode 切换 host |
| **仪表盘 - 选币** | 规则引擎 + DeepSeek Agent 一键选币 | `/api/v1/dashboard/smart-select`、`/agent-select`、`/watchlist/batch` |
| **仪表盘 - K 线** | lightweight-charts，多周期，订单叠加 | `renderer/pages/dashboard/kline-chart.js`、`kline-order-overlays.js` |
| **仪表盘 - 订单审核** | 自选列表逐标的跑策略引擎 → DeepSeek 审核 → 人工通过 → Gate 下单 | `/api/v1/order-audit/*` |
| **账户总览** | 投资组合（净值曲线、Alpha/Beta、Sharpe、回撤）、资产、交易流水、持仓 | `/api/v1/portfolio/*`、`/assets/*`、`/trading/*` |
| **策略中心** | 内置策略 + 用户自定义策略，订阅与运行状态 | `/api/v1/strategies/*`、`/user-strategies/*` |
| **回测页** | 多标的组合回测、净值/基准、可镜像到账户概览 | `renderer/pages/strategy/backtest.html`，`/api/v1/backtest-runs/*` |
| **风险设置** | 按 mode 独立的风控参数（最大仓位、止损、Kelly 上限） | `/api/v1/risk/settings` |
| **个人中心** | DeepSeek API Key 绑定、个人信息、昵称头像 | `/api/v1/users/*` |

---

## 量化引擎与 AI 工程（已落地）

### 策略引擎 (`backend/services/strategy_engine/`)

| 模块 | 能力 |
|------|------|
| `factors.py` | 基础技术因子：动量、反转、波动率、成交量异常、RSI、布林位置、MACD 柱、均线乖离 |
| `alpha158.py` | Qlib 风格 Alpha158 量价特征生成（ML 模型特征源） |
| `factor_evaluation.py` | 单因子 IC / Rank IC / ICIR / 分组收益 |
| `factor_mining_evaluation.py` | DeepSeek 生成新因子的批量评估与筛选 |
| `dynamic_factors_executor.py` | 动态因子表达式编译执行（AST 白名单沙箱） |
| `weights.py` | ICIR softmax 归一化加权合成综合得分 |
| `ml_model.py` | scikit-learn 逻辑回归预测 `p_up`（涨跌方向概率） |
| `position_risk.py` | ATR 止损止盈 / Kelly 仓位 / 波动率定标 / 账户硬约束 |
| `backtest.py` | 单标的滚动回测（夏普近似、最大回撤、胜率、盈亏比） |
| `portfolio_report.py` | 多标的组合回测 + 净值曲线 + Brinson 归因 + 风险摘要 |
| `runner.py` | 信号生成调度入口 |

### DeepSeek 集成 (`backend/services/deepseek_*`)

| 服务 | 用途 |
|------|------|
| `deepseek_service.py` | DeepSeek 通用 chat / chat-json 客户端 |
| `deepseek_coin_agent.py` | 从规则候选池中精选 Top N 标的（Agent 选币） |
| `deepseek_factor_agent.py` | 生成新因子表达式 + 逻辑解释 |
| `deepseek_factor_mining_agent.py` | 解读因子评估结果，给出 keep / improve / drop |
| `deepseek_backtest_report.py` | 回测报告异常点诊断与风格漂移提示 |
| `deepseek_risk_presets.py` | 根据用户偏好画像生成风控预设 |

### 归因与风险 (`backend/services/analytics/`)

| 文件 | 功能 |
|------|------|
| `brinson.py` | Brinson-Fachler 多期归因（配置/选股/交互效应，支持行业聚合） |
| `risk_model.py` | 简化 Barra 风险模型（B 暴露 + F 协方差 + D 特异） |
| `panel.py` | 三矩阵（组合权重 / 基准权重 / 资产收益）对齐工具 |
| `config.py` | 基准定义（等权 / 流动性前 N / 固定比例）、行业映射 |

### 后台 Worker

| Worker | 周期 | 用途 |
|--------|------|------|
| `bracket_track_worker` | 2.5s | 追踪止损/止盈条件单触发 |
| `factor_library_refresh_worker` | 6h | 动态因子库刷新（DeepSeek 挖掘 + 评估 + 入库/失效） |
| `trust_copier_service` | 25s | 跟单/同步任务 |

---

## 订单审核 API（需登录）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/users/preferences` | 是否已绑定 DeepSeek Key |
| PUT | `/api/v1/users/preferences` | body: `{ "deepseek_api_key": "sk-..." }`（空字符串清除） |
| POST | `/api/v1/order-audit/generate` | body: `{ "symbol": "BTC_USDT", "signal": { ... }, "use_strategy_engine": true }` |
| GET | `/api/v1/order-audit/list` | 审核列表 |
| POST | `/api/v1/order-audit/{id}/approve` | 按审核内容下单 |
| POST | `/api/v1/order-audit/{id}/reject` | 拒绝 |

调试策略引擎原始输出：`GET /api/v1/strategy-engine/analyze?symbol=BTC_USDT&interval=1h`。

---

## 界面说明

- **单窗口架构**：欢迎页、登录、注册、主界面均在同一窗口内切换。
- **Alpaca 风格 UI**：浅色主题、卡片式布局、左侧图标导航；金币雨动画装饰欢迎/登录/注册三页。
- **订单审核（仪表盘）**：K 线区右侧为「订单审核」栏。绑定 **DeepSeek API Key** 后，点击 **「开始交易」**（需已在策略中心选择订阅）会自动对 **自选列表中的每个标的** 依次跑策略引擎并生成审核单；侧栏 **状态区** 显示 `审核中 当前/总数`（批量生成中）或 `审核中 已打开K线标的数/自选总数`（空闲时）；停止交易为 **「审核已停止」**。**停止交易**会先中止正在进行的批量审核再关闭交易。**通过/不通过**仍人工操作。列表新单在底部并自动滚动可见。
- **开始/停止交易**：净值卡片旁按钮切换——未运行时「开始交易」，运行中「停止交易」。
- **回测页**：策略中心二级页面。左侧选择因子/参数/区间，右侧实时绘制净值与基准曲线；底部「已保存的回测」可载入、镜像到账户概览（用回测净值替换账户面板的真实数据）、删除。

---

## 项目结构

```
ai-quant-trading/
├── run.bat                            # 一键启动器（推荐双击）
├── 打开应用.vbs                       # 静默启动 Electron（需后端已运行）
├── 开发需求文档.md                    # 完整开发文档
├── README.md                          # 本文件
├── package.json                       # Electron + npm 配置
├── scripts/                           # 启动/停止/初始化脚本
├── database/                          # init.sql 建表脚本（MySQL 用）
├── backend/                           # FastAPI 后端
│   ├── main.py                        # 应用入口（监听 :8081）
│   ├── config.py                      # 配置（端口/数据库/CORS）
│   ├── requirements.txt               # Python 依赖
│   ├── api/                           # REST 路由（auth, dashboard, market, portfolio,
│   │                                  #   trading, strategies, risk, order_audit,
│   │                                  #   strategy_engine_api, backtest_runs,
│   │                                  #   simulated_mirror, user_strategies, …）
│   ├── core/                          # database / security / schema_migrate / websocket
│   ├── models/                        # SQLAlchemy 数据模型
│   ├── services/                      # 业务服务
│   │   ├── strategy_engine/           # 策略引擎（因子/ML/回测/风险）
│   │   ├── analytics/                 # Brinson 归因 + 风险模型
│   │   ├── deepseek_*.py              # DeepSeek 各类 Agent
│   │   ├── gate_account_service.py    # Gate 账户/订单/持仓
│   │   ├── order_audit_service.py     # 订单审核
│   │   ├── simulated_mirror_service.py# 镜像账户
│   │   ├── bracket_track_worker.py    # 条件单追踪
│   │   └── factor_library_refresh_worker.py
│   └── utils/gate_client.py           # 按 mode 切换 host 的 Gate 客户端
├── main/                              # Electron 主进程
│   ├── main.js / preload.js / window-manager.js / ipc-handlers.js
└── renderer/                          # 渲染进程
    ├── index.html / auth.html / app.html
    ├── pages/dashboard/               # 仪表盘（选币、K 线、订单审核、快捷下单、交易记录）
    ├── pages/account/                 # 账户总览
    ├── pages/strategy/                # 策略中心 + 回测
    ├── pages/profile/                 # 个人中心
    ├── js/                            # api.js / auth.js / app-unified.js / coin-rain.js
    └── css/
```

---

## 常见问题

### 注册 / 登录报错

| 现象 | 可能原因 | 解决 |
|------|----------|------|
| `Unexpected token 'I', 'Internal S'... is not valid JSON` | 后端返回了 HTML 错误页（500） | ① 先运行 `run.bat` 或 `start-backend.bat`；② 查看后端窗口 Python 报错；③ `pip install -r backend/requirements.txt` 补依赖 |
| `登录账户或密码错误` | 未注册 / 密码错 / 后端未启动 | 先注册；确认后端无报错；检查 `backend/ai_quant.db` 是否生成 |
| `连接失败，请确保后端已启动` | 后端未运行或端口不对 | 运行 `run.bat`；确认 :8081 未被占用 |

### 依赖问题（bcrypt / passlib）

若启动时报 `AttributeError: module 'bcrypt' has no attribute '__about__'`，已在 `backend/core/security.py` 做兼容；若仍异常：

```bash
pip install "passlib[bcrypt]==1.7.4" "bcrypt>=4.0.0,<5"
```

### 数据库

- **SQLite（默认）**：首次运行 `python backend/main.py` 在 `backend/` 目录自动创建 `ai_quant.db`。
- **工作目录**：必须从 `backend/` 启动（`run.bat` / `start-backend.bat` 已自动 cd）。
- **MySQL**：见上方「3. 数据库」一节。

### `run.bat` 报「不是内部命令」之类乱码错误

若双击 `run.bat` 出现中文乱码 + 命令解析失败，多半是脚本文件被改成了 UTF-8 编码后又混入了中文字符。当前版 `run.bat` 全部使用 ASCII 文本，避免任何中文导致的 GBK/UTF-8 解析冲突；若你修改后再次出现，请保持纯 ASCII 注释或将文件保存为 GBK 编码。

---

## 数据流（简要）

```
 Electron 渲染进程 ──HTTP/WS──> FastAPI 后端 ──> SQLite/MySQL
                                  │
                                  ├──> Gate.io API（实盘 api.gateio.ws / 模拟 api-testnet.gateapi.io）
                                  ├──> DeepSeek API（订单审核 / 选币 / 因子挖掘）
                                  └──> 策略引擎 + 后台 Worker
```

---

## 打包成 Windows 安装程序（含 Electron GUI 安装器）

把整个项目（含 Python 后端 + Electron 前端）打包成可分发的安装程序。现在支持两种产物：

- `dist-installer-gui\SilentSigma-Installer-GUI-<version>.exe`：**Electron 图形安装器（推荐）**
- `dist\SilentSigma-Setup-<version>.exe`：传统 NSIS 向导安装器

两者都内嵌便携 Python 运行时，最终用户**无需自行安装 Python**。

### 1. 打包前置条件

- Windows 10/11 x64
- Node.js 18+（自带 npm/npx）
- PowerShell 5+
- 网络（首次会下载 Python 嵌入式发行版与 PyPI 依赖）

### 2. 一键打包

在项目根目录执行：

```powershell
npm run build:gui-installer
```

脚本会依次完成：

1. **准备便携 Python**：下载 `python-3.11.9-embed-amd64.zip` 解压到 `python_runtime/`，启用 `site-packages`，引导 `pip`，按 `backend/requirements.txt` 安装依赖（含 numpy / pandas / scikit-learn 等编译好的 wheel）。
2. **安装 npm 依赖**：未装则执行 `npm install`。
3. **构建核心 NSIS 包**：先生成 `dist\SilentSigma-Setup-*.exe`；
4. **构建 Electron GUI 安装器**：把上一步核心包嵌入 `installer_gui/payload`，再生成 `dist-installer-gui\SilentSigma-Installer-GUI-*.exe`。

完成后在 `dist-installer-gui/` 看到 `SilentSigma-Installer-GUI-1.0.0.exe`（推荐分发给用户）。

### 3. 加速 / 二次打包

- 已经准备好 `python_runtime/` 时跳过这一步：
  ```powershell
  npm run build:gui-installer -- -SkipPython
  ```
- 强制重新构建便携 Python：
  ```powershell
  npm run build:gui-installer -- -ForcePython
  ```
- 单独准备/重做 Python：
  ```powershell
  npm run prepare:python
  ```

### 4. 安装包能做什么

- **自定义安装路径**（默认 `%LOCALAPPDATA%\Programs\SilentSigma`，安装向导可改）；
- **桌面 + 开始菜单快捷方式**（中文名 `SilentSigma`）；
- **不需要管理员权限**（每用户安装，`requestedExecutionLevel: asInvoker`）；
- **完整离线运行**：双击桌面图标即可，Electron 自动以子进程方式拉起 `resources\python_runtime\python.exe resources\backend\main.py`，等待 `/api/v1/health` 通过后才显示主窗口；
- **可写数据隔离**：SQLite 数据库与日志写到 `%APPDATA%\SilentSigma\data\`（由 `SILENTSIGMA_DATA_DIR` 环境变量注入，避免 Program Files 只读问题）。

### 5. 替换图标（可选）

放置一份 256x256 多尺寸 ICO 到 `build/icon.ico`，再在 `package.json` 的 `build.win` 里加一行：

```json
"icon": "build/icon.ico"
```

重新打包即可生效。未提供图标时使用 Electron 默认图标。

---

## 参考资源

- Gate.io API 文档：<https://www.gate.com/docs/developers/apiv4/zh_CN/>
- gate-api Python SDK：<https://github.com/gate/gateapi-python>
- DeepSeek API：<https://platform.deepseek.com/>
- lightweight-charts：<https://tradingview.github.io/lightweight-charts/>
- Electron：<https://www.electronjs.org/docs>
