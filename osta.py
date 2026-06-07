import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import pinecone
from pinecone import Pinecone
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain.text_splitter import RecursiveCharacterTextSplitter
import fitz  # PyMuPDF
import edge_tts
import asyncio
import os
import json
import base64
import re
from openai import OpenAI

# ==========================================
# 1. إعدادات الصفحة وواجهة النيون (CSS)
# ==========================================
st.set_page_config(page_title="AI Agent - Neon Chat", page_icon="🤖", layout="wide", initial_sidebar_state="collapsed")

def inject_neon_css():
    st.markdown("""
    <style>
        /* خلفية داكنة جداً */
        .stApp {
            background-color: #09090b;
            color: #e0e0e0;
        }
        /* تصميم الأزرار النيون */
        .stButton>button {
            background-color: transparent !important;
            color: #00f3ff !important;
            border: 2px solid #00f3ff !important;
            border-radius: 15px !important;
            box-shadow: 0 0 10px #00f3ff, inset 0 0 5px #00f3ff !important;
            transition: all 0.3s ease;
            font-weight: bold;
            font-size: 16px;
            width: 100%;
        }
        .stButton>button:hover {
            background-color: #00f3ff !important;
            color: #000 !important;
            box-shadow: 0 0 20px #00f3ff, inset 0 0 10px #00f3ff !important;
        }
        /* حقول الإدخال */
        .stTextInput>div>div>input, .stSelectbox>div>div>div, .stTextArea>div>textarea {
            background-color: #16161a !important;
            color: #00f3ff !important;
            border: 1px solid #bc13fe !important;
            border-radius: 10px;
            box-shadow: inset 0 0 5px #bc13fe;
        }
        /* رسائل الشات */
        .user-msg {
            background: linear-gradient(135deg, #bc13fe, #8a2be2);
            color: white;
            padding: 15px;
            border-radius: 20px 20px 0px 20px;
            margin-bottom: 10px;
            width: fit-content;
            max-width: 80%;
            margin-left: auto;
            box-shadow: 0 4px 15px rgba(188, 19, 254, 0.4);
            font-size: 18px;
        }
        .bot-msg {
            background: linear-gradient(135deg, #00f3ff, #0088ff);
            color: black;
            padding: 15px;
            border-radius: 20px 20px 20px 0px;
            margin-bottom: 10px;
            width: fit-content;
            max-width: 80%;
            margin-right: auto;
            box-shadow: 0 4px 15px rgba(0, 243, 255, 0.4);
            font-size: 18px;
            font-weight: bold;
        }
        /* إخفاء القوائم العلوية لستريملت لتبدو كتطبيق حقيقي */
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

inject_neon_css()

# ==========================================
# 2. التهيئة وقواعد البيانات (Firebase)
# ==========================================
@st.cache_resource
def init_firebase():
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate('firebase_config.json')
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error("خطأ في الاتصال بقاعدة بيانات Firebase. تأكد من ملف firebase_config.json")
        return None

db = init_firebase()

# ==========================================
# 3. الدوال المساعدة (الصوت، معالجة النصوص، Pinecone)
# ==========================================

# دالة لتنظيف النص من الأرقام والرموز قبل القراءة
def clean_text_for_speech(text):
    # إزالة الأرقام والرموز (ترك الحروف العربية والإنجليزية والمسافات والنقاط)
    cleaned = re.sub(r'[0-9!@#$%^&*()_+\-=\[\]{};\':"\\|,.<>\/?]+', ' ', text)
    return cleaned

# دالة تحويل النص إلى صوت (لهجة مصرية)
async def generate_audio(text, output_file="response.mp3"):
    cleaned_text = clean_text_for_speech(text)
    if not cleaned_text.strip():
        cleaned_text = "لا يوجد نص مقروء"
    # ar-EG-SalmaNeural (صوت أنثوي مصري) أو ar-EG-ShakirNeural (صوت ذكوري)
    communicate = edge_tts.Communicate(cleaned_text, "ar-EG-SalmaNeural")
    await communicate.save(output_file)

# دالة التشغيل التلقائي للصوت
def autoplay_audio(file_path: str):
    with open(file_path, "rb") as f:
        data = f.read()
        b64 = base64.b64encode(data).decode()
        md = f"""
            <audio controls autoplay="true" style="width: 100%; border-radius: 10px; border: 1px solid #00f3ff;">
            <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
            </audio>
            """
        st.markdown(md, unsafe_allow_html=True)

# دالة تحويل الصوت إلى نص (باستخدام OpenAI Whisper)
def transcribe_audio(audio_file, api_key):
    try:
        client = OpenAI(api_key=api_key)
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
        return transcript.text
    except Exception as e:
        st.error(f"خطأ في التعرف على الصوت: {e}")
        return None

# ==========================================
# 4. إدارة الجلسات وتسجيل الدخول
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'username' not in st.session_state:
    st.session_state.username = None

def login_screen():
    st.markdown("<h1 style='text-align: center; color: #00f3ff; text-shadow: 0 0 20px #00f3ff;'>تسجيل الدخول</h1>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        username = st.text_input("👤 اسم المستخدم", placeholder="أدخل اسم المستخدم")
        # ستريملت يدعم type="password" لإظهار النقاط وتوفير علامة العين في بعض المتصفحات
        password = st.text_input("🔑 كلمة المرور", type="password", placeholder="أدخل الرقم السري")
        
        if st.button("دخول 🚀"):
            if db:
                users_ref = db.collection('users').where('username', '==', username).where('password', '==', password).stream()
                user = list(users_ref)
                if user:
                    user_data = user[0].to_dict()
                    st.session_state.logged_in = True
                    st.session_state.role = user_data.get('role', 'worker')
                    st.session_state.username = username
                    st.rerun()
                else:
                    # حساب افتراضي للمدير في حالة عدم وجود بيانات (لأول مرة)
                    if username == "admin" and password == "admin123":
                        st.session_state.logged_in = True
                        st.session_state.role = 'manager'
                        st.session_state.username = "Admin"
                        st.rerun()
                    else:
                        st.error("❌ بيانات الدخول غير صحيحة!")

# ==========================================
# 5. واجهة التطبيق الرئيسية (شاشات المدير والعامل)
# ==========================================
def main_app():
    # جلب الإعدادات من Firebase
    settings = db.collection('settings').document('config').get().to_dict() or {}
    
    openai_api_key = settings.get('openai_api_key', '')
    pinecone_api_key = settings.get('pinecone_api_key', '')
    pinecone_env = settings.get('pinecone_env', '')
    pinecone_index = settings.get('pinecone_index', '')
    llm_model = settings.get('llm_model', 'gpt-4o-mini')
    system_prompt = settings.get('system_prompt', 'أنت مساعد ذكي ومفيد. أجب باللغة العربية.')
    agent_name = settings.get('agent_name', 'المساعد الذكي')

    # القائمة الجانبية (للمدير فقط أو زر تسجيل الخروج للعامل)
    with st.sidebar:
        st.markdown(f"### أهلاً، {st.session_state.username} 👋")
        if st.session_state.role == 'manager':
            page = st.radio("القائمة", ["💬 الشات", "⚙️ الإعدادات العامة", "🗂️ إدارة قاعدة المعرفة (Pinecone)", "👥 إدارة الحسابات"])
        else:
            page = "💬 الشات"
            st.info("صلاحيات عامل: واجهة المحادثة فقط.")
        
        if st.button("تسجيل الخروج 🚪"):
            st.session_state.logged_in = False
            st.rerun()

    # -----------------------------------------
    # صفحة الشات (متاحة للجميع)
    # -----------------------------------------
    if page == "💬 الشات":
        st.markdown(f"<h2 style='text-align: center; color: #bc13fe;'>🤖 {agent_name}</h2>", unsafe_allow_html=True)
        
        if 'messages' not in st.session_state:
            st.session_state.messages = []

        # عرض الرسائل السابقة
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.markdown(f"<div class='user-msg'>{msg['content']}</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div class='bot-msg'>{msg['content']}</div>", unsafe_allow_html=True)

        # قسم الإدخال (صوت + صورة + نص) بطريقة تشبه واتساب
        st.markdown("---")
        
        # التقاط الصوت مباشرة من المتصفح (ميزة جديدة في ستريملت)
        audio_value = st.audio_input("🎤 اضغط للتحدث (رسالة صوتية)")
        uploaded_image = st.file_uploader("📷 إرفاق صورة (اختياري)", type=['png', 'jpg', 'jpeg'])
        prompt = st.chat_input("✍️ أو اكتب رسالتك هنا...")

        user_input = None

        if audio_value:
            with st.spinner("جاري الاستماع وتحويل الصوت..."):
                user_input = transcribe_audio(audio_value, openai_api_key)
                if user_input:
                     st.success(f"تم سماع: {user_input}")

        if prompt:
            user_input = prompt

        if user_input:
            if not openai_api_key:
                st.error("⚠️ يرجى من المدير إدخال مفتاح OpenAI في الإعدادات.")
                return

            # إضافة رسالة المستخدم للشاشة
            st.session_state.messages.append({"role": "user", "content": user_input})
            st.markdown(f"<div class='user-msg'>{user_input}</div>", unsafe_allow_html=True)

            with st.spinner("جاري التفكير... 🤔"):
                try:
                    # تجهيز Langchain & Pinecone
                    os.environ['OPENAI_API_KEY'] = openai_api_key
                    os.environ['PINECONE_API_KEY'] = pinecone_api_key
                    
                    llm = ChatOpenAI(model_name=llm_model, temperature=0.3)
                    
                    # محاولة الاتصال بـ Pinecone للحصول على السياق
                    context = ""
                    if pinecone_api_key and pinecone_index:
                        try:
                            pc = Pinecone(api_key=pinecone_api_key)
                            embeddings = OpenAIEmbeddings()
                            vectorstore = PineconeVectorStore(index_name=pinecone_index, embedding=embeddings)
                            retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
                            docs = retriever.invoke(user_input)
                            context = "\n".join([doc.page_content for doc in docs])
                        except Exception as e:
                            st.warning("تعذر جلب البيانات من Pinecone. سيتم الرد من معلومات الموديل العامة.")
                    
                    # دمج البرومبت مع السياق
                    final_prompt = f"{system_prompt}\n\nمعلومات إضافية للمساعدة:\n{context}\n\nسؤال المستخدم: {user_input}"
                    
                    response = llm.invoke(final_prompt)
                    bot_reply = response.content

                    # حفظ وعرض رسالة البوت
                    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
                    st.markdown(f"<div class='bot-msg'>{bot_reply}</div>", unsafe_allow_html=True)

                    # تحويل الرد إلى صوت وتشغيله تلقائياً
                    asyncio.run(generate_audio(bot_reply, "temp_reply.mp3"))
                    autoplay_audio("temp_reply.mp3")

                except Exception as e:
                    st.error(f"حدث خطأ أثناء معالجة الطلب: {str(e)}")

    # -----------------------------------------
    # صفحة الإعدادات (للمدير فقط)
    # -----------------------------------------
    elif page == "⚙️ الإعدادات العامة":
        st.header("⚙️ إعدادات النظام و APIs")
        with st.form("settings_form"):
            new_name = st.text_input("🤖 اسم المساعد (يظهر في الشات)", value=agent_name)
            new_prompt = st.text_area("🧠 شخصية المساعد (System Prompt)", value=system_prompt)
            new_model = st.selectbox("⚙️ نموذج LLM", ["gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini"], index=["gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini"].index(llm_model) if llm_model in ["gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini"] else 2)
            
            # حقول سرية (نوع password لرؤية النجوم، ومعظم المتصفحات تظهر عين للكشف)
            new_openai = st.text_input("🔑 مفتاح OpenAI API", value=openai_api_key, type="password")
            new_pinecone = st.text_input("🔑 مفتاح Pinecone API", value=pinecone_api_key, type="password")
            new_pinecone_idx = st.text_input("🗂️ اسم فهرس Pinecone (Index Name)", value=pinecone_index)

            submit = st.form_submit_button("حفظ الإعدادات 💾")
            if submit:
                db.collection('settings').document('config').set({
                    'agent_name': new_name,
                    'system_prompt': new_prompt,
                    'llm_model': new_model,
                    'openai_api_key': new_openai,
                    'pinecone_api_key': new_pinecone,
                    'pinecone_index': new_pinecone_idx
                })
                st.success("✅ تم حفظ الإعدادات بنجاح!")
                st.rerun()

    # -----------------------------------------
    # صفحة إدارة Pinecone (للمدير فقط)
    # -----------------------------------------
    elif page == "🗂️ إدارة قاعدة المعرفة (Pinecone)":
        st.header("🗂️ رفع الملفات لتدريب المساعد")
        if not pinecone_api_key or not pinecone_index or not openai_api_key:
            st.warning("⚠️ يرجى ضبط مفاتيح Pinecone و OpenAI من الإعدادات أولاً.")
        else:
            uploaded_file = st.file_uploader("رفع ملف PDF", type="pdf")
            if uploaded_file is not None:
                if st.button("بدء الرفع والتحليل 🚀"):
                    with st.spinner("جاري استخراج النص وتشفيره ورفعه لـ Pinecone..."):
                        try:
                            # قراءة PDF
                            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
                            text = ""
                            for page_num in range(len(doc)):
                                text += doc.page_content
                            
                            # تقسيم النص
                            text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
                            chunks = text_splitter.split_text(text)
                            
                            # الرفع
                            os.environ['OPENAI_API_KEY'] = openai_api_key
                            pc = Pinecone(api_key=pinecone_api_key)
                            embeddings = OpenAIEmbeddings()
                            PineconeVectorStore.from_texts(chunks, embeddings, index_name=pinecone_index)
                            
                            st.success("✅ تم التدريب على الملف بنجاح! يمكن للمساعد الآن الإجابة منه.")
                        except Exception as e:
                            st.error(f"❌ حدث خطأ: {e}")
            
            st.markdown("---")
            st.subheader("🗑️ مسح جميع البيانات من Pinecone")
            if st.button("حذف الكُل ⚠️"):
                try:
                    pc = Pinecone(api_key=pinecone_api_key)
                    index = pc.Index(pinecone_index)
                    index.delete(delete_all=True)
                    st.success("✅ تم تفريغ قاعدة البيانات بنجاح.")
                except Exception as e:
                    st.error(f"❌ خطأ أثناء الحذف: {e}")

    # -----------------------------------------
    # صفحة إدارة الحسابات (للمدير فقط)
    # -----------------------------------------
    elif page == "👥 إدارة الحسابات":
        st.header("👥 إنشاء وإدارة حسابات العمال")
        
        with st.form("new_user"):
            new_u = st.text_input("اسم المستخدم")
            new_p = st.text_input("كلمة المرور", type="password")
            new_r = st.selectbox("الصلاحية", ["worker", "manager"], format_func=lambda x: "عامل (شات فقط)" if x == "worker" else "مدير (تحكم كامل)")
            
            if st.form_submit_button("إنشاء حساب ➕"):
                db.collection('users').add({
                    'username': new_u,
                    'password': new_p,
                    'role': new_r
                })
                st.success(f"✅ تم إنشاء حساب '{new_u}' بنجاح!")
        
        st.markdown("---")
        st.subheader("الحسابات الحالية")
        users = db.collection('users').stream()
        for u in users:
            udata = u.to_dict()
            colA, colB, colC = st.columns([2,2,1])
            colA.write(f"👤 {udata['username']}")
            colB.write(f"🏷️ {'مدير' if udata['role'] == 'manager' else 'عامل'}")
            if colC.button("حذف 🗑️", key=u.id):
                db.collection('users').document(u.id).delete()
                st.rerun()

# ==========================================
# 6. نقطة الإطلاق التشغيلية
# ==========================================
if __name__ == "__main__":
    if not st.session_state.logged_in:
        login_screen()
    else:
        main_app()
