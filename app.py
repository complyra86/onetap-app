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
import ast                     # ← needed for fallback parsing of dict‑like strings
from postgrest.exceptions import APIError

# --------------------------------------------------------------
#  SECRETS
# --------------------------------------------------------------
OCR_API_KEY   = st.secrets.get("OCR_API_KEY", "helloworld")
GROQ_API_KEY  = st.secrets.get("GROQ_API_KEY", "")
SUPABASE_URL  = st.secrets.get("SUPABASE_URL", "")
SUPABASE_KEY  = st.secrets.get("SUPABASE_KEY", "")
# optional service‑role (keep secret!)
SUPABASE_SERVICE_ROLE = st.secrets.get("SUPABASE_SERVICE_ROLE", None)

# --------------------------------------------------------------
#  SUPABASE & GROQ CLIENTS
# --------------------------------------------------------------
client = Groq(api_key=GROQ_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# If you want a privileged client for writes, uncomment the block below:
# if SUPABASE_SERVICE_ROLE:
#     service_supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE)
# else:
#     service_supabase = supabase

# --------------------------------------------------------------
#  STREAMLIT PAGE SETTINGS
# --------------------------------------------------------------
st.set_page_config(page_title="ClaimShield Pro", layout="wide", page_icon="🛡️")

# --------------------------------------------------------------
#  HELPER: safe_execute
# --------------------------------------------------------------
def _ensure_mapping(maybe_mapping):
    """
    Coerce `maybe_mapping` into a dict‑like object that always supports `.get()`.

    Handles:
        * Already a dict → returned unchanged
        * JSON string (double‑quoted) → parsed with `json.loads`
        * Python‑literal string (single‑quoted dict) → parsed with `ast.literal_eval`
        * Anything else → wrapped into a minimal dict with a generic “unknown” code
    """
    if isinstance(maybe_mapping, dict):
        return maybe_mapping

    if isinstance(maybe_mapping, str):
        # Try proper JSON first
        try:
            parsed = json.loads(maybe_mapping)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Fallback to a Python literal (covers single‑quoted dicts)
        try:
            parsed = ast.literal_eval(maybe_mapping)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, SyntaxError):
            pass

        # Still a plain string → treat it as the error message
        return {"code": "unknown", "message": maybe_mapping}

    # Anything else (None, int, etc.) → stringify it
    return {"code": "unknown", "message": str(maybe_mapping)}


def safe_execute(q, context: str = "unknown"):
    """
    Execute a Supabase query (`q`) and present a friendly error UI if it fails.

    Parameters
    ----------
    q : Any
        An object that implements `.execute()`. In Supabase this is usually a
        `PostgrestQueryBuilder` (e.g. `supabase.table(...).select(...)`).

    context : str, optional
        Human‑readable description of where the query is run; used in the UI
        and in the console log.

    Returns
    -------
    The result of `q.execute()` on success, otherwise `None`.
    """
    try:
        return q.execute()
    except APIError as err:
        # -----------------------------------------------------------------
        # 1️⃣ Extract the raw payload (could be a dict, JSON string, or plain text)
        # -----------------------------------------------------------------
        raw_payload = err.args[0] if err.args else {"code": "unknown", "message": str(err)}

        # -----------------------------------------------------------------
        # 2️⃣ Convert to a dict that always supports .get()
        # -----------------------------------------------------------------
        payload = _ensure_mapping(raw_payload)

        # -----------------------------------------------------------------
        # 3️⃣ Show a nice error message inside Streamlit
        # -----------------------------------------------------------------
        st.error(
            f"❗ Supabase error ({payload.get('code', 'unknown')}) in {context}: "
            f"{payload.get('message', str(err))}"
        )
        st.caption("Full error payload:")
        st.code(json.dumps(payload, indent=2, sort_keys=True), language="json")

        # -----------------------------------------------------------------
        # 4️⃣ Also log to the console – handy during development
        # -----------------------------------------------------------------
        print(f"[{context}] Supabase APIError payload:", payload)

        return None

# --------------------------------------------------------------
#  AUTH LOGIC
# --------------------------------------------------------------
def login_user(email: str, password: str):
    """Log the user in and store the JWT in `st.session_state`."""
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        st.session_state["user"] = res.user
        st.session_state["session"] = supabase.auth.session()

        # tiny debug badge (remove for production)
        if st.session_state.get("session"):
            token = st.session_state["session"].access_token
            st.caption(f"🔐 JWT (first 30 chars): {token[:30]}…")

        st.rerun()
    except Exception:
        st.error("❌ Invalid email or password.")


def register_user(email: str, password: str):
    """Create a new account."""
    try:
        supabase.auth.sign_up({"email": email, "password": password})
        st.success("✅ Registration successful! Check your inbox for the confirmation link.")
    except Exception as e:
        st.error(f"❌ Registration failed: {e}")


def logout_user():
    """Sign out and clear the session."""
    supabase.auth.sign_out()
    for k in ["user", "session"]:
        st.session_state.pop(k, None)
    st.rerun()


def send_password_reset(email: str):
    """Email the user a password‑reset link."""
    try:
        supabase.auth.reset_password_for_email(email)
        st.success(f"✅ Password reset link sent to {email}. Check your inbox.")
    except Exception as e:
        st.error(f"❌ Could not send reset link: {e}")


def update_email(new_email: str):
    """Change the logged‑in user's login email (requires confirmation)."""
    try:
        supabase.auth.update_user({"email": new_email})
        st.success(
            f"✅ Confirmation link sent to {new_email}. "
            "Your login email will change once you confirm it."
        )
    except Exception as e:
        st.error(f"❌ Could not update email: {e}")

# --------------------------------------------------------------
#  CORE APP FUNCTIONS
# --------------------------------------------------------------
def generate_pdf(text: str) -> bytes:
    """Create a simple PDF from the supplied text and return the binary data."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "FORMAL MEDICAL APPEAL", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 8, text)
    return pdf.output(dest="S").encode("latin1")   # return bytes for Streamlit download


def save_claim(company: str, amount: float, letter: str):
    """Persist a claim row in the `claims` table."""
    data = {
        "user_id": st.session_state["user"].id,
        "insurance_company": company,
        "bill_amount": amount,
        "appeal_letter": letter,
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
#  UI: AUTH / GATEKEEPER
# --------------------------------------------------------------
if "user" not in st.session_state:
    st.title("🛡️ ClaimShield")
    st.subheader("The AI‑Powered Machine for Fighting Medical Debt")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown(
            """
            ### Why ClaimShield?
            * **Instant Audits:** Scan your bill for *No Surprises Act* violations.  
            * **Legal Leverage:** AI drafts high‑authority appeals in seconds.  
            * **Zero Cost:** Built for patients, not for profit.
            """
        )
        st.image(
            "https://img.icons8.com/fluency/240/security-shield.png",
            width=200,
        )

    with col2:
        mode = st.radio("Access Portal", ["Login", "Register"])
        email = st.text_input("Email")
        pwd = st.text_input("Password", type="password")

        if mode == "Login":
            if st.button("Unlock Dashboard"):
                login_user(email, pwd)
            with st.expander("Forgot your password?"):
                reset_email = st.text_input("Email for password reset", key="reset_email")
                if st.button("Send Reset Link"):
                    if reset_email:
                        send_password_reset(reset_email)
                    else:
                        st.warning("Enter your email above first.")
        else:
            if st.button("Create Free Account"):
                register_user(email, pwd)

    st.info("💡 Tip: Use a strong password to protect your medical claim history.")
    st.stop()   # stop execution until the user logs in

# --------------------------------------------------------------
#  UI: MAIN APP (after login)
# --------------------------------------------------------------
with st.sidebar:
    st.write(f"👤 **User:** {st.session_state['user'].email}")
    if st.button("Log Out"):
        logout_user()

    with st.expander("⚙️ Account Settings"):
        st.caption("Change login email")
        new_email = st.text_input("New email", key="new_email")
        if st.button("Update Email"):
            if new_email:
                update_email(new_email)
            else:
                st.warning("Enter a new email above first.")

        st.caption("Change password")
        st.write("We'll email you a secure reset link.")
        if st.button("Send Password Reset Link"):
            send_password_reset(st.session_state["user"].email)

    st.divider()
    is_admin = st.session_state["user"].email == "complyra86@gmail.com"
    if is_admin:
        st.warning("👑 ADMIN ACCESS ENABLED")

st.title("🛡️ ClaimShield: One‑Tap Appeal Platform")
tab_new, tab_hist = st.tabs(["🚀 New Appeal", "📊 History & Analytics"])

# ------------------- NEW APPEAL TAB -------------------------
with tab_new:
    c_left, c_right = st.columns(2)

    # ---- 1️⃣ OCR + LLM ----
    with c_left:
        st.header("1️⃣ Scan & Extract")
        uploaded = st.file_uploader(
            "Upload Medical Bill (JPG/PNG/PDF)", type=["jpg", "jpeg", "png", "pdf"]
        )
        if uploaded and st.button("Analyze Document"):
            with st.spinner("🔍 Running OCR + LLM…"):
                file_ext = uploaded.name.rsplit(".", 1)[-1].upper()
                payload = {
                    "apikey": OCR_API_KEY,
                    "OCREngine": 2,
                    "filetype": "PDF" if file_ext == "PDF" else file_ext,
                }
                ocr_res = requests.post(
                    "https://api.ocr.space/parse/image",
                    files={"file": (uploaded.name, uploaded.getvalue())},
                    data=payload,
                ).json()

                if ocr_res.get("IsErroredOnProcessing"):
                    err_msg = "; ".join(ocr_res.get("ErrorMessage", []) or ["Unknown OCR error"])
                    st.error(f"❌ OCR failed – {err_msg}")
                elif ocr_res.get("ParsedResults"):
                    # Concatenate text across all pages (multi‑page PDFs included)
                    txt = "\n".join(
                        page.get("ParsedText", "") for page in ocr_res["ParsedResults"]
                    ).strip()
                    if not txt:
                        st.error("❌ OCR found no readable text – try another file.")
                    else:
                        st.session_state["last_text"] = txt

                        prompt = (
                            f"System: You are a legal advocate. "
                            f"User: Draft a No Surprises Act appeal for: {txt}"
                        )
                        chat = client.chat.completions.create(
                            model="llama-3.1-70b-versatile",
                            messages=[{"role": "user", "content": prompt}],
                        )
                        st.session_state["last_letter"] = chat.choices[0].message.content
                        st.success("✅ Analysis ready!")
                else:
                    st.error("❌ OCR failed – try another file.")

    # ---- 2️⃣ Review / Save ----
    with c_right:
        st.header("2️⃣ Review & Save")
        if "last_letter" in st.session_state:
            letter = st.text_area(
                "Final Appeal Letter", st.session_state["last_letter"], height=300
            )
            with st.form("save_form"):
                ins = st.text_input("Insurance Provider")
                val = st.number_input(
                    "Bill Value ($)", min_value=0.0, format="%.2f", step=0.01
                )
                if st.form_submit_button("📁 Save to My Case History"):
                    save_claim(ins, float(val), letter)
                    st.balloons()

            st.download_button(
                "📥 Download PDF",
                data=generate_pdf(letter),
                file_name="Appeal.pdf",
                mime="application/pdf",
            )
        else:
            st.info(
                "📂 Upload a bill and click **Analyze Document** to generate a letter."
            )

# ------------------- HISTORY TAB -------------------------
with tab_hist:
    st.header("📂 Your Claim History")
    base_query = (
        supabase.table("claims")
        .select("id,created_at,insurance_company,bill_amount,status")
    )
    if not is_admin:
        base_query = base_query.eq("user_id", st.session_state["user"].id)

    resp = safe_execute(base_query, context="fetch_claims")
    if resp and resp.data:
        df = pd.DataFrame(resp.data)
        if "created_at" in df.columns:
            df["created_at"] = pd.to_datetime(df["created_at"])
        # Show a tidy table
        st.dataframe(
            df[["created_at", "insurance_company", "bill_amount", "status"]],
            use_container_width=True,
        )
        # Simple KPI
        total = df["bill_amount"].sum()
        st.metric("Total Disputed Amount", f"${total:,.2f}")
    else:
        st.info(
            "🗂️ No claims saved yet. Start by uploading a bill in the **New Appeal** tab!"
        )

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
