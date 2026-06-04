import streamlit as st
import time

# ==========================================
# 1. إعدادات الصفحة الأساسية
# ==========================================
st.set_page_config(
    page_title="المساعد الذكي المتقدم",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 2. مكتبة الأيقونات (SVG Neon Icons)
# ==========================================
SVGS = {
    "chat": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(0,243,255,0.8));"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>""",
    "settings": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(255,0,255,0.8));"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>""",
    "database": """<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 5px rgba(0,255,136,0.8));"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path></svg>""",
    "user": """<svg width="60" height="60" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="filter: drop-shadow(0 0 10px rgba(0,243,255,0.6));"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>""",
    "attach": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#00f3ff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path></svg>""",
    "logout": """<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ff0044" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>"""
}

# ==========================================
# 3. محرك التصميم (CSS Master Engine)
# ==========================================
def inject_premium_css():
    st.markdown("""
        <style>
        /* 1. إعدادات اللغة وتوجيه الشاشة لليمين (RTL) */
        .stApp {
            direction: rtl;
            background-color: #080b10;
            background-image: radial-gradient(circle at 50% 0%, #111823 0%, #080b10 100%);
            color: #ffffff;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }

        /* 2. نقل القائمة الجانبية لليمين */
        [data-testid="stSidebar"] {
            left: auto !important;
            right: 0 !important;
            background: rgba(8, 11, 16, 0.7) !important;
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border-left: 1px solid rgba(0, 243, 255, 0.15) !important;
            border-right: none !important;
        }
        
        .stApp > header {
            right: 0 !important;
            left: auto !important;
            background: transparent !important;
        }

        /* 3. تصميم أزرار التنقل (بدون نقاط، ظلال نيون) */
        div[role="radiogroup"] > label > div:first-child {
            display: none !important; /* إخفاء دائرة الاختيار */
        }
        div[role="radiogroup"] {
            gap: 15px;
        }
        div[role="radiogroup"] > label {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 12px;
            padding: 12px 20px;
            border-right: 4px solid transparent;
            transition: all 0.3s ease;
            cursor: pointer;
            width: 100%;
        }
        div[role="radiogroup"] > label:hover {
            background: rgba(255, 255, 255, 0.05);
        }
        /* تأثير النيون عند التحديد */
        div[role="radiogroup"] > label[data-checked="true"] {
            background: rgba(0, 243, 255, 0.05);
            border-right: 4px solid #00f3ff;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.3), inset 0 0 10px rgba(0, 243, 255, 0.1);
        }
        div[role="radiogroup"] label p {
            font-size: 18px !important;
            font-weight: bold !important;
            color: #e6edf3 !important;
            margin: 0 !important;
        }
        div[role="radiogroup"] label[data-checked="true"] p {
            color: #00f3ff !important;
            text-shadow: 0 0 8px rgba(0, 243, 255, 0.6);
        }

        /* 4. تصميم فقاعات الشات (WhatsApp Glass Style) */
        .stChatMessage {
            background: rgba(255, 255, 255, 0.03) !important;
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
            border-radius: 15px !important;
            backdrop-filter: blur(10px) !important;
            margin-bottom: 15px;
            padding: 15px !important;
        }
        /* تمييز رسائل المستخدم (الأرجواني) */
        .stChatMessage:nth-child(even) {
            border-right: 3px solid #ff00ff !important;
            background: rgba(255, 0, 255, 0.03) !important;
            box-shadow: 0 5px 15px rgba(255, 0, 255, 0.05);
        }
        /* تمييز رسائل الذكاء الاصطناعي (السماوي) */
        .stChatMessage:nth-child(odd) {
            border-right: 3px solid #00f3ff !important;
            background: rgba(0, 243, 255, 0.03) !important;
            box-shadow: 0 5px 15px rgba(0, 243, 255, 0.05);
        }

        /* 5. تصميم المدخلات والأزرار (Neon Inputs) */
        .stTextInput>div>div>input, .stTextArea>div>div>textarea {
            background: rgba(0, 0, 0, 0.4) !important;
            border: 1px solid rgba(0, 243, 255, 0.3) !important;
            color: #fff !important;
            border-radius: 12px !important;
        }
        .stTextInput>div>div>input:focus {
            border-color: #00f3ff !important;
            box-shadow: 0 0 15px rgba(0, 243, 255, 0.4) !important;
        }
        
        .stButton>button {
            background: transparent !important;
            border: 1px solid #00f3ff !important;
            color: #00f3ff !important;
            border-radius: 10px !important;
            box-shadow: 0 0 10px rgba(0, 243, 255, 0.2) !important;
            transition: all 0.3s !important;
        }
        .stButton>button:hover {
            background: rgba(0, 243, 255, 0.1) !important;
            box-shadow: 0 0 20px rgba(0, 243, 255, 0.5) !important;
        }

        /* إخفاء القوائم الافتراضية */
        #MainMenu, footer, header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)

inject_premium_css()

# ==========================================
# 4. إدارة الجلسة (Session State)
# ==========================================
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.user_role = None
    st.session_state.username = ""
    st.session_state.messages = []

# ==========================================
# 5. واجهة تسجيل الدخول
# ==========================================
def login_page():
    st.markdown("<div style='height: 10vh;'></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='display: flex; justify-content: center; align-items: center; gap: 15px;'><h1 style='color: #00f3ff; margin:0; font-size: 3rem;'>بوابة النظام الذكي</h1>{SVGS['database']}</div>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #888;'>يرجى المصادقة للوصول إلى مركز البيانات</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        username = st.text_input("معرف المستخدم")
        password = st.text_input("رمز المرور", type="password")
        if st.button("تسجيل الدخول", use_container_width=True):
            if username == "admin" and password == "admin":
                st.session_state.logged_in = True
                st.session_state.user_role = "admin"
                st.session_state.username = "المهندس العام"
                st.rerun()
            elif username == "worker" and password == "123":
                st.session_state.logged_in = True
                st.session_state.user_role = "worker"
                st.session_state.username = "الأسطى أحمد"
                st.rerun()
            else:
                st.error("بيانات غير مصرح بها!")

# ==========================================
# 6. واجهة الشات الاحترافية (WhatsApp Style)
# ==========================================
def chat_page():
    st.markdown(f"<div style='display: flex; align-items: center; gap: 15px; margin-bottom: 20px;'><h2 style='margin:0; color:#00f3ff;'>غرفة الدعم الفني</h2>{SVGS['chat']}</div>", unsafe_allow_html=True)

    # مساحة عرض الرسائل (Scrollable)
    chat_container = st.container(height=500, border=False)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("audio"):
                    st.audio(msg["audio"])

    st.markdown("<br>", unsafe_allow_html=True)

    # شريط الإدخال المدمج (واتساب ستايل)
    input_cols = st.columns([1, 11])
    
    with input_cols[0]:
        # زر الإرفاق (مشبك الورق) يفتح قائمة منبثقة للصور والصوت
        with st.popover(SVGS["attach"], help="إرفاق ملف أو تسجيل صوت"):
            st.markdown("<h4 style='color:#00f3ff; text-align:center;'>المرفقات الصوتية والمرئية</h4>", unsafe_allow_html=True)
            audio_val = st.audio_input("تسجيل مشكلة صوتية")
            img_val = st.file_uploader("رفع صورة للعطل", type=["png", "jpg"])

    with input_cols[1]:
        text_val = st.chat_input("اكتب رسالتك للأسطى سيد هنا...")

    # معالجة المدخلات
    if text_val or audio_val or img_val:
        user_text = text_val if text_val else "تم إرسال مرفق (صوت/صورة)."
        
        st.session_state.messages.append({"role": "user", "content": user_text})
        
        # رد وهمي لمحاكاة الذكاء الاصطناعي
        ai_response = "حاضر يا هندسة، جاري فحص المشكلة بناءً على المرفقات."
        st.session_state.messages.append({"role": "assistant", "content": ai_response})
        
        st.rerun() # تحديث الشاشة لعرض رسالة المستخدم فوراً

# ==========================================
# 7. الإعدادات الشاملة وقاعدة المعرفة
# ==========================================
def settings_page():
    st.markdown(f"<div style='display: flex; align-items: center; gap: 15px; margin-bottom: 20px;'><h2 style='margin:0; color:#ff00ff;'>الإعدادات المتقدمة للنظام</h2>{SVGS['settings']}</div>", unsafe_allow_html=True)
    
    # استخدام التابات لتنظيم الإعدادات باحترافية
    tab1, tab2, tab3 = st.tabs(["قاعدة المعرفة", "محركات الذكاء الاصطناعي", "صلاحيات النظام"])
    
    with tab1:
        st.markdown("<h3 style='color:#00f3ff;'>رفع الكتالوجات وتدريب النظام</h3>", unsafe_allow_html=True)
        st.info("الملفات المرفوعة هنا تتم معالجتها فوراً وتحفظ في قاعدة البيانات.")
        files = st.file_uploader("اسحب وافلت ملفات (PDF, TXT, CSV) هنا", accept_multiple_files=True)
        if st.button("معالجة ورفع لقاعدة البيانات", use_container_width=True):
            if files:
                with st.spinner("جاري الحقن في قاعدة البيانات..."):
                    time.sleep(2)
                    st.success("تم التحديث بنجاح!")
            else:
                st.warning("الرجاء إرفاق ملفات أولاً.")

    with tab2:
        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### مفاتيح الربط")
            st.text_input("OpenAI API Key", type="password")
            st.text_input("Pinecone API Key", type="password")
            st.text_input("ElevenLabs API Key", type="password")
        with colB:
            st.markdown("#### هندسة الأوامر")
            st.slider("مستوى إبداع الرد", 0.0, 1.0, 0.7)
            st.text_area("تعليمات شخصية المساعد", height=150, value="أنت الأسطى سيد، خبير التشغيل المعدني...")
            st.button("حفظ إعدادات الذكاء الاصطناعي", use_container_width=True)

    with tab3:
        st.markdown("#### إدارة المستخدمين")
        st.text_area("Firebase Admin SDK JSON", placeholder="لصق الكود هنا...")
        st.button("مزامنة مع السحابة", use_container_width=True)

# ==========================================
# 8. الهيكل العام للتطبيق
# ==========================================
def main():
    if not st.session_state.logged_in:
        login_page()
    else:
        with st.sidebar:
            st.markdown(f"<div style='display: flex; justify-content: center; margin-top: 20px;'>{SVGS['user']}</div>", unsafe_allow_html=True)
            st.markdown(f"<h3 style='text-align: center; color:#e6edf3; margin-top: 10px;'>{st.session_state.username}</h3>", unsafe_allow_html=True)
            st.markdown("<hr style='border-color: rgba(0, 243, 255, 0.2);'>", unsafe_allow_html=True)
            
            # التنقل الفاخر
            if st.session_state.user_role == "admin":
                menu_options = ["الدعم الفني والتشخيص", "لوحة التحكم والإعدادات"]
            else:
                menu_options = ["الدعم الفني والتشخيص"]
                
            choice = st.radio("القائمة", menu_options, label_visibility="collapsed")
            
            st.markdown("<hr style='border-color: rgba(0, 243, 255, 0.2);'>", unsafe_allow_html=True)
            
            # زر تسجيل الخروج مع تصميم مخصص
            if st.button("إنهاء الجلسة", use_container_width=True):
                st.session_state.clear()
                st.rerun()

        # عرض الصفحات
        if choice == "الدعم الفني والتشخيص":
            chat_page()
        elif choice == "لوحة التحكم والإعدادات":
            settings_page()

if __name__ == "__main__":
    main()
