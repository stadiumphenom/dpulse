import streamlit as st
import subprocess
import os

st.set_page_config(page_title="DPULSE Web Interface", layout="wide")

st.title("🧠 DPULSE OSINT Scanner (Streamlit Wrapper)")
st.markdown("Run DPULSE scans directly from a browser UI instead of the CLI.")

# --- Inputs ---
target = st.text_input("Target Domain", placeholder="example.com")
mode = st.selectbox("Scan Mode", ["Basic Scan", "PageSearch", "Dorking", "API Scan"])

if st.button("Run Scan"):
    if not target:
        st.error("Please enter a target domain first.")
    else:
        st.info(f"Running {mode} scan on **{target}** ... This may take a minute.")
        
        # Run DPULSE via subprocess (Poetry or direct Python)
        cmd = ["poetry", "run", "python", "dpulse.py", target]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, error = process.communicate()

        if process.returncode == 0:
            st.success("✅ Scan completed successfully!")
            st.text_area("Scan Output", output, height=400)
        else:
            st.error("❌ DPULSE encountered an error:")
            st.code(error)
