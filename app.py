import streamlit as st
import requests
from groq import Groq
from fpdf import FPDF
from supabase import create_client, Client
import pandas as pd

# --- 1. CONFIGURATION & SECRETS ---
# Ensure these are set in your Streamlit Cloud Secrets or .env
OCR_API_KEY = st.secrets.get("OCR_API_KEY", "helloworld")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "")
SUPABASE_URL = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY", "")

# Initialize Clients
client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="ClaimShield Pro", layout="wide", page_icon="🛡️")

# --- 2. AUTHENTICATION LOGIC ---

def login_user(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = res.user
        st.rerun()
    except Exception as e:
        st.error("Invalid email or password.")

def register_user(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.success("Registration successful! Please check your email or login.")
    except Exception as e:
        st.error(f"Registration failed: {e}")

def logout_user():
    supabase.auth.sign_out()
    del st.session_state['user']
    st.rerun()

# --- 3. CORE APP FUNCTIONS ---

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
    supabase.table("claims").insert(data).execute()

# --- 4. NAVIGATION & ROUTING ---

if 'user' not in st.session_state:
    # --- LANDING PAGE / LOGIN ---
    st.title("🛡️ ClaimShield")
    st.subheader("The AI-Powered Machine for Fighting Medical Debt")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        ### Why ClaimShield?
        * **Instant Audits:** We scan your bill for 'No Surprises Act' violations.
        * **Legal Leverage:** AI drafts high-authority appeals in seconds.
        * **Zero Cost:** Built for patients, not for profit.
        """)
        st.image("https://img.icons8.com/fluency/240/security-shield.png", width=200)

    with col2:
        auth_mode = st.radio("Access Portal", ["Login", "Register"])
        email = st.text_input("Email Address")
        password = st.text_input("Password", type="password")
        
        if auth_mode == "Login":
            if st.button("Unlock Dashboard", use_container_width=True):
                login_user(email, password)
        else:
            if st.button("Create Free Account", use_container_width=True):
                register_user(email, password)
    
    st.info("💡 Tip: Use a strong password to protect your medical claim history.")
    st.stop() # Force app to stop here if not logged in

else:
    # --- AUTHENTICATED APP INTERFACE ---
    with st.sidebar:
        st.write(f"👤 **User:** {st.session_state['user'].email}")
        if st.button("Log Out"):
            logout_user()
        
        st.divider()
        # Admin logic
        is_admin = st.session_state['user'].email == "complyra86@gmail.com" # Change to your email
        if is_admin:
            st.warning("👑 ADMIN ACCESS ENABLED")

    st.title("🛡️ ClaimShield: One-Tap Appeal Platform")
    
    tab1, tab2 = st.tabs(["🚀 New Appeal", "📊 History & Analytics"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.header("1. Scan & Extract")
            file = st.file_uploader("Upload Medical Bill (JPG/PNG)", type=["jpg", "png"])
            if file and st.button("Analyze Document"):
                with st.spinner("AI is auditing for legal violations..."):
                    payload = {'apikey': OCR_API_KEY, 'OCREngine': 2}
                    res = requests.post('https://api.ocr.space/parse/image', 
                                        files={'file': file.getvalue()}, data=payload).json()
                    
                    if res.get('ParsedResults'):
                        text = res['ParsedResults'][0]['ParsedText']
                        st.session_state['last_text'] = text
                        
                        prompt = f"System: You are a legal advocate. User: Draft a No Surprises Act appeal for: {text}"
                        chat = client.chat.completions.create(
                            model="llama-3.1-70b-versatile",
                            messages=[{"role": "user", "content": prompt}]
                        )
                        st.session_state['last_letter'] = chat.choices[0].message.content
                        st.success("Analysis Ready!")

        with c2:
            st.header("2. Review & Save")
            if 'last_letter' in st.session_state:
                letter = st.text_area("Final Appeal Letter", st.session_state['last_letter'], height=300)
                
                with st.form("save_case"):
                    ins = st.text_input("Insurance Provider")
                    val = st.number_input("Bill Value ($)", min_value=0.0)
                    if st.form_submit_button("📁 Save to My Case History"):
                        save_claim(ins, val, letter)
                        st.balloons()
                
                st.download_button("📥 Download PDF", data=generate_pdf(letter), file_name="Appeal.pdf")

    with tab2:
        st.header("Your Claim History")
        # Filter data by logged-in user ID
        query = supabase.table("claims").select("*")
        if not is_admin:
            query = query.eq("user_id", st.session_state['user'].id)
        
        data = query.execute()
        
        if data.data:
            df = pd.DataFrame(data.data)
            st.dataframe(df[['created_at', 'insurance_company', 'bill_amount', 'status']], use_container_width=True)
            st.metric("Total Disputed Amount", f"${df['bill_amount'].sum():,.2f}")
        else:
            st.info("No claims saved yet. Start by uploading a bill in the first tab!")

# --- FOOTER ---
st.markdown("<br><hr><center><small>ClaimShield is a tool, not a law firm. Verify all documents before submission.</small></center>", unsafe_allow_html=True)
