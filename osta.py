import streamlit as st
import os
import tempfile
import time
import hashlib
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, CSVLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from audio_recorder_streamlit import audio_recorder

st.set_page_config(
    page_title="OSTA AI | Enterprise System",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

WORLD_CLASS_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700;800&display=swap');
    
    /* الأساسيات */
    html, body, [class*="css"] {
        font-family: 'Tajawal', sans-serif !important;
        direction: rtl;
        text-align: right;
    }
    
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
        color: #f8fafc;
    }

    /* إخفاء عناصر Streamlit الافتراضية */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* الشريط الجانبي الاحترافي (Sidebar) */
    [data-testid="stSidebar"] {
        background-color: rgba(15, 23, 42, 0.6) !important;
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border-left: 1px solid rgba(255, 255, 255, 0.05);
        padding-top: 2rem;
    }
    
    /* البطاقات الزجاجية (Glassmorphism Cards) */
    .glass-card {
        background: rgba(30, 41, 59, 0.4);
        backdrop-filter: blur(12px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
        transition: transform 0.3s ease, box-shadow 0.3s ease;
    }
    .glass-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
        border: 1px solid rgba(139, 92, 246, 0.3);
    }

    /* حقول الإدخال العالمية */
    .stTextInput input, .stTextArea textarea, .stSelectbox select, .stNumberInput input {
        background-color: rgba(15, 23, 42, 0.8) !important;
        color: #e2e8f0 !important;
        border: 1px solid #334155 !important;
        border-radius: 10px !important;
        padding: 12px !important;
        transition: all 0.3s ease !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #8b5cf6 !important;
        box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2) !important;
    }

    /* الأزرار المتقدمة */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.5rem 1rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        width: 100%;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3) !important;
    }
    .stButton > button:hover {
        transform: scale(1.02) !important;
        box-shadow: 0 8px 25px rgba(139, 92, 246, 0.5) !important;
    }
    
    /* زر الخروج (أحمر) */
    .btn-logout > button {
        background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
        box-shadow: 0 4px 15px rgba(239, 68, 68, 0.3) !important;
    }

    /* القوائم الجانبية (Radio as Menu) */
    div.row-widget.stRadio > div {
        background: transparent;
        gap: 10px;
    }
    div.row-widget.stRadio > div > label {
        background-color: rgba(30, 41, 59, 0.5);
        border-radius: 8px;
        padding: 10px 15px;
        border: 1px solid transparent;
        transition: all 0.2s;
    }
    div.row-widget.stRadio > div > label:hover {
        background-color: rgba(99, 102, 241, 0.1);
        border-color: rgba(99, 102, 241, 0.3);
    }
    div.row-widget.stRadio > div > label[data-baseweb="radio"] > div:first-child {
        display: none; /* إخفاء الدائرة الافتراضية */
    }
    
    /* تخصيص التبويبات (Tabs) */
    .stTabs [data-baseweb="tab-list"] {
        background-color: rgba(15, 23, 42, 0.4);
        border-radius: 12px;
        padding: 5px;
        gap: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent;
        border-radius: 8px;
        color: #94a3b8;
        font-weight: 600;
        padding: 8px 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #334155 !important;
        color: #fff !important;
    }

    /* رسائل التنبيه */
    .stAlert {
        border-radius: 12px !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }
</style>
"""
st.markdown(WORLD_CLASS_CSS, unsafe_allow_html=True)

def init_session_state():
    defaults = {
        'logged_in': False,
        'role': None,
        # API Keys & Security
        'openai_api_key': "",
        'pinecone_api_key': "",
        'index_name': "osta-enterprise-rag",
        # LLM Settings
        'llm_model': "gpt-4o-mini",
        'temperature': 0.2,
        'system_prompt': "أنت 'أسطى كبير' مصري محترف جداً في صيانة ضواغط الهواء والتصنيع المعدني. كلامك كله بلهجة صنايعية مصرية عامية بسيطة. إجابتك يجب أن تكون في خطوات مرقمة (1، 2، 3). إذا لم تكن المعلومة في النص قل 'يا ابني دي مش عندي في الكتالوج دلوقتي'. اعتمد على [المعلومات المرفقة] فقط.",
        # RAG Settings
        'chunk_size': 1000,
        'chunk_overlap': 150,
        'k_results': 4,
        # Voice Settings
        'tts_voice': "onyx",
        # App State
        'last_audio_hash': None
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

def login(username, password):
    # في بيئة الإنتاج يتم التوصيل بـ DB، هنا محاكاة آمنة
    admin_hash = hashlib.sha256("admin2024".encode()).hexdigest()
    worker_hash = hashlib.sha256("worker".encode()).hexdigest()
    
    input_hash = hashlib.sha256(password.encode()).hexdigest()
    
    if username == "admin" and input_hash == admin_hash:
        st.session_state['logged_in'] = True
        st.session_state['role'] = "Manager"
        return True
    elif username == "worker" and input_hash == worker_hash:
        st.session_state['logged_in'] = True
        st.session_state['role'] = "Worker"
        return True
    return False

def secure_logout():
    # تصفير كل البيانات الحساسة عند الخروج
    keys_to_clear = ['openai_api_key', 'pinecone_api_key', 'logged_in', 'role']
    for key in keys_to_clear:
        if key in ['logged_in']: st.session_state[key] = False
        elif key in ['role']: st.session_state[key] = None
        else: st.session_state[key] = ""
    st.rerun()

def get_pinecone_client():
    if not st.session_state['pinecone_api_key']:
        raise ValueError("مفتاح Pinecone API مفقود. يرجى إعداده من لوحة التحكم.")
    return Pinecone(api_key=st.session_state['pinecone_api_key'])

def process_and_upload_documents(uploaded_files):
    os.environ['OPENAI_API_KEY'] = st.session_state['openai_api_key']
    pc = get_pinecone_client()
    index_name = st.session_state['index_name']
    
    # التأكد من وجود الفهرس أو إنشاؤه
    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=1536,
            metric='cosine',
            spec=ServerlessSpec(cloud='aws', region='us-east-1')
        )
        while not pc.describe_index(index_name).status['ready']:
            time.sleep(1)
            
    index = pc.Index(index_name)
    embeddings = OpenAIEmbeddings()
    vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")
    
    all_documents = []
    
    for uploaded_file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file_path = tmp_file.name
        
        loader = None
        if uploaded_file.name.endswith('.pdf'): loader = PyPDFLoader(tmp_file_path)
        elif uploaded_file.name.endswith('.txt'): loader = TextLoader(tmp_file_path, encoding='utf-8')
        elif uploaded_file.name.endswith('.docx'): loader = Docx2txtLoader(tmp_file_path)
        elif uploaded_file.name.endswith('.csv'): loader = CSVLoader(tmp_file_path, encoding='utf-8')
        
        if loader:
            documents = loader.load()
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=st.session_state['chunk_size'], 
                chunk_overlap=st.session_state['chunk_overlap']
            )
            split_docs = text_splitter.split_documents(documents)
            all_documents.extend(split_docs)
        
        os.unlink(tmp_file_path)
    
    if all_documents:
        vector_store.add_documents(all_documents)
        return len(all_documents)
    return 0

def generate_osta_response(user_query):
    os.environ['OPENAI_API_KEY'] = st.session_state['openai_api_key']
    pc = get_pinecone_client()
    
    # محاولة جلب السياق من قاعدة البيانات (إن وجدت بيانات)
    context = ""
    try:
        index = pc.Index(st.session_state['index_name'])
        embeddings = OpenAIEmbeddings()
        vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")
        docs = vector_store.similarity_search(user_query, k=st.session_state['k_results'])
        context = "\n\n".join([doc.page_content for doc in docs])
    except Exception as e:
        context = "لا توجد معلومات متوفرة في قاعدة البيانات حالياً."

    llm = ChatOpenAI(
        model_name=st.session_state['llm_model'], 
        temperature=st.session_state['temperature']
    )
    
    prompt = f"المعلومات المرفقة:\n{context}\n\nسؤال العامل: {user_query}"
    
    messages = [
        {"role": "system", "content": st.session_state['system_prompt']},
        {"role": "user", "content": prompt}
    ]
    
    response = llm.invoke(messages)
    return response.content

def transcribe_audio(audio_bytes):
    client = OpenAI(api_key=st.session_state['openai_api_key'])
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_audio:
        tmp_audio.write(audio_bytes)
        tmp_audio_path = tmp_audio.name
    
    with open(tmp_audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            language="ar"
        )
    os.unlink(tmp_audio_path)
    return transcript.text

def text_to_speech(text):
    client = OpenAI(api_key=st.session_state['openai_api_key'])
    response = client.audio.speech.create(
        model="tts-1",
        voice=st.session_state['tts_voice'],
        input=text
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
        response.stream_to_file(tmp_mp3.name)
        return tmp_mp3.name

def render_login():
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <div class="glass-card" style="text-align: center;">
            <h1 style="color: #8b5cf6; margin-bottom: 0;">OSTA AI</h1>
            <p style="color: #94a3b8; font-size: 1.1rem; margin-top: 5px;">Enterprise Maintenance RAG System</p>
            <hr style="border-color: rgba(255,255,255,0.1);">
        </div>
        """, unsafe_allow_html=True)
        
        username = st.text_input("👤 اسم المستخدم", placeholder="أدخل اسم المستخدم هنا...")
        password = st.text_input("🔒 كلمة المرور", type="password", placeholder="أدخل كلمة المرور...")
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("تسجيل الدخول للنظام 🚀"):
            if login(username, password):
                st.rerun()
            else:
                st.error("❌ خطأ في بيانات الاعتماد. الدخول مرفوض.")
        
        with st.expander("ℹ️ بيانات الدخول التجريبية"):
            st.code("المدير:\nUser: admin\nPass: admin2024\n\nالعامل:\nUser: worker\nPass: worker")

def render_manager_dashboard():
    # الشريط الجانبي
    with st.sidebar:
        st.markdown("### 👨‍💻 إدارة النظام العالمية")
        st.markdown("<hr style='border-color: rgba(255,255,255,0.1); margin-top:0;'>", unsafe_allow_html=True)
        
        menu_selection = st.radio(
            "اختر القسم:",
            ["⚙️ الإعدادات المتقدمة والأمان", "📚 إدارة قاعدة المعرفة (RAG)", "🧪 مختبر الأسطى (Test)"]
        )
        
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<div class='btn-logout'>", unsafe_allow_html=True)
        if st.button("🚪 إغلاق الجلسة أمنياً"):
            secure_logout()
        st.markdown("</div>", unsafe_allow_html=True)

    # القسم الأول: الإعدادات والأمان
    if menu_selection == "⚙️ الإعدادات المتقدمة والأمان":
        st.markdown("<h2>⚙️ لوحة التحكم الشاملة والأمان</h2>", unsafe_allow_html=True)
        
        tab1, tab2, tab3 = st.tabs(["🔐 مفاتيح الـ API والاتصال", "🧠 إعدادات العقل (LLM & Voice)", "🗂️ هندسة البيانات (RAG)"])
        
        with tab1:
            st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
            st.markdown("#### 🛡️ بوابات الاتصال الآمنة (Secure Connections)")
            st.info("يتم تشفير المفاتيح أثناء الجلسة وتُمسح بمجرد تسجيل الخروج.")
            openai_key = st.text_input("🔑 OpenAI API Key", value=st.session_state['openai_api_key'], type="password")
            pinecone_key = st.text_input("🔑 Pinecone API Key", value=st.session_state['pinecone_api_key'], type="password")
            index_name = st.text_input("🗄️ اسم الفهرس (Index Name)", value=st.session_state['index_name'])
            
            if st.button("💾 حفظ الإعدادات الأمنية"):
                st.session_state['openai_api_key'] = openai_key
                st.session_state['pinecone_api_key'] = pinecone_key
                st.session_state['index_name'] = index_name
                st.success("✅ تم تحديث بروتوكولات الاتصال بنجاح.")
            st.markdown("</div>", unsafe_allow_html=True)

        with tab2:
            st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### 🤖 محرك اللغة (LLM)")
                st.session_state['llm_model'] = st.selectbox("الموديل المستخدَم:", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"], index=1)
                st.session_state['temperature'] = st.slider("درجة الإبداع (Temperature):", 0.0, 1.0, st.session_state['temperature'], 0.1)
            with col2:
                st.markdown("#### 🎙️ المحرك الصوتي (TTS)")
                st.session_state['tts_voice'] = st.selectbox("صوت الأسطى:", ["alloy", "echo", "fable", "onyx", "nova", "shimmer"], index=3, help="Onyx هو الصوت الأجش المناسب للأسطى")
            
            st.markdown("#### 🎭 شخصية الذكاء الاصطناعي (System Prompt)")
            st.session_state['system_prompt'] = st.text_area("تعليمات التوجيه:", value=st.session_state['system_prompt'], height=150)
            st.markdown("</div>", unsafe_allow_html=True)

        with tab3:
            st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
            st.markdown("#### ✂️ إعدادات تقطيع النصوص ومعالجتها")
            st.session_state['chunk_size'] = st.number_input("حجم المقطع (Chunk Size):", min_value=100, max_value=4000, value=st.session_state['chunk_size'])
            st.session_state['chunk_overlap'] = st.number_input("نسبة التداخل (Chunk Overlap):", min_value=0, max_value=1000, value=st.session_state['chunk_overlap'])
            st.session_state['k_results'] = st.slider("عدد الوثائق المسترجعة (K-Results):", 1, 10, st.session_state['k_results'])
            st.markdown("</div>", unsafe_allow_html=True)

    # القسم الثاني: إدارة المعرفة
    elif menu_selection == "📚 إدارة قاعدة المعرفة (RAG)":
        st.markdown("<h2>📚 محرك تغذية البيانات (Vector Database)</h2>", unsafe_allow_html=True)
        
        if not st.session_state['openai_api_key'] or not st.session_state['pinecone_api_key']:
            st.warning("⚠️ يرجى إعداد مفاتيح API في قسم الإعدادات أولاً للتمكن من رفع البيانات.")
            return

        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        uploaded_files = st.file_uploader("📂 ارفع كتالوجات الصيانة والوثائق (PDF, TXT, DOCX, CSV)", accept_multiple_files=True)
        
        if st.button("🚀 تدريب المحرك بالوثائق (Process & Embed)"):
            if uploaded_files:
                with st.spinner("جاري تحليل النصوص، تحويلها لمتجهات، وضخها في Pinecone..."):
                    try:
                        chunks_count = process_and_upload_documents(uploaded_files)
                        st.success(f"✅ تمت العملية بنجاح. تم ضخ {chunks_count} مقطع في الفهرس [{st.session_state['index_name']}].")
                    except Exception as e:
                        st.error(f"❌ خطأ تقني أثناء المعالجة: {e}")
            else:
                st.warning("الرجاء إرفاق ملفات أولاً.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='glass-card' style='border-color: rgba(239, 68, 68, 0.3);'>", unsafe_allow_html=True)
        st.markdown("#### 🗑️ منطقة الخطر (Danger Zone)")
        st.write("حذف جميع البيانات المتجهة الخاصة بهذا الفهرس نهائياً من سحابة Pinecone.")
        if st.button("🔥 تصفير الذاكرة بالكامل (Delete Index)"):
            try:
                pc = get_pinecone_client()
                if st.session_state['index_name'] in pc.list_indexes().names():
                    pc.delete_index(st.session_state['index_name'])
                    st.success("تم تدمير الفهرس بنجاح. سيتم إنشاء واحد جديد عند الرفع القادم.")
                else:
                    st.info("الفهرس غير موجود بالفعل.")
            except Exception as e:
                st.error(f"خطأ: {e}")
        st.markdown("</div>", unsafe_allow_html=True)

    # القسم الثالث: الشات
    elif menu_selection == "🧪 مختبر الأسطى (Test)":
        st.markdown("<h2>🧪 مختبر النظام (Text QA)</h2>", unsafe_allow_html=True)
        if not st.session_state['openai_api_key']:
            st.warning("⚠️ أدخل مفتاح OpenAI في الإعدادات أولاً.")
            return
            
        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
        user_input = st.text_area("اطرح سؤالاً لاختبار دقة استرجاع البيانات والشخصية المبرمجة:")
        if st.button("إرسال استعلام ⚡"):
            if user_input:
                with st.spinner("يقوم محرك RAG بالبحث والتوليد..."):
                    try:
                        answer = generate_osta_response(user_input)
                        st.markdown("<hr style='border-color: rgba(255,255,255,0.1);'>", unsafe_allow_html=True)
                        st.markdown("### 🤖 رد النظام:")
                        st.write(answer)
                    except Exception as e:
                        st.error(f"خطأ أثناء التوليد: {e}")
        st.markdown("</div>", unsafe_allow_html=True)

def render_worker_view():
    # إخفاء كامل للشريط الجانبي للعامل للتركيز فقط على الميكروفون
    st.markdown("""
        <style>
            [data-testid="collapsedControl"] {display: none;}
            [data-testid="stSidebar"] {display: none;}
        </style>
    """, unsafe_allow_html=True)
    
    col_out1, col_out2, col_out3 = st.columns([1, 10, 1])
    with col_out3:
        if st.button("خروج"):
            secure_logout()
            
    st.markdown("<h1 style='text-align: center; color: #00f3ff; font-size: 3.5rem; margin-top: 2rem;'>🎙️ اسأل الأسطى</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.5rem; color: #94a3b8;'>دوس على المايك تحت واتكلم عن المشكلة اللي عندك</p>", unsafe_allow_html=True)
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if not st.session_state['openai_api_key'] or not st.session_state['pinecone_api_key']:
            st.error("⚠️ النظام حالياً غير متصل بالخوادم. يرجى إبلاغ المهندس المسئول.")
            return

        st.markdown("<div style='display:flex; justify-content:center;'>", unsafe_allow_html=True)
        audio_bytes = audio_recorder(
            text="🔴 تسجيل",
            recording_color="#ef4444",
            neutral_color="#8b5cf6",
            icon_size="4x"
        )
        st.markdown("</div>", unsafe_allow_html=True)
        
        if audio_bytes:
            current_hash = hashlib.md5(audio_bytes).hexdigest()
            if current_hash != st.session_state['last_audio_hash']:
                st.session_state['last_audio_hash'] = current_hash
                
                with st.spinner("🎧 الأسطى بيسمعك..."):
                    try:
                        # 1. تفريغ الصوت
                        user_text = transcribe_audio(audio_bytes)
                        
                        st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
                        st.markdown(f"<h4 style='color:#cbd5e1;'>🗣️ أنت قلت:</h4> <p style='font-size:1.2rem;'>{user_text}</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
                        
                        # 2. توليد الرد
                        with st.spinner("🧠 الأسطى بيفكر في الحل..."):
                            ai_answer = generate_osta_response(user_text)
                        
                        # 3. تحويل لصوت
                        with st.spinner("🔊 جاري تجهيز الرد الصوتي..."):
                            audio_path = text_to_speech(ai_answer)
                        
                        st.success("✅ الرد جاهز!")
                        st.audio(audio_path, format="audio/mp3", autoplay=True)
                        
                        st.markdown("<div class='glass-card' style='border-left: 4px solid #8b5cf6;'>", unsafe_allow_html=True)
                        st.markdown("### 📋 الرد المكتوب:")
                        st.write(ai_answer)
                        st.markdown("</div>", unsafe_allow_html=True)
                        
                    except Exception as e:
                        st.error(f"❌ معلش حصل مشكلة في الاتصال: {e}")

def main():
    if not st.session_state['logged_in']:
        render_login()
    else:
        if st.session_state['role'] == "Manager":
            render_manager_dashboard()
        elif st.session_state['role'] == "Worker":
            render_worker_view()

if __name__ == "__main__":
    main()
