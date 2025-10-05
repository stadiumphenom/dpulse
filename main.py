# main.py
# 🧠 Cold Case Investigative Console (Refactored v2)
# Streamlit-based dashboard for DPULSE + Profiler + Case Search
# Compatible with Streamlit 1.38+, Python ≥3.10

from __future__ import annotations
import sys
import os
import json
import time
import glob
import shlex
import traceback
import subprocess
from pathlib import Path
from typing import Optional, List

import streamlit as st
import pandas as pd

# -----------------------------------------------------------------------------
# SAFE OPTIONAL IMPORTS
# -----------------------------------------------------------------------------
try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

try:
    import dpulse
except ImportError:
    dpulse = None

try:
    import requests
except ImportError:
    requests = None

# -----------------------------------------------------------------------------
# GLOBAL CONFIG
# -----------------------------------------------------------------------------
APP_TITLE = "🧠 Cold Case Investigative Console"
ROOT_DIR = Path(__file__).resolve().parent
REPORTS_DIR = ROOT_DIR / "reports"
DATA_DIR = ROOT_DIR / "data"
DEFAULT_DATASET = DATA_DIR / "namus_cases.csv"
PROFILER_API_URL = os.getenv("PROFILER_API_URL", "").strip()

# -----------------------------------------------------------------------------
# PAGE CONFIG / LOOK
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Cold Case Console", page_icon="🧠", layout="wide")

st.markdown("""
<style>
.stApp {
    background-color: #0f1620;
    color: #E2E8F0;
}
.stTabs [data-baseweb="tab"] {
    font-weight: 600;
    color: #A7F3D0;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #00c896;
    border-bottom: 3px solid #00c896;
}
.pill { padding: 4px 10px; border-radius: 999px; background: #1b2430; color: #A7F3D0; margin-right: 8px; display: inline-block; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }
.small-note { opacity: 0.75; font-size: 0.9rem; }
.stButton button {
    background-color: #00c896; color: #0f1620; font-weight: bold; border-radius: 6px; border: none; transition: all 0.2s ease;
}
.stButton button:hover { background-color: #00a67d; transform: scale(1.02); }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
def _which(cmd: str) -> Optional[str]:
    exts = (".exe", ".bat") if os.name == "nt" else ("",)
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for ext in exts:
            c = Path(p) / f"{cmd}{ext}"
            if c.exists() and os.access(c, os.X_OK):
                return str(c)
    return None

def _has_poetry() -> bool:
    return _which("poetry") is not None

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
ensure_dirs()

def run_streamed(cmd: List[str]) -> tuple[int, str]:
    """Run subprocess and stream output cleanly into Streamlit."""
    st.write(f"**Command:** `{shlex.join(cmd)}`")
    out_box = st.empty()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as proc:
        buffer = ""
        for line in proc.stdout:
            buffer += line
            out_box.code(buffer[-4000:], language="bash")
            time.sleep(0.03)
    return proc.returncode or 0, buffer

@st.cache_data(show_spinner=False, ttl=30)
def list_reports() -> List[Path]:
    files = [Path(p) for p in glob.glob(str(REPORTS_DIR / "*"))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files

@st.cache_data(show_spinner=False, ttl=30)
def load_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    ext = path.suffix.lower()
    try:
        if ext == ".csv":
            return pd.read_csv(path, dtype=str, low_memory=False)
        if ext in {".json", ".ndjson"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            try:
                data = json.loads(text)
            except Exception:
                data = [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]
            if isinstance(data, dict):
                data = [data]
            return pd.DataFrame(data)
    except Exception:
        st.error(f"Error loading file: {path.name}")
    return pd.DataFrame()

# -----------------------------------------------------------------------------
# TABS
# -----------------------------------------------------------------------------
tab_scan, tab_reports, tab_search, tab_profiler = st.tabs(
    ["📡 DPULSE Scanner", "📁 Reports Viewer", "🔍 Cold Case Search", "🧩 Profiler"]
)

# === SCANNER ===
with tab_scan:
    st.subheader("📡 DPULSE Scanner")
    if dpulse is None:
        st.error("DPULSE module not found. Please ensure it is installed in this environment.")
    else:
        left, right = st.columns([2, 1])
        with left:
            target = st.text_input("Target Domain", placeholder="example.com")
            mode = st.selectbox("Scan Mode", ["Basic Scan", "PageSearch", "Dorking", "API Scan"])
            extra_args = st.text_input("Extra Args (optional)", placeholder="--pagesearch yes --dorking web")
        with right:
            use_poetry = st.toggle("Use Poetry", value=_has_poetry())
            run_btn = st.button("Run Scan", type="primary")

        if run_btn:
            if not target.strip():
                st.error("Please enter a target domain.")
            else:
                st.info(f"Running DPULSE scan for `{target}` …")
                with st.spinner("Running scan in headless mode..."):
                    try:
                        result = dpulse.run_headless_scan(
                            short_domain=target.strip(),
                            report_filetype="html",
                            pagesearch_flag="n",
                            dorking_flag="n",
                            snapshotting_flag="n",
                            used_api_flag=["Empty"],
                        )
                        if result.get("success"):
                            st.success("✅ DPULSE scan finished successfully!")
                            for f in result.get("report_files", []):
                                st.code(f, language="bash")
                        else:
                            st.error("❌ Scan failed.")
                            st.code(result.get("trace", "Unknown error"), language="bash")
                    except Exception as e:
                        st.error(f"DPULSE run failed: {e}")
                        with st.expander("Traceback"):
                            st.code(traceback.format_exc())

# === REPORTS ===
with tab_reports:
    st.subheader("📁 Reports Viewer")
    files = list_reports()
    if not files:
        st.info("No reports found yet. Run a scan first.")
    else:
        selection = st.selectbox(
            "Select a report",
            files,
            format_func=lambda p: f"{p.name} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}",
        )
        open_btn = st.button("Open")
        if open_btn:
            try:
                text = selection.read_text(encoding="utf-8", errors="ignore")
                ext = selection.suffix.lower()
                if ext == ".html":
                    st.components.v1.html(text, height=900, scrolling=True)
                elif ext in {".json", ".ndjson"}:
                    st.json(json.loads(text))
                elif ext == ".csv":
                    st.dataframe(pd.read_csv(selection, dtype=str), use_container_width=True)
                else:
                    st.text_area("Raw Content", text, height=400)
            except Exception as e:
                st.error(f"Could not open report: {e}")
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())

# === COLD CASE SEARCH ===
with tab_search:
    st.subheader("🔍 Cold Case Search")
    st.caption("Search publicly available case data or your internal exports.")

    with st.container():
        q1, q2 = st.columns(2)
        q_name = q1.text_input("Victim Name")
        q_city = q2.text_input("City")

        q3, q4 = st.columns(2)
        q_state = q3.text_input("State")
        q_year = q4.text_input("Year")

        q5, q6 = st.columns(2)
        q_status = q5.selectbox("Case Type", ["Any", "Identified", "Unidentified / Unknown"])
        q_race = q6.text_input("Race / Ethnicity (optional)")

        fuzzy_threshold = st.slider("Fuzzy Match Threshold", 50, 100, 75)
        search_btn = st.button("Search", type="primary")

    @st.cache_data(show_spinner=False, ttl=60)
    def _load_dataset(path: str) -> pd.DataFrame:
        return load_table(Path(path))

    df = _load_dataset(str(DEFAULT_DATASET))
    if search_btn:
        if df.empty:
            st.warning("No dataset found. Place a CSV or JSON file in ./data folder.")
        else:
            cols = {c.lower(): c for c in df.columns}
            def pick(*names): return next((cols[n.lower()] for n in names if n.lower() in cols), None)

            col_name, col_city, col_state, col_year, col_status = (
                pick("Victim", "Name", "FullName", "Title"),
                pick("City"), pick("State", "Province"),
                pick("Year", "IncidentYear"), pick("Status", "CaseStatus")
            )

            def fuzzy_contains(needle, hay):
                if not needle: return True
                if fuzz: return fuzz.partial_ratio(needle.lower(), str(hay).lower()) >= fuzzy_threshold
                return needle.lower() in str(hay).lower()

            res = df.copy()
            mask = pd.Series(True, index=res.index)
            if col_name: mask &= res[col_name].fillna("").apply(lambda x: fuzzy_contains(q_name, x))
            if col_city: mask &= res[col_city].fillna("").apply(lambda x: fuzzy_contains(q_city, x))
            if col_state: mask &= res[col_state].fillna("").str.upper().eq(q_state.strip().upper())
            if col_year: mask &= res[col_year].fillna("").str.upper().eq(q_year.strip().upper())
            if col_status and q_status != "Any":
                if "unidentified" in q_status.lower():
                    mask &= res[col_status].fillna("").str.contains("unidentified", case=False, na=False)
                else:
                    mask &= ~res[col_status].fillna("").str.contains("unidentified", case=False, na=False)

            out = res[mask]
            if out.empty:
                st.warning("No matching records found.")
            else:
                st.success(f"Found {len(out)} records (showing first 200).")
                view_cols = [c for c in [col_name, col_city, col_state, col_year, col_status] if c]
                st.dataframe(out.loc[:, view_cols].head(200), use_container_width=True)

# === PROFILER ===
with tab_profiler:
    st.subheader("🧩 Availability Profiler")
    if not PROFILER_API_URL:
        st.info("Set `PROFILER_API_URL` to enable this feature.")
    elif requests is None:
        st.error("`requests` library not found. Install with `pip install requests`.")
    else:
        st.caption(f"Connected to: `{PROFILER_API_URL}`")
        q_lat = st.number_input("Latitude", value=37.7749, format="%.6f")
        q_lon = st.number_input("Longitude", value=-122.4194, format="%.6f")
        radius = st.slider("Radius (m)", 100, 20000, 2000, 100)
        if st.button("Query Profiler"):
            payload = {"latitude": q_lat, "longitude": q_lon, "radius_meters": radius}
            try:
                r = requests.post(f"{PROFILER_API_URL.rstrip('/')}/availability/query", json=payload, timeout=60)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and "candidates" in data:
                    st.dataframe(pd.DataFrame(data["candidates"]), use_container_width=True)
                else:
                    st.json(data)
            except requests.exceptions.Timeout:
                st.error("Profiler request timed out. Try reducing radius or check server.")
            except Exception as e:
                st.error(f"Profiler request failed: {e}")
                with st.expander("Traceback"):
                    st.code(traceback.format_exc())

# -----------------------------------------------------------------------------
# MAIN ENTRY
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    pass
