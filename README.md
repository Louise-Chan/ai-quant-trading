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
