import streamlit as st
import requests
from groq import Groq
from fpdf import FPDF
from supabase import create_client, Client
import pandas as pd
import os

# --- CONFIGURATION (Use st.secrets in production!) ---

OCR_API_KEY = st.secrets["OCR_API_KEY"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# Initialize Clients
client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="ClaimShield Pro", layout="wide")

# --- DAY 4: PDF LOGIC ---
def generate_pdf(text):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "FORMAL MEDICAL APPEAL", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=12)
    pdf.multi_cell(0, 10, text)
    return pdf.output()

# --- DAY 5: DATABASE LOGIC ---
def save_to_supabase(company, amount, letter):
    data = {"insurance_company": company, "bill_amount": amount, "appeal_letter": letter}
    supabase.table("claims").insert(data).execute()

# --- UI LAYOUT ---
st.title("🛡️ ClaimShield: One-Tap Appeal Platform")

tab1, tab2 = st.tabs(["🚀 New Appeal", "📊 Offender Dashboard"])

with tab1:
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.header("1. Scan Bill")
        uploaded_file = st.file_uploader("Upload Bill Image", type=["jpg", "png"], key="up")
        
        if uploaded_file and st.button("Extract & Analyze"):
            # OCR Step
            payload = {'apikey': OCR_API_KEY, 'OCREngine': 2}
            res = requests.post('https://api.ocr.space/parse/image', 
                                files={'file': uploaded_file.getvalue()}, data=payload).json()
            
            if res.get('ParsedResults'):
                text = res['ParsedResults'][0]['ParsedText']
                st.session_state['raw_text'] = text
                
                # AI Step (The Justice Prompt)
                chat = client.chat.completions.create(
                    model="llama-3.1-70b-versatile",
                    messages=[{"role": "system", "content": "You are a medical billing advocate. Draft an appeal letter based on the No Surprises Act."},
                              {"role": "user", "content": text}],
                    temperature=0.1
                )
                st.session_state['appeal_letter'] = chat.choices[0].message.content
                st.success("Analysis Complete!")

    with col_b:
        st.header("2. Legal Review")
        if 'appeal_letter' in st.session_state:
            st.text_area("Drafted Letter", st.session_state['appeal_letter'], height=300)
            
            # Form to save and download
            with st.form("save_case"):
                ins_co = st.text_input("Insurance Company")
                amt = st.number_input("Bill Amount ($)", min_value=0.0)
                submit = st.form_submit_button("📁 Save & Lock Case")
                
                if submit:
                    save_to_supabase(ins_co, amt, st.session_state['appeal_letter'])
                    st.balloons()
            
            pdf_bytes = generate_pdf(st.session_state['appeal_letter'])
            st.download_button("📥 Download PDF", data=pdf_bytes, file_name="Appeal.pdf")

with tab2:
    st.header("Insurance Company Leaderboard")
    response = supabase.table("claims").select("insurance_company, bill_amount").execute()
    if response.data:
        df = pd.DataFrame(response.data)
        st.subheader("Claims by Provider")
        st.bar_chart(df['insurance_company'].value_counts())
        st.metric("Total Value of Appeals", f"${df['bill_amount'].sum():,.2f}")




# --- AUTH FUNCTIONS ---
def sign_up(email, password):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        st.success("Registration successful! You can now log in.")
    except Exception as e:
        st.error(f"Error: {e}")

def sign_in(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state['user'] = res.user
        st.rerun()
    except Exception as e:
        st.error("Invalid login credentials.")

# --- LOGIN UI ---
if 'user' not in st.session_state:
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        if st.button("Log In"):
            sign_in(email, pw)
    with tab2:
        new_email = st.text_input("New Email")
        new_pw = st.text_input("New Password", type="password")
        if st.button("Create Account"):
            sign_up(new_email, new_pw)
    st.stop() # Stops the rest of the app from loading until logged in


if st.session_state['user'].email == "complyra86@gmail.com":
    st.sidebar.subheader("👑 Admin Mode")
    if st.sidebar.button("View Global Analytics"):
        # Fetch all claims from DB instead of just user's claims
        all_data = supabase.table("claims").select("*").execute()
        st.write(pd.DataFrame(all_data.data))


with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/shield.png", width=80)
    st.title("ClaimShield Guide")
    st.info("""
    **How it works:**
    1. **Upload:** Take a clear photo of your bill.
    2. **Analyze:** Our AI scans for Federal law violations.
    3. **Appeal:** Download the PDF and send it to your insurer.
    
    *Success Rate Tip:* Appeals sent via **Certified Mail** are 40% more likely to get a response!
    """)
    
    st.warning("⚠️ **Reminder:** Always redact your Social Security Number (SSN) before uploading for extra privacy.")


    # --- DAY 7: LEGAL FOOTER ---
st.markdown("---") # Visual separator

st.markdown(
    """
    <style>
    .footer {
        font-size: 10px;
        color: #808495;
        text-align: center;
    }
    </style>
    <div class="footer">
        <p>🛡️ <b>ClaimShield Pro (v1.0.0)</b> | 2026 Patient Advocacy Project</p>
        <p><b>LEGAL DISCLAIMER:</b> ClaimShield is an automated document assistant. We are not a law firm, attorney, 
        or medical professional. This tool generates draft appeals based on the No Surprises Act (42 U.S.C. § 300gg-131). 
        Users are responsible for verifying the accuracy of all generated documents before submission. 
        By using this service, you agree that ClaimShield is not liable for any outcomes related to your medical claims.</p>
    </div>
    """,
    unsafe_allow_html=True
)
