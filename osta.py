"""
osta.py - Streamlit wrapper يشغل FastAPI في الخلفية ويعرض الواجهة كاملة
"""
import os
import sys
import threading
import time
import streamlit as st
import streamlit.components.v1 as components

# =====================================================================
# إعداد صفحة Streamlit - لازم يكون أول حاجة
# =====================================================================
st.set_page_config(
    page_title="نظام الدريني",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# إخفاء كل عناصر Streamlit الافتراضية بالكامل
st.markdown("""
<style>
    #MainMenu, header, footer, .stDeployButton,
    [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], .viewerBadge_container__1QSob,
    .styles_viewerBadge__1yB5_, #stDecoration,
    [data-testid="collapsedControl"] { display: none !important; }
    
    .main .block-container {
        padding: 0 !important;
        max-width: 100% !important;
    }
    .main {
        padding: 0 !important;
    }
    iframe {
        border: none !important;
        display: block !important;
    }
</style>
""", unsafe_allow_html=True)

# =====================================================================
# تهيئة Firebase من Streamlit Secrets
# =====================================================================
def setup_firebase_from_secrets():
    """استخراج مفاتيح Firebase من Streamlit Secrets وحفظها في ملف مؤقت"""
    if os.path.exists("firebase-key.json"):
        return True
    try:
        if "firebase" in st.secrets:
            import json
            firebase_dict = dict(st.secrets["firebase"])
            # تحويل private_key من string لـ newlines حقيقية
            if "private_key" in firebase_dict:
                firebase_dict["private_key"] = firebase_dict["private_key"].replace("\\n", "\n")
            with open("firebase-key.json", "w", encoding="utf-8") as f:
                json.dump(firebase_dict, f, ensure_ascii=False, indent=2)
            return True
    except Exception as e:
        pass
    return False

# =====================================================================
# تهيئة متغيرات البيئة من Streamlit Secrets
# =====================================================================
def setup_env_from_secrets():
    """نقل الـ secrets لـ environment variables"""
    try:
        secret_keys = ["FERNET_KEY", "SECRET_KEY", "ENV"]
        for key in secret_keys:
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = st.secrets[key]
    except Exception:
        pass

# =====================================================================
# تشغيل FastAPI في Thread منفصل
# =====================================================================
_server_started = False
_server_lock = threading.Lock()

def start_fastapi_server():
    """تشغيل uvicorn في background thread"""
    global _server_started
    
    with _server_lock:
        if _server_started:
            return
        _server_started = True

    def run():
        try:
            import uvicorn
            # استيراد التطبيق من main.py
            from main import app
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=8502,
                log_level="error",
                access_log=False
            )
        except Exception as e:
            pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    
    # انتظار حتى يبدأ السيرفر
    import socket
    max_wait = 30
    waited = 0
    while waited < max_wait:
        try:
            with socket.create_connection(("localhost", 8502), timeout=1):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
            waited += 0.5

# =====================================================================
# الصفحة الرئيسية - iframe يعرض FastAPI
# =====================================================================
def main():
    # تهيئة الأسرار
    setup_env_from_secrets()
    setup_firebase_from_secrets()
    
    # تشغيل السيرفر
    if "server_started" not in st.session_state:
        start_fastapi_server()
        st.session_state["server_started"] = True
        time.sleep(2)  # انتظار إضافي للتأكد

    # رسالة تحميل
    if "loaded" not in st.session_state:
        st.session_state["loaded"] = True
        placeholder = st.empty()
        with placeholder.container():
            st.markdown("""
            <div style="
                display:flex; align-items:center; justify-content:center;
                height:100vh; background:#0A0E17; color:#00F0FF;
                font-family:'Cairo',sans-serif; font-size:1.5rem; font-weight:700;
                flex-direction:column; gap:20px;
            ">
                <div style="font-size:3rem;">⚙️</div>
                <div>جاري تشغيل نظام الدريني...</div>
                <div style="font-size:0.9rem; color:#8B9BB4;">يستغرق ذلك بضع ثوانٍ في أول مرة</div>
            </div>
            """, unsafe_allow_html=True)
        time.sleep(3)
        placeholder.empty()

    # عرض التطبيق كاملاً داخل iframe
    components.html(
        """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body { overflow: hidden; background: #0A0E17; }
                iframe {
                    width: 100vw;
                    height: 100vh;
                    border: none;
                    display: block;
                }
            </style>
        </head>
        <body>
            <iframe 
                id="appFrame"
                src="http://localhost:8502"
                allowfullscreen
                allow="microphone; camera; autoplay; clipboard-read; clipboard-write"
            ></iframe>
            <script>
                // تحديث الـ iframe تلقائياً لو السيرفر لسه بيبدأ
                const frame = document.getElementById('appFrame');
                let attempts = 0;
                
                frame.onerror = function() {
                    if (attempts < 10) {
                        attempts++;
                        setTimeout(() => { frame.src = frame.src; }, 2000);
                    }
                };

                // resize الـ iframe مع الصفحة
                function resizeFrame() {
                    frame.style.height = window.innerHeight + 'px';
                    frame.style.width = window.innerWidth + 'px';
                }
                window.addEventListener('resize', resizeFrame);
                resizeFrame();
            </script>
        </body>
        </html>
        """,
        height=1080,
        scrolling=False
    )

if __name__ == "__main__":
    main()
