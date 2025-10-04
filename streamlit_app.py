import streamlit as st
import subprocess
import os
import glob
import json

st.set_page_config(
    page_title="DPULSE Investigative Console",
    layout="wide",
    page_icon="🧠",
)

st.title("🧠 DPULSE Investigative Console")
st.caption("Run domain intelligence scans, review reports, and feed structured results into your profiler.")

tabs = st.tabs(["📡 Run Scan", "📁 Reports", "🧩 Profiler"])

# === SCAN TAB ===
with tabs[0]:
    st.subheader("📡 Run a DPULSE Scan")

    target = st.text_input("Target Domain", placeholder="example.com")
    mode = st.selectbox("Scan Mode", ["Basic Scan", "PageSearch", "Dorking", "API Scan"])

    if st.button("Run Scan"):
        if not target:
            st.error("Please enter a target domain.")
        else:
            st.info(f"Running {mode} scan on {target}...")
            cmd = ["poetry", "run", "python", "dpulse.py", target]
            with st.spinner("Running DPULSE... this may take a while."):
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                output, error = process.communicate()

            if process.returncode == 0:
                st.success("✅ Scan completed successfully!")
                st.text_area("Scan Output", output, height=400)
            else:
                st.error("❌ Error running DPULSE")
                st.code(error)

# === REPORTS TAB ===
with tabs[1]:
    st.subheader("📁 Available Reports")

    report_dir = "./reports"
    if not os.path.exists(report_dir):
        st.info("No reports found yet. Run a scan first.")
    else:
        reports = sorted(glob.glob(os.path.join(report_dir, "*.*")), key=os.path.getmtime, reverse=True)

        if reports:
            selected_report = st.selectbox("Select report to view", reports)
            if st.button("Open Report"):
                try:
                    with open(selected_report, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    # Try to auto-detect JSON reports
                    if selected_report.endswith(".json"):
                        try:
                            data = json.loads(content)
                            st.success("Structured report detected (JSON)")
                            st.json(data)

                            # Optional: if it looks like a list of dicts, make a table
                            if isinstance(data, list) and all(isinstance(i, dict) for i in data):
                                st.dataframe(data, use_container_width=True)

                        except json.JSONDecodeError:
                            st.warning("JSON report is malformed, showing raw text.")
                            st.text_area("Report Content", content, height=400)

                    elif selected_report.endswith(".html"):
                        st.components.v1.html(content, height=800, scrolling=True)

                    else:
                        st.text_area("Report Content", content, height=400)

                except Exception as e:
                    st.error(f"Error reading report: {e}")

        else:
            st.info("No completed scans yet.")

# === PROFILER TAB ===
with tabs[2]:
    st.subheader("🧩 Profiler Integration")
    st.write("""
        🔧 Coming soon: this will connect directly to your Availability Profiler API.
        Once linked, you’ll be able to feed DPULSE scan results into your profiling logic —
        automatically filtering suspects, matching geolocation data, and identifying behavioral overlap.
    """)
    st.info("For now, run scans in the first tab and review structured output in Reports.")
