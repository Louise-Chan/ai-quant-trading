# AI量化交易平台

基于 Electron + FastAPI 的加密货币量化交易桌面应用。

## 快速启动

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
# 复制 .env.example 为 .env（可选，默认 SQLite）
python main.py
# 或: uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

若修改端口，需同步更新 `renderer/js/config.js` 中的 `API_BASE`。

### 2. 前端 (Electron)

```bash
npm install
npm start
```

### 3. 数据库

**默认 SQLite**：无需配置，首次启动自动创建 `backend/ai_quant.db`。

**使用 MySQL**：
1. 复制 `backend/.env.example` 为 `backend/.env`
2. 设置 `USE_SQLITE=false` 并配置 MySQL 连接
3. 执行初始化：`cd backend && python ../scripts/init_mysql.py`

## 运行脚本（双击即可）

| 脚本 | 说明 |
|------|------|
| **打开应用.vbs** | 双击直接打开 Electron 桌面应用（无黑窗口） |
| **start-backend.bat** | 启动后端 (端口 8080) |
| stop-backend.bat | 停止后端 |
| start-frontend.bat | 启动 Electron 客户端 |
| stop-frontend.bat | 停止客户端 |
| run.bat | 菜单式启动/停止 |

**使用顺序**：先启动后端 → 再双击「打开应用.vbs」或运行 start-frontend.bat

> 注意：后端默认端口为 **8081**（README 中若写 8080 请以实际 start-backend.bat 为准）

## 常见问题（拉取后首次运行）

### 注册/登录报错

| 现象 | 可能原因 | 解决方式 |
|------|----------|----------|
| `Unexpected token 'I', 'Internal S'... is not valid JSON` | 后端返回了 HTML 错误页（500） | 1. 确保先运行 **start-backend.bat** 启动后端<br>2. 查看后端控制台是否有 Python 报错<br>3. 执行 `pip install -r backend/requirements.txt` 确保依赖完整 |
| `登录账户或密码错误` | ① 未先注册 ② 密码错误 ③ 后端未正常启动 | 1. 先完成注册<br>2. 确认后端已启动且无报错<br>3. 检查 `backend/ai_quant.db` 是否存在（SQLite 首次启动会自动创建） |
| `连接失败，请确保后端已启动` | 后端未运行或端口不对 | 1. 运行 start-backend.bat<br>2. 确认端口 8081 未被占用 |

### 依赖问题（bcrypt / passlib）

若后端启动时报 `AttributeError: module 'bcrypt' has no attribute '__about__'`，项目已在 `backend/core/security.py` 中做了兼容。若仍有问题，可尝试：

```bash
pip install "passlib[bcrypt]==1.7.4" "bcrypt>=4.0.0,<5"
```

### 数据库

- **SQLite（默认）**：首次运行 `python backend/main.py` 会在 `backend/` 目录下自动创建 `ai_quant.db`
- **工作目录**：必须从 `backend` 目录启动，或使用 start-backend.bat（会自动 cd 到 backend）

## 界面说明

- **单窗口**：欢迎、登录、主界面均在同一窗口内切换，不新增窗口
- **Alpaca 风格**：浅色主题、卡片式布局、左侧图标导航

## 项目结构

```
├── backend/          # FastAPI 后端
│   ├── api/          # 路由
│   ├── core/         # 核心模块
│   ├── models/       # 数据模型
│   ├── services/     # 业务服务
│   └── utils/        # 工具（gate_client 按 mode 切换 host）
├── main/             # Electron 主进程
├── renderer/         # 渲染进程（页面、JS、CSS）
├── database/         # init.sql 建表脚本
└── package.json
```

## 功能说明

- **交易模式**：实盘 (api.gateio.ws) / 模拟 (api-testnet.gateapi.io)
- **策略引擎、交易执行**：当前为 mock/占位，可后续实现
- **Redis**：可选，当前跳过
