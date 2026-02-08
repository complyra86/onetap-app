# --------------------------------------------------------------
#  IMPORTS & CONFIG
# --------------------------------------------------------------
import streamlit as st
import requests
from groq import Groq
from fpdf import FPDF
from supabase import create_client, Client
import pandas as pd
import json
from postgrest.exceptions import APIError

# --- Secrets -------------------------------------------------
OCR_API_KEY   = st.secrets.get("OCR_API_KEY", "helloworld")
GROQ_API_KEY  = st.secrets.get("GROQ_API_KEY", "")
SUPABASE_URL  = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY  = st.secrets.get("SUPABASE_KEY", "")
# optional service‑role (keep secret!)
SUPABASE_SERVICE_ROLE = st.secrets.get("SUPABASE_SERVICE_ROLE", None)

# --- Clients -------------------------------------------------
client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# If you want a privileged client for writes, uncomment:
# if SUPABASE_SERVICE_ROLE:
#     service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
# else:
#     service_supabase = supabase

st.set_page_config(page_title="ClaimShield Pro", layout="wide", page_icon="🛡️")

# --------------------------------------------------------------
#  HELPER: safe_execute
# --------------------------------------------------------------
def safe_execute(q, context: str = "unknown"):
    """Run a Supabase query and display the real error JSON."""
    try:
        return q.execute()
    except APIError as err:
        payload = err.args[0] if err.args else {"code":"unknown","message":str(err)}
        st.error(f"❗ Supabase error ({payload.get('code')}) in {context}: {payload.get('message')}")
        st.caption("Full error payload:")
        st.code(json.dumps(payload, indent=2), language="json")
        print(f"[{context}] Supabase APIError payload:", payload)
        return None

# --------------------------------------------------------------
#  AUTH LOGIC
# --------------------------------------------------------------
def login_user(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = res.user
        st.session_state['session'] = supabase.auth.session()
        # tiny debug badge (remove for production)
        if st.session_state.get('session'):
            token = st.session_state['session'].access_token
            st.caption(f"🔐 JWT (first 30 chars): {token[:30]}…")
        st.rerun()
    except Exception:
        st.error("❌ Invalid email or password.")

def register_user(email, password):
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        st.success("✅ Registration successful! Check your inbox for the confirmation link.")
    except Exception as e:
        st.error(f"❌ Registration failed: {e}")

def logout_user():
    supabase.auth.sign_out()
    for k in ["user", "session"]:
        st.session_state.pop(k, None)
    st.rerun()

# --------------------------------------------------------------
#  CORE APP FUNCTIONS
# --------------------------------------------------------------
def generate_pdf(text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "FORMAL MEDICAL APPEAL", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, text)
    return pdf.output()

def save_claim(company, amount, letter):
    data = {
        "user_id": st.session_state['user'].id,
        "insurance_company": company,
        "bill_amount": amount,
        "appeal_letter": letter
    }
    # Use the privileged client only if you set SUPABASE_SERVICE_ROLE
    # client_to_use = service_supabase if SUPABASE_SERVICE_ROLE else supabase
    # resp = safe_execute(client_to_use.table("claims").insert(data), context="save_claim")
    resp = safe_execute(supabase.table("claims").insert(data), context="save_claim")
    if resp:
        st.success("✅ Claim saved to your history!")
    else:
        st.warning("❌ Claim NOT saved – see error above.")

# --------------------------------------------------------------
#  UI: AUTH/GATEKEEPER
# --------------------------------------------------------------
if 'user' not in st.session_state:
    st.title("🛡️ ClaimShield")
    st.subheader("The AI‑Powered Machine for Fighting Medical Debt")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown("""
        ### Why ClaimShield?
        * **Instant Audits:** Scan your bill for *No Surprises Act* violations.  
        * **Legal Leverage:** AI drafts high‑authority appeals in seconds.  
        * **Zero Cost:** Built for patients, not for profit.
        """)
        st.image("https://img.icons8.com/fluency/240/security-shield.png", width=200)
    with col2:
        mode = st.radio("Access Portal", ["Login", "Register"])
        email = st.text_input("Email")
        pwd   = st.text_input("Password", type="password")
        if mode == "Login":
            if st.button("Unlock Dashboard"):
                login_user(email, pwd)
        else:
            if st.button("Create Free Account"):
                register_user(email, pwd)
    st.info("💡 Tip: Use a strong password to protect your medical claim history.")
    st.stop()

# --------------------------------------------------------------
#  UI: MAIN APP (after login)
# --------------------------------------------------------------
with st.sidebar:
    st.write(f"👤 **User:** {st.session_state['user'].email}")
    if st.button("Log Out"):
        logout_user()
    st.divider()
    is_admin = st.session_state['user'].email == "complyra86@gmail.com"
    if is_admin:
        st.warning("👑 ADMIN ACCESS ENABLED")

st.title("🛡️ ClaimShield: One‑Tap Appeal Platform")
tab_new, tab_hist = st.tabs(["🚀 New Appeal", "📊 History & Analytics"])

# ------------------- NEW APPEAL TAB -------------------------
with tab_new:
    c_left, c_right = st.columns(2)

    # ---- 1. OCR + LLM ----
    with c_left:
        st.header("1️⃣ Scan & Extract")
        uploaded = st.file_uploader("Upload Medical Bill (JPG/PNG)", type=["jpg","png"])
        if uploaded and st.button("Analyze Document"):
            with st.spinner("🔍 Running OCR + LLM…"):
                payload = {'apikey': OCR_API_KEY, 'OCREngine': 2}
                ocr_res = requests.post(
                    "https://api.ocr.space/parse/image",
                    files={'file': uploaded.getvalue()},
                    data=payload,
                ).json()
                if ocr_res.get('ParsedResults'):
                    txt = ocr_res['ParsedResults'][0]['ParsedText']
                    st.session_state['last_text'] = txt
                    prompt = f"System: You are a legal advocate. User: Draft a No Surprises Act appeal for: {txt}"
                    chat = client.chat.completions.create(
                        model="llama-3.1-70b-versatile",
                        messages=[{"role":"user","content":prompt}]
                    )
                    st.session_state['last_letter'] = chat.choices[0].message.content
                    st.success("✅ Analysis ready!")
                else:
                    st.error("❌ OCR failed – try another image.")

    # ---- 2. Review / Save ----
    with c_right:
        st.header("2️⃣ Review & Save")
        if 'last_letter' in st.session_state:
            letter = st.text_area("Final Appeal Letter", st.session_state['last_letter'], height=300)
            with st.form("save_form"):
                ins = st.text_input("Insurance Provider")
                val = st.number_input("Bill Value ($)", min_value=0.0)
                if st.form_submit_button("📁 Save to My Case History"):
                    save_claim(ins, val, letter)
                    st.balloons()
            st.download_button(
                "📥 Download PDF",
                data=generate_pdf(letter),
                file_name="Appeal.pdf",
                mime="application/pdf",
            )
        else:
            st.info("📂 Upload a bill and click **Analyze Document** to generate a letter.")

# ------------------- HISTORY TAB -------------------------
with tab_hist:
    st.header("📂 Your Claim History")
    base_query = supabase.table("claims").select("id,created_at,insurance_company,bill_amount,status")
    if not is_admin:
        base_query = base_query.eq("user_id", st.session_state['user'].id)

    resp = safe_execute(base_query, context="fetch_claims")
    if resp and resp.data:
        df = pd.DataFrame(resp.data)
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"])
        st.dataframe(df[["created_at","insurance_company","bill_amount","status"]],
                     use_container_width=True)
        st.metric("Total Disputed Amount",
                  f"${df['bill_amount'].sum():,.2f}")
    else:
        st.info("🗂️ No claims saved yet. Start by uploading a bill in the **New Appeal** tab!")

# --------------------------------------------------------------
#  FOOTER
# --------------------------------------------------------------
st.markdown("---")
st.markdown(
    """
    <style>
    .complyra-footer {
        font-size:12px;
        color:#5d6d7e;
        text-align:center;
        padding:20px;
        line-height:1.6;
    }
    </style>
    <div class="complyra-footer">
        <p>© 2026 <b>Complyra</b>. All Rights Reserved.</p>
        <p><i>ClaimShield is a proprietary technology of Complyra. Unauthorized duplication or 
        commercial use of this platform's AI logic and legal‑audit workflows is strictly prohibited.</i></p>
        <p><b>Legal Notice:</b> This application provides automated assistance based on the No Surprises Act. 
        It does not constitute legal representation. All generated appeals must be reviewed by the user.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
