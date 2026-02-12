import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json
from docx import Document
from docx.shared import RGBColor
import time
import re
import random
from datetime import datetime

# --- CẤU HÌNH TRANG ---
st.set_page_config(page_title="Quiz Master Pro", layout="wide", page_icon="😎")

# --- 1. KẾT NỐI GOOGLE SHEETS (DÙNG CACHE) ---
@st.cache_resource
def get_gspread_client():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        return None

def get_db_connection():
    client = get_gspread_client()
    if client:
        try:
            return client.open("QuizDatabase")
        except: return None
    return None

# --- 2. ĐỌC DỮ LIỆU (DÙNG CACHE DATA) ---
@st.cache_data(ttl=60)
def get_all_topics():
    sh = get_db_connection()
    if not sh: return []
    try:
        ws = sh.worksheet("Topics")
        data = ws.get_all_values()
        return sorted(data[1:], key=lambda x: x[0], reverse=True) if len(data) > 1 else []
    except: return []

@st.cache_data(show_spinner=False)
def get_questions_by_topic(topic_id):
    sh = get_db_connection()
    if not sh: return []
    try:
        ws = sh.worksheet("Questions")
        all_rows = ws.get_all_values()
        questions = []
        str_tid = str(topic_id)
        for row in all_rows[1:]:
            if len(row) >= 4 and row[0] == str_tid:
                questions.append({
                    "question": row[1],
                    "options": json.loads(row[2]),
                    "correct_option": row[3]
                })
        return questions
    except: return []

# --- 3. GHI DỮ LIỆU ---
def save_topic_to_db(topic_name, questions_list):
    sh = get_db_connection()
    if not sh: return False
    with st.spinner("Đang lưu lên đám mây..."):
        try:
            topics_ws = sh.worksheet("Topics")
            topic_id = int(time.time())
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            topics_ws.append_row([topic_id, topic_name, created_at])
            
            questions_ws = sh.worksheet("Questions")
            rows = []
            for q in questions_list:
                opt_str = json.dumps(q['options'], ensure_ascii=False)
                rows.append([topic_id, q['question'], opt_str, q['correct_option']])
            questions_ws.append_rows(rows)
            
            get_all_topics.clear()
            return True
        except Exception as e:
            st.error(f"Lỗi: {e}")
            return False

def delete_topic_from_db(topic_id):
    sh = get_db_connection()
    if not sh: return
    try:
        str_tid = str(topic_id)
        t_ws = sh.worksheet("Topics")
        cell = t_ws.find(str_tid)
        if cell: t_ws.delete_rows(cell.row)
        
        q_ws = sh.worksheet("Questions")
        rows = q_ws.get_all_values()
        new_rows = [rows[0]] + [r for r in rows[1:] if r[0] != str_tid]
        q_ws.clear()
        q_ws.update(new_rows)
        
        get_all_topics.clear()
        get_questions_by_topic.clear()
        st.toast("Đã xóa bộ đề!", icon="🗑️")
        time.sleep(1)
    except: pass

# --- 4. XỬ LÝ WORD THÔNG MINH ---
def is_correct_answer(para):
    if para.style and 'Strong' in para.style.name: return True
    for run in para.runs:
        if run.bold or run.underline: return True
        if run.font.color and run.font.color.rgb:
            if run.font.color.rgb == RGBColor(255, 0, 0): return True
            if run.font.color.rgb == RGBColor(0, 0, 255): return True
            if run.font.color.rgb == RGBColor(255, 0, 255): return True
    if para.text.strip().startswith("*"): return True
    return False

def parse_docx(file):
    doc = Document(file)
    questions = []
    current_q = None
    q_pattern_1 = re.compile(r'^(\d+[\.\)\/]|Câu\s+\d+|Bài\s+\d+)', re.IGNORECASE)
    opt_pattern = re.compile(r'^([A-D]|[a-d])[\.\)\-]')

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text: continue
        
        is_bold = False
        if para.style and 'Strong' in para.style.name: is_bold = True
        for run in para.runs:
            if run.bold: is_bold = True; break
            
        is_question = False
        if q_pattern_1.match(text): is_question = True
        elif is_bold and not opt_pattern.match(text): is_question = True

        if is_question:
            if current_q:
                if len(current_q['options']) > 0 and not current_q['correct_option']:
                    current_q['correct_option'] = current_q['options'][0]
                if len(current_q['options']) >= 2:
                    questions.append(current_q)
            
            clean_text = text
            if not q_pattern_1.match(text):
                clean_text = f"Câu hỏi: {text}"
            current_q = {"question": clean_text, "options": [], "correct_option": None}
            
        else:
            if current_q:
                clean_opt = re.sub(r'^([A-D]|[a-d])[\.\)\-]\s*', '', text)
                current_q["options"].append(clean_opt)
                if is_correct_answer(para):
                    current_q["correct_option"] = clean_opt

    if current_q and len(current_q['options']) >= 2:
        if not current_q['correct_option']:
            current_q['correct_option'] = current_q['options'][0]
        questions.append(current_q)
    return questions

# --- 5. GIAO DIỆN CHÍNH ---
if 'quiz_data' not in st.session_state: st.session_state.quiz_data = []
if 'score' not in st.session_state: st.session_state.score = 0
if 'user_answers' not in st.session_state: st.session_state.user_answers = {}
if 'current_topic_id' not in st.session_state: st.session_state.current_topic_id = None
if 'quiz_indices' not in st.session_state: st.session_state.quiz_indices = []

with st.sidebar:
    st.title("⚡ Quiz Master Pro")
    
    # --- THAY ĐỔI CỦA BẠN Ở ĐÂY ---
    st.caption("manhducdeptrai") 
    # ------------------------------

    mode = st.radio("Chế độ:", ["Theo thứ tự", "Ngẫu nhiên"])
    
    if 'mode' not in st.session_state: st.session_state.mode = mode
    if st.session_state.mode != mode:
        st.session_state.mode = mode
        if st.session_state.quiz_data:
            idxs = list(range(len(st.session_state.quiz_data)))
            if mode == "Ngẫu nhiên": random.shuffle(idxs)
            st.session_state.quiz_indices = idxs
            st.session_state.q_index = 0
            st.rerun()

    st.divider()
    tab1, tab2 = st.tabs(["📂 Kho Đề", "➕ Thêm Mới"])
    
    with tab1:
        if st.button("🔄 Cập nhật"):
            get_all_topics.clear()
            st.rerun()
        topics = get_all_topics()
        if not topics: st.info("Trống.")
        else:
            for row in topics:
                t_id, t_name = row[0], row[1]
                c1, c2 = st.columns([4, 1])
                if c1.button(f"📖 {t_name}", key=f"btn_{t_id}"):
                    st.session_state.current_topic_id = t_id
                    with st.spinner("Đang tải..."):
                        data = get_questions_by_topic(t_id)
                    st.session_state.quiz_data = data
                    idxs = list(range(len(data)))
                    if mode == "Ngẫu nhiên": random.shuffle(idxs)
                    st.session_state.quiz_indices = idxs
                    st.session_state.user_answers = {}
                    st.session_state.score = 0
                    st.session_state.q_index = 0
                    st.rerun()
                if c2.button("🗑️", key=f"del_{t_id}"):
                    delete_topic_from_db(t_id)
                    st.rerun()

    with tab2:
        uploaded = st.file_uploader("Upload Word (.docx)", type=['docx'])
        if uploaded:
            name = st.text_input("Tên bộ đề:", value=uploaded.name.replace(".docx", ""))
            if st.button("Lưu ngay", type="primary"):
                qs = parse_docx(uploaded)
                if qs:
                    success = save_topic_to_db(name, qs)
                    if success:
                        st.success(f"Đã lưu {len(qs)} câu.")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.error("Lỗi đọc file!")

# --- MÀN HÌNH LÀM BÀI ---
if st.session_state.current_topic_id and st.session_state.quiz_data:
    qs = st.session_state.quiz_data
    indices = st.session_state.quiz_indices
    total = len(qs)
    
    if len(indices) != total:
        indices = list(range(total))
        if mode == "Ngẫu nhiên": random.shuffle(indices)
        st.session_state.quiz_indices = indices

    # --- KHU VỰC ĐIỀU HƯỚNG MỚI (CHỌN CÂU) ---
    st.markdown("### 🎯 Khu vực làm bài")
    
    col_sel_1, col_sel_2, col_sel_3 = st.columns([2, 1, 2])
    
    with col_sel_1:
        list_numbers = list(range(1, total + 1))
        current_num = st.session_state.q_index + 1
        
        selected_num = st.selectbox(
            "🔍 Đi đến câu số:", 
            list_numbers, 
            index=st.session_state.q_index
        )
        
        if selected_num != current_num:
            st.session_state.q_index = selected_num - 1
            st.rerun()

    with col_sel_3:
        st.metric("Điểm số", f"{st.session_state.score}")

    st.progress(len(st.session_state.user_answers)/total if total>0 else 0)

    # --- NỘI DUNG CÂU HỎI ---
    real_idx = indices[st.session_state.q_index]
    q = qs[real_idx]

    st.markdown("---")
    st.markdown(f"#### Câu {st.session_state.q_index + 1}: {q['question']}")

    prev = st.session_state.user_answers.get(real_idx)
    
    if prev:
        st.radio("Bạn đã chọn:", q['options'], 
                 index=q['options'].index(prev) if prev in q['options'] else 0,
                 key=f"dis_{real_idx}", disabled=True)
        if prev == q['correct_option']: 
            st.success(f"✅ Chính xác! Đáp án: {q['correct_option']}")
        else: 
            st.error(f"❌ Sai rồi! Bạn chọn: {prev}")
            st.info(f"👉 Đáp án đúng là: **{q['correct_option']}**")
    else:
        with st.form(key=f"f_{real_idx}"):
            choice = st.radio("Chọn đáp án:", q['options'], key=f"r_{real_idx}")
            if st.form_submit_button("Chốt đáp án", type="primary"):
                st.session_state.user_answers[real_idx] = choice
                if choice == q['correct_option']:
                    st.session_state.score += 1
                    st.balloons()
                st.rerun()

    st.markdown("---")
    c1, c2 = st.columns(2)
    if c1.button("⬅️ Câu trước", use_container_width=True) and st.session_state.q_index > 0:
        st.session_state.q_index -= 1
        st.rerun()
    if c2.button("Câu sau ➡️", use_container_width=True) and st.session_state.q_index < total - 1:
        st.session_state.q_index += 1
        st.rerun()

else:
    st.info("👈 Hãy chọn đề thi bên trái.")