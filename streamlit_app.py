# streamlit_app.py
# Cold Case Investigative Console (DPULSE + Profiler)
# Tabs: Scanner, Reports, Cold Case Search, Profiler

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
try:  # pragma: no cover
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None

APP_TITLE = "🧠 Cold Case Investigative Console"

# Paths
REPORTS_DIR = Path("./reports")                  # where dpulse writes artifacts
DATA_DIR = Path("./data")                        # where you drop public datasets
DEFAULT_DATASET = DATA_DIR / "namus_cases.csv"   # change to your real dataset

# Profiler API endpoint (set in Streamlit Cloud → Secrets or local env)
PROFILER_API_URL = os.getenv("PROFILER_API_URL", "").strip()

# -----------------------------------------------------------------------------
# PAGE CONFIG & LOOK
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Cold Case Console", page_icon="🧠", layout="wide")

# Light CSS (Matrix-ish; full theme lives in .streamlit/config.toml)
st.markdown(
    """
    <style>
      .stApp { background:#0f1620; }
      .stTabs [data-baseweb="tab"] { font-weight:600; }
      .small-note { opacity:.75;font-size:.9rem }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; }
      .pill { padding:4px 10px;border-radius:999px;background:#001a10;color:#90EE90;margin-right:8px;display:inline-block }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title(APP_TITLE)
st.caption(
    "Profiling ≠ guessing. We fuse availability + geography + behavior + time to surface credible leads."
)

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


def run_streamed(cmd: List[str]):
    """
    Run a command and stream stdout/stderr to Streamlit.
    Returns (exit_code, captured_stdout, captured_stderr).
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
            # flush remains
            if proc.stdout:
                rem = proc.stdout.read()
                if rem:
                    so.append(rem)
                    out_box.code("".join(so)[-4000:], language="bash")
            if proc.stderr:
                rem = proc.stderr.read()
                if rem:
                    se.append(rem)
                    err_box.code("".join(se)[-4000:], language="bash")
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


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


ensure_dirs()

# -----------------------------------------------------------------------------
# TABS
# -----------------------------------------------------------------------------
tab_scan, tab_reports, tab_search, tab_profiler = st.tabs(
    ["📡 DPULSE Scanner", "📁 Reports Viewer", "🔍 Cold Case Search", "🧩 Profiler"]
)

# === SCANNER ================================================================
with tab_scan:
    st.subheader("📡 DPULSE Scanner")
    st.markdown("Run DPULSE from the browser. We’ll try **Poetry** first, then fall back to system Python.")

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
        use_poetry = st.toggle("Use Poetry", value=_has_poetry(), help="If off, uses `python dpulse.py`")
        run_btn = st.button("Run Scan", type="primary")

    if run_btn:
        if not target.strip():
            st.error("Please enter a target domain.")
        else:
            with st.spinner(f"Running DPULSE on {target}…"):
                base = ["poetry", "run", "python"] if use_poetry and _has_poetry() else ["python"]
                cmd = base + ["dpulse.py", target]
                if extra_args.strip():
                    cmd += shlex.split(extra_args.strip())
                code, _, _ = run_streamed(cmd)

            if code == 0:
                st.success("✅ Scan completed")
                st.caption("Outputs and artifacts should appear under `./reports/`.")
            else:
                st.error("❌ DPULSE returned a non-zero exit code.")
                st.caption("Check the error pane above for details.")

    st.divider()
    st.markdown(
        '<span class="small-note">Tip: if dependencies are missing, run '
        '<code class="mono">poetry install</code> or '
        '<code class="mono">pip install -r requirements.txt</code>.</span>',
        unsafe_allow_html=True,
    )

# === REPORTS ================================================================
with tab_reports:
    st.subheader("📁 Reports Viewer")
    st.caption("Newest first. HTML (inline), JSON (pretty), CSV (table).")

    files = list_reports()
    if not files:
        st.info("No reports found yet. Run a scan first.")
    else:
        selection = st.selectbox(
            "Select a report",
            files,
            format_func=lambda p: f"{p.name} — {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}",
        )

        c1, c2, _ = st.columns([1, 1, 2])
        with c1:
            open_btn = st.button("Open")
        with c2:
            st.download_button(
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

    st.markdown('<span class="small-note">Need a bundle? Zip all reports:</span>', unsafe_allow_html=True)
    if st.button("Zip All Reports"):
        zip_path = REPORTS_DIR.parent / "reports_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in list_reports():
                zf.write(f, arcname=f.name)
        st.download_button("Download ZIP", data=zip_path.read_bytes(), file_name=zip_path.name, mime="application/zip")

# === COLD CASE SEARCH =======================================================
with tab_search:
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
            q_zip_q = st.text_input("Zip Code")
        with q8:
            q_county = st.text_input("County")

        if st.button("Search", type="primary"):
            res = df.copy()

            def eq_filter(series: Optional[pd.Series], val: str):
                if series is not None and val.strip():
                    return series.fillna("").str.upper() == val.strip().upper()
                return pd.Series([True] * len(res))

            def contains_filter(series: Optional[pd.Series], val: str):
                if series is not None and val.strip():
                    return series.fillna("").apply(lambda x: fuzzy_contains(val, x))
                return pd.Series([True] * len(res))

            mask = pd.Series([True] * len(res))
            if col_name:
                mask &= contains_filter(res[col_name], q_name)
            if col_city:
                mask &= contains_filter(res[col_city], q_city)
            if col_state:
                mask &= eq_filter(res[col_state], q_state)
            if col_year:
                mask &= eq_filter(res[col_year], q_year)
            if col_zip:
                mask &= eq_filter(res[col_zip], q_zip_q)
            if col_county:
                mask &= contains_filter(res[col_county], q_county)
            if col_gender and q_gender != "Any":
                mask &= eq_filter(res[col_gender], q_gender)
            if col_race and q_race.strip():
                mask &= contains_filter(res[col_race], q_race)

            out = res[mask].copy()
            if out.empty:
                st.warning("No matching cases.")
            else:
                view_cols = [
                    c
                    for c in [col_name, col_city, col_state, col_year, col_gender, col_race, col_status, col_url]
                    if c
                ]
                if not view_cols:
                    view_cols = list(out.columns)[:8]
                st.success(f"Found {len(out)} cases (showing first 200).")
                st.dataframe(out.loc[:, view_cols].head(200), use_container_width=True)

                if col_url:
                    st.caption("Clickable links (first 100):")
                    html = []
                    for _, row in out.head(100).iterrows():
                        nm = str(row.get(col_name, "Case")).strip() if col_name else "Case"
                        url = str(row.get(col_url, "")).strip()
                        if url.startswith("http"):
                            html.append(f'<div class="pill"><a href="{url}" target="_blank">{nm}</a></div>')
                    if html:
                        st.markdown(" ".join(html), unsafe_allow_html=True)

# === PROFILER ==============================================================
with tab_profiler:
    st.subheader("🧩 Availability Profiler")
    st.caption("When your API is ready, set env var `PROFILER_API_URL` and we’ll call it from here.")

    if not PROFILER_API_URL:
        st.info("Set `PROFILER_API_URL` in environment to enable this tab.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            q_lat = st.number_input("Latitude", value=37.7749, format="%.6f")
        with c2:
            q_lon = st.number_input("Longitude", value=-122.4194, format="%.6f")
        radius = st.slider("Radius (meters)", 100, 20000, 2000, 100)
        date = st.text_input("Occurred Date (YYYY-MM-DD)", value="")
        sex = st.selectbox("Sex (optional)", ["", "male", "female"])
        a1, a2 = st.columns(2)
        with a1:
            q_min_age = st.number_input("Min Age", min_value=0, max_value=120, value=0)
        with a2:
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
