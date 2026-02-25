import streamlit as st
import pandas as pd

st.set_page_config(page_title="מערכת שיבוץ מילוי מקום", layout="wide", page_icon="📅")

st.title("🎯 מערכת שיבוץ אוטומטית - מילוי מקום")

st.sidebar.header("1. העלאת נתונים")
classes_file = st.sidebar.file_uploader("העלה את קובץ הכיתות (CSV/Excel)", type=["csv", "xlsx"])
teachers_file = st.sidebar.file_uploader("העלה את קובץ המורים (CSV/Excel)", type=["csv", "xlsx"])

day_of_week = st.sidebar.selectbox("בחר יום לשיבוץ", ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי"])

st.sidebar.header("2. אילוצים יומיים")
full_absent_input = st.sidebar.text_input("מורים חסרים (יום שלם) - מופרדים בפסיק", "דליה, נועה, רותם, דקלה")
partial_absent_input = st.sidebar.text_area("היעדרויות חלקיות (פורמט: שם:שעות)", "נדין:3,4,5\nסתיו:3,4,5,6\nלירון צדוביץ:5,6\nרחל נוב:5,6\nאביטל:2,3,4,5,6")
external_subs_input = st.sidebar.text_area("מחליפים חיצוניים (פורמט: שם:שעות)", "יואב:1,2,3,4,5,6\nגלית:1,2,3,4,5\nאירית:3,4,5,6")
no_sub_input = st.sidebar.text_input("מורים שלא משבצים כמחליפים בכלל", "ספיר, לילך")

if st.sidebar.button("⚙️ הפק שיבוץ יומי") and classes_file and teachers_file:
    try:
        # טעינת נתונים
        if classes_file.name.endswith("csv"):
            classes_df = pd.read_csv(classes_file)
        else:
            classes_df = pd.read_excel(classes_file)
            
        if teachers_file.name.endswith("csv"):
            teachers_df = pd.read_csv(teachers_file)
        else:
            teachers_df = pd.read_excel(teachers_file)

        # ניקוי וסידור נתונים בסיסי
        classes_df.iloc[:, 0] = classes_df.iloc[:, 0].ffill()
        classes_df = classes_df.replace("\n", "", regex=True)
        today_c = classes_df[classes_df.iloc[:, 0].astype(str).str.contains(day_of_week, na=False)]

        teachers_df.iloc[:, 0] = teachers_df.iloc[:, 0].ffill()
        teachers_df = teachers_df.replace("\n", "", regex=True)
        today_t = teachers_df[teachers_df.iloc[:, 0].astype(str).str.contains(day_of_week, na=False)]

        # עיבוד קלטים מהמשתמש
        full_absent = [x.strip() for x in full_absent_input.split(",")] if full_absent_input else []
        no_sub_list = [x.strip() for x in no_sub_input.split(",")] if no_sub_input else []
        
        partial_absent = {}
        if partial_absent_input:
            for line in partial_absent_input.split("\n"):
                if ":" in line:
                    name, hours = line.split(":")
                    partial_absent[name.strip()] = [int(h.strip()) for h in hours.split(",")]

        external_subs = {}
        if external_subs_input:
            for line in external_subs_input.split("\n"):
                if ":" in line:
                    name, hours = line.split(":")
                    external_subs[name.strip()] = [int(h.strip()) for h in hours.split(",")]

        # מיפוי מורים חוקיים מקובץ מורים
        valid_t = {}
        for i, col in enumerate(teachers_df.columns):
            t_name = str(teachers_df.iloc[0, i]).strip()
            if t_name not in ["nan", "חווה חקלאית"] and "Unnamed" not in t_name:
                valid_t[col] = t_name

        # מציאת מורים ביום חופשי
        working_teachers = set()
        for _, row in today_c.iterrows():
            for col in today_c.columns[2:]:
                teacher = str(row[col]).strip()
                if teacher != "nan":
                    for p in teacher.replace("+", "/").split("/"):
                        for _, t_name in valid_t.items():
                            if t_name in p or p.strip() in t_name:
                                working_teachers.add(t_name)
                                
        for _, row in today_t.iterrows():
            for col, t_name in valid_t.items():
                if str(row[col]).strip() != "nan":
                    working_teachers.add(t_name)
                    
        day_off_teachers = set(valid_t.values()) - working_teachers

        # חישוב צרכי מילוי מקום
        covers = []
        for _, row in today_c.iterrows():
            try: hour = int(float(row.iloc[1]))
            except: continue
            if hour > 6: continue
            
            for col in today_c.columns[2:]:
                teacher = str(row[col]).strip()
                if teacher == "nan": continue
                
                needs_cover = any(m in teacher for m in full_absent)
                if not needs_cover:
                    for m, hours in partial_absent.items():
                        if m in teacher and hour in hours: needs_cover = True
                
                if needs_cover:
                    present_teacher = False
                    for p in teacher.replace("+", "/").split("/"):
                        p_name = p.strip()
                        if not p_name: continue
                        is_p_missing = any(m in p_name for m in full_absent)
                        for m, hours in partial_absent.items():
                            if m in p_name and hour in hours: is_p_missing = True
                        if not is_p_missing: present_teacher = True
                    
                    assigned = "(אין צורך במחליף)" if present_teacher else None
                    covers.append({"שעה": hour, "כיתה": col, "מורה חסרה": teacher, "מחליף ששובץ": assigned, "הערות": ""})

        # בניית פול מורים זמינים
        teaching_schedule = {h: [] for h in range(1, 7)}
        for _, row in today_c.iterrows():
