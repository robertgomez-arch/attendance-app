import streamlit as st
import pandas as pd
import re
import io
from datetime import datetime

# --- App Configuration ---
st.set_page_config(page_title="Attendance Reconciliation App", layout="wide")
st.title("📊 Weekly Attendance Reconciliation")
st.write("Upload your reports below to calculate the valid Distance Learning (DL) hours.")

# --- File Uploaders ---
col1, col2, col3 = st.columns(3)
with col1:
    aztec_files = st.file_uploader("1. Upload Aztec Reports (.csv)", accept_multiple_files=True, type=['csv'])
with col2:
    essential_files = st.file_uploader("2. Upload Essential Ed Reports (.csv)", accept_multiple_files=True, type=['csv'])
with col3:
    asap_files = st.file_uploader("3. Upload ASAP Reports (.csv)", accept_multiple_files=True, type=['csv'])

if st.button("Reconcile Attendance"):
    if not (aztec_files or essential_files or asap_files):
        st.warning("Please upload at least some files to begin.")
    else:
        with st.spinner("Processing files..."):
            # --- 1. Process Aztec Data ---
            aztec_data = []
            pattern = re.compile(r"Login:\s+(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)\s+Logout:\s+(\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M)")

            for f in aztec_files:
                if "Summary" in f.name: continue
                name_part = f.name.split(" - ")[-1]
                student_name = name_part.split("(")[0].strip() if "(" in name_part else name_part.replace(".csv", "").strip()
                
                try:
                    df = pd.read_csv(f)
                    if 'Events' in df.columns:
                        for _, row in df.iterrows():
                            lines = str(row['Events']).split('\n')
                            for line in lines:
                                match = pattern.search(line)
                                if match:
                                    login_dt = datetime.strptime(match.group(1), "%m/%d/%Y %I:%M %p")
                                    logout_dt = datetime.strptime(match.group(2), "%m/%d/%Y %I:%M %p")
                                    duration_hours = (logout_dt - login_dt).total_seconds() / 3600.0
                                    aztec_data.append({
                                        "Student Name": student_name,
                                        "Login": login_dt,
                                        "Logout": logout_dt,
                                        "Duration": duration_hours,
                                        "Date_Str": login_dt.strftime('%m/%d/%Y'),
                                        "Source": "Aztec"
                                    })
                except: pass
            df_aztec = pd.DataFrame(aztec_data)

            # --- 2. Process Essential Ed Data ---
            essential_data = []
            for f in essential_files:
                try:
                    df_essential = pd.read_csv(f, header=1) 
                    for _, row in df_essential.iterrows():
                        f_name = str(row.get('First Name', '')).strip()
                        l_name = str(row.get('Last Name', '')).strip()
                        if not f_name or f_name == 'nan': continue
                        
                        duration_str = str(row.get('Total Time on Task', '00:00:00'))
                        h, m, s = map(int, duration_str.split(':'))
                        duration_hours = h + m/60.0 + s/3600.0
                        
                        if duration_hours > 0:
                            essential_data.append({
                                "Student Name": f"{l_name}, {f_name}",
                                "Duration": duration_hours,
                                "Source": "EssentialEd"
                            })
                except: pass
            df_ee = pd.DataFrame(essential_data)

            # --- 3. Process ASAP Data ---
            asap_attendance = []
            for f in asap_files:
                class_start, class_end = None, None
                lines = f.getvalue().decode("utf-8").splitlines()
                for line in lines[:12]:
                    if "Time" in line and ("AM" in line or "PM" in line):
                        match = re.search(r"(\d{1,2}:\d{2}\s+[AP]M)-(\d{1,2}:\d{2}\s+[AP]M)", line)
                        if match:
                            class_start = datetime.strptime(match.group(1), "%I:%M %p").time()
                            class_end = datetime.strptime(match.group(2), "%I:%M %p").time()
                            break
                if not class_start: continue
                
                try:
                    f.seek(0)
                    df_asap = pd.read_csv(f, header=9)
                    date_map = {}
                    for col in df_asap.columns:
                        if re.match(r"\d{2}/\d{2}", col):
                            date_map[col] = col + "/2026" # Assuming current year or pull dynamically
                    
                    for _, row in df_asap.iterrows():
                        s_name = row['StudentName']
                        if pd.isna(s_name): continue
                        for day_col, date_str in date_map.items():
                            hours = row.get(day_col)
                            if pd.notna(hours) and str(hours).strip():
                                try:
                                    h, m = map(int, str(hours).split(':'))
                                    duration = h + m/60.0
                                    if duration > 0:
                                        asap_attendance.append({
                                            "Student Name": str(s_name).strip(),
                                            "Date": date_str,
                                            "InPerson_Duration": duration,
                                            "InPerson_Start": class_start,
                                            "InPerson_End": class_end
                                        })
                                except: pass
                except: pass
            df_asap_combined = pd.DataFrame(asap_attendance)

            # --- 4. Match & Reconcile ---
            def normalize_name(name):
                name_clean = re.sub(r"[^a-zA-Z\s]", " ", str(name)).lower()
                parts = name_clean.split()
                if "," in str(name): return f"{parts[0]} {parts[1]}" if len(parts) >= 2 else name_clean.strip()
                elif len(parts) >= 2: return " ".join(sorted([parts[0], parts[-1]])) 
                return name_clean.strip()

            if not df_asap_combined.empty: df_asap_combined['match_name'] = df_asap_combined['Student Name'].apply(normalize_name)
            if not df_aztec.empty: df_aztec['match_name'] = df_aztec['Student Name'].apply(normalize_name)
            if not df_ee.empty: df_ee['match_name'] = df_ee['Student Name'].apply(normalize_name)

            final_results = []
            if not df_aztec.empty:
                for _, az_row in df_aztec.iterrows():
                    overlap_hours = 0
                    if not df_asap_combined.empty:
                        asap_records = df_asap_combined[(df_asap_combined['match_name'] == az_row['match_name']) & (df_asap_combined['Date'] == az_row['Date_Str'])]
                        for _, rec in asap_records.iterrows():
                            o_start = max(az_row['Login'], datetime.combine(az_row['Login'].date(), rec['InPerson_Start']))
                            o_end = min(az_row['Logout'], datetime.combine(az_row['Login'].date(), rec['InPerson_End']))
                            if o_start < o_end:
                                overlap_hours += (o_end - o_start).total_seconds() / 3600.0
                    final_results.append({
                        "Student Name": az_row['Student Name'], "match_name": az_row['match_name'],
                        "Source": "Aztec", "Raw Duration": az_row['Duration'], "Overlap": overlap_hours,
                        "Valid Duration": max(0, az_row['Duration'] - overlap_hours)
                    })

            if not df_ee.empty:
                for _, ee_row in df_ee.iterrows():
                    final_results.append({
                        "Student Name": ee_row['Student Name'], "match_name": ee_row['match_name'],
                        "Source": "EssentialEd", "Raw Duration": ee_row['Duration'], "Overlap": 0, "Valid Duration": ee_row['Duration']
                    })

            df_final = pd.DataFrame(final_results)

            # --- 5. Generate Output ---
            if not df_final.empty:
                def dec_to_hm(hf):
                    if pd.isna(hf) or hf == 0: return "0h 0m"
                    h, m = int(hf), int(round((hf - int(hf)) * 60))
                    if m == 60: h, m = h+1, 0
                    return f"{h}h {m}m"

                summary = df_final.groupby("match_name").agg({"Student Name": "first", "Valid Duration": "sum", "Overlap": "sum"}).reset_index()
                aztec_only = df_final[df_final['Source']=='Aztec'].groupby("match_name")['Raw Duration'].sum().reset_index().rename(columns={'Raw Duration': 'Aztec Raw'})
                ee_only = df_final[df_final['Source']=='EssentialEd'].groupby("match_name")['Raw Duration'].sum().reset_index().rename(columns={'Raw Duration': 'Essential Raw'})
                
                summary = pd.merge(summary, aztec_only, on='match_name', how='left').fillna(0)
                summary = pd.merge(summary, ee_only, on='match_name', how='left').fillna(0)

                if not df_asap_combined.empty:
                    asap_totals = df_asap_combined.groupby("match_name")["InPerson_Duration"].sum().reset_index().rename(columns={'InPerson_Duration': 'Total In-Person Hours'})
                    summary = pd.merge(summary, asap_totals, on='match_name', how='left').fillna(0)
                else:
                    summary['Total In-Person Hours'] = 0

                summary.sort_values("Student Name", inplace=True)
                
                for col in ['Total In-Person Hours', 'Aztec Raw', 'Essential Raw', 'Overlap', 'Valid Duration']:
                    summary[col.replace('Hours', '(h m)').replace('Duration', 'DL (h m)')] = summary[col].apply(dec_to_hm)

                display_cols = ['Student Name', 'Total In-Person (h m)', 'Aztec Raw (h m)', 'Essential Raw (h m)', 'Overlap (h m)', 'Valid DL (h m)']
                output_df = summary[display_cols]

                st.success("Reconciliation Complete!")
                st.dataframe(output_df)

                # Download Button
                csv = output_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Final Report (CSV)",
                    data=csv,
                    file_name="Reconciled_Attendance.csv",
                    mime="text/csv",
                )
            else:
                st.error("No valid data found in the uploaded files. Please check the formats.")
