import streamlit as st
import os
import tempfile
import time
import hashlib
import sqlite3
import base64
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import streamlit.components.v1 as components

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="OSTA AI | Enterprise System",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 1. إعداد قاعدة البيانات (Database Setup)
# ==========================================
@st.cache_resource
def init_db():
    conn = sqlite3.connect('osta_enterprise.db', check_same_thread=False)
    c = conn.cursor()
    # جداول النظام
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS chat_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT, created_at DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT, content TEXT, image_b64 TEXT, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, title TEXT, content TEXT, timestamp DATETIME)')
    
    # المستخدمين الافتراضيين
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
              ('admin', hashlib.sha256(b'admin2024').hexdigest(), 'Manager'))
    c.execute("INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)", 
              ('worker', hashlib.sha256(b'worker').hexdigest(), 'Worker'))
    
    # الإعدادات الافتراضية
    default_settings = {
        'llm_provider': 'OpenAI',
        'llm_model': 'gpt-4o-mini',
        'temperature': '0.2',
        'chunk_size': '1000',
        'chunk_overlap': '150',
        'k_results': '4',
        'tts_voice': 'onyx',
        'use_openai_tts': 'True',
        'system_prompt': "أنت 'أسطى كبير' مصري محترف جداً في صيانة ضواغط الهواء والتصنيع المعدني. كلامك كله بلهجة صنايعية مصرية عامية بسيطة. إجابتك يجب أن تكون في خطوات مرقمة (1، 2، 3). إذا لم تكن المعلومة في النص قل 'يا ابني دي مش عندي في الكتالوج دلوقتي'. اعتمد على [المعلومات المرفقة] فقط.",
        'index_name': 'osta-enterprise-rag'
    }
    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    return conn

conn = init_db()

# دوال مساعدة لقاعدة البيانات
def get_setting(key, default=""):
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key=?", (key,))
    res = c.fetchone()
    return res[0] if res else default

def set_setting(key, value):
    c = conn.cursor()
    c.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

# ==========================================
# 2. مهام الخلفية والتحليل التلقائي (Cron Jobs)
# ==========================================
def cron_fault_analysis():
    c = conn.cursor()
    yesterday = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("SELECT content FROM messages WHERE role='user' AND timestamp >= datetime('now', '-1 day')")
    msgs = c.fetchall()
    
    keywords = ['عطل', 'مشكلة', 'حرارة', 'تسريب', 'صوت', 'دخان', 'باظ', 'وقف']
    fault_count = sum(1 for m in msgs if any(w in str(m[0]) for w in keywords))
    
    if fault_count > 0:
        c.execute("INSERT INTO alerts (title, content, timestamp) VALUES (?, ?, datetime('now'))",
                  ("تحليل الأعطال اليومي", f"تم رصد {fault_count} بلاغات من العمال تحتوي على كلمات تشير لأعطال محتملة خلال آخر 24 ساعة. يرجى مراجعة سجلات المحادثة."))
        conn.commit()

@st.cache_resource
def start_scheduler():
    scheduler = BackgroundScheduler()
    # جدولة المهمة لتعمل كل يوم الساعة 2 صباحاً
    scheduler.add_job(cron_fault_analysis, 'cron', hour=2)
    scheduler.start()
    return scheduler

start_scheduler()

# ==========================================
# 3. الاعتماديات المتأخرة والـ LLMs
# ==========================================
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from audio_recorder_streamlit import audio_recorder

def get_llm():
    provider = get_setting('llm_provider')
    temp = float(get_setting('temperature', 0.2))
    
    if provider == 'Google Gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=get_setting('gemini_model', 'gemini-1.5-flash'), 
                                      google_api_key=get_setting('google_api_key'), temperature=temp)
    elif provider == 'Anthropic':
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=get_setting('anthropic_model', 'claude-3-haiku-20240307'), 
                             api_key=get_setting('anthropic_api_key'), temperature=temp)
    elif provider == 'Custom URL':
        return ChatOpenAI(model=get_setting('custom_model', 'local-model'), 
                          openai_api_base=get_setting('custom_base_url'), 
                          openai_api_key=get_setting('custom_api_key', 'dummy'), temperature=temp)
    else: # Default OpenAI
        return ChatOpenAI(model=get_setting('llm_model', 'gpt-4o-mini'), 
                          openai_api_key=get_setting('openai_api_key'), temperature=temp)

# ==========================================
# 4. التصميم والواجهة (World-Class UI/UX)
# ==========================================
WORLD_CLASS_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Tajawal', sans-serif !important;
        direction: rtl; text-align: right;
    }
    
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        color: #f8fafc;
    }

    #MainMenu, footer, header {visibility: hidden;}
    
    [data-testid="stSidebar"] {
        background-color: rgba(15, 23, 42, 0.7) !important;
        backdrop-filter: blur(20px);
        border-left: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    .glass-card {
        background: rgba(30, 41, 59, 0.4);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        margin-bottom: 20px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .glass-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
        border-color: rgba(139, 92, 246, 0.3);
    }
    
    .metric-box {
        text-align: center;
        padding: 20px;
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.1) 0%, rgba(139, 92, 246, 0.1) 100%);
        border-radius: 12px;
        border: 1px solid rgba(139, 92, 246, 0.2);
    }
    .metric-value { font-size: 2.5rem; font-weight: 800; color: #00f3ff; }
    .metric-title { font-size: 1.1rem; color: #94a3b8; }

    .stTextInput input, .stTextArea textarea, .stSelectbox select, .stNumberInput input {
        background-color: rgba(15, 23, 42, 0.8) !important;
        color: #e2e8f0 !important;
        border: 1px solid #334155 !important;
        border-radius: 10px !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus { border-color: #8b5cf6 !important; }

    .stButton > button {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
        color: white !important; border: none !important; border-radius: 10px !important;
        font-weight: 700 !important; transition: all 0.3s !important; width: 100%;
    }
    .stButton > button:hover { transform: scale(1.02) !important; box-shadow: 0 8px 25px rgba(139, 92, 246, 0.5) !important; }
    .btn-logout > button { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important; }
    
    .chat-bubble-user {
        background: rgba(99, 102, 241, 0.15); border-radius: 15px 15px 0 15px;
        padding: 15px; margin-bottom: 10px; border: 1px solid rgba(99, 102, 241, 0.3);
    }
    .chat-bubble-ai {
        background: rgba(30, 41, 59, 0.6); border-radius: 15px 15px 15px 0;
        padding: 15px; margin-bottom: 10px; border: 1px solid rgba(255, 255, 255, 0.05);
    }
</style>
"""
st.markdown(WORLD_CLASS_CSS, unsafe_allow_html=True)

# ==========================================
# 5. دوال مساعدة للـ Audio و RAG
# ==========================================
def fallback_tts(text):
    # محرك نطق مجاني (Web Speech API) متوافق مع المتصفحات
    js = f"""
    <script>
        const text = `{text.replace('`', '').replace('"', '')}`;
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = "ar-EG";
        utterance.rate = 0.9;
        window.speechSynthesis.speak(utterance);
    </script>
    """
    components.html(js, height=0, width=0)

def speak_text(text):
    api_key = get_setting('openai_api_key')
    if api_key and get_setting('use_openai_tts') == 'True':
        try:
            client = OpenAI(api_key=api_key)
            response = client.audio.speech.create(
                model="tts-1", voice=get_setting('tts_voice', 'onyx'), input=text
            )
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
                response.stream_to_file(tmp_mp3.name)
                st.audio(tmp_mp3.name, format="audio/mp3", autoplay=True)
        except Exception:
            fallback_tts(text)
    else:
        fallback_tts(text)

def transcribe_audio(audio_bytes):
    api_key = get_setting('openai_api_key')
    if not api_key: return "تحويل الصوت لنص يتطلب OpenAI API Key."
    client = OpenAI(api_key=api_key)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
        tmp_audio.write(audio_bytes)
        tmp_audio_path = tmp_audio.name
    with open(tmp_audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="ar")
    os.unlink(tmp_audio_path)
    return transcript.text

def process_documents(uploaded_files):
    os.environ['OPENAI_API_KEY'] = get_setting('openai_api_key')
    pc = Pinecone(api_key=get_setting('pinecone_api_key'))
    idx_name = get_setting('index_name')
    if idx_name not in pc.list_indexes().names():
        pc.create_index(name=idx_name, dimension=1536, metric='cosine', spec=ServerlessSpec(cloud='aws', region='us-east-1'))
        while not pc.describe_index(idx_name).status['ready']: time.sleep(1)
    
    index = pc.Index(idx_name)
    vector_store = PineconeVectorStore(index=index, embedding=OpenAIEmbeddings(), text_key="text")
    all_docs = []
    
    for uf in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uf.name.split('.')[-1]}") as tmp:
            tmp.write(uf.getvalue())
            tmp_path = tmp.name
        
        loader = None
        if uf.name.endswith('.pdf'): loader = PyPDFLoader(tmp_path)
        elif uf.name.endswith('.txt'): loader = TextLoader(tmp_path, encoding='utf-8')
        elif uf.name.endswith('.docx'): loader = Docx2txtLoader(tmp_path)
        
        if loader:
            docs = loader.load()
            splitter = RecursiveCharacterTextSplitter(chunk_size=int(get_setting('chunk_size', 1000)), chunk_overlap=int(get_setting('chunk_overlap', 150)))
            all_docs.extend(splitter.split_documents(docs))
        os.unlink(tmp_path)
        
    if all_docs:
        vector_store.add_documents(all_docs)
        return len(all_docs)
    return 0

# ==========================================
# 6. واجهات المستخدم (Views)
# ==========================================
if 'user_id' not in st.session_state:
    st.session_state.update({'logged_in': False, 'role': None, 'user_id': None, 'username': None, 'current_session': None})

def render_login():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""<div class="glass-card" style="text-align: center;">
            <h1 style="color: #8b5cf6;">OSTA AI Enterprise</h1>
            <p style="color: #94a3b8;">منصة التحليل والصيانة المعتمدة على الذكاء الاصطناعي</p>
            <hr style="border-color: rgba(255,255,255,0.1);"></div>""", unsafe_allow_html=True)
        
        user = st.text_input("👤 اسم المستخدم")
        pwd = st.text_input("🔒 كلمة المرور", type="password")
        if st.button("تسجيل الدخول 🚀"):
            c = conn.cursor()
            c.execute("SELECT id, role FROM users WHERE username=? AND password=?", (user, hashlib.sha256(pwd.encode()).hexdigest()))
            res = c.fetchone()
            if res:
                st.session_state.update({'logged_in': True, 'user_id': res[0], 'role': res[1], 'username': user})
                st.rerun()
            else:
                st.error("❌ بيانات الدخول غير صحيحة.")

def render_admin_dashboard():
    with st.sidebar:
        st.markdown(f"### 👋 أهلاً، {st.session_state['username']}")
        menu = st.radio("القائمة:", ["📊 لوحة التحكم والإحصائيات", "👥 إدارة المستخدمين (Tenants)", "⚙️ الإعدادات والـ APIs", "📚 محرك المعرفة (RAG)"])
        st.markdown("<div class='btn-logout'>", unsafe_allow_html=True)
        if st.button("🚪 تسجيل الخروج"):
            st.session_state.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    if menu == "📊 لوحة التحكم والإحصائيات":
        st.markdown("<h2>📊 نظرة عامة على النظام</h2>", unsafe_allow_html=True)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users WHERE role='Worker'")
        workers_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM messages")
        msgs_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM alerts")
        alerts_count = c.fetchone()[0]
        
        col1, col2, col3 = st.columns(3)
        with col1: st.markdown(f"<div class='metric-box'><div class='metric-value'>{workers_count}</div><div class='metric-title'>العمال المسجلين</div></div>", unsafe_allow_html=True)
        with col2: st.markdown(f"<div class='metric-box'><div class='metric-value'>{msgs_count}</div><div class='metric-title'>إجمالي الرسائل</div></div>", unsafe_allow_html=True)
        with col3: st.markdown(f"<div class='metric-box'><div class='metric-value'>{alerts_count}</div><div class='metric-title'>تنبيهات الأعطال التلقائية</div></div>", unsafe_allow_html=True)
        
        st.markdown("<br><h3>🚨 أحدث تنبيهات النظام (Cron Alerts)</h3>", unsafe_allow_html=True)
        c.execute("SELECT title, content, timestamp FROM alerts ORDER BY timestamp DESC LIMIT 5")
        alerts = c.fetchall()
        for a in alerts:
            st.error(f"**{a[2]} | {a[0]}**\n\n{a[1]}")
            
    elif menu == "👥 إدارة المستخدمين (Tenants)":
        st.markdown("<h2>👥 إدارة فرق العمل</h2>", unsafe_allow_html=True)
        with st.form("add_user"):
            nu = st.text_input("اسم المستخدم الجديد")
            np = st.text_input("كلمة المرور", type="password")
            nr = st.selectbox("الصلاحية", ["Worker", "Manager"])
            if st.form_submit_button("إضافة مستخدم"):
                try:
                    c = conn.cursor()
                    c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (nu, hashlib.sha256(np.encode()).hexdigest(), nr))
                    conn.commit()
                    st.success("تم الإضافة بنجاح!")
                except sqlite3.IntegrityError:
                    st.error("اسم المستخدم موجود بالفعل.")
        
        st.markdown("### المستخدمين الحاليين")
        c = conn.cursor()
        users = c.execute("SELECT id, username, role FROM users").fetchall()
        for u in users:
            col1, col2 = st.columns([4, 1])
            col1.write(f"🆔 **{u[1]}** ({u[2]})")
            if u[1] != 'admin' and col2.button("حذف", key=f"del_{u[0]}"):
                c.execute("DELETE FROM users WHERE id=?", (u[0],))
                conn.commit()
                st.rerun()

    elif menu == "⚙️ الإعدادات والـ APIs":
        st.markdown("<h2>⚙️ إعدادات الذكاء الاصطناعي</h2>", unsafe_allow_html=True)
        t1, t2 = st.tabs(["مقدمي الخدمة (Providers)", "شخصية الأسطى و TTS"])
        with t1:
            provider = st.selectbox("المحرك الأساسي (LLM Provider)", ["OpenAI", "Google Gemini", "Anthropic", "Custom URL"], index=["OpenAI", "Google Gemini", "Anthropic", "Custom URL"].index(get_setting('llm_provider', 'OpenAI')))
            set_setting('llm_provider', provider)
            
            if provider == "OpenAI":
                set_setting('openai_api_key', st.text_input("OpenAI API Key", get_setting('openai_api_key'), type="password"))
                set_setting('llm_model', st.selectbox("Model", ["gpt-4o", "gpt-4o-mini"], index=0 if get_setting('llm_model')=='gpt-4o' else 1))
            elif provider == "Google Gemini":
                set_setting('google_api_key', st.text_input("Google API Key", get_setting('google_api_key'), type="password"))
                set_setting('gemini_model', st.text_input("Model Name", get_setting('gemini_model', 'gemini-1.5-flash')))
            elif provider == "Anthropic":
                set_setting('anthropic_api_key', st.text_input("Anthropic API Key", get_setting('anthropic_api_key'), type="password"))
                set_setting('anthropic_model', st.text_input("Model Name", get_setting('anthropic_model', 'claude-3-haiku-20240307')))
            elif provider == "Custom URL":
                set_setting('custom_base_url', st.text_input("Base URL", get_setting('custom_base_url', 'http://localhost:11434/v1')))
                set_setting('custom_api_key', st.text_input("API Key (Optional)", get_setting('custom_api_key', 'dummy'), type="password"))
                set_setting('custom_model', st.text_input("Model Name", get_setting('custom_model', 'llama3')))
                
            set_setting('pinecone_api_key', st.text_input("Pinecone API Key (For RAG)", get_setting('pinecone_api_key'), type="password"))
            set_setting('temperature', st.slider("Temperature", 0.0, 1.0, float(get_setting('temperature', 0.2))))
            
        with t2:
            set_setting('system_prompt', st.text_area("System Prompt", get_setting('system_prompt'), height=150))
            set_setting('use_openai_tts', st.checkbox("استخدام OpenAI للصوت (إن وجد، وإلا سيستخدم المجاني)", value=(get_setting('use_openai_tts', 'True')=='True')))
            set_setting('tts_voice', st.selectbox("نبرة الصوت", ["onyx", "echo", "alloy"], index=0))

    elif menu == "📚 محرك المعرفة (RAG)":
        st.markdown("<h2>📚 إدارة الداتا وتدريب المحرك</h2>", unsafe_allow_html=True)
        set_setting('index_name', st.text_input("Pinecone Index Name", get_setting('index_name')))
        col1, col2 = st.columns(2)
        set_setting('chunk_size', col1.number_input("Chunk Size", value=int(get_setting('chunk_size', 1000))))
        set_setting('k_results', col2.number_input("K-Results", value=int(get_setting('k_results', 4))))
        
        uf = st.file_uploader("ارفع الملفات", accept_multiple_files=True)
        if st.button("معالجة ورفع لـ Pinecone"):
            if uf and get_setting('pinecone_api_key'):
                with st.spinner("جاري المعالجة..."):
                    cnt = process_documents(uf)
                    st.success(f"تم رفع {cnt} مقطع!")
            else:
                st.error("تأكد من إرفاق ملفات وإدخال مفتاح Pinecone.")

def render_worker_chat():
    c = conn.cursor()
    uid = st.session_state['user_id']
    
    # إدارة الجلسات في الشريط الجانبي
    with st.sidebar:
        st.markdown("### 🗂️ سجل المحادثات")
        if st.button("➕ محادثة جديدة"):
            c.execute("INSERT INTO chat_sessions (user_id, title, created_at) VALUES (?, ?, datetime('now'))", (uid, "استشارة جديدة"))
            conn.commit()
            st.session_state['current_session'] = c.lastrowid
            st.rerun()
            
        sessions = c.execute("SELECT id, title FROM chat_sessions WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
        if not sessions:
            st.info("لا توجد محادثات سابقة.")
            
        for sid, title in sessions:
            col1, col2 = st.columns([4, 1])
            if col1.button(f"💬 {title}", key=f"sess_{sid}"):
                st.session_state['current_session'] = sid
                st.rerun()
            if col2.button("🗑️", key=f"del_{sid}"):
                c.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
                c.execute("DELETE FROM messages WHERE session_id=?", (sid,))
                conn.commit()
                if st.session_state['current_session'] == sid: st.session_state['current_session'] = None
                st.rerun()
                
        st.markdown("<div class='btn-logout'>", unsafe_allow_html=True)
        if st.button("تسجيل خروج"):
            st.session_state.clear()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    # إنشاء جلسة افتراضية إذا لم تكن موجودة
    if not st.session_state['current_session']:
        if sessions:
            st.session_state['current_session'] = sessions[0][0]
        else:
            c.execute("INSERT INTO chat_sessions (user_id, title, created_at) VALUES (?, ?, datetime('now'))", (uid, "استشارة جديدة"))
            conn.commit()
            st.session_state['current_session'] = c.lastrowid

    sid = st.session_state['current_session']
    
    # عرض الرسائل السابقة
    st.markdown("<h2>🛠️ ورشة الأسطى للذكاء الاصطناعي</h2>", unsafe_allow_html=True)
    msgs = c.execute("SELECT role, content, image_b64 FROM messages WHERE session_id=? ORDER BY timestamp ASC", (sid,)).fetchall()
    
    for role, content, img_b64 in msgs:
        if role == 'user':
            with st.chat_message("user"):
                st.write(content)
                if img_b64: st.image(base64.b64decode(img_b64))
        else:
            with st.chat_message("assistant"):
                st.write(content)

    # أدوات الإدخال (صوت، صورة، نص)
    st.markdown("---")
    col_mic, col_cam, col_txt = st.columns([1, 1, 3])
    
    audio_bytes = None
    with col_mic: audio_bytes = audio_recorder("🔴 سجل صوت", icon_size="2x")
    with col_cam: img_file = st.camera_input("📸 صور العطل", label_visibility="collapsed")
    
    user_text = st.chat_input("أو اكتب مشكلتك هنا...")
    
    prompt = user_text
    if audio_bytes and get_setting('openai_api_key'):
        with st.spinner("جاري تفريغ الصوت..."): prompt = transcribe_audio(audio_bytes)
        
    if prompt or img_file:
        img_b64 = base64.b64encode(img_file.getvalue()).decode() if img_file else None
        
        # حفظ وعرض رسالة المستخدم
        with st.chat_message("user"):
            st.write(prompt)
            if img_file: st.image(img_file)
        c.execute("INSERT INTO messages (session_id, role, content, image_b64, timestamp) VALUES (?, ?, ?, ?, datetime('now'))", (sid, 'user', prompt, img_b64))
        conn.commit()
        
        # جلب السياق من Pinecone
        context = ""
        if get_setting('pinecone_api_key'):
            try:
                os.environ['OPENAI_API_KEY'] = get_setting('openai_api_key')
                pc = Pinecone(api_key=get_setting('pinecone_api_key'))
                idx = pc.Index(get_setting('index_name'))
                vs = PineconeVectorStore(index=idx, embedding=OpenAIEmbeddings(), text_key="text")
                docs = vs.similarity_search(prompt, k=int(get_setting('k_results', 4)))
                context = "\n\n".join([d.page_content for d in docs])
            except: pass

        # تجهيز الرسالة للمحرك
        sys_msg = get_setting('system_prompt')
        full_prompt = f"المعلومات المرفقة:\n{context}\n\nسؤال العامل: {prompt}"
        
        lc_msgs = [{"role": "system", "content": sys_msg}]
        if img_b64:
            lc_msgs.append({"role": "user", "content": [{"type": "text", "text": full_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}]})
        else:
            lc_msgs.append({"role": "user", "content": full_prompt})

        # توليد الرد بشكل حي (Streaming)
        with st.chat_message("assistant"):
            try:
                llm = get_llm()
                # st.write_stream يعرض الكلمات تباعاً
                answer = st.write_stream(llm.stream(lc_msgs)) 
                
                c.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, datetime('now'))", (sid, 'assistant', answer))
                conn.commit()
                
                # نطق الرد
                speak_text(answer)
                
            except Exception as e:
                st.error(f"خطأ في محرك الذكاء الاصطناعي: {e}")

def main():
    if not st.session_state['logged_in']:
        render_login()
    else:
        if st.session_state['role'] == "Manager":
            render_admin_dashboard()
        elif st.session_state['role'] == "Worker":
            render_worker_chat()

if __name__ == "__main__":
    main()
