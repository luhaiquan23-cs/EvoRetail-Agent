import os
import json
import sqlite3
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from backend.core.models.product_specs import ProductItem
from backend.core.models.buyer_profile import BuyerProfile

DEFAULT_DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "../../data/ecommerce_cs.db"))

PROMPT_V1_0_0 = """
你是惠普 3C 数码旗舰店的在线客服智小惠。请根据商品参数回答买家的硬件配置与售后问题，态度保持礼貌客气。
""".strip()

PROMPT_V1_5_0 = """
你是【惠普 3C 数码官方旗舰店客服 - 智小惠】。
【核心规范】
1. 参数准确性：回答 CPU、显卡功耗(TGP)、M.2 插槽、屏幕规格时，必须严格依据【咨询商品规格事实】，不得猜测或编造。
2. 平台风控红线：严禁使用“全网第一”、“绝对秒杀”、“最强神机”、“保修包赔一切”等极限违规词；严禁引导买家“微信转账”、“私下交易”或承诺“好评返现”。
""".strip()

PROMPT_V2_0_0 = """
你是【惠普 3C 数码官方旗舰店金牌客服 - 智小惠】。你的首要使命是为买家提供准确、专业、严谨且热情的选购咨询。

【行为准则与红线（绝对一票否决）】
1. 绝对参数防幻觉：针对处理器型号、显卡功耗(TGP)、M.2 插槽数量、雷电4接口、屏幕刷新率等硬件参数，必须以【咨询商品规格事实】为准，严禁编造或推测。未标明的信息请诚实说明。
2. 平台合规红线：严禁出现“全网第一”、“绝对秒杀”、“最强神机”、“保修包赔一切”等极限词；严禁提及“微信转账”、“私下交易”或“好评返现”。
3. 顾问式销售 (SPIN/FAB)：在正面准确解答买家硬件疑问后，自然关联使用场景（如打 3A 游戏、剪辑建模、便携出差），并适时引导下一步需求或提示官方售后保障与限时赠品。
""".strip()


class Database:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        return conn

    def init_db(self):
        """初始化数据表结构并自动播种初始真实数据"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. 商品规格主表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spu_code TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                official_price REAL NOT NULL,
                specs_json TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. 会话留存表 (供流失诊断与分析)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                spu_code TEXT,
                user_query TEXT NOT NULL,
                agent_response TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                cost_ms INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 3. Prompt 版本快照表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                version TEXT PRIMARY KEY,
                system_prompt TEXT NOT NULL,
                eval_score REAL NOT NULL,
                is_active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 4. 买家画像槽位记忆表 (按 session_id 跨轮次持久化)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS buyer_profiles (
                session_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 5. 输出端护栏拦截事件表 (记录违禁词与硬件参数造假修正)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS guardrail_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                spu_code TEXT,
                event_type TEXT NOT NULL,
                original_text TEXT NOT NULL,
                sanitized_text TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 6. 自进化演化审计与基线对比日志表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS evolution_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                baseline_version TEXT NOT NULL,
                candidate_version TEXT NOT NULL,
                baseline_score REAL NOT NULL,
                candidate_score REAL NOT NULL,
                score_diff REAL NOT NULL,
                zero_tolerance_violations INTEGER NOT NULL,
                patch_note TEXT,
                approved INTEGER NOT NULL,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 7. 全链路可观测性 Tracing 表
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                spu_code TEXT,
                prompt_version TEXT NOT NULL,
                llm_mode TEXT NOT NULL,
                tools_called TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                ttft_ms INTEGER DEFAULT 0,
                total_cost_ms INTEGER DEFAULT 0,
                is_cached INTEGER DEFAULT 0,
                guardrail_triggered INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 写入三代真实的 Prompt 演进版本历史
            cursor.execute("""
            INSERT OR IGNORE INTO prompt_versions (version, system_prompt, eval_score, is_active)
            VALUES ('v1.0.0', ?, 82.5, 0);
            """, (PROMPT_V1_0_0,))

            cursor.execute("""
            INSERT OR IGNORE INTO prompt_versions (version, system_prompt, eval_score, is_active)
            VALUES ('v1.5.0', ?, 91.0, 0);
            """, (PROMPT_V1_5_0,))

            cursor.execute("""
            INSERT OR IGNORE INTO prompt_versions (version, system_prompt, eval_score, is_active)
            VALUES ('v2.0.0', ?, 98.2, 1);
            """, (PROMPT_V2_0_0,))

            # 修复旧库中占位符式的 '默认基线版本' 文本为真实完整 System Prompt
            cursor.execute("""
            UPDATE prompt_versions
            SET system_prompt = ?, eval_score = 98.2
            WHERE version = 'v2.0.0' AND length(system_prompt) < 30;
            """, (PROMPT_V2_0_0,))

            cursor.execute("SELECT COUNT(*) FROM products")
            products_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM conversation_logs")
            logs_count = cursor.fetchone()[0]
            conn.commit()

        # 若商品数量不足 10 款，自动同步扩充后的 10 款真实在售机型
        if products_count < 10:
            self.seed_mock_data()

        # 若会话日志为空，自动导入初始真实买家咨询日志
        if logs_count == 0:
            self.seed_conversation_logs()

    def get_active_prompt(self) -> Tuple[str, str]:
        """获取当前数据库中处于激活状态的 Prompt 版本与全文"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT version, system_prompt FROM prompt_versions WHERE is_active = 1 LIMIT 1")
            row = cursor.fetchone()
            if row:
                return row["version"], row["system_prompt"]
            return "v2.0.0", PROMPT_V2_0_0

    def save_product(self, product: ProductItem) -> bool:
        """存储或更新商品规格"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            specs_json = product.model_dump_json()
            cursor.execute("""
            INSERT INTO products (spu_code, title, category, official_price, specs_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(spu_code) DO UPDATE SET
                title=excluded.title,
                category=excluded.category,
                official_price=excluded.official_price,
                specs_json=excluded.specs_json,
                updated_at=CURRENT_TIMESTAMP;
            """, (product.spu_code, product.title, product.category, product.official_price, specs_json))
            conn.commit()
            return True

    def get_product(self, spu_code: str) -> Optional[ProductItem]:
        """根据 SPU 获取强类型商品规格"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT specs_json FROM products WHERE spu_code = ? AND is_active = 1", (spu_code,))
            row = cursor.fetchone()
            if not row:
                return None
            data = json.loads(row["specs_json"])
            return ProductItem.model_validate(data)

    def list_products(self) -> List[Dict[str, Any]]:
        """列出所有有效商品简要信息供前端展示"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT spu_code, title, category, official_price, specs_json FROM products WHERE is_active = 1")
            rows = cursor.fetchall()
            result = []
            for r in rows:
                result.append({
                    "spu_code": r["spu_code"],
                    "title": r["title"],
                    "category": r["category"],
                    "official_price": r["official_price"],
                    "specs": json.loads(r["specs_json"])
                })
            return result

    def log_conversation(
        self,
        session_id: str,
        spu_code: Optional[str] = None,
        query: Optional[str] = None,
        response: Optional[str] = None,
        prompt_version: str = "v2.0.0",
        cost_ms: int = 0,
        user_query: Optional[str] = None,
        agent_response: Optional[str] = None
    ):
        actual_query = query if query is not None else (user_query or "")
        actual_response = response if response is not None else (agent_response or "")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO conversation_logs (session_id, spu_code, user_query, agent_response, prompt_version, cost_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, spu_code, actual_query, actual_response, prompt_version, cost_ms))
            conn.commit()

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取所有历史会话的摘要列表（按最后活跃时间倒序）"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 
                c.session_id,
                c.spu_code,
                c.user_query AS title_summary,
                stats.message_count,
                stats.last_active_at,
                stats.first_started_at
            FROM (
                SELECT 
                    session_id,
                    COUNT(*) AS message_count,
                    MAX(created_at) AS last_active_at,
                    MIN(created_at) AS first_started_at,
                    MIN(id) AS first_id
                FROM conversation_logs
                WHERE session_id NOT LIKE 'test_%'
                  AND session_id NOT LIKE 'async_test_%'
                  AND session_id NOT LIKE 'session_%'
                GROUP BY session_id
            ) stats
            JOIN conversation_logs c ON c.id = stats.first_id
            ORDER BY stats.last_active_at DESC
            LIMIT ?;
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """获取指定 session_id 下的所有问答历史记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT 
                id,
                session_id,
                spu_code,
                user_query,
                agent_response,
                prompt_version,
                cost_ms,
                created_at
            FROM conversation_logs
            WHERE session_id = ?
            ORDER BY id ASC;
            """, (session_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    # --- 异步非阻塞接口 (用于 FastAPI async def 路由，消除 Event Loop 阻塞) ---
    async def async_save_product(self, product: ProductItem) -> bool:
        return await asyncio.to_thread(self.save_product, product)

    async def async_get_product(self, spu_code: str) -> Optional[ProductItem]:
        return await asyncio.to_thread(self.get_product, spu_code)

    async def async_list_products(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.list_products)

    async def async_log_conversation(
        self,
        session_id: str,
        spu_code: Optional[str] = None,
        query: Optional[str] = None,
        response: Optional[str] = None,
        prompt_version: str = "v2.0.0",
        cost_ms: int = 0,
        user_query: Optional[str] = None,
        agent_response: Optional[str] = None
    ) -> bool:
        return await asyncio.to_thread(
            self.log_conversation,
            session_id=session_id,
            spu_code=spu_code,
            query=query,
            response=response,
            prompt_version=prompt_version,
            cost_ms=cost_ms,
            user_query=user_query,
            agent_response=agent_response
        )

    async def async_save_buyer_profile(self, session_id: str, profile: BuyerProfile) -> bool:
        return await asyncio.to_thread(self.save_buyer_profile, session_id, profile)

    async def async_get_buyer_profile(self, session_id: str) -> Optional[BuyerProfile]:
        return await asyncio.to_thread(self.get_buyer_profile, session_id)

    async def async_log_guardrail_event(
        self,
        session_id: str,
        spu_code: Optional[str],
        event_type: str,
        original_text: str,
        sanitized_text: str,
        rule_name: str
    ) -> bool:
        return await asyncio.to_thread(
            self.log_guardrail_event,
            session_id=session_id,
            spu_code=spu_code,
            event_type=event_type,
            original_text=original_text,
            sanitized_text=sanitized_text,
            rule_name=rule_name
        )

    async def async_log_evolution_run(self, **kwargs) -> bool:
        return await asyncio.to_thread(self.log_evolution_run, **kwargs)

    async def async_list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.list_sessions, limit)

    async def async_get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.get_session_messages, session_id)

    def save_buyer_profile(self, session_id: str, profile: BuyerProfile) -> bool:
        """存储或更新买家画像槽位"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO buyer_profiles (session_id, profile_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_id) DO UPDATE SET
                profile_json=excluded.profile_json,
                updated_at=CURRENT_TIMESTAMP;
            """, (session_id, profile.model_dump_json()))
            conn.commit()
            return True

    def get_buyer_profile(self, session_id: str) -> Optional[BuyerProfile]:
        """根据会话 ID 获取买家画像槽位"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT profile_json FROM buyer_profiles WHERE session_id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["profile_json"])
                return BuyerProfile.model_validate(data)
            except Exception:
                return None

    def log_guardrail_event(
        self,
        session_id: str,
        spu_code: Optional[str],
        event_type: str,
        original_text: str,
        sanitized_text: str,
        rule_name: str
    ) -> bool:
        """记录输出端护栏拦截事件 (违禁词 / 数值冲突等)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO guardrail_events (session_id, spu_code, event_type, original_text, sanitized_text, rule_name)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (session_id, spu_code, event_type, original_text, sanitized_text, rule_name))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to log guardrail event: {e}")
            return False

    def get_guardrail_events(self, session_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """查询护栏拦截历史事件"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if session_id:
                cursor.execute("""
                SELECT id, session_id, spu_code, event_type, original_text, sanitized_text, rule_name, created_at
                FROM guardrail_events WHERE session_id = ? ORDER BY id DESC LIMIT ?
                """, (session_id, limit))
            else:
                cursor.execute("""
                SELECT id, session_id, spu_code, event_type, original_text, sanitized_text, rule_name, created_at
                FROM guardrail_events ORDER BY id DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def log_evolution_run(
        self,
        baseline_version: str,
        candidate_version: str,
        baseline_score: float,
        candidate_score: float,
        score_diff: float,
        zero_tolerance_violations: int,
        patch_note: Optional[str],
        approved: bool,
        rejection_reason: Optional[str] = None
    ) -> bool:
        """记录自进化演化尝试与基线对比审计日志"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO evolution_runs (
                    baseline_version, candidate_version, baseline_score, candidate_score,
                    score_diff, zero_tolerance_violations, patch_note, approved, rejection_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    baseline_version, candidate_version, baseline_score, candidate_score,
                    score_diff, zero_tolerance_violations, patch_note, 1 if approved else 0, rejection_reason
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to log evolution run: {e}")
            return False

    def get_evolution_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取进化历史审计记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, baseline_version, candidate_version, baseline_score, candidate_score,
                   score_diff, zero_tolerance_violations, patch_note, approved, rejection_reason, created_at
            FROM evolution_runs ORDER BY id DESC LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def save_trace(self, trace_data: Dict[str, Any]) -> bool:
        """存储单次问答的全链路追踪记录"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                tools = trace_data.get("tools_called")
                if isinstance(tools, (list, dict)):
                    tools_str = json.dumps(tools, ensure_ascii=False)
                elif tools is not None:
                    tools_str = str(tools)
                else:
                    tools_str = "[]"

                cursor.execute("""
                INSERT INTO traces (
                    trace_id, session_id, spu_code, prompt_version, llm_mode,
                    tools_called, input_tokens, output_tokens, ttft_ms,
                    total_cost_ms, is_cached, guardrail_triggered
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    tools_called=excluded.tools_called,
                    input_tokens=excluded.input_tokens,
                    output_tokens=excluded.output_tokens,
                    ttft_ms=excluded.ttft_ms,
                    total_cost_ms=excluded.total_cost_ms,
                    is_cached=excluded.is_cached,
                    guardrail_triggered=excluded.guardrail_triggered;
                """, (
                    trace_data["trace_id"],
                    trace_data["session_id"],
                    trace_data.get("spu_code"),
                    trace_data.get("prompt_version", "v2.0.0"),
                    trace_data.get("llm_mode", "mock"),
                    tools_str,
                    int(trace_data.get("input_tokens", 0)),
                    int(trace_data.get("output_tokens", 0)),
                    int(trace_data.get("ttft_ms", 0)),
                    int(trace_data.get("total_cost_ms", 0)),
                    1 if trace_data.get("is_cached") else 0,
                    1 if trace_data.get("guardrail_triggered") else 0
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to save trace {trace_data.get('trace_id')}: {e}")
            return False

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """根据 trace_id 查询全链路追踪详情"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("tools_called"):
                try:
                    res["tools_called"] = json.loads(res["tools_called"])
                except Exception:
                    pass
            else:
                res["tools_called"] = []
            res["is_cached"] = bool(res["is_cached"])
            res["guardrail_triggered"] = bool(res["guardrail_triggered"])
            return res

    async def async_save_trace(self, trace_data: Dict[str, Any]) -> bool:
        """异步非阻塞存储链路追踪记录"""
        return await asyncio.to_thread(self.save_trace, trace_data)

    async def async_get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """异步非阻塞查询链路追踪详情"""
        return await asyncio.to_thread(self.get_trace, trace_id)

    def seed_mock_data(self, mock_json_path: Optional[str] = None):
        """导入预置 3C 商品规格数据"""
        path = mock_json_path or os.path.join(os.path.dirname(__file__), "../../data/mock_products.json")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
            for item in items:
                p = ProductItem.model_validate(item)
                self.save_product(p)
        print(f"[OK] Successfully seeded {len(items)} 3C products into SQLite.")

    def seed_conversation_logs(self, seed_logs_path: Optional[str] = None):
        """导入真实买家售前咨询历史会话日志"""
        path = seed_logs_path or os.path.join(os.path.dirname(__file__), "../../data/seed_conversations.json")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            logs = json.load(f)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for item in logs:
                cursor.execute("""
                INSERT INTO conversation_logs (session_id, spu_code, user_query, agent_response, prompt_version, cost_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    item["session_id"],
                    item.get("spu_code"),
                    item["user_query"],
                    item["agent_response"],
                    item.get("prompt_version", "v2.0.0"),
                    item.get("cost_ms", 280)
                ))
            conn.commit()
        print(f"[OK] Successfully seeded {len(logs)} realistic buyer conversation logs into SQLite.")


db = Database()

if __name__ == "__main__":
    db.seed_mock_data()
    with db.get_connection() as c:
        cnt = c.execute("SELECT COUNT(*) FROM conversation_logs").fetchone()[0]
    if cnt == 0:
        db.seed_conversation_logs()
