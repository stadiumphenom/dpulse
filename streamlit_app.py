# streamlit_app.py
# DPULSE + Profiler dashboard (tabs: Scan, Reports, Cold Case Search, Profiler)
# - Drop-in for Codespaces or local. Minimal deps: streamlit, pandas, rapidfuzz.
# - If you use Poetry, the app will try poetry->python, else fall back to system python.

from __future__ import annotations

import os
import sys
import json
import time
import glob
import shlex
import zipfile
import traceback
import subprocess
from pathlib import Path
from typing import Optional, List, Dict

import streamlit as st
import pandas as pd

# Optional fuzzy search (install recommended: `poetry add rapidfuzz` or `pip install rapidfuzz`)
try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None

APP_TITLE = "🧠 Cold Case Investigative Console"
REPORTS_DIR = Path("./reports")               # DPULSE default output folder
DATA_DIR = Path("./data")                     # where you'll drop public datasets (e.g., NamUs CSV)
DEFAULT_DATASET = DATA_DIR / "namus_cases.csv"  # swap with your real dataset file
PROFILER_API_URL = os.getenv("PROFILER_API_URL", "").strip()  # set later when your API is live

# ------------------------------ UI LOOK & FEEL ------------------------------
st.set_page_config(page_title="Cold Case Console", page_icon="🧠", layout="wide")
CUSTOM_CSS = """
<style>
    .stApp { background: #0f1620; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; }
    .small-note { opacity: 0.7; font-size: 0.9rem; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
    .pill { padding: 4px 10px; border-radius: 999px; background: #1f2937; color: #e5e7eb; margin-right: 8px; display:inline-block; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.title(APP_TITLE)
st.caption("Profiling ≠ guessing. We fuse availability + geography + behavior + time to surface credible leads.")

# ------------------------------ UTILITIES ------------------------------
def which(cmd: str) -> Optional[str]:
    """Return absolute path to executable if found on PATH."""
    for p in os.environ.get("PATH", "").split(os.pathsep):
        cand = Path(p) / cmd
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
    return None

def has_poetry() -> bool:
    return which("poetry") is not None

def run_streamed(cmd: List[str]):
    """
    Run a command and stream stdout/stderr into Streamlit in near-real-time.
    Returns (exit_code, captured_stdout, captured_stderr)
    """
    st.write(f"**Command:** `{shlex.join(cmd)}`")
    out_box = st.empty()
    err_box = st.empty()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    stdout_acc, stderr_acc = [], []
    while True:
        # stream stdout
        if proc.stdout:
            line = proc.stdout.readline()
            if line:
                stdout_acc.append(line)
                out_box.code("".join(stdout_acc)[-4000:], language="bash")
        # stream stderr
        if proc.stderr:
            err = proc.stderr.readline()
            if err:
                stderr_acc.append(err)
                err_box.code("".join(stderr_acc)[-4000:], language="bash")
        if proc.poll() is not None:
            # flush remaining
            if proc.stdout:
                rem = proc.stdout.read()
                if rem:
                    stdout_acc.append(rem)
                    out_box.code("".join(stdout_acc)[-4000:], language="bash")
            if proc.stderr:
                rem = proc.stderr.read()
                if rem:
                    stderr_acc.append(rem)
                    err_box.code("".join(stderr_acc)[-4000:], language="bash")
            break
        time.sleep(0.02)
    return proc.returncode or 0, "".join(stdout_acc), "".join(stderr_acc)

@st.cache_data(show_spinner=False)
def list_reports() -> List[Path]:
    if not REPORTS_DIR.exists():
        return []
    files = [Path(p) for p in glob.glob(str(REPORTS_DIR / "*"))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files

@st.cache_data(show_spinner=False)
def load_table(path: Path) -> pd.DataFrame:
    """Load CSV/JSON into DataFrame (best-effort)."""
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str, low_memory=False)
    if path.suffix.lower() in {".json", ".ndjson"}:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            # try line-delimited
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
        # basic fallback
        return needle.lower() in str(hay).lower()
    return fuzz.partial_ratio(needle.lower(), str(hay).lower()) >= thresh

def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

ensure_dirs()

# ------------------------------ TABS ------------------------------
scan_tab, reports_tab, search_tab, profiler_tab = st.tabs(
    ["📡 DPULSE Scanner", "📁 Reports Viewer", "🔍 Cold Case Search", "🧩 Profiler"]
)

# === 1) SCAN TAB ===
with scan_tab:
    st.subheader("📡 DPULSE Scanner")
    st.markdown(
        "Run DPULSE from the browser. We’ll try **Poetry** first, then fall back to system Python."
    )

    left, right = st.columns([2, 1])
    with left:
        target = st.text_input("Target Domain", placeholder="example.com")
        mode = st.selectbox(
            "Scan Mode (UI only — dpulse.py may ignore until wired)",
            ["Basic Scan", "PageSearch", "Dorking", "API Scan"],
            index=0,
        )
        extra_args = st.text_input(
            "Extra Args (optional)",
            placeholder="--pagesearch yes --dorking web",
            help="Passed verbatim to dpulse.py (once hooked up).",
        )
    with right:
        use_poetry = st.toggle(
            "Use Poetry", value=has_poetry(), help="If off, use `python dpulse.py`"
        )
        btn = st.button("Run Scan", type="primary")

    if btn:
        if not target.strip():
            st.error("Please enter a target domain.")
        else:
            with st.spinner(f"Running DPULSE on {target}…"):
                base_cmd = ["poetry", "run", "python"] if use_poetry and has_poetry() else ["python"]
                cmd = base_cmd + ["dpulse.py", target]
                if extra_args.strip():
                    cmd += shlex.split(extra_args.strip())
                code, out, err = run_streamed(cmd)
            if code == 0:
                st.success("✅ Scan completed")
                st.caption("Outputs and artifacts should appear under `./reports/`.")
            else:
                st.error("❌ DPULSE returned a non-zero exit code.")
                st.caption("Check stderr above for details.")

    st.divider()
    st.markdown(
        '<span class="small-note">Tip: if the process fails to find dependencies, run '
        '<code class="mono">poetry install</code> (or <code class="mono">pip install -r requirements.txt</code>) '
        "in the terminal.</span>",
        unsafe_allow_html=True,
    )

# === 2) REPORTS TAB ===
with reports_tab:
    st.subheader("📁 Reports Viewer")
    st.caption("Newest first. Supports HTML (inline), JSON (pretty), CSV (table).")

    files = list_reports()
    if not files:
        st.info("No reports found yet. Run a scan first.")
    else:
        selection = st.selectbox(
            "Select a report",
            files,
            format_func=lambda p: f"{p.name} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}",
        )
        act_col1, act_col2, act_col3 = st.columns([1, 1, 2])
        with act_col1:
            open_btn = st.button("Open")
        with act_col2:
            dl_btn = st.download_button(
                "Download",
                data=selection.read_bytes(),
                file_name=selection.name,
                mime="application/octet-stream",
            )

        if open_btn:
            try:
                ext = selection.suffix.lower()
                text = selection.read_text(encoding="utf-8", errors="ignore")
                if ext == ".html":
                    st.components.v1.html(text, height=900, scrolling=True)
                elif ext in {".json", ".ndjson"}:
                    try:
                        js = json.loads(text)
                    except Exception:
                        # try row-wise
                        js = [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]
                    st.json(js)
                    if isinstance(js, list) and js and isinstance(js[0], dict):
                        st.dataframe(pd.DataFrame(js), use_container_width=True)
                elif ext == ".csv":
                    df = pd.read_csv(selection, dtype=str, low_memory=False)
                    st.dataframe(df, use_container_width=True)
                else:
                    st.text_area("Raw Content", text, height=400)
            except Exception as e:
                st.error(f"Could not open report: {e}")
                st.code(traceback.format_exc())

    st.markdown(
        '<span class="small-note">Need a zipped bundle? Use the button below.</span>',
        unsafe_allow_html=True,
    )
    if st.button("Zip All Reports"):
        zip_path = REPORTS_DIR.parent / "reports_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in list_reports():
                zf.write(f, arcname=f.name)
        st.download_button(
            "Download ZIP",
            data=zip_path.read_bytes(),
            file_name=zip_path.name,
            mime="application/zip",
        )

# === 3) COLD CASE SEARCH TAB ===
with search_tab:
    st.subheader("🔍 Cold Case Search")
    st.caption("Point this at a NamUs-style CSV (or your internal case export).")

    with st.expander("Dataset", expanded=True):
        left, right = st.columns([3, 1])
        with left:
            ds_path = st.text_input(
                "Path to dataset (CSV or JSON)",
                value=str(DEFAULT_DATASET),
                help="Place your dataset under ./data and point to it here.",
            )
        with right:
            reload_btn = st.button("Load / Reload")

    @st.cache_data(show_spinner=False)
    def _load_dataset(path: str) -> pd.DataFrame:
        p = Path(path)
        if not p.exists():
            return pd.DataFrame()
        return load_table(p)

    if reload_btn or "search_df" not in st.session_state:
        st.session_state["search_df"] = _load_dataset(ds_path)

    df = st.session_state["search_df"]
    if df.empty:
        st.warning("No dataset loaded. Drop a CSV/JSON under ./data and update the path.")
    else:
        # Normalize a few common columns if present
        cols = {c.lower(): c for c in df.columns}
        def pick(*names):
            for n in names:
                if n.lower() in cols:
                    return cols[n.lower()]
            return None

        col_name = pick("Victim", "VictimName", "Name", "FullName", "Title")
        col_city = pick("City", "Municipality")
        col_state = pick("State", "Province", "Region")
        col_zip = pick("Zip", "ZipCode", "PostalCode")
        col_county = pick("County")
        col_year = pick("Year", "IncidentYear", "CaseYear", "DateYear")
        col_gender = pick("Gender", "Sex")
        col_race = pick("Race", "Ethnicity")
        col_status = pick("Status", "CaseStatus")
        col_url = pick("URL", "Link")

        q1, q2, q3, q4 = st.columns(4)
        with q1:
            q_name = st.text_input("Victim Name")
        with q2:
            q_city = st.text_input("City")
        with q3:
            q_state = st.text_input("State")
        with q4:
            q_year = st.text_input("Year")

        q5, q6, q7, q8 = st.columns(4)
        with q5:
            q_gender = st.selectbox("Victim Gender", ["Any", "Male", "Female", "Other"])
        with q6:
            q_race = st.text_input("Victim Race")
        with q7:
            q_zip = st.text_input("Zip Code")
        with q8:
            q_county = st.text_input("County")

        search_btn = st.button("Search", type="primary")
        if search_btn:
            res = df.copy()

            # string equality-ish filters
            def eq_filter(series: Optional[pd.Series], val: str):
                if not series is None and val.strip():
                    return series.fillna("").str.upper() == val.strip().upper()
                return pd.Series([True] * len(res))

            # fuzzy / contains filters
            def contains_filter(series: Optional[pd.Series], val: str):
                if not series is None and val.strip():
                    return series.fillna("").apply(lambda x: fuzzy_contains(val, x))
                return pd.Series([True] * len(res))

            mask = pd.Series([True] * len(res))
            if col_name:   mask &= contains_filter(res[col_name], q_name)
            if col_city:   mask &= contains_filter(res[col_city], q_city)
            if col_state:  mask &= eq_filter(res[col_state], q_state)
            if col_year:   mask &= eq_filter(res[col_year], q_year)
            if col_zip:    mask &= eq_filter(res[col_zip], q_zip)
            if col_county: mask &= contains_filter(res[col_county], q_county)
            if col_gender and q_gender != "Any":
                mask &= eq_filter(res[col_gender], q_gender)
            if col_race and q_race.strip():
                mask &= contains_filter(res[col_race], q_race)

            out = res[mask].copy()
            if out.empty:
                st.warning("No matching cases.")
            else:
                # Show a tidy subset of columns if available
                view_cols = [c for c in [col_name, col_city, col_state, col_year, col_gender, col_race, col_status, col_url] if c]
                if not view_cols:
                    view_cols = list(out.columns)[:8]
                st.success(f"Found {len(out)} cases (showing first 200).")
                st.dataframe(out.loc[:, view_cols].head(200), use_container_width=True)

                # Optional HTML links
                if col_url:
                    st.caption("Clickable links (if provided):")
                    html = []
                    for _, row in out.head(100).iterrows():
                        name = str(row.get(col_name, "Case")).strip() if col_name else "Case"
                        url = str(row.get(col_url, "")).strip()
                        if url and url.startswith("http"):
                            html.append(f'<div class="pill"><a href="{url}" target="_blank">{name}</a></div>')
                    if html:
                        st.markdown(" ".join(html), unsafe_allow_html=True)

# === 4) PROFILER TAB ===
with profiler_tab:
    st.subheader("🧩 Availability Profiler")
    st.caption("When your API is ready, set env var `PROFILER_API_URL` and we’ll call it from here.")

    if not PROFILER_API_URL:
        st.info("Set `PROFILER_API_URL` in environment to enable this tab.")
    else:
        lat, lon = st.columns(2)
        with lat:
            q_lat = st.number_input("Latitude", value=37.7749, format="%.6f")
        with lon:
            q_lon = st.number_input("Longitude", value=-122.4194, format="%.6f")
        radius = st.slider("Radius (meters)", min_value=100, max_value=20000, value=2000, step=100)
        date = st.text_input("Occurred Date (YYYY-MM-DD)", value="")
        sex = st.selectbox("Sex (optional)", ["", "male", "female"])
        min_age, max_age = st.columns(2)
        with min_age:
            q_min_age = st.number_input("Min Age", min_value=0, max_value=120, value=0)
        with max_age:
            q_max_age = st.number_input("Max Age", min_value=0, max_value=120, value=0)

        if st.button("Query Profiler", type="primary"):
            import requests
            payload = {
                "latitude": q_lat,
                "longitude": q_lon,
                "radius_meters": radius,
                "occurred_date": date or None,
                "sex": sex or None,
                "min_age": int(q_min_age) or None,
                "max_age": int(q_max_age) or None,
                "limit": 50,
            }
            try:
                r = requests.post(f"{PROFILER_API_URL.rstrip('/')}/availability/query", json=payload, timeout=60)
                r.raise_for_status()
                data = r.json()
                st.success("Profiler results")
                if isinstance(data, dict) and "candidates" in data:
                    st.dataframe(pd.DataFrame(data["candidates"]), use_container_width=True)
                else:
                    st.json(data)
            except Exception as e:
                st.error(f"Profiler request failed: {e}")
                st.code(traceback.format_exc())
