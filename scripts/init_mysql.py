"""MySQL 数据库初始化脚本 - 创建数据库并执行建表"""
import sys
import os

# 添加 backend 到路径并加载 .env
backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
sys.path.insert(0, backend_dir)
os.chdir(backend_dir)
env_file = os.path.join(backend_dir, '.env')
if os.path.exists(env_file):
    from dotenv import load_dotenv
    load_dotenv(env_file)

try:
    import pymysql
except ImportError:
    print("请先安装: pip install pymysql")
    sys.exit(1)

# 从环境变量或 .env 读取
host = os.getenv("MYSQL_HOST", "localhost")
port = int(os.getenv("MYSQL_PORT", "3306"))
user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "")
database = os.getenv("MYSQL_DATABASE", "ai_quant_trading")

if not password:
    print("请设置环境变量 MYSQL_PASSWORD，或在 .env 中配置")
    print("示例: set MYSQL_PASSWORD=your_password")
    sys.exit(1)

def main():
    # 1. 连接 MySQL（不指定数据库）
    conn = pymysql.connect(host=host, port=port, user=user, password=password, charset='utf8mb4')
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARSET utf8mb4")
            print(f"数据库 {database} 已就绪")
        conn.select_db(database)
        
        # 2. 执行 init.sql
        init_sql = os.path.join(os.path.dirname(__file__), '..', 'database', 'init.sql')
        if not os.path.exists(init_sql):
            print(f"未找到 {init_sql}")
            sys.exit(1)
        with open(init_sql, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        # 移除 USE 语句（已 select_db）
        sql_content = sql_content.replace(f"USE {database};", "").replace(f"USE `{database}`;", "").strip()
        with conn.cursor() as cur:
            for stmt in sql_content.split(';'):
                stmt = stmt.strip()
                if stmt and not stmt.startswith('--'):
                    try:
                        cur.execute(stmt + ';')
                    except pymysql.err.OperationalError as e:
                        if "1050" in str(e):  # Table already exists
                            print(f"  表已存在，跳过")
                        else:
                            raise
        conn.commit()
        print("建表完成")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
