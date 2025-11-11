import sqlite3
import re

DB_FILE = 'quiz.db'
GITHUB_RAW_BASE = 'https://raw.githubusercontent.com/runkwell/telegram-quiz-bot/main'  # Thay bằng repo thật, e.g., 'https://raw.githubusercontent.com/ChrisDevil55797/telegram-quiz-bot/main'

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

def parse_and_insert_questions(filename='pasted-text.txt'):
    init_db()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Tách các câu hỏi bằng regex (dựa trên số + . + text + options + --------------------------------------------------)
    questions_blocks = re.split(r'-{20,}', content)  # Split bằng dấu gạch ngang dài
    
    inserted_count = 0
    for block in questions_blocks:
        block = block.strip()
        if not block or len(block) < 100:  # Skip empty/truncated
            continue
        
        # Tách số câu + question_text (dòng đầu, bao gồm images nếu có)
        # Parse images trước: ![alt](images/filename.jpg) → extract filename
        image_matches = re.findall(r'!\[([^\]]+)\]\(images/([^\)]+\.jpg)\)', block)
        image_url = None
        if image_matches:
            # Lấy image đầu tiên (hoặc chỉnh logic nếu multiple)
            alt, filename = image_matches[0]
            image_url = f"{GITHUB_RAW_BASE}/images/{filename}"
            print(f"Found image for alt '{alt}': {image_url}")
        
        # Tách question_text (loại bỏ images markup để clean text)
        clean_block = re.sub(r'!\[[^\]]+\]\(images/[^\)]+\)', '', block)  # Remove ![ ] markup
        q_match = re.match(r'(\d+\.\s+.+?)(?=\n\n|\n-{2,}|\Z)', clean_block, re.DOTALL)
        if not q_match:
            continue
        question_text = q_match.group(1).strip()
        
        # Tìm options (dòng bắt đầu bằng - [ ] hoặc [x])
        options_lines = re.findall(r'-\s+\[([x ])\]\s+(.+)', clean_block)
        if len(options_lines) < 2:
            continue  # Skip invalid
        
        options = {}
        correct = []
        num_options = len(options_lines)
        
        for i, (mark, text) in enumerate(options_lines, 1):
            opt_key = chr(ord('A') + i - 1)
            options[opt_key] = text.strip()
            if mark == 'x':
                correct.append(opt_key)
        
        correct_str = ','.join(correct) if len(correct) > 1 else correct[0] if correct else ''
        
        # Check duplicate (dựa trên question_text)
        cursor.execute("SELECT id FROM questions WHERE question_text = ?", (question_text,))
        if cursor.fetchone():
            print(f"Skip duplicate: {question_text[:50]}...")
            continue
        
        # Insert
        values = (
            question_text, image_url,
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
        print(f"Inserted: {question_text[:50]}... (correct: {correct_str}, image: {image_url or 'None'})")
    
    conn.commit()
    conn.close()
    print(f"\nHoàn tất! Đã import {inserted_count} câu hỏi vào DB.")

if __name__ == '__main__':
    parse_and_insert_questions()