# app.py — Epstein Files · Resume Screener
import streamlit as st
import fitz
import pandas as pd
import json
import hashlib
import os
import time
import uuid
import pytesseract
from PIL import Image
import io
from groq import Groq
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ─────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────

SHEET_ID = "1MZNcsXXf0l5xG7l0Xg221yKfDAkjD1s9mxI1AUCoH34"

CRITERIA = """
1. Relevant experience (years + quality)
2. Key skills & tools match
3. Education / certifications
4. Achievements & impact (quantified)
5. Overall fit, transferable skills, potential growth
6. Soft skills, leadership, attitude
"""

MODELS_TO_TRY = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]

exhausted_models = set()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Column order ──
# Left side:  auto-filled by system
# Right side: manually updated by recruiter
TRACKER_COLUMNS = [
    "record_id", "candidate_name", "phone_number", "job_position", "company",
    "screening_status", "total_score", "confidence_level", "missing_requirements",
    "detailed_reasoning", "screened_date",
    "batch_id", "batch_date", "sent_by", "sent_date", "send_status",
    "times_contacted", "last_contacted_date", "duplicate_flag",
    "updated_at", "updated_by",
    "reply_status", "interview_scheduled", "interview_date", "final_outcome", "notes"
]

# ─────────────────────────────────────────
#  SCREENING STATUS LOGIC
# ─────────────────────────────────────────

def get_screening_status(shortlist, score):
    try:
        score = float(score)
    except Exception:
        score = 0
    if shortlist:
        return "Accepted"
    elif score >= 5:
        return "Potential"
    else:
        return "Rejected"

# ─────────────────────────────────────────
#  GOOGLE SHEETS HELPERS
# ─────────────────────────────────────────

@st.cache_resource
def get_gsheet_client():
    try:
        creds_dict = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception:
        return None

def get_gsheet():
    try:
        gc = get_gsheet_client()
        if gc is None:
            return None
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.sheet1
        existing = ws.row_values(1)
        if not existing or existing[0] != "record_id":
            ws.insert_row(TRACKER_COLUMNS, 1)
        return ws
    except Exception:
        return None

def write_screening_to_sheet(df_results, job_position="", company=""):
    ws = get_gsheet()
    if ws is None:
        return 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_add = []
    try:
        for _, row in df_results.iterrows():
            shortlist = str(row.get("shortlist", "False")).strip().lower() == "true"
            score = row.get("total_score", 0)
            screening_status = get_screening_status(shortlist, score)
            record_id = f"SCR-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
            row_data = [
                record_id,
                str(row.get("candidate_name", "")),
                "'" + str(row.get("phone_number", "")),
                job_position,
                company,
                screening_status,
                str(score),
                str(row.get("confidence_level", "")),
                str(row.get("missing_requirements", "")),
                str(row.get("detailed_reasoning", "")),
                now_str,
                "", "", "", "", "",        # batch_id, batch_date, sent_by, sent_date, send_status
                "0", "", "No",             # times_contacted, last_contacted_date, duplicate_flag
                now_str, "",               # updated_at, updated_by
                "Pending", "No", "", "TBD", ""  # reply_status, interview_scheduled, interview_date, final_outcome, notes
            ]
            rows_to_add.append(row_data)
        if rows_to_add:
            ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        return len(rows_to_add)
    except Exception as e:
        st.warning(f"⚠️ Could not save to sheet: {e}")
        return 0

# ─────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────

st.set_page_config(page_title="EPSTEIN FILES", layout="wide", page_icon="🗂️")

# ─────────────────────────────────────────
#  CUSTOM CSS
# ─────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --bg: #0b0f1a;
    --panel: rgba(17, 24, 39, 0.85);
    --panel2: rgba(26, 34, 53, 0.9);
    --border: #1e2d45;
    --accent: #ff6b4a;
    --accent2: #4af0c4;
    --text: #e2e8f0;
    --muted: #4a5568;
    --muted2: #718096;
}

* { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Outfit', sans-serif !important;
}

.bg-slideshow { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 0; overflow: hidden; }
.bg-slide { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background-size: cover; background-position: center; opacity: 0; transition: opacity 2s ease-in-out; filter: brightness(0.15) saturate(0.3) sepia(0.5); }
.bg-slide.active { opacity: 1; }

[data-testid="stAppViewContainer"] { background: transparent !important; position: relative; z-index: 1; }
[data-testid="stAppViewContainer"]::before {
    content: ''; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: radial-gradient(ellipse at 0% 0%, rgba(255,107,74,0.06) 0%, transparent 50%), radial-gradient(ellipse at 100% 100%, rgba(74,240,196,0.04) 0%, transparent 50%), linear-gradient(180deg, rgba(11,15,26,0.7) 0%, rgba(11,15,26,0.5) 100%);
    z-index: 0; pointer-events: none;
}
[data-testid="stAppViewContainer"]::after {
    content: ''; position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
    background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.03) 2px, rgba(0,0,0,0.03) 4px);
    pointer-events: none; z-index: 0;
}

[data-testid="stSidebar"] { display: none; }
[data-testid="stHeader"] { background: transparent !important; border-bottom: 1px solid rgba(30,45,69,0.5) !important; }
footer { display: none !important; }
#MainMenu { display: none !important; }

.main-title { font-family: 'Bebas Neue', sans-serif !important; font-size: 80px !important; letter-spacing: 8px !important; line-height: 1 !important; color: var(--text) !important; margin-bottom: 4px !important; text-shadow: 0 0 40px rgba(255,107,74,0.3) !important; }
.main-title span { color: var(--accent); text-shadow: 0 0 30px rgba(255,107,74,0.6) !important; }
.main-sub { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted2); letter-spacing: 5px; text-transform: uppercase; margin-bottom: 48px; }
.classified-stamp { display: inline-block; border: 3px solid rgba(255,107,74,0.4); color: rgba(255,107,74,0.5); font-family: 'Bebas Neue', sans-serif; font-size: 14px; letter-spacing: 6px; padding: 4px 16px; margin-bottom: 16px; transform: rotate(-2deg); }

.section-label { font-family: 'JetBrains Mono', monospace; font-size: 10px; font-weight: 500; letter-spacing: 4px; text-transform: uppercase; color: var(--accent); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.section-label::after { content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, var(--border), transparent); }

input[type="range"] { -webkit-appearance: none !important; width: 100% !important; height: 6px !important; background: linear-gradient(90deg, var(--accent), var(--accent2)) !important; border-radius: 99px !important; outline: none !important; cursor: pointer !important; }
input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none !important; width: 22px !important; height: 22px !important; border-radius: 50% !important; background: white !important; border: 3px solid var(--accent) !important; cursor: pointer !important; box-shadow: 0 0 12px rgba(255,107,74,0.5) !important; }
input[type="range"]::-moz-range-thumb { width: 22px !important; height: 22px !important; border-radius: 50% !important; background: white !important; border: 3px solid var(--accent) !important; cursor: pointer !important; }

div[data-testid="stSlider"] { padding: 8px 0 !important; }
div[data-testid="stSlider"] > div { background: transparent !important; }
div[data-testid="stSlider"] > div > div { background: transparent !important; }
div[data-testid="stSlider"] > div > div > div { background: var(--accent) !important; box-shadow: 0 0 12px rgba(255,107,74,0.5) !important; }

div[data-testid="stTextArea"] textarea { background: var(--panel2) !important; border: 1px solid var(--border) !important; border-radius: 12px !important; color: var(--text) !important; font-family: 'Outfit', sans-serif !important; font-size: 14px !important; resize: vertical !important; }
div[data-testid="stTextArea"] textarea:focus { border-color: var(--accent) !important; box-shadow: 0 0 0 3px rgba(255,107,74,0.1) !important; }

div[data-testid="stFileUploader"] { background: var(--panel2) !important; border: 1px dashed var(--border) !important; border-radius: 12px !important; padding: 8px !important; }
div[data-testid="stFileUploader"]:hover { border-color: var(--accent) !important; }

div[data-testid="stButton"] > button { background: var(--accent) !important; color: white !important; border: none !important; border-radius: 12px !important; font-family: 'Bebas Neue', sans-serif !important; font-size: 18px !important; padding: 14px 32px !important; letter-spacing: 3px !important; width: 100% !important; box-shadow: 0 4px 20px rgba(255,107,74,0.3) !important; transition: all 0.2s !important; }
div[data-testid="stButton"] > button:hover { transform: translateY(-2px) !important; box-shadow: 0 8px 32px rgba(255,107,74,0.5) !important; }

div[data-testid="stDownloadButton"] > button { background: rgba(26,34,53,0.9) !important; color: var(--accent2) !important; border: 1px solid var(--accent2) !important; border-radius: 12px !important; font-family: 'Bebas Neue', sans-serif !important; font-size: 16px !important; letter-spacing: 2px !important; padding: 12px 28px !important; width: 100% !important; transition: all 0.2s !important; }
div[data-testid="stDownloadButton"] > button:hover { background: rgba(74,240,196,0.1) !important; transform: translateY(-2px) !important; }

div[data-testid="stDataFrame"] { border: 1px solid var(--border) !important; border-radius: 12px !important; overflow: hidden !important; }
div[data-testid="stDataFrame"] th { background: rgba(26,34,53,0.95) !important; color: var(--accent) !important; font-family: 'JetBrains Mono', monospace !important; font-size: 11px !important; letter-spacing: 2px !important; text-transform: uppercase !important; border-bottom: 1px solid var(--border) !important; }
div[data-testid="stDataFrame"] td { color: var(--text) !important; font-size: 13px !important; border-bottom: 1px solid var(--border) !important; background: rgba(17,24,39,0.9) !important; }

div[data-testid="stInfo"], div[data-testid="stSuccess"], div[data-testid="stWarning"] { background: var(--panel2) !important; border-radius: 12px !important; border-left: 3px solid var(--accent) !important; }
div[data-testid="stSuccess"] { border-left-color: var(--accent2) !important; }
div[data-testid="stWarning"] { border-left-color: #ffc832 !important; }

div[data-testid="stProgress"] > div > div { background: linear-gradient(90deg, var(--accent), var(--accent2)) !important; border-radius: 99px !important; }
div[data-testid="stProgress"] > div { background: var(--border) !important; border-radius: 99px !important; }

.mode-pill { display: inline-flex; align-items: center; gap: 8px; padding: 8px 20px; border-radius: 99px; font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; margin-top: 12px; }
.mode-flex   { background: rgba(74,240,196,0.1); border: 1px solid rgba(74,240,196,0.3); color: #4af0c4; }
.mode-bal    { background: rgba(255,200,50,0.1);  border: 1px solid rgba(255,200,50,0.3);  color: #ffc832; }
.mode-strict { background: rgba(255,107,74,0.1);  border: 1px solid rgba(255,107,74,0.3);  color: #ff6b4a; }

p, li { color: var(--text) !important; font-family: 'Outfit', sans-serif !important; }
label { color: var(--muted2) !important; font-family: 'JetBrains Mono', monospace !important; font-size: 10px !important; letter-spacing: 3px !important; text-transform: uppercase !important; }
div[data-testid="stTextInput"] input { background: var(--panel2) !important; border: 1px solid var(--border) !important; border-radius: 8px !important; color: var(--text) !important; }

::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--accent); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent2); }

@keyframes fadeInUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
.animate-in { animation: fadeInUp 0.6s ease forwards; }
</style>

<div class="bg-slideshow">
    <div class="bg-slide active" style="background-image: url('https://images.unsplash.com/photo-1568605114967-8130f3a36994?w=1920&q=80')"></div>
    <div class="bg-slide" style="background-image: url('https://images.unsplash.com/photo-1521587760476-6c12a4b040da?w=1920&q=80')"></div>
    <div class="bg-slide" style="background-image: url('https://images.unsplash.com/photo-1507842217343-583bb7270b66?w=1920&q=80')"></div>
    <div class="bg-slide" style="background-image: url('https://images.unsplash.com/photo-1554224155-6726b3ff858f?w=1920&q=80')"></div>
    <div class="bg-slide" style="background-image: url('https://images.unsplash.com/photo-1483058712412-4245e9b90334?w=1920&q=80')"></div>
</div>
<script>
    let current = 0;
    const slides = document.querySelectorAll('.bg-slide');
    function nextSlide() { slides[current].classList.remove('active'); current = (current + 1) % slides.length; slides[current].classList.add('active'); }
    setInterval(nextSlide, 5000);
</script>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────

st.markdown("""
<div class="animate-in" style="padding: 40px 0 20px 0;">
    <div class="classified-stamp">◈ CLASSIFIED · LEVEL 5 CLEARANCE REQUIRED ◈</div>
    <div class="main-title">EPSTEIN <span>FILES</span></div>
    <div class="main-sub">AI-Powered Recruitment Intelligence System · Eyes Only</div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
#  HELPER FUNCTIONS
# ─────────────────────────────────────────

def get_file_hash(pdf_file):
    contents = pdf_file.read()
    pdf_file.seek(0)
    return hashlib.md5(contents).hexdigest()

def extract_text_from_pdf(pdf_file):
    try:
        pdf_bytes = pdf_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text")
        if len(text.strip()) < 50:
            text = ""
            for page in doc:
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))
                text += pytesseract.image_to_string(img)
        doc.close()
        return text.strip()
    except Exception as e:
        st.warning(f"⚠️ Could not read `{pdf_file.name}`: {str(e)}")
        return ""

def get_strictness_instructions(level):
    if level == 1:
        return """
SCORING MODE: FLEXIBLE
- Weight potential, attitude, and transferable skills heavily
- Shortlist anyone scoring 5 and above
- Be generous with borderline candidates
"""
    elif level == 2:
        return """
SCORING MODE: BALANCED
- Direct experience preferred but transferable skills considered
- Shortlist anyone scoring 6 and above
- Be fair but realistic with borderline candidates
"""
    else:
        return """
SCORING MODE: STRICT
- Must-have requirements are NON-NEGOTIABLE
- Only shortlist candidates scoring 7 and above
- Do not give benefit of the doubt
- A candidate with 2 years experience for a 5 year role scores 3 or below
"""

def screen_resume(resume_text, groq_api_key, strictness, job_description):
    client = Groq(api_key=groq_api_key)
    strictness_instructions = get_strictness_instructions(strictness)
    prompt = f"""
You are an expert senior recruiter. Score this resume against the job description.
The resume may be written in English or Bahasa Malaysia — read it carefully either way.

{strictness_instructions}

Job Description:
{job_description}

Evaluation Criteria:
{CRITERIA}

Resume:
{resume_text}

Respond ONLY with valid JSON (no extra text, no markdown, no code fences), with these exact keys:
{{
  "candidate_name": "extract the real full name from the resume",
  "phone_number": "extract the real phone number from the resume",
  "total_score": a number from 0 to 10,
  "shortlist": true or false,
  "confidence_level": "High, Medium, or Low",
  "missing_requirements": "list the key requirements this candidate is missing",
  "detailed_reasoning": "Explain why the candidate got this score."
}}
"""
    available_models = [m for m in MODELS_TO_TRY if m not in exhausted_models]
    if not available_models:
        return {"candidate_name": "Unknown", "phone_number": "", "total_score": 0,
                "shortlist": False, "confidence_level": "Low",
                "missing_requirements": "N/A", "model_used": "none",
                "detailed_reasoning": "All models hit rate limit. Please try again tomorrow."}

    for model in available_models:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            result = json.loads(raw)
            result["model_used"] = model
            return result
        except Exception as e:
            error_msg = str(e)
            if "rate_limit_exceeded" in error_msg or "429" in error_msg:
                exhausted_models.add(model)
                st.warning(f"⚠️ `{model}` rate limit hit, switching...")
                continue
            else:
                return {"candidate_name": "Unknown", "phone_number": "", "total_score": 0,
                        "shortlist": False, "confidence_level": "Low",
                        "missing_requirements": "N/A", "model_used": model,
                        "detailed_reasoning": f"Error: {error_msg}"}

    return {"candidate_name": "Unknown", "phone_number": "", "total_score": 0,
            "shortlist": False, "confidence_level": "Low",
            "missing_requirements": "N/A", "model_used": "none",
            "detailed_reasoning": "All models hit rate limit."}

# ─────────────────────────────────────────
#  MAIN UI
# ─────────────────────────────────────────

st.markdown('<div class="section-label">00 — Access Credentials</div>', unsafe_allow_html=True)
groq_api_key = st.text_input("Groq API Key", type="password",
    placeholder="Enter your Groq API key (gsk_...)", label_visibility="collapsed")
if groq_api_key:
    st.markdown('<p style="font-family: JetBrains Mono, monospace; font-size: 12px; color: #4af0c4; margin-top: 4px; margin-bottom: 16px;">🔑 Credentials accepted</p>', unsafe_allow_html=True)
else:
    st.markdown('<p style="font-family: JetBrains Mono, monospace; font-size: 12px; color: #ff6b4a; margin-top: 4px; margin-bottom: 16px;">⚠ No credentials — <a href="https://console.groq.com/keys" target="_blank" style="color: #ff6b4a;">get a free Groq API key</a></p>', unsafe_allow_html=True)

col1, col2 = st.columns([3, 2], gap="large")

with col1:
    st.markdown('<div class="section-label">01 — Dossiers</div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader("Upload PDF resumes", type=["pdf"],
        accept_multiple_files=True, label_visibility="collapsed")
    if uploaded_files:
        st.markdown(f'<p style="font-family: JetBrains Mono, monospace; font-size: 12px; color: #4af0c4; margin-top: 8px;">⬆ {len(uploaded_files)} dossier(s) loaded</p>', unsafe_allow_html=True)

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown('<div class="section-label" style="margin-top: 16px;">Job Position</div>', unsafe_allow_html=True)
        screening_job = st.text_input("Job Position", placeholder="e.g. Admin Accountant",
            label_visibility="collapsed", key="screening_job")
    with sc2:
        st.markdown('<div class="section-label" style="margin-top: 16px;">Company</div>', unsafe_allow_html=True)
        screening_company = st.text_input("Company", placeholder="e.g. Acme Sdn Bhd",
            label_visibility="collapsed", key="screening_company")

    st.markdown('<div class="section-label" style="margin-top: 28px;">02 — Mission Brief</div>', unsafe_allow_html=True)
    job_description = st.text_area("Job description", height=220,
        placeholder="Paste your dirty secret here...", label_visibility="collapsed")

with col2:
    st.markdown('<div class="section-label">03 — Clearance Level</div>', unsafe_allow_html=True)
    strictness = st.slider("Strictness", min_value=1, max_value=3, value=2, step=1, label_visibility="collapsed")

    if strictness == 1:
        st.markdown('<div class="mode-pill mode-flex">🟢 FLEXIBLE — Potential weighted heavily</div>', unsafe_allow_html=True)
    elif strictness == 2:
        st.markdown('<div class="mode-pill mode-bal">🟡 BALANCED — Direct experience preferred</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="mode-pill mode-strict">🔴 STRICT — Must-haves enforced</div>', unsafe_allow_html=True)

    st.markdown('<div style="margin-top: 32px;"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-label">04 — Initiate</div>', unsafe_allow_html=True)
    start_button = st.button("⚡ OPEN THE FILES")

    if uploaded_files and job_description:
        st.markdown(f"""
        <div style="margin-top: 20px; padding: 16px; background: rgba(26,34,53,0.9); border-radius: 12px; border: 1px solid #1e2d45;">
            <div style="font-family: JetBrains Mono, monospace; font-size: 10px; color: #4a5568; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 12px;">Dossiers Queued</div>
            <div style="font-family: Bebas Neue, sans-serif; font-size: 32px; letter-spacing: 3px; color: #e2e8f0;">{len(uploaded_files)} <span style="font-size: 16px; color: #718096; font-family: Outfit, sans-serif;">subjects</span></div>
        </div>
        """, unsafe_allow_html=True)

# ─────────────────────────────────────────
#  SCREENING RUN
# ─────────────────────────────────────────

if start_button:
    if not groq_api_key:
        st.error("🔑 Please enter your Groq API key above to proceed.")
    elif not uploaded_files:
        st.warning("⚠️ Please upload at least one PDF resume.")
    elif not job_description.strip():
        st.warning("⚠️ Please paste the job description.")
    elif not screening_job.strip():
        st.warning("⚠️ Please enter the Job Position.")
    elif not screening_company.strip():
        st.warning("⚠️ Please enter the Company name.")
    else:
        seen_hashes = set()
        seen_names  = set()
        unique_files = []
        skipped = 0

        for file in uploaded_files:
            file_hash = get_file_hash(file)
            if file_hash in seen_hashes or file.name in seen_names:
                skipped += 1
            else:
                seen_hashes.add(file_hash)
                seen_names.add(file.name)
                unique_files.append(file)

        if skipped > 0:
            st.warning(f"⚠️ Removed {skipped} duplicate file(s).")

        strictness_labels = {1: "🟢 Flexible", 2: "🟡 Balanced", 3: "🔴 Strict"}
        st.info(f"enjoyingggg ahhhhh on {len(unique_files)} subjects in **{strictness_labels[strictness]}** mode...")

        results    = []
        progress   = st.progress(0)
        status_txt = st.empty()
        total_start = time.time()

        for i, file in enumerate(unique_files):
            resume_start = time.time()
            status_txt.markdown(f"""
            <div style="padding: 10px 16px; background: rgba(26,34,53,0.9); border: 1px solid #1e2d45; border-radius: 10px;">
                <span style="font-family: JetBrains Mono, monospace; font-size: 11px; color: #ff6b4a;">⟳ </span>
                <span style="font-family: JetBrains Mono, monospace; font-size: 11px; color: #718096;">Investigating {i+1}/{len(unique_files)} — {file.name}</span>
            </div>""", unsafe_allow_html=True)

            text = extract_text_from_pdf(file)
            if len(text) < 50:
                results.append({"file_name": file.name, "candidate_name": "Unknown",
                    "phone_number": "", "total_score": 0, "shortlist": False,
                    "confidence_level": "Low", "missing_requirements": "N/A",
                    "model_used": "none", "detailed_reasoning": "Empty or unreadable PDF"})
            else:
                result = screen_resume(text, groq_api_key, strictness, job_description)
                result["file_name"] = file.name
                results.append(result)

            resume_elapsed = time.time() - resume_start
            total_elapsed  = time.time() - total_start
            progress.progress((i + 1) / len(unique_files))
            status_txt.markdown(f"""
            <div style="padding: 10px 16px; background: rgba(26,34,53,0.9); border: 1px solid rgba(74,240,196,0.2); border-radius: 10px;">
                <span style="font-family: JetBrains Mono, monospace; font-size: 11px; color: #4af0c4;">✓ </span>
                <span style="font-family: JetBrains Mono, monospace; font-size: 11px; color: #718096;">{i+1}/{len(unique_files)} — {file.name} · {resume_elapsed:.1f}s · total {total_elapsed:.1f}s</span>
            </div>""", unsafe_allow_html=True)

        total_time = time.time() - total_start
        minutes    = int(total_time // 60)
        seconds    = int(total_time % 60)

        df = pd.DataFrame(results)
        col_order = ["file_name", "candidate_name", "phone_number", "total_score", "shortlist",
                     "confidence_level", "missing_requirements", "model_used", "detailed_reasoning"]
        df = df[[c for c in col_order if c in df.columns]]
        df = df.sort_values(by="total_score", ascending=False).reset_index(drop=True)

        accepted  = df[df['shortlist'] == True].shape[0] if 'shortlist' in df.columns else 0
        potential = df[(df['shortlist'] == False) & (df['total_score'] >= 5)].shape[0] if 'total_score' in df.columns else 0
        rejected  = df[(df['shortlist'] == False) & (df['total_score'] < 5)].shape[0] if 'total_score' in df.columns else 0

        st.markdown(f"""
        <div style="margin: 32px 0 16px 0;">
            <div class="section-label">Intelligence Report</div>
            <div style="font-family: Bebas Neue, sans-serif; font-size: 56px; letter-spacing: 4px; line-height: 1; color: #e2e8f0; text-shadow: 0 0 30px rgba(255,107,74,0.3);">
                {len(unique_files)} <span style="color: #4af0c4;">SUBJECTS</span> · {minutes}M {seconds}S
            </div>
        </div>""", unsafe_allow_html=True)

        st.markdown(f"""
        <div style="display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;">
            <div style="padding: 10px 20px; background: rgba(74,240,196,0.08); border: 1px solid rgba(74,240,196,0.25); border-radius: 99px; font-family: JetBrains Mono, monospace; font-size: 12px; color: #4af0c4;">✓ {accepted} Accepted</div>
            <div style="padding: 10px 20px; background: rgba(255,200,50,0.08); border: 1px solid rgba(255,200,50,0.25); border-radius: 99px; font-family: JetBrains Mono, monospace; font-size: 12px; color: #ffc832;">◈ {potential} Potential</div>
            <div style="padding: 10px 20px; background: rgba(255,107,74,0.08); border: 1px solid rgba(255,107,74,0.25); border-radius: 99px; font-family: JetBrains Mono, monospace; font-size: 12px; color: #ff6b4a;">✗ {rejected} Rejected</div>
            <div style="padding: 10px 20px; background: rgba(26,34,53,0.9); border: 1px solid #1e2d45; border-radius: 99px; font-family: JetBrains Mono, monospace; font-size: 12px; color: #718096;">{strictness_labels[strictness]} Mode</div>
        </div>""", unsafe_allow_html=True)

        st.dataframe(df, use_container_width=True, height=420)

        output_excel = "shortlist.xlsx"
        df.to_excel(output_excel, index=False)
        with open(output_excel, "rb") as f:
            st.download_button(
                label="⬇ Download Intelligence Report",
                data=f,
                file_name="epstein_files_report.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        with st.spinner("💾 Saving to Recruitment Tracker..."):
            written = write_screening_to_sheet(
                df,
                job_position=screening_job.strip(),
                company=screening_company.strip()
            )
        if written > 0:
            st.markdown(f'<p style="font-family: JetBrains Mono, monospace; font-size: 12px; color: #4af0c4; margin-top: 8px;">📊 {written} candidates saved to Recruitment Tracker</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p style="font-family: JetBrains Mono, monospace; font-size: 12px; color: #ff6b4a; margin-top: 8px;">⚠ Could not save to Tracker — check Google Sheets connection</p>', unsafe_allow_html=True)
