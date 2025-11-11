import sqlite3
import os
import random
import logging
import json
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Cấu hình logging (DEBUG để check image_map)
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Database setup
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

init_db()

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(questions)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'num_options' not in columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN num_options INTEGER DEFAULT 4")
    if 'correct_answers' not in columns:
        cursor.execute("ALTER TABLE questions ADD COLUMN correct_answers TEXT DEFAULT ''")
    for opt in ['e', 'f', 'g']:
        col_name = f'option_{opt}'
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE questions ADD COLUMN {col_name} TEXT")
    if 'correct_answer' in columns:
        cursor.execute("UPDATE questions SET correct_answers = correct_answer WHERE correct_answers = '' AND correct_answer IS NOT NULL")
    conn.commit()
    conn.close()

migrate_db()

# Trạng thái Conversation
QUESTION_TEXT, IMAGE_URL, NUM_OPTIONS, OPTIONS_INPUT, CORRECT_ANSWERS, EXAM_COUNT = range(6)

# Lưu trạng thái quiz
user_quizzes = {}

TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    raise ValueError("TOKEN chưa được set!")

# Helper
def get_options(row):
    opts = {}
    if row[3]: opts['A'] = row[3]
    if row[4]: opts['B'] = row[4]
    if row[5]: opts['C'] = row[5]
    if row[6]: opts['D'] = row[6]
    if len(row) > 7 and row[7]: opts['E'] = row[7]
    if len(row) > 8 and row[8]: opts['F'] = row[8]
    if len(row) > 9 and row[9]: opts['G'] = row[9]
    return opts

def get_correct(correct_str):
    stripped = correct_str.upper().replace(' ', '')
    if ',' in stripped:
        return set(c.strip() for c in stripped.split(','))
    else:
        return stripped

def parse_images_json(image_url_str, q_id):
    """Parse image_url: JSON array hoặc single string, map theo opt từ filename."""
    image_map = {}
    if not image_url_str:
        return image_map
    
    # Handle single string (câu 48)
    if not image_url_str.startswith('['):
        filename = image_url_str.split('/')[-1]
        match = re.match(r'question(\d+)(_[A-G])?\.jpg', filename)
        if match:
            num = match.group(1)
            opt = match.group(2)[1] if match.group(2) else 'general'
            if num == str(q_id):
                image_map[opt] = image_url_str
        logger.debug(f"Single image for {q_id}: {image_map}")
        return image_map
    
    # Handle JSON array (câu 30)
    try:
        urls = json.loads(image_url_str)
        for url in urls:
            filename = url.split('/')[-1]
            match = re.match(r'question(\d+)_([A-G])\.jpg', filename)
            if match:
                num = match.group(1)
                opt = match.group(2)
                if num == str(q_id):
                    image_map[opt] = url
            else:
                # Fallback general nếu không match opt
                image_map['general'] = url
        logger.debug(f"JSON images for {q_id}: {image_map}")
    except json.JSONDecodeError:
        logger.error(f"JSON parse error for {q_id}: {image_url_str}")
        image_map['general'] = image_url_str
    
    return image_map

# Thêm câu hỏi
async def add_question_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Gửi nội dung câu hỏi:')
    return QUESTION_TEXT

async def add_question_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['question_text'] = update.message.text
    await update.message.reply_text('Gửi URL hình ảnh (hoặc /skip):')
    return IMAGE_URL

async def add_question_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == '/skip':
        context.user_data['image_url'] = None
    else:
        context.user_data['image_url'] = update.message.text
    await update.message.reply_text('Số lượng lựa chọn (1-7, gợi ý 4 cho single):')
    return NUM_OPTIONS

async def add_num_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        num = int(update.message.text)
        if 1 <= num <= 7:
            context.user_data['num_options'] = num
            context.user_data['options'] = {}
            await update.message.reply_text('Gửi đáp án A:')
            context.user_data['current_opt'] = 'A'
            return OPTIONS_INPUT
        else:
            await update.message.reply_text('Phải 1-7. Thử lại:')
            return NUM_OPTIONS
    except ValueError:
        await update.message.reply_text('Số hợp lệ. Thử lại:')
        return NUM_OPTIONS

async def add_options_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opt_key = context.user_data['current_opt']
    context.user_data['options'][opt_key] = update.message.text
    
    num = context.user_data['num_options']
    next_opt = chr(ord(opt_key) + 1)
    if ord(next_opt) <= ord('A') + num - 1:
        context.user_data['current_opt'] = next_opt
        await update.message.reply_text(f'Gửi đáp án {next_opt}:')
        return OPTIONS_INPUT
    else:
        await update.message.reply_text('Đáp án đúng (vd: A cho single, hoặc A,B cho multiple):')
        return CORRECT_ANSWERS

async def add_correct_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    correct_str = update.message.text.upper().replace(' ', '')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    e_opt = context.user_data['options'].get('E', '')
    f_opt = context.user_data['options'].get('F', '')
    g_opt = context.user_data['options'].get('G', '')
    values = (
        context.user_data['question_text'],
        context.user_data['image_url'],
        context.user_data['options'].get('A', ''),
        context.user_data['options'].get('B', ''),
        context.user_data['options'].get('C', ''),
        context.user_data['options'].get('D', ''),
        e_opt,
        f_opt,
        g_opt,
        context.user_data['num_options'],
        correct_str
    )
    cursor.execute('''
        INSERT INTO questions (question_text, image_url, option_a, option_b, option_c, option_d, option_e, option_f, option_g, num_options, correct_answers)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', values)
    conn.commit()
    conn.close()
    
    await update.message.reply_text('Thêm thành công!')
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Hủy.')
    context.user_data.clear()
    return ConversationHandler.END

# Xem pool
async def pool_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM questions')
    total = cursor.fetchone()[0]
    conn.close()
    await update.message.reply_text(f'Question pool hiện có {total} câu hỏi.')

# Xem câu theo ID
async def view_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text('Sử dụng: /view_question <ID> (e.g., /view_question 5)')
        return
    
    try:
        q_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('ID phải là số nguyên!')
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM questions WHERE id = ?', (q_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        await update.message.reply_text(f'Câu hỏi ID {q_id} không tồn tại!')
        return
    
    q_text = row[1]
    options = get_options(row)
    correct_str = row[11]
    num_opts = row[10]
    image_map = parse_images_json(row[2], q_id)
    logger.debug(f"Image map for {q_id}: {image_map}")
    
    text = f"Câu {q_id}:\n\n{q_text}\n\nĐáp án:"
    for i in range(1, num_opts + 1):
        opt = chr(ord('A') + i - 1)
        opt_text = options.get(opt, '')
        opt_link = f" [Xem hình {opt}]({image_map.get(opt, '')})" if image_map.get(opt) else ""
        text += f"\n{opt}: {opt_text}{opt_link}"
    
    if 'general' in image_map:
        text += f"\n\n[Xem hình chung]({image_map['general']})"
    
    text += f"\n\nĐáp án đúng: {correct_str}"
    
    await update.message.reply_text(text, parse_mode='Markdown', disable_web_page_preview=False)

# Tạo exam
async def create_exam_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM questions')
    total = cursor.fetchone()[0]
    conn.close()
    
    if total == 0:
        await update.message.reply_text('Pool chưa có câu hỏi nào! Hãy thêm bằng /add_question.')
        return ConversationHandler.END
    
    await update.message.reply_text(f'Pool có {total} câu hỏi. Nhập số câu để random (1-{total}):')
    return EXAM_COUNT

async def create_exam_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        num_q = int(update.message.text)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM questions')
        total = cursor.fetchone()[0]
        conn.close()
        
        if num_q < 1 or num_q > total:
            await update.message.reply_text(f'Số câu phải từ 1 đến {total}. Thử lại:')
            return EXAM_COUNT
        
        user_id = update.effective_user.id
        cursor.execute('SELECT * FROM questions')
        all_questions = cursor.fetchall()
        selected = random.sample(all_questions, num_q)
        quiz_data = {
            'questions': [
                {
                    'id': q[0],
                    'text': q[1],
                    'image': q[2],
                    'options': get_options(q),
                    'num_options': q[10],
                    'correct': get_correct(q[11]),
                    'is_multiple': isinstance(get_correct(q[11]), set)
                } for q in selected
            ],
            'current_index': 0,
            'answers': {}
        }
        user_quizzes[user_id] = quiz_data
        await show_question(update, context)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text('Số hợp lệ. Thử lại:')
        return EXAM_COUNT

# Hiển thị câu
async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_quizzes:
        if update.message:
            await update.message.reply_text('Tạo exam trước bằng /create_exam!')
        return
    
    quiz = user_quizzes[user_id]
    total_q = len(quiz['questions'])
    idx = quiz['current_index']
    q = quiz['questions'][idx]
    
    select_type = "1 đáp án" if not q['is_multiple'] else "tất cả đúng"
    q_text = q['text']
    image_map = parse_images_json(q['image'], q['id'])
    logger.debug(f"Quiz image map for {q['id']}: {image_map}")
    
    text = f"Câu {idx+1}/{total_q}:\n\n{q_text}\n\n(Chọn {select_type})"
    
    # Lấy selected hiện tại
    selected = quiz['answers'].get(idx, '' if not q['is_multiple'] else set())
    
    # Keyboard động với image links
    keyboard = []
    for i in range(q['num_options']):
        opt = chr(ord('A') + i)
        opt_text = q['options'][opt]
        opt_link = f" [img {opt}]({image_map.get(opt, '')})" if image_map.get(opt) else ""
        label = f"{opt}: {opt_text}{opt_link}"
        if q['is_multiple']:
            if opt in selected:
                label += ' ✅'
        else:
            if selected == opt:
                label += ' ✅'
        keyboard.append([InlineKeyboardButton(label, callback_data=f"ans_{idx}_{opt}")])
    
    keyboard += [
        [InlineKeyboardButton("Next", callback_data=f"next_{idx}")],
        [InlineKeyboardButton("Back", callback_data=f"back_{idx}")],
        [InlineKeyboardButton("Confirm", callback_data=f"confirm_{idx}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown', disable_web_page_preview=False)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown', disable_web_page_preview=False)

# Callback
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    if user_id not in user_quizzes:
        await query.answer("Chưa có quiz!")
        return
    
    quiz = user_quizzes[user_id]
    total_q = len(quiz['questions'])
    idx = quiz['current_index']
    q = quiz['questions'][idx]
    
    if data.startswith('ans_'):
        _, _, idx_str, opt = data.split('_')
        idx = int(idx_str)
        q = quiz['questions'][idx]
        if q['is_multiple']:
            selected = quiz['answers'].setdefault(idx, set())
            if opt in selected:
                selected.discard(opt)
                await query.answer(f"Bỏ {opt}")
            else:
                selected.add(opt)
                await query.answer(f"Chọn {opt}")
        else:
            if quiz['answers'].get(idx) == opt:
                quiz['answers'][idx] = ''
                await query.answer("Bỏ chọn")
            else:
                quiz['answers'][idx] = opt
                await query.answer(f"Chọn {opt}")
        await show_question(update, context)
    
    elif data.startswith('next_'):
        if idx < total_q - 1:
            quiz['current_index'] += 1
            await show_question(update, context)
        else:
            result = end_quiz(user_id)
            await context.bot.send_message(user_id, result)
            del user_quizzes[user_id]
    
    elif data.startswith('back_'):
        if idx > 0:
            quiz['current_index'] -= 1
            await show_question(update, context)
    
    elif data.startswith('confirm_'):
        selected = quiz['answers'].get(idx, '' if not q['is_multiple'] else set())
        correct = q['correct']
        
        if q['is_multiple']:
            if selected == correct:
                result = "✅ Đúng hoàn toàn!"
            else:
                correct_list = ', '.join(sorted(correct))
                result = f"❌ Sai! Đúng: {correct_list}"
        else:
            if selected == correct:
                result = "✅ Đúng!"
            else:
                result = f"❌ Sai! Đúng là {correct}: {q['options'][correct]}"
        
        await query.answer(result)

# Kết quả
def end_quiz(user_id):
    if user_id not in user_quizzes:
        return "Không có quiz."
    
    quiz = user_quizzes[user_id]
    total = len(quiz['questions'])
    correct_count = 0
    wrong_positions = []
    for i in range(total):
        q = quiz['questions'][i]
        selected = quiz['answers'].get(i, '' if not q['is_multiple'] else set())
        if (q['is_multiple'] and selected == q['correct']) or (not q['is_multiple'] and selected == q['correct']):
            correct_count += 1
        else:
            wrong_positions.append(str(q['id']))
    
    wrong_count = total - correct_count
    result_text = f"Kết quả:\n✅ Đúng: {correct_count}/{total}\n❌ Sai: {wrong_count}\nVị trí sai trong pool: {', '.join(wrong_positions)}"
    return result_text

# Start và button
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Thêm câu hỏi", callback_data="add_q")],
        [InlineKeyboardButton("Tạo đề thi", callback_data="create_exam")],
        [InlineKeyboardButton("Xem pool", callback_data="pool_count")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Chào! Chọn chức năng:', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "add_q":
        await query.edit_message_text("Dùng /add_question để thêm.")
    elif query.data == "create_exam":
        return await create_exam_start(update, context)
    elif query.data == "pool_count":
        await pool_count(update, context)

async def finish_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    result = end_quiz(user_id)
    await update.message.reply_text(result)
    if user_id in user_quizzes:
        del user_quizzes[user_id]

# Main
def main():
    application = Application.builder().token(TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('add_question', add_question_start)],
        states={
            QUESTION_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_text)],
            IMAGE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_image)],
            NUM_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_num_options)],
            OPTIONS_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_options_input)],
            CORRECT_ANSWERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_correct_answers)],
            EXAM_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_exam_count)],
        },
        fallbacks=[CommandHandler('cancel', cancel_add)],
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('pool_count', pool_count))
    application.add_handler(CommandHandler('view_question', view_question))
    application.add_handler(CommandHandler('create_exam', create_exam_start))
    application.add_handler(CommandHandler('finish_quiz', finish_quiz))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern='^(ans_|next_|back_|confirm_)'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^(add_q|create_exam|pool_count)'))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()