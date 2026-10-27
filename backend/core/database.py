import os
import json
import sqlite3
from typing import Optional, List, Dict, Any, Tuple
from backend.core.models.product_specs import ProductItem

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
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
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

    def log_conversation(self, session_id: str, spu_code: Optional[str], query: str, response: str, prompt_version: str, cost_ms: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO conversation_logs (session_id, spu_code, user_query, agent_response, prompt_version, cost_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (session_id, spu_code, query, response, prompt_version, cost_ms))
            conn.commit()

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
