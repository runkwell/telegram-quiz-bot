import sqlite3
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
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
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='questions';")
    table_exists = cursor.fetchone() is not None
    
    if not table_exists:
        print("Bảng chưa tồn tại, sẽ tạo mới qua init_db.")
        conn.close()
        init_db()
        conn = sqlite3.connect(DB_FILE)  # Reconnect
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
QUESTION_TEXT, IMAGE_URL, NUM_OPTIONS, OPTIONS_INPUT, CORRECT_ANSWERS = range(5)

# Lưu trạng thái quiz
user_quizzes = {}

TOKEN = os.environ.get('TOKEN')
if not TOKEN:
    raise ValueError("TOKEN chưa được set!")

# Helper lấy options dict từ row DB
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

# Helper lấy correct (str cho single, set cho multiple)
def get_correct(correct_str):
    stripped = correct_str.upper().replace(' ', '')
    if ',' in stripped:
        return set(c.strip() for c in stripped.split(','))
    else:
        return stripped  # str cho single

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
    
    # Lưu DB
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

# Tạo exam
async def create_exam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM questions')
    all_questions = cursor.fetchall()
    conn.close()
    
    if len(all_questions) < 65:
        await update.message.reply_text('Pool chưa đủ 65 câu. Thêm thêm!')
        return
    
    selected = random.sample(all_questions, 65)
    quiz_data = {
        'questions': [
            {
                'id': q[0],
                'text': q[1],
                'image': q[2],
                'options': get_options(q),
                'num_options': q[10],
                'correct': get_correct(q[11]),
                'is_multiple': isinstance(get_correct(q[11]), set)  # True nếu multiple
            } for q in selected
        ],
        'current_index': 0,
        'answers': {}  # {idx: str (single) hoặc set (multiple)}
    }
    user_quizzes[user_id] = quiz_data
    await show_question(update, context)

# Hiển thị câu
async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_quizzes:
        if update.message:
            await update.message.reply_text('Tạo exam trước bằng /create_exam!')
        return
    
    quiz = user_quizzes[user_id]
    idx = quiz['current_index']
    q = quiz['questions'][idx]
    
    select_type = "1 đáp án" if not q['is_multiple'] else "tất cả đúng"
    text = f"Câu {idx+1}/65:\n{q['text']}\n(Chọn {select_type})"
    
    # Lấy selected hiện tại
    selected = quiz['answers'].get(idx, '' if not q['is_multiple'] else set())
    
    # Keyboard động
    keyboard = []
    for i in range(q['num_options']):
        opt = chr(ord('A') + i)
        label = f"{opt}: {q['options'][opt]}"
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
        await query.edit_message_text(text, reply_markup=reply_markup)
        if q['image']:
            await context.bot.send_photo(query.message.chat_id, q['image'])
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)
        if q['image']:
            await context.bot.send_photo(update.effective_chat.id, q['image'])

# Callback
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    if user_id not in user_quizzes:
        await query.answer("Chưa có quiz!")
        return
    
    quiz = user_quizzes[user_id]
    idx = quiz['current_index']
    q = quiz['questions'][idx]
    
    if data.startswith('ans_'):
        _, _, idx_str, opt = data.split('_')
        idx = int(idx_str)
        q = quiz['questions'][idx]  # Re-get for this idx
        if q['is_multiple']:
            selected = quiz['answers'].setdefault(idx, set())
            if opt in selected:
                selected.discard(opt)
                await query.answer(f"Bỏ {opt}")
            else:
                selected.add(opt)
                await query.answer(f"Chọn {opt}")
        else:
            # Single: thay đổi lựa chọn
            if quiz['answers'].get(idx) == opt:
                quiz['answers'][idx] = ''  # Unselect
                await query.answer("Bỏ chọn")
            else:
                quiz['answers'][idx] = opt
                await query.answer(f"Chọn {opt}")
        await show_question(update, context)
    
    elif data.startswith('next_'):
        if idx < 64:
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
        [InlineKeyboardButton("Tạo đề thi", callback_data="create_exam")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Chào! Chọn chức năng:', reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "add_q":
        await query.edit_message_text("Dùng /add_question để thêm.")
    elif query.data == "create_exam":
        await create_exam(update, context)

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
        },
        fallbacks=[CommandHandler('cancel', cancel_add)],
    )
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('create_exam', create_exam))
    application.add_handler(CommandHandler('finish_quiz', finish_quiz))
    application.add_handler(CallbackQueryHandler(handle_callback, pattern='^(ans_|next_|back_|confirm_)'))
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^(add_q|create_exam)'))
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()