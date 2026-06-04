import streamlit as st
import time
import base64
import os
# سيتم استخدام هذه المكتبات عند توفر الـ API Keys
# import openai
# import pinecone
# import firebase_admin
# from firebase_admin import credentials, auth, firestore

# ==========================================
# 1. إعدادات الصفحة الأساسية
# ==========================================
st.set_page_config(
    page_title="مساعد الورشة الذكي | AI Workshop",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# ==========================================
SVGS = {
    "gear": """<svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 8px rgba(0,243,255,0.8));"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>""",
    "mic": """<svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="#ff00ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 8px rgba(255,0,255,0.8));"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>""",
    "folder": """<svg width="35" height="35" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 8px rgba(0,243,255,0.8));"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>""",
    "user": """<svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 10px rgba(0,243,255,0.6));"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>"""
}

# ==========================================
# 2. تصميم CSS (Glassmorphism & Neon)
# ==========================================
def inject_custom_css():
    st.markdown("""
        <style>
        /* خلفية التطبيق داكنة */
        .stApp {
            background-color: #0d1117;
            background-image: radial-gradient(circle at 50% 0%, #1a202c 0%, #0d1117 100%);
            color: #e6edf3;
            font-family: 'Cairo', sans-serif;
        }
        
        /* تأثير الزجاج (Glassmorphism) للـ Sidebar */
        [data-testid="stSidebar"] {
            background: rgba(13, 17, 23, 0.6) !important;
            backdrop-filter: blur(15px) !important;
            -webkit-backdrop-filter: blur(15px) !important;
            border-left: 1px solid rgba(0, 255, 255, 0.2);
        }

        /* نيون للأزرار */
        .stButton>button {
            background: transparent !important;
            border: 2px solid #00f3ff !important;
            color: #00f3ff !important;
            border-radius: 12px !important;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.3), inset 0 0 5px rgba(0, 243, 255, 0.2) !important;
            transition: all 0.3s ease !important;
            font-weight: bold !important;
        }
        .stButton>button:hover {
            background: #00f3ff !important;
            color: #000 !important;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.6), inset 0 0 10px rgba(0, 243, 255, 0.4) !important;
        }

        /* تأثير الزجاج لصناديق الإدخال */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea {
            background: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid rgba(255, 0, 255, 0.3) !important;
            color: #fff !important;
            border-radius: 10px !important;
            backdrop-filter: blur(5px) !important;
        }
        .stTextInput>div>div>input:focus, .stTextArea>div>div>textarea:focus {
            border: 1px solid #ff00ff !important;
            box-shadow: 0 0 10px rgba(255, 0, 255, 0.4) !important;
        }

        /* رسائل الشات */
        .stChatMessage {
            background: rgba(20, 25, 30, 0.6) !important;
            border: 1px solid rgba(0, 255, 255, 0.1) !important;
            border-radius: 15px !important;
            backdrop-filter: blur(10px) !important;
            margin-bottom: 10px;
        }

        /* عناوين نيون */
        h1, h2, h3 {
            text-shadow: 0 0 10px rgba(0, 243, 255, 0.5);
        }
        
        /* إخفاء القائمة العلوية الافتراضية لستريمليت لمظهر احترافي */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

inject_custom_css()

# ==========================================
# 3. إدارة حالة التطبيق (Session State)
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_role' not in st.session_state:
    st.session_state.user_role = None # 'admin' or 'worker'
if 'username' not in st.session_state:
    st.session_state.username = ""
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'api_keys' not in st.session_state:
    st.session_state.api_keys = {"openai": "", "pinecone": "", "firebase": ""}

# ==========================================
# 4. الـ System Prompt (شخصية الأسطى المصري)
# ==========================================
SYSTEM_PROMPT = """
أنت 'الأسطى سيد'، مهندس وصنايعي مصري مخضرم في شركة تصنيع معدات هندسية.
خبرتك تشمل: ماكينات CNC، المخارط، الفرايز، المقاشط، المثاقب، الليزر، اللحام، وقسم الهواء (ضواغط ومجففات).
بتكلم العمال اللي أغلبهم مش متعلمين أوي، فلازم يكون ردك:
- بلهجة مصرية عامية دارجة جداً ومحببة (يا هندسة، يا بطل، بص يا سيدي، صلي على النبي).
- اجابات عملية جداً ومباشرة ومظبوطة هندسياً.
- متستخدمش مصطلحات معقدة، بسط المعلومة على قد ما تقدر.
- لو العامل قال مشكلة، شخصها واديله الحل خطوة بخطوة كأنك واقف جنبه على المكنة.
"""

# ==========================================
# 5. دوال محاكاة الذكاء الاصطناعي والصوت
# ==========================================
def mock_ai_response(user_text):
    """محاكاة لرد الذكاء الاصطناعي في حال عدم وضع API Key"""
    time.sleep(1.5)
    if "صوت" in user_text or "عالي" in user_text:
        return "بص يا هندسة، الصوت العالي في المكنة الـ CNC غالباً معناه إن فيه بوش في الرومان بلي أو الطرد المركزي مش مظبوط. وقف المكنة فوراً وراجع على زيت التزييت واتاكد إن مفيش رايش حاشر في الـ Spindle. الله ينور عليك."
    elif "هواء" in user_text or "كومبريسور" in user_text or "ضاغط" in user_text:
        return "يا ريس، لو الكومبريسور مابيرفعش ضغط، أول حاجة تبص عليها هي فلاتر الهواء ممكن تكون مكتومة، وبعدين شيك على بلف السحب (Intake valve). نضفهم كويس وجرب تاني وبلغني."
    else:
        return "يا بطل، عشان أقدر أفيدك صح، قولي العطل في أي مكنة بالظبط؟ مخرطة ولا فريزة ولا كومبريسور؟ وإيه اللي بيحصل معاك؟"

# ==========================================
# 6. واجهة تسجيل الدخول (Authentication)
# ==========================================
def login_page():
    st.markdown(f"<div style='display: flex; justify-content: center; align-items: center; gap: 15px;'><h1 style='color: #00f3ff; margin:0;'>نظام إدارة الورشة الذكي</h1>{SVGS['gear']}</div>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #aaa; margin-top: 10px;'>يرجى تسجيل الدخول للوصول إلى النظام</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.container():
            st.markdown("<div class='glass-container' style='padding: 20px;'>", unsafe_allow_html=True)
            username = st.text_input("اسم المستخدم", placeholder="أدخل الكود أو الاسم")
            password = st.text_input("كلمة المرور", type="password", placeholder="أدخل كلمة المرور")
            
            if st.button("تسجيل الدخول", use_container_width=True):
                # هنا يتم ربط Firebase Auth مستقبلاً
                if username == "admin" and password == "admin":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "admin"
                    st.session_state.username = "المدير العام"
                    st.rerun()
                elif username == "worker" and password == "123":
                    st.session_state.logged_in = True
                    st.session_state.user_role = "worker"
                    st.session_state.username = "الأسطى أحمد"
                    st.rerun()
                else:
                    st.error("بيانات الدخول غير صحيحة!")
            st.markdown("</div>", unsafe_allow_html=True)

# ==========================================
# 7. واجهة المساعد الصوتي (Chat & Voice)
# ==========================================
def chat_page():
    st.markdown(f"<div style='display: flex; align-items: center; gap: 15px;'><h2 style='margin:0;'>المساعد الذكي (الأسطى سيد)</h2>{SVGS['mic']}</div>", unsafe_allow_html=True)
    st.caption("سجل مشكلتك بصوتك أو اكتبها، والأسطى سيد هيرد عليك بالحل.")

    # عرض الرسائل السابقة
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("audio"):
                st.audio(msg["audio"])

    # تسجيل الصوت (باستخدام ميزة Streamlit الجديدة)
    audio_value = st.audio_input("سجل رسالتك هنا يا هندسة")
    
    # مربع الكتابة كبديل
    text_input = st.chat_input("أو اكتب مشكلتك هنا...")

    user_query = None

    if audio_value:
        # هنا يتم إرسال ملف الصوت إلى OpenAI Whisper لتحويله لنص
        st.success("تم استلام التسجيل! جاري الترجمة...")
        # محاكاة الترجمة
        user_query = "صوت المكنة عالي قوي يا أسطى" 
        
    if text_input:
        user_query = text_input

    if user_query:
        # إضافة رسالة المستخدم
        st.session_state.messages.append({"role": "user", "content": user_query})
        with st.chat_message("user"):
            st.markdown(user_query)

        # الرد من الذكاء الاصطناعي (مع الـ RAG)
        with st.chat_message("assistant"):
            with st.spinner("الأسطى سيد بيفكر..."):
                # هنا كود الـ RAG (Pinecone + OpenAI)
                # اذا لم يتوفر API سيتم استخدام المحاكاة
                response_text = mock_ai_response(user_query)
                st.markdown(response_text)
                
                # هنا كود تحويل النص إلى صوت TTS (مثال ElevenLabs)
                # نقوم بمحاكاة الصوت بمكون صوت فارغ للتوضيح
                st.caption("تشغيل الرد الصوتي:")
                # st.audio("path_to_generated_audio.mp3") 
                
        st.session_state.messages.append({"role": "assistant", "content": response_text})

# ==========================================
# 8. إدارة الملفات والـ RAG (للمدير فقط)
# ==========================================
def data_management_page():
    st.markdown(f"<div style='display: flex; align-items: center; gap: 15px;'><h2 style='margin:0;'>إدارة البيانات (Pinecone RAG)</h2>{SVGS['folder']}</div>", unsafe_allow_html=True)
    st.info("ارفع الكتالوجات، ملفات الصيانة، وأعطال الضواغط والماكينات لتدريب المساعد الذكي.")

    uploaded_files = st.file_uploader("اختر الملفات (PDF, TXT, DOCX, CSV)", accept_multiple_files=True)
    
    if st.button("رفع ومعالجة البيانات (Embeddings)", type="primary"):
        if uploaded_files:
            with st.spinner("جاري استخراج النصوص وتحويلها إلى Embeddings ورفعها لـ Pinecone..."):
                time.sleep(2) # محاكاة وقت الرفع
                st.success(f"تم بنجاح رفع ومعالجة {len(uploaded_files)} ملف/ملفات.")
        else:
            st.warning("يرجى اختيار ملفات أولاً.")

    st.markdown("---")
    st.subheader("الملفات الحالية في قاعدة البيانات")
    
    # محاكاة لملفات موجودة
    files = ["كتالوج_ضاغط_أطلس_كوبكو.pdf", "أعطال_مخرطة_CNC_شائعة.txt", "دليل_مجففات_الهواء.docx"]
    for f in files:
        col1, col2 = st.columns([4, 1])
        col1.markdown(f"**ملف:** `{f}`")
        if col2.button("حذف", key=f):
            st.toast(f"تم حذف {f} من قاعدة البيانات.")

# ==========================================
# 9. صفحة الإعدادات والربط (للمدير فقط)
# ==========================================
def settings_page():
    st.markdown(f"<div style='display: flex; align-items: center; gap: 15px;'><h2 style='margin:0;'>إعدادات النظام و الـ APIs</h2>{SVGS['gear']}</div>", unsafe_allow_html=True)
    st.caption("أدخل مفاتيح الربط لتفعيل الذكاء الاصطناعي الحقيقي وقاعدة البيانات.")

    with st.expander("OpenAI API Settings (للشات وفهم الكلام)"):
        openai_key = st.text_input("OpenAI API Key", type="password", value=st.session_state.api_keys["openai"])
    
    with st.expander("Pinecone Vector DB (للذاكرة والـ RAG)"):
        pinecone_key = st.text_input("Pinecone API Key", type="password", value=st.session_state.api_keys["pinecone"])
        pinecone_env = st.text_input("Pinecone Environment / Index Name")

    with st.expander("Firebase Settings (للمستخدمين وقاعدة البيانات)"):
        st.text_area("Firebase Admin JSON", placeholder='{"type": "service_account", ...}')

    with st.expander("إعدادات الصوت (Text-to-Speech)"):
        st.selectbox("مزود الصوت", ["ElevenLabs (موصى به للصوت المصري)", "Google Cloud TTS", "OpenAI TTS"])
        tts_key = st.text_input("TTS API Key", type="password")
        st.text_input("Voice ID (رقم المعرف لصوت الأسطى المصري)")

    if st.button("حفظ الإعدادات"):
        st.session_state.api_keys["openai"] = openai_key
        st.session_state.api_keys["pinecone"] = pinecone_key
        st.success("تم حفظ الإعدادات بنجاح!")

# ==========================================
# 10. الهيكل الرئيسي للتطبيق (Main App Flow)
# ==========================================
def main():
    if not st.session_state.logged_in:
        login_page()
    else:
        # القائمة الجانبية المخصصة
        with st.sidebar:
            st.markdown(f"<div style='display: flex; justify-content: center; margin-top: 20px; margin-bottom: 10px;'>{SVGS['user']}</div>", unsafe_allow_html=True)
            st.markdown(f"<h3 style='text-align: center; margin-bottom: 0;'>مرحباً بك يا</h3><h2 style='text-align: center; color:#00f3ff; margin-top: 5px;'>{st.session_state.username}</h2>", unsafe_allow_html=True)
            st.markdown("---")
            
            # تحديد الصفحات بناءً على الصلاحيات
            if st.session_state.user_role == "admin":
                page = st.radio("القائمة الرئيسية", ["المساعد الذكي", "رفع البيانات", "الإعدادات"])
            else:
                page = st.radio("القائمة الرئيسية", ["المساعد الذكي"])
            
            st.markdown("---")
            if st.button("تسجيل الخروج", key="logout"):
                st.session_state.logged_in = False
                st.session_state.user_role = None
                st.rerun()

        # التوجيه للصفحات
        if page == "المساعد الذكي":
            chat_page()
        elif page == "رفع البيانات" and st.session_state.user_role == "admin":
            data_management_page()
        elif page == "الإعدادات" and st.session_state.user_role == "admin":
            settings_page()

if __name__ == "__main__":
    main()
