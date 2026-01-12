import streamlit as st
import requests
from groq import Groq
from fpdf import FPDF
from supabase import create_client, Client
import pandas as pd
from dotenv import load_dotenv
import os

load_dotenv()  # reads .env file

# --- CONFIGURATION (Use st.secrets in production!) ---

OCR_API_KEY = os.getenv("OCR_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

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