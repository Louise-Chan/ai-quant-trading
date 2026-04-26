"""轻量列迁移：create_all 不会给已有表加列"""
from sqlalchemy import inspect, text

from core.database import engine


def ensure_portfolio_watchlist_columns() -> None:
    """portfolio_snapshots.account_scope、watchlist.quote_market 及自选去重唯一约束"""
    try:
        insp = inspect(engine)
        names = insp.get_table_names()
        if "portfolio_snapshots" in names:
            cols = {c["name"] for c in insp.get_columns("portfolio_snapshots")}
            with engine.begin() as conn:
                if "account_scope" not in cols:
                    conn.execute(
                        text(
                            "ALTER TABLE portfolio_snapshots ADD COLUMN account_scope VARCHAR(16) DEFAULT 'spot' NOT NULL"
                        )
                    )
                    conn.execute(text("UPDATE portfolio_snapshots SET account_scope = 'spot' WHERE account_scope IS NULL"))
        if "watchlist" in names:
            cols = {c["name"] for c in insp.get_columns("watchlist")}
            with engine.begin() as conn:
                if "quote_market" not in cols:
                    conn.execute(
                        text("ALTER TABLE watchlist ADD COLUMN quote_market VARCHAR(16) DEFAULT 'spot' NOT NULL")
                    )
                    conn.execute(text("UPDATE watchlist SET quote_market = 'spot' WHERE quote_market IS NULL"))
                # 去重 (user_id, symbol)，保留最小 id
                conn.execute(
                    text(
                        """
                        DELETE FROM watchlist WHERE id NOT IN (
                          SELECT MIN(id) FROM watchlist GROUP BY user_id, symbol, quote_market
                        )
                        """
                    )
                )
                # SQLite 无 IF NOT EXISTS INDEX：尝试创建，忽略已存在
                try:
                    conn.execute(
                        text(
                            "CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_user_symbol_market "
                            "ON watchlist (user_id, symbol, quote_market)"
                        )
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"[schema_migrate] portfolio/watchlist: {e}")


def ensure_bracket_track_extra_columns() -> None:
    try:
        insp = inspect(engine)
        names = insp.get_table_names()
        if "bracket_tracks" not in names:
            return
        cols = {c["name"] for c in insp.get_columns("bracket_tracks")}
        with engine.begin() as conn:
            if "bracket_limit_order_id" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE bracket_tracks ADD COLUMN bracket_limit_order_id VARCHAR(64)"
                    )
                )
            if "entry_fill_price" not in cols:
                conn.execute(
                    text("ALTER TABLE bracket_tracks ADD COLUMN entry_fill_price VARCHAR(32)")
                )
    except Exception as e:
        print(f"[schema_migrate] bracket_tracks: {e}")


def ensure_subscription_user_strategy_column() -> None:
    """subscriptions.user_strategy_id（用户保存策略订阅）"""
    try:
        insp = inspect(engine)
        names = insp.get_table_names()
        if "subscriptions" not in names:
            return
        cols = {c["name"] for c in insp.get_columns("subscriptions")}
        with engine.begin() as conn:
            if "user_strategy_id" not in cols:
                conn.execute(
                    text("ALTER TABLE subscriptions ADD COLUMN user_strategy_id INTEGER")
                )
    except Exception as e:
        print(f"[schema_migrate] subscriptions user_strategy_id: {e}")


def ensure_default_builtin_user_strategies() -> None:
    """
    老用户与新用户一致：每人一条「内置策略（默认）」，
    config.active_factors 为 rev_1 / vol_20 / vol_z（与 factors.DEFAULT_BUILTIN_FACTOR_IDS 一致）。
    """
    try:
        import json

        from core.database import SessionLocal
        from models.user import User
        from models.user_strategy import UserStrategy
        from services.strategy_engine.factors import DEFAULT_BUILTIN_FACTOR_IDS

        insp = inspect(engine)
        if "users" not in insp.get_table_names() or "user_strategies" not in insp.get_table_names():
            return

        default_name = "内置策略（默认）"
        default_desc = "默认因子：1期反转、20期波动、成交量Z（rev_1, vol_20, vol_z）"
        factor_list = list(DEFAULT_BUILTIN_FACTOR_IDS)
        base_cfg = {
            "symbols": "",
            "interval": "1h",
            "max_opens_per_day": 0,
            "avg_daily_mode": "trading",
            "active_factors": factor_list,
        }

        db = SessionLocal()
        try:
            users = db.query(User).all()
            for u in users:
                rows = (
                    db.query(UserStrategy)
                    .filter(
                        UserStrategy.user_id == u.id,
                        UserStrategy.status == "active",
                        UserStrategy.name == default_name,
                    )
                    .all()
                )
                if not rows:
                    r = UserStrategy(
                        user_id=u.id,
                        name=default_name,
                        description=default_desc,
                        status="active",
                        config_json=json.dumps(base_cfg, ensure_ascii=False),
                        weights_json=json.dumps({}, ensure_ascii=False),
                        backtest_summary_json=None,
                    )
                    db.add(r)
                else:
                    for r in rows:
                        cfg = {}
                        if r.config_json:
                            try:
                                cfg = json.loads(r.config_json)
                            except Exception:
                                cfg = {}
                        cfg["active_factors"] = factor_list
                        for k, v in base_cfg.items():
                            if k != "active_factors" and k not in cfg:
                                cfg[k] = v
                        r.config_json = json.dumps(cfg, ensure_ascii=False)
                        if not (r.description or "").strip():
                            r.description = default_desc
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[schema_migrate] default_builtin_user_strategies: {e}")
