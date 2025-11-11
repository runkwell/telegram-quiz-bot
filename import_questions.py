import sqlite3
import re
import json

DB_FILE = 'quiz.db'
GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/runkwell/telegram-quiz-bot/main'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            image_url TEXT,
            option_a TEXT,
            option_b TEXT,
            option_c TEXT,
            option_d TEXT,
            option_e TEXT,
            option_f TEXT,
            option_g TEXT,
            num_options INTEGER DEFAULT 4,
            correct_answers TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

def parse_and_insert_questions(filename='pasted-text.txt', update_existing=False, reset_images=False):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if reset_images:
        cursor.execute("UPDATE questions SET image_url = NULL")
        print("Đã reset tất cả image_url về NULL.")
    
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    questions_blocks = re.split(r'-{20,}', content)
    
    inserted_count = 0
    updated_count = 0
    for block in questions_blocks:
        block = block.strip()
        if not block or len(block) < 100:
            continue
        
        # Parse TẤT CẢ images
        image_matches = re.findall(r'!\[([^\]]+)\]\(images/([^\)]+\.jpg)\)', block)
        images_json = []  # Array [urlA, urlB, ...]
        if image_matches:
            for alt, filename in image_matches:
                raw_url = f"{GITHUB_RAW_BASE}/images/{filename}"
                images_json.append(raw_url)
                print(f"Found image for alt '{alt}': {raw_url}")
        
        image_url_json = json.dumps(images_json) if images_json else None
        
        # Clean block
        clean_block = re.sub(r'!\[[^\]]+\]\(images/[^\)]+\)', '', block)
        
        # Tách question_text
        q_match = re.match(r'(\d+\.\s+.+?)(?=\n\n|\n-{2,}|\Z)', clean_block, re.DOTALL)
        if not q_match:
            continue
        question_text = q_match.group(1).strip()
        
        # Parse options
        options_lines = re.findall(r'-\s+\[([x ])\]\s+(.+)', clean_block)
        if len(options_lines) < 2:
            continue
        
        options = {}
        correct = []
        num_options = len(options_lines)
        
        for i, (mark, text) in enumerate(options_lines, 1):
            opt_key = chr(ord('A') + i - 1)
            options[opt_key] = text.strip()
            if mark == 'x':
                correct.append(opt_key)
        
        correct_str = ','.join(correct) if len(correct) > 1 else correct[0] if correct else ''
        
        # Check duplicate/update
        cursor.execute("SELECT id FROM questions WHERE question_text LIKE ?", (f"%{question_text[:50]}%",))
        existing = cursor.fetchone()
        if existing:
            if update_existing:
                cursor.execute('''
                    UPDATE questions SET image_url = ?, num_options = ?, correct_answers = ?
                    WHERE id = ?
                ''', (image_url_json, num_options, correct_str, existing[0]))
                if image_url_json:
                    updated_count += 1
                    print(f"Updated images JSON for: {question_text[:50]}... → {len(images_json)} images")
            else:
                print(f"Skip duplicate: {question_text[:50]}...")
            continue
        
        # Insert mới
        values = (
            question_text, image_url_json,
            options.get('A', ''), options.get('B', ''), options.get('C', ''), options.get('D', ''),
            options.get('E', ''), options.get('F', ''), options.get('G', ''),
            num_options, correct_str
        )
        cursor.execute('''
            INSERT INTO questions (question_text, image_url, option_a, option_b, option_c, option_d, 
                                  option_e, option_f, option_g, num_options, correct_answers)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', values)
        inserted_count += 1
        print(f"Inserted: {question_text[:50]}... (correct: {correct_str}, images: {len(images_json)})")
    
    conn.commit()
    conn.close()
    print(f"\nHoàn tất! Insert {inserted_count}, update {updated_count}.")

if __name__ == '__main__':
    parse_and_insert_questions(update_existing=True, reset_images=True)