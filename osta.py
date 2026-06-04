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

# ==========================================
# إعدادات الصفحة الأساسية
# ==========================================
st.set_page_config(
    page_title="نظام الأسطى - صيانة ضواغط الهواء",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# CSS - Cyberpunk / Neon Theme (RTL)
# ==========================================
CYBERPUNK_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;700;900&display=swap');
    
    /* إعدادات الاتجاه والخلفية الأساسية */
    .stApp {
        background-color: #0a0a10;
        color: #e0e0e0;
        font-family: 'Cairo', sans-serif;
        direction: rtl;
        text-align: right;
    }
    
    /* تخصيص الشريط الجانبي */
    [data-testid="stSidebar"] {
        background-color: #11111a;
        border-left: 2px solid #8a2be2;
        box-shadow: -5px 0 15px rgba(138, 43, 226, 0.3);
    }
    
    /* الأزرار النيون (Cyan & Purple) */
    .stButton > button {
        background-color: transparent !important;
        color: #00f3ff !important;
        border: 2px solid #00f3ff !important;
        border-radius: 8px !important;
        box-shadow: 0 0 10px rgba(0, 243, 255, 0.4), inset 0 0 5px rgba(0, 243, 255, 0.2) !important;
        font-weight: 700 !important;
        transition: all 0.3s ease-in-out !important;
        width: 100%;
    }
    .stButton > button:hover {
        background-color: #00f3ff !important;
        color: #0a0a10 !important;
        box-shadow: 0 0 20px rgba(0, 243, 255, 0.8), inset 0 0 10px rgba(0, 243, 255, 0.5) !important;
    }
    
    /* حقول الإدخال */
    .stTextInput input, .stTextArea textarea, .stSelectbox select {
        background-color: #1a1a24 !important;
        color: #00f3ff !important;
        border: 1px solid #8a2be2 !important;
        border-radius: 5px !important;
        box-shadow: inset 0 0 5px rgba(138, 43, 226, 0.3) !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #00f3ff !important;
        box-shadow: 0 0 10px rgba(0, 243, 255, 0.5) !important;
    }
    
    /* العناوين */
    h1, h2, h3 {
        color: #e81cff !important;
        text-shadow: 0 0 10px rgba(232, 28, 255, 0.5);
    }
    
    /* تخصيص رفع الملفات */
    [data-testid="stFileUploadDropzone"] {
        background-color: #11111a !important;
        border: 2px dashed #8a2be2 !important;
        border-radius: 10px !important;
    }
    [data-testid="stFileUploadDropzone"]:hover {
        border-color: #00f3ff !important;
        background-color: #1a1a24 !important;
    }
    
    /* رسائل التنبيه والنجاح */
    .stAlert {
        background-color: #1a1a24 !important;
        border: 1px solid #8a2be2 !important;
        color: #fff !important;
    }
    
    /* إخفاء القائمة العلوية لـ Streamlit لمظهر أكثر احترافية */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
"""
st.markdown(CYBERPUNK_CSS, unsafe_allow_html=True)

# ==========================================
# إدارة حالة الجلسة (Session State)
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'role' not in st.session_state:
    st.session_state['role'] = None
if 'openai_api_key' not in st.session_state:
    st.session_state['openai_api_key'] = ""
if 'pinecone_api_key' not in st.session_state:
    st.session_state['pinecone_api_key'] = ""
if 'pinecone_env' not in st.session_state:
    st.session_state['pinecone_env'] = "gcp-starter"
if 'index_name' not in st.session_state:
    st.session_state['index_name'] = "osta-rag-system"
if 'last_audio_hash' not in st.session_state:
    st.session_state['last_audio_hash'] = None

# ==========================================
# وظائف أساسية (Core Functions)
# ==========================================
def login_user(username, password):
    # نظام صلاحيات مبسط للأغراض التجريبية في بيئة الإنتاج
    if username == "admin" and password == "admin123":
        st.session_state['logged_in'] = True
        st.session_state['role'] = "Manager"
        return True
    elif username == "worker" and password == "worker123":
        st.session_state['logged_in'] = True
        st.session_state['role'] = "Worker"
        return True
    return False

def logout():
    for key in ['logged_in', 'role']:
        st.session_state[key] = False if key == 'logged_in' else None
    st.rerun()

def get_pinecone_client():
    if not st.session_state['pinecone_api_key']:
        raise ValueError("الرجاء إعداد Pinecone API Key في الإعدادات.")
    return Pinecone(api_key=st.session_state['pinecone_api_key'])

def ensure_pinecone_index(pc):
    index_name = st.session_state['index_name']
    if index_name not in pc.list_indexes().names():
        pc.create_index(
            name=index_name,
            dimension=1536, # بُعد OpenAI text-embedding-ada-002
            metric='cosine',
            spec=ServerlessSpec(
                cloud='aws',
                region='us-east-1' # يمكن تخصيصه حسب الحاجة
            )
        )
        # انتظار حتى يتم إنشاء الفهرس
        while not pc.describe_index(index_name).status['ready']:
            time.sleep(1)
    return pc.Index(index_name)

def process_documents(uploaded_files):
    os.environ['OPENAI_API_KEY'] = st.session_state['openai_api_key']
    pc = get_pinecone_client()
    index = ensure_pinecone_index(pc)
    
    embeddings = OpenAIEmbeddings()
    vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")
    
    all_documents = []
    
    for uploaded_file in uploaded_files:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_file_path = tmp_file.name
        
        loader = None
        if uploaded_file.name.endswith('.pdf'):
            loader = PyPDFLoader(tmp_file_path)
        elif uploaded_file.name.endswith('.txt'):
            loader = TextLoader(tmp_file_path, encoding='utf-8')
        elif uploaded_file.name.endswith('.docx'):
            loader = Docx2txtLoader(tmp_file_path)
        elif uploaded_file.name.endswith('.csv'):
            loader = CSVLoader(tmp_file_path, encoding='utf-8')
        
        if loader:
            documents = loader.load()
            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
            split_docs = text_splitter.split_documents(documents)
            all_documents.extend(split_docs)
        
        os.unlink(tmp_file_path)
    
    if all_documents:
        vector_store.add_documents(all_documents)
        return len(all_documents)
    return 0

def delete_pinecone_data():
    pc = get_pinecone_client()
    index_name = st.session_state['index_name']
    if index_name in pc.list_indexes().names():
        index = pc.Index(index_name)
        index.delete(delete_all=True)
        return True
    return False

def query_osta_rag(user_query):
    os.environ['OPENAI_API_KEY'] = st.session_state['openai_api_key']
    pc = get_pinecone_client()
    index = pc.Index(st.session_state['index_name'])
    embeddings = OpenAIEmbeddings()
    vector_store = PineconeVectorStore(index=index, embedding=embeddings, text_key="text")
    
    # استرجاع الوثائق المتعلقة
    docs = vector_store.similarity_search(user_query, k=4)
    context = "\n\n".join([doc.page_content for doc in docs])
    
    llm = ChatOpenAI(model_name="gpt-4o-mini", temperature=0.2)
    
    system_prompt = """
    أنت 'أسطى كبير' مصري محترف جداً في صيانة ضواغط الهواء والتصنيع المعدني. 
    كلامك كله بلهجة صنايعية مصرية عامية بسيطة جداً وكأنك واقف في الورشة بتعلم صبي أو عامل أمي.
    مهمتك: الإجابة على سؤال العامل بناءً على [المعلومات المرفقة] فقط.
    قواعد هامة:
    1. قدم إجابتك في خطوات مرقمة (1، 2، 3) عشان تكون سهلة الفهم.
    2. استخدم ألفاظ الورشة (يا ابني، ركز معايا، خد بالك، هات العدة، وغيرها).
    3. إذا كانت الإجابة غير موجودة في [المعلومات المرفقة]، قل بالنص: "يا ابني دي مش عندي في الكتالوج دلوقتي، اسأل المهندس". لا تؤلف أي معلومات من خارج النص.
    """
    
    prompt = f"المعلومات المرفقة:\n{context}\n\nسؤال العامل: {user_query}"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    response = llm.invoke(messages)
    return response.content

def transcribe_audio_to_text(audio_bytes):
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

def text_to_speech_osta(text):
    client = OpenAI(api_key=st.session_state['openai_api_key'])
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx", # صوت قوي يناسب الأسطى
        input=text
    )
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_mp3:
        response.stream_to_file(tmp_mp3.name)
        return tmp_mp3.name

# ==========================================
# واجهات المستخدم (Views)
# ==========================================

def render_login():
    st.markdown("<h1 style='text-align: center;'>⚡ بوابة الدخول للنظام ⚡</h1>", unsafe_allow_html=True)
    st.write("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("### تسجيل الدخول")
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")
        
        if st.button("دخول للنظام"):
            if login_user(username, password):
                st.rerun()
            else:
                st.error("اسم المستخدم أو كلمة المرور غير صحيحة!")
        
        st.info("💡 **تجربة النظام:**\n- للمدير: `admin` / `admin123`\n- للعامل: `worker` / `worker123`")

def render_manager_dashboard():
    st.sidebar.markdown("## 👨‍💻 لوحة تحكم المدير")
    menu = st.sidebar.radio("القائمة:", ["إعدادات النظام (API)", "إدارة البيانات والتدريب", "شات الاختبار النصي"])
    
    if st.sidebar.button("تسجيل الخروج"):
        logout()
    
    if menu == "إعدادات النظام (API)":
        st.markdown("## ⚙️ إعدادات الربط مع واجهات التطبيقات (APIs)")
        st.info("يجب إدخال المفاتيح لتشغيل المحرك الصوتي والنصي للعمال.")
        
        openai_key = st.text_input("OpenAI API Key (لـ Whisper و TTS و LLM)", value=st.session_state['openai_api_key'], type="password")
        pinecone_key = st.text_input("Pinecone API Key (لقاعدة البيانات الموجهة)", value=st.session_state['pinecone_api_key'], type="password")
        
        if st.button("حفظ الإعدادات"):
            st.session_state['openai_api_key'] = openai_key
            st.session_state['pinecone_api_key'] = pinecone_key
            st.success("تم حفظ الإعدادات في الجلسة بنجاح!")
            
    elif menu == "إدارة البيانات والتدريب":
        st.markdown("## 📚 رفع كتالوجات الصيانة والبيانات")
        if not st.session_state['openai_api_key'] or not st.session_state['pinecone_api_key']:
            st.warning("يرجى إدخال مفاتيح API في نافذة الإعدادات أولاً.")
            return
            
        uploaded_files = st.file_uploader("ارفع الملفات (PDF, TXT, DOCX, CSV)", accept_multiple_files=True)
        if st.button("معالجة ورفع إلى Pinecone"):
            if uploaded_files:
                with st.spinner("جاري تقطيع النصوص ومعالجتها ورفعها..."):
                    try:
                        chunks_count = process_documents(uploaded_files)
                        st.success(f"تمت المعالجة بنجاح! تم رفع {chunks_count} مقطع نصي لقاعدة البيانات.")
                    except Exception as e:
                        st.error(f"حدث خطأ أثناء الرفع: {e}")
            else:
                st.warning("الرجاء اختيار ملفات أولاً.")
                
        st.write("---")
        st.markdown("### 🗑️ مسح الذاكرة")
        if st.button("حذف كافة البيانات من Pinecone (تصفير الذاكرة)"):
            with st.spinner("جاري الحذف..."):
                try:
                    if delete_pinecone_data():
                        st.success("تم حذف جميع البيانات بنجاح.")
                except Exception as e:
                    st.error(f"حدث خطأ: {e}")

    elif menu == "شات الاختبار النصي":
        st.markdown("## 🧪 تجربة محرك 'الأسطى' النصي")
        if not st.session_state['openai_api_key']:
            st.warning("أدخل OpenAI API Key في الإعدادات.")
            return
            
        user_input = st.text_area("اطرح سؤالاً لاختبار رد الذكاء الاصطناعي بناءً على الداتا:")
        if st.button("إرسال السؤال"):
            if user_input:
                with st.spinner("الأسطى بيفكر..."):
                    try:
                        answer = query_osta_rag(user_input)
                        st.markdown("### رد الأسطى:")
                        st.info(answer)
                    except Exception as e:
                        st.error(f"خطأ: {e}")

def render_worker_view():
    # إخفاء الشريط الجانبي تماما للعامل لبساطة الواجهة
    st.markdown("""
        <style>
            [data-testid="collapsedControl"] {display: none;}
            [data-testid="stSidebar"] {display: none;}
        </style>
    """, unsafe_allow_html=True)
    
    st.markdown("<h1 style='text-align: center; font-size: 3rem;'>🎙️ اسأل الأسطى</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; font-size: 1.5rem;'>اضغط على الميكروفون تحت واتكلم، وبعدين استنى الرد</p>", unsafe_allow_html=True)
    st.write("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        if not st.session_state['openai_api_key'] or not st.session_state['pinecone_api_key']:
            st.error("⚠️ النظام غير جاهز، المهندس لسة مظبطش الإعدادات.")
            if st.button("خروج"):
                logout()
            return

        # تسجيل الصوت
        audio_bytes = audio_recorder(
            text="🔴 اضغط هنا وسجل سؤالك",
            recording_color="#e81cff",
            neutral_color="#00f3ff",
            icon_size="3x"
        )
        
        if audio_bytes:
            current_hash = hashlib.md5(audio_bytes).hexdigest()
            if current_hash != st.session_state['last_audio_hash']:
                st.session_state['last_audio_hash'] = current_hash
                
                with st.spinner("جاري سماع صوتك..."):
                    try:
                        # 1. تحويل الصوت لنص
                        user_text = transcribe_audio_to_text(audio_bytes)
                        st.markdown(f"**سؤالك:** {user_text}")
                        
                        # 2. الاستعلام من قاعدة البيانات وتوليد الرد بشخصية الأسطى
                        st.spinner("الأسطى بيراجع الكتالوج ويرد عليك...")
                        ai_answer = query_osta_rag(user_text)
                        
                        # 3. تحويل رد الأسطى لصوت
                        st.spinner("الأسطى بيتكلم...")
                        audio_path = text_to_speech_osta(ai_answer)
                        
                        st.success("الرد جاهز!")
                        st.audio(audio_path, format="audio/mp3", autoplay=True)
                        st.markdown("### 📋 رد الأسطى مكتوب:")
                        st.info(ai_answer)
                        
                    except Exception as e:
                        st.error(f"معلش يا ابني حصل مشكلة في المكنة: {e}")
        
        st.write("---")
        if st.button("🚪 خروج من الورشة"):
            logout()

# ==========================================
# المشغل الرئيسي (Main App Router)
# ==========================================
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
