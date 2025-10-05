# main.py
# 🧠 Cold Case Investigative Console
# (DPULSE + Profiler Dashboard)
# Tabs: Scanner, Reports, Cold Case Search, Profiler
# - Streamlit Cloud entry point (rename-safe)
# - Works locally or on VPS; auto-detects Poetry

from __future__ import annotations

import os
import json
import time
import glob
import shlex
import zipfile
import traceback
import subprocess
from pathlib import Path
from typing import Optional, List

import streamlit as st
import pandas as pd

# Optional fuzzy search (install: pip install rapidfuzz)
try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

# -----------------------------------------------------------------------------
# GLOBAL CONFIG
# -----------------------------------------------------------------------------
APP_TITLE = "🧠 Cold Case Investigative Console"

# Directories
ROOT_DIR = Path(__file__).resolve().parent
REPORTS_DIR = ROOT_DIR / "reports"          # where dpulse writes artifacts
DATA_DIR = ROOT_DIR / "data"                # where datasets go
DEFAULT_DATASET = DATA_DIR / "namus_cases.csv"

# Profiler API endpoint (set via Streamlit Secrets or ENV var)
PROFILER_API_URL = os.getenv("PROFILER_API_URL", "").strip()

# -----------------------------------------------------------------------------
# PAGE CONFIG / LOOK
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Cold Case Console", page_icon="🧠", layout="wide")

# Inline CSS (Matrix inspired)
st.markdown("""
<style>
/* App background and global text */
.stApp {
    background-color: #0f1620;
    color: #E2E8F0;
}

/* Tabs and header feel */
.stTabs [data-baseweb="tab"] {
    font-weight: 600;
    color: #A7F3D0;
}
.stTabs [data-baseweb="tab"][aria-selected="true"] {
    color: #00c896;
    border-bottom: 3px solid #00c896;
}

/* Softened highlight elements */
.pill {
    padding: 4px 10px;
    border-radius: 999px;
    background: #1b2430;
    color: #A7F3D0;
    margin-right: 8px;
    display: inline-block;
}

/* Subtle monospace style for technical content */
.mono {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
}

/* Notes and captions */
.small-note {
    opacity: 0.75;
    font-size: 0.9rem;
}

/* Buttons: glow slightly when hovered */
.stButton button {
    background-color: #00c896;
    color: #0f1620;
    font-weight: bold;
    border-radius: 6px;
    border: none;
    transition: all 0.2s ease;
}
.stButton button:hover {
    background-color: #00a67d;
    transform: scale(1.02);
}
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# UTILITIES
# -----------------------------------------------------------------------------
def _which(cmd: str) -> Optional[str]:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        c = Path(p) / cmd
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return None

def _has_poetry() -> bool:
    return _which("poetry") is not None

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
ensure_dirs()

def run_streamed(cmd: List[str]):
    """Run a subprocess and stream its output live into Streamlit."""
    st.write(f"**Command:** `{shlex.join(cmd)}`")
    out_box = st.empty()
    err_box = st.empty()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, universal_newlines=True
    )
    so, se = [], []
    while True:
        if proc.stdout:
            line = proc.stdout.readline()
            if line:
                so.append(line)
                out_box.code("".join(so)[-4000:], language="bash")
        if proc.stderr:
            line = proc.stderr.readline()
            if line:
                se.append(line)
                err_box.code("".join(se)[-4000:], language="bash")
        if proc.poll() is not None:
            break
        time.sleep(0.02)
    return proc.returncode or 0, "".join(so), "".join(se)

@st.cache_data(show_spinner=False)
def list_reports() -> List[Path]:
    if not REPORTS_DIR.exists():
        return []
    files = [Path(p) for p in glob.glob(str(REPORTS_DIR / "*"))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files

@st.cache_data(show_spinner=False)
def load_table(path: Path) -> pd.DataFrame:
    """Load CSV/JSON into a DataFrame (best-effort)."""
    if not path.exists():
        return pd.DataFrame()
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if ext in {".json", ".ndjson"}:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            rows = []
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
            data = rows
        if isinstance(data, dict):
            data = [data]
        return pd.DataFrame(data)
    return pd.DataFrame()

def fuzzy_contains(needle: str, hay: str, thresh: int = 75) -> bool:
    if not needle:
        return True
    if hay is None:
        return False
    if fuzz is None:
        return needle.lower() in str(hay).lower()
    return fuzz.partial_ratio(needle.lower(), str(hay).lower()) >= thresh

# -----------------------------------------------------------------------------
# TABS
# -----------------------------------------------------------------------------
tab_scan, tab_reports, tab_search, tab_profiler = st.tabs(
    ["📡 DPULSE Scanner", "📁 Reports Viewer", "🔍 Cold Case Search", "🧩 Profiler"]
)

# === SCANNER ===
with tab_scan:
    st.subheader("📡 DPULSE Scanner")
    st.markdown("Run DPULSE from the browser. Tries **Poetry** first, falls back to system Python.")

    left, right = st.columns([2, 1])
    with left:
        target = st.text_input("Target Domain", placeholder="example.com")
        mode = st.selectbox(
            "Scan Mode (UI only — dpulse.py may ignore until wired)",
            ["Basic Scan", "PageSearch", "Dorking", "API Scan"],
        )
        extra_args = st.text_input("Extra Args (optional)", placeholder="--pagesearch yes --dorking web")
    with right:
        use_poetry = st.toggle("Use Poetry", value=_has_poetry(), help="If off, uses `python dpulse.py`")
        run_btn = st.button("Run Scan", type="primary")

    import dpulse

if run_btn:
    if not target.strip():
        st.error("Please enter a target domain.")
    else:
        st.info(f"Running DPULSE scan for `{target}` …")

        log_box = st.empty()

        def _log(msg: str):
            """Stream live logs into the UI."""
            prev = log_box.text_area("Live Log", msg, height=200)
            log_box.text_area("Live Log", prev + "\n" + msg, height=300)

        with st.spinner("Running scan in headless mode..."):
            result = dpulse.run_headless_scan(
                short_domain=target.strip(),
                report_filetype="html",
                pagesearch_flag="n",
                dorking_flag="n",
                snapshotting_flag="n",
                used_api_flag=["Empty"],
                log_callback=_log,
            )

        if result.get("success"):
            st.success("✅ DPULSE scan finished successfully!")
            if result.get("report_files"):
                st.caption("Reports generated:")
                for f in result["report_files"]:
                    st.code(f, language="bash")
            else:
                st.info("No reports found in ./reports/")
        else:
            st.error("❌ Scan failed.")
            st.code(result.get("trace", result.get("message", "Unknown error")), language="bash")

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
                ext = selection.suffix.lower()
                text = selection.read_text(encoding="utf-8", errors="ignore")
                if ext == ".html":
                    st.components.v1.html(text, height=900, scrolling=True)
                elif ext in {".json", ".ndjson"}:
                    js = json.loads(text)
                    st.json(js)
                elif ext == ".csv":
                    st.dataframe(pd.read_csv(selection, dtype=str), use_container_width=True)
                else:
                    st.text_area("Raw Content", text, height=400)
            except Exception as e:
                st.error(f"Could not open report: {e}")
                st.code(traceback.format_exc())

# === SEARCH ===
with tab_search:
    st.subheader("🔍 Cold Case Search")
    st.caption("Load NamUs-style datasets or internal exports.")
    path = st.text_input("Dataset Path", value=str(DEFAULT_DATASET))
    if st.button("Load Dataset"):
        df = load_table(Path(path))
        if df.empty:
            st.warning("No data loaded.")
        else:
            st.dataframe(df.head(100), use_container_width=True)

# === PROFILER ===
with tab_profiler:
    st.subheader("🧩 Availability Profiler")
    if not PROFILER_API_URL:
        st.info("Set `PROFILER_API_URL` to enable this feature.")
    else:
        st.caption(f"Connected to: `{PROFILER_API_URL}`")
        q_lat = st.number_input("Latitude", value=37.7749, format="%.6f")
        q_lon = st.number_input("Longitude", value=-122.4194, format="%.6f")
        radius = st.slider("Radius (m)", 100, 20000, 2000, 100)
        if st.button("Query Profiler"):
            import requests
            payload = {"latitude": q_lat, "longitude": q_lon, "radius_meters": radius}
            try:
                r = requests.post(f"{PROFILER_API_URL.rstrip('/')}/availability/query", json=payload, timeout=60)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, dict) and "candidates" in data:
                    st.dataframe(pd.DataFrame(data["candidates"]), use_container_width=True)
                else:
                    st.json(data)
            except Exception as e:
                st.error(f"Profiler request failed: {e}")
                st.code(traceback.format_exc())

# -----------------------------------------------------------------------------
# MAIN ENTRY
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Streamlit Cloud auto-runs `main.py`, so no manual entry needed.
    # This guard just prevents import-time side effects.
    pass
