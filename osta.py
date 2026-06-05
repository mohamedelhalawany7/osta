import os
import sys
import json
import threading
import time
import socket
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="نظام الدريني",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
#MainMenu,header,footer,.stDeployButton,
[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],[data-testid="collapsedControl"]{
    display:none!important;
}
.main .block-container{padding:0!important;max-width:100%!important;}
.main{padding:0!important;}
body{margin:0;padding:0;background:#0A0E17;}
iframe{border:none!important;}
</style>
""", unsafe_allow_html=True)

SERVER_PORT = 8502


def setup_secrets():
    try:
        for key in ["FERNET_KEY", "SECRET_KEY", "ENV", "NGROK_TOKEN"]:
            if key in st.secrets and not os.getenv(key):
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass
    if not os.path.exists("firebase-key.json"):
        try:
            if "firebase" in st.secrets:
                fb = dict(st.secrets["firebase"])
                if "private_key" in fb:
                    fb["private_key"] = fb["private_key"].replace("\\n", "\n")
                with open("firebase-key.json", "w", encoding="utf-8") as f:
                    json.dump(fb, f, ensure_ascii=False)
        except Exception:
            pass


def is_port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except Exception:
        return False


def start_fastapi():
    if is_port_open(SERVER_PORT):
        return True

    def run():
        try:
            import uvicorn
            sys.path.insert(0, os.getcwd())
            from main import app
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=SERVER_PORT,
                log_level="critical",
                access_log=False
            )
        except Exception as e:
            st.session_state["fastapi_error"] = str(e)

    threading.Thread(target=run, daemon=True).start()

    for _ in range(40):
        if is_port_open(SERVER_PORT):
            return True
        time.sleep(0.5)
    return False


def start_ngrok():
    cached = st.session_state.get("ngrok_url")
    if cached:
        return cached

    ngrok_token = os.getenv("NGROK_TOKEN", "")

    try:
        from pyngrok import ngrok, conf
        if ngrok_token:
            conf.get_default().auth_token = ngrok_token
        ngrok.kill()
        time.sleep(1)
        tunnel = ngrok.connect(SERVER_PORT, "http")
        url = tunnel.public_url.replace("http://", "https://")
        st.session_state["ngrok_url"] = url
        return url
    except Exception as e:
        st.session_state["ngrok_error"] = str(e)
        return None


def show_loading(msg):
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:center;
        height:90vh;background:#0A0E17;color:#00F0FF;
        font-family:Cairo,sans-serif;font-size:1.3rem;font-weight:700;
        flex-direction:column;gap:24px;">
        <div style="font-size:4rem;">⚙️</div>
        <div>{msg}</div>
    </div>
    """, unsafe_allow_html=True)


def main():
    setup_secrets()

    # الخطوة 1: تشغيل FastAPI
    if "fastapi_started" not in st.session_state:
        show_loading("جاري تشغيل محرك النظام...")
        ok = start_fastapi()

        if not ok:
            err = st.session_state.get("fastapi_error", "خطأ غير معروف")
            st.error(f"فشل تشغيل FastAPI: {err}")
            st.info("تأكد من وجود main.py في نفس مجلد osta.py")
            if st.button("إعادة المحاولة"):
                st.rerun()
            return

        st.session_state["fastapi_started"] = True
        st.rerun()

    # الخطوة 2: تشغيل ngrok
    if "ngrok_url" not in st.session_state:
        show_loading("جاري فتح النفق للإنترنت...")
        url = start_ngrok()

        if not url:
            err = st.session_state.get("ngrok_error", "")
            st.warning(f"تعذر فتح ngrok: {err}")
            st.info("أضف NGROK_TOKEN في Streamlit Secrets من ngrok.com")
            st.markdown(f"""
            <div style="background:#0A0E17;border:1px solid #00F0FF;
                border-radius:16px;padding:40px;text-align:center;
                font-family:Cairo,sans-serif;color:#00F0FF;margin-top:20px;">
                <div style="font-size:3rem;">⚙️</div>
                <h2 style="color:#fff;margin:16px 0;">السيرفر يعمل محلياً</h2>
                <p style="color:#8B9BB4;">افتح الرابط ده في تاب جديد:</p>
                <a href="http://localhost:{SERVER_PORT}" target="_blank"
                   style="color:#00F0FF;font-size:1.2rem;font-weight:700;">
                   http://localhost:{SERVER_PORT}
                </a>
            </div>
            """, unsafe_allow_html=True)
            return

        st.rerun()

    # الخطوة 3: عرض التطبيق
    url = st.session_state.get("ngrok_url", "")

    iframe_html = f"""<!DOCTYPE html>
<html>
<head>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ width:100%; height:100vh; overflow:hidden; background:#0A0E17; }}
iframe {{ width:100%; height:100vh; border:none; display:block; }}
</style>
</head>
<body>
<iframe
    src="{url}"
    allow="microphone *; camera *; autoplay *; clipboard-read *; clipboard-write *"
    allowfullscreen
></iframe>
<script>
function resize() {{
    document.querySelector('iframe').style.height = window.innerHeight + 'px';
}}
window.addEventListener('resize', resize);
resize();
</script>
</body>
</html>"""

    components.html(iframe_html, height=850, scrolling=False)

    st.markdown(f"""
    <div style="position:fixed;bottom:10px;left:10px;z-index:9999;">
        <a href="{url}" target="_blank" style="
            background:#00F0FF;color:#000;padding:8px 16px;
            border-radius:20px;font-family:Cairo,sans-serif;
            font-weight:700;text-decoration:none;font-size:0.85rem;
            box-shadow:0 0 15px #00F0FF;">
            فتح في تاب جديد ↗
        </a>
    </div>
    """, unsafe_allow_html=True)


main()
