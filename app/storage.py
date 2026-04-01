"""SQLite persistence layer."""
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "linkedin_responder.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                participant_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                sender_name TEXT NOT NULL,
                body TEXT NOT NULL,
                received_at TEXT NOT NULL DEFAULT (datetime('now')),
                is_mine INTEGER NOT NULL DEFAULT 0,
                screenshot_path TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );

            CREATE TABLE IF NOT EXISTS response_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                chosen_response_index INTEGER,
                chosen_body TEXT,
                chosen_at TEXT,
                feedback TEXT,
                FOREIGN KEY (message_id) REFERENCES messages(id)
            );

            CREATE TABLE IF NOT EXISTS generated_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                response_index INTEGER NOT NULL,
                body TEXT NOT NULL,
                tone_label TEXT,
                FOREIGN KEY (session_id) REFERENCES response_sessions(id)
            );
        """)


# --- Conversations ---

def create_conversation(participant_name: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (participant_name) VALUES (?)",
            (participant_name,)
        )
        return cur.lastrowid


def delete_conversation(conv_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM generated_responses WHERE session_id IN (SELECT s.id FROM response_sessions s JOIN messages m ON m.id = s.message_id WHERE m.conversation_id = ?)", (conv_id,))
        conn.execute("DELETE FROM response_sessions WHERE message_id IN (SELECT id FROM messages WHERE conversation_id = ?)", (conv_id,))
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))


def get_conversation(conv_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()


def list_conversations():
    with get_conn() as conn:
        return conn.execute("""
            SELECT c.*,
                   COUNT(DISTINCT m.id) as message_count,
                   MAX(m.received_at) as last_message_at,
                   COUNT(DISTINCT CASE WHEN s.chosen_body IS NULL THEN s.id END) as pending_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            LEFT JOIN response_sessions s ON s.message_id = m.id
            GROUP BY c.id
            ORDER BY last_message_at DESC NULLS LAST
        """).fetchall()


def find_conversation_by_name(name: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM conversations WHERE participant_name = ? COLLATE NOCASE",
            (name,)
        ).fetchone()


# --- Messages ---

def add_message(conversation_id: int, sender_name: str, body: str,
                is_mine: bool = False, screenshot_path: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO messages (conversation_id, sender_name, body, is_mine, screenshot_path)
            VALUES (?, ?, ?, ?, ?)
        """, (conversation_id, sender_name, body, int(is_mine), screenshot_path or ""))
        conn.execute(
            "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
            (conversation_id,)
        )
        return cur.lastrowid


def get_message(msg_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT m.*, c.participant_name
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE m.id = ?
        """, (msg_id,)).fetchone()


def get_conversation_messages(conv_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT m.*, s.id as session_id, s.chosen_body
            FROM messages m
            LEFT JOIN response_sessions s ON s.message_id = m.id
            WHERE m.conversation_id = ?
            ORDER BY m.received_at ASC
        """, (conv_id,)).fetchall()


# --- Response sessions ---

def create_response_session(message_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO response_sessions (message_id) VALUES (?)",
            (message_id,)
        )
        return cur.lastrowid


def save_generated_responses(session_id: int, responses: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO generated_responses (session_id, response_index, body, tone_label)
            VALUES (?, ?, ?, ?)
        """, [(session_id, i, r["body"], r.get("tone", "")) for i, r in enumerate(responses)])


def get_session_with_responses(session_id: int):
    with get_conn() as conn:
        session = conn.execute("""
            SELECT s.*, m.body as message_body, m.sender_name,
                   m.conversation_id, c.participant_name
            FROM response_sessions s
            JOIN messages m ON m.id = s.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE s.id = ?
        """, (session_id,)).fetchone()
        responses = conn.execute("""
            SELECT * FROM generated_responses
            WHERE session_id = ? ORDER BY response_index
        """, (session_id,)).fetchall()
        return session, responses


def record_choice(session_id: int, response_index: int, body: str, feedback: str = ""):
    with get_conn() as conn:
        conn.execute("""
            UPDATE response_sessions
            SET chosen_response_index = ?, chosen_body = ?,
                chosen_at = datetime('now'), feedback = ?
            WHERE id = ?
        """, (response_index, body, feedback, session_id))


def get_pending_sessions():
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.created_at, m.body as message_body,
                   m.sender_name, c.participant_name, c.id as conversation_id
            FROM response_sessions s
            JOIN messages m ON m.id = s.message_id
            JOIN conversations c ON c.id = m.conversation_id
            WHERE s.chosen_body IS NULL
            ORDER BY s.created_at DESC
        """).fetchall()


def get_feedback_history(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.chosen_response_index, s.feedback,
                   m.body as message_body,
                   s.chosen_body, gr.tone_label
            FROM response_sessions s
            JOIN messages m ON m.id = s.message_id
            LEFT JOIN generated_responses gr
              ON gr.session_id = s.id
             AND gr.response_index = s.chosen_response_index
            WHERE s.chosen_body IS NOT NULL
            ORDER BY s.chosen_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
