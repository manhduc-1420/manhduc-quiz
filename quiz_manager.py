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

# CSS BIẾN NÚT BẤM THÀNH CHỮ (GHOST MODE)
st.markdown("""
    <style>
    div.stButton > button:first-child {
        border: none;
        background: transparent;
        color: #808495;
        padding: 0;
        margin: 0;
        font-size: 0.85rem;
        font-family: sans-serif;
        font-weight: normal;
        text-align: left;
    }
    div.stButton > button:first-child:hover {
        color: #ff4b4b;
        background: transparent;
    }
    div.stButton > button:first-child:active {
        background: transparent;
        color: #ff4b4b;
    }
    </style>
""", unsafe_allow_html=True)

# --- 1. KẾT NỐI GOOGLE SHEETS ---
@st.cache_resource
def get_gspread_client():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except: return None

def get_db_connection():
    client = get_gspread_client()
    return client.open("QuizDatabase") if client else None

# --- 2. ĐỌC DỮ LIỆU ---
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
        str_tid = str(topic_id)
        return [{"question": r[1], "options": json.loads(r[2]), "correct_option": r[3]} for r in all_rows[1:] if r[0] == str_tid]
    except: return []

# --- 3. GHI & XÓA DỮ LIỆU ---
def save_topic_to_db(topic_name, questions_list):
    sh = get_db_connection()
    if not sh: return False
    try:
        topics_ws = sh.worksheet("Topics")
        topic_id = int(time.time())
        topics_ws.append_row([topic_id, topic_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        questions_ws = sh.worksheet("Questions")
        rows = [[topic_id, q['question'], json.dumps(q['options'], ensure_ascii=False), q['correct_option']] for q in questions_list]
        questions_ws.append_rows(rows)
        get_all_topics.clear()
        return True
    except: return False

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
        q_ws.clear(); q_ws.update(new_rows)
        get_all_topics.clear(); get_questions_by_topic.clear()
        st.toast("Đã xóa xong!", icon="🗑️")
    except: pass

# --- 4. XỬ LÝ WORD THÔNG MINH ---
def is_correct_answer(para):
    if para.style and 'Strong' in para.style.name: return True
    for run in para.runs:
        if run.bold or run.underline: return True
        if run.font.color and run.font.color.rgb and run.font.color.rgb in [RGBColor(255,0,0), RGBColor(0,0,255)]: return True
    return para.text.strip().startswith("*")

def parse_docx(file):
    doc = Document(file)
    questions, current_q = [], None
    q_pat = re.compile(r'^(\d+[\.\)\/]|Câu\s+\d+|Bài\s+\d+)', re.IGNORECASE)
    opt_pat = re.compile(r'^([A-D]|[a-d])[\.\)\-]')
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text: continue
        is_bold = any(run.bold for run in para.runs) or (para.style and 'Strong' in para.style.name)
        if q_pat.match(text) or (is_bold and not opt_pat.match(text)):
            if current_q and len(current_q['options']) >= 2:
                if not current_q['correct_option']: current_q['correct_option'] = current_q['options'][0]
                questions.append(current_q)
            current_q = {"question": text if q_pat.match(text) else f"Câu hỏi: {text}", "options": [], "correct_option": None}
        elif current_q:
            clean_opt = re.sub(r'^([A-D]|[a-d])[\.\)\-]\s*', '', text)
            current_q["options"].append(clean_opt)
            if is_correct_answer(para): current_q["correct_option"] = clean_opt
    if current_q and len(current_q['options']) >= 2:
        if not current_q['correct_option']: current_q['correct_option'] = current_q['options'][0]
        questions.append(current_q)
    return questions

# --- 5. GIAO DIỆN CHÍNH ---
if 'quiz_data' not in st.session_state: st.session_state.quiz_data = []
if 'q_index' not in st.session_state: st.session_state.q_index = 0
if 'user_answers' not in st.session_state: st.session_state.user_answers = {}
if 'show_admin' not in st.session_state: st.session_state.show_admin = False

with st.sidebar:
    st.title("⚡ Quiz Master Pro")
    
    # DÒNG CHỮ BÍ MẬT (Click vào chữ để hiện ô nhập mã)
    if st.button("manhducdeptrai"):
        st.session_state.show_admin = not st.session_state.show_admin
        st.rerun()

    is_admin = False
    if st.session_state.show_admin:
        pw = st.text_input("Mã bảo vệ:", type="password")
        is_admin = (pw == "manhducdeptrai")

    st.divider()
    tab1, tab2 = st.tabs(["📂 Kho Đề", "➕ Thêm"])
    with tab1:
        if st.button("🔄 Cập nhật"): get_all_topics.clear(); st.rerun()
        for row in get_all_topics():
            t_id, t_name = row[0], row[1]
            c1, c2 = st.columns([4, 1])
            if c1.button(f"📖 {t_name}", key=f"btn_{t_id}"):
                st.session_state.current_topic_id = t_id
                st.session_state.quiz_data = get_questions_by_topic(t_id)
                st.session_state.quiz_indices = list(range(len(st.session_state.quiz_data)))
                st.session_state.user_answers, st.session_state.score, st.session_state.q_index = {}, 0, 0
                st.rerun()
            if is_admin:
                if c2.button("🗑️", key=f"del_{t_id}"): delete_topic_from_db(t_id); st.rerun()

    with tab2:
        up = st.file_uploader("Upload Word", type=['docx'])
        if up:
            name = st.text_input("Tên bộ đề:", value=up.name.replace(".docx", ""))
            if st.button("Lưu ngay", type="primary"):
                qs = parse_docx(up)
                if qs and save_topic_to_db(name, qs):
                    st.success("Đã lưu!"); time.sleep(1); st.rerun()

# --- MÀN HÌNH LÀM BÀI ---
if 'current_topic_id' in st.session_state and st.session_state.quiz_data:
    indices = st.session_state.quiz_indices
    total = len(st.session_state.quiz_data)
    st.markdown(f"### 🎯 Câu {st.session_state.q_index + 1}/{total}")
    
    sel_n = st.selectbox("Nhảy nhanh đến câu:", range(1, total + 1), index=st.session_state.q_index)
    if sel_n != st.session_state.q_index + 1:
        st.session_state.q_index = sel_n - 1; st.rerun()

    q = st.session_state.quiz_data[indices[st.session_state.q_index]]
    st.markdown("---")
    st.markdown(f"#### {q['question']}")

    idx = indices[st.session_state.q_index]
    prev = st.session_state.user_answers.get(idx)
    if prev:
        st.radio("Bạn chọn:", q['options'], index=q['options'].index(prev), disabled=True)
        if prev == q['correct_option']: st.success(f"✅ Đúng! {q['correct_option']}")
        else: st.error(f"❌ Sai! Đáp án: {q['correct_option']}")
    else:
        with st.form(f"f_{st.session_state.q_index}"):
            choice = st.radio("Chọn:", q['options'])
            if st.form_submit_button("Chốt"):
                st.session_state.user_answers[idx] = choice
                if choice == q['correct_option']: st.session_state.score += 1; st.balloons()
                st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("⬅️ Trước") and st.session_state.q_index > 0: st.session_state.q_index -= 1; st.rerun()
    if c2.button("Sau ➡️") and st.session_state.q_index < total - 1: st.session_state.q_index += 1; st.rerun()
else:
    st.info("👈 Chọn đề từ Kho Đề để bắt đầu.")
