import sqlite3

DB_FILE = 'quiz.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            image_url TEXT,
            option_a TEXT NOT NULL,
            option_b TEXT NOT NULL,
            option_c TEXT NOT NULL,
            option_d TEXT NOT NULL,
            option_e TEXT,
            option_f TEXT,
            option_g TEXT,
            num_options INTEGER DEFAULT 4,
            correct_answers TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()
    print("DB initialized successfully! (Bảng 'questions' đã tạo hoặc tồn tại.)")

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Kiểm tra bảng có tồn tại không
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions';")
    table_exists = cursor.fetchone() is not None
    
    if not table_exists:
        print("Bảng chưa tồn tại, sẽ tạo mới qua init_db.")
        conn.close()
        init_db()
        conn = sqlite3.connect(DB_FILE)  # Reconnect
        cursor = conn.cursor()
    
    # Lấy info cột hiện tại
    cursor.execute("PRAGMA table_info(questions)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"Cột hiện tại: {columns}")
    
    # Thêm cột nếu chưa có
    added = []
    if 'num_options' not in columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN num_options INTEGER DEFAULT 4")
        added.append('num_options')
    if 'correct_answers' not in columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN correct_answers TEXT DEFAULT ''")
        added.append('correct_answers')
    for opt in ['e', 'f', 'g']:
        col_name = f'option_{opt}'
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE questions ADD COLUMN {col_name} TEXT")
            added.append(col_name)
    
    # Migrate data cũ (nếu có cột correct_answer cũ)
    if 'correct_answer' in columns:
        cursor.execute("UPDATE questions SET correct_answers = correct_answer WHERE correct_answers = '' AND correct_answer IS NOT NULL")
        added.append('migrated correct_answer')
    
    conn.commit()
    conn.close()
    
    if added:
        print(f"Đã thêm/migrate: {', '.join(added)}")
    else:
        print("Không cần thay đổi, DB đã up-to-date.")

if __name__ == '__main__':
    init_db()
    migrate_db()
    print("Migrate hoàn tất! File 'quiz.db' đã sẵn sàng.")