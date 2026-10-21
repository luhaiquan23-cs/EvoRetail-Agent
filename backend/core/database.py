import os
import json
import sqlite3
from typing import Optional, List, Dict, Any
from backend.core.models.product_specs import ProductItem

DEFAULT_DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "../../data/ecommerce_cs.db"))

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
        """初始化数据表结构"""
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

            cursor.execute("""
            INSERT OR IGNORE INTO prompt_versions (version, system_prompt, eval_score, is_active)
            VALUES ('v2.0.0', '默认基线版本', 98.0, 1);
            """)
            cursor.execute("SELECT COUNT(*) FROM products")
            is_empty = cursor.fetchone()[0] == 0
            conn.commit()

        if is_empty:
            self.seed_mock_data()

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
        """导入预置 3C 商品数据"""
        path = mock_json_path or os.path.join(os.path.dirname(__file__), "../../data/mock_products.json")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
            for item in items:
                p = ProductItem.model_validate(item)
                self.save_product(p)
        print(f"[OK] Successfully seeded {len(items)} 3C mock products into SQLite.")

db = Database()

if __name__ == "__main__":
    db.seed_mock_data()
