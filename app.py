import streamlit as st
import pandas as pd
import io

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

        # ניקוי בסיסי
        classes_df.columns = [str(c).strip() for c in classes_df.columns]
        teachers_df.columns = [str(c).strip() for c in teachers_df.columns]
        
        classes_df.iloc[:, 0] = classes_df.iloc[:, 0].ffill()
        classes_df = classes_df.replace("\n", " ", regex=True)
        
        # סינון לפי יום
        today_c = classes_df[classes_df.iloc[:, 0].astype(str).str.contains(day_of_week, na=False)].copy()
        
        teachers_df.iloc[:, 0] = teachers_df.iloc[:, 0].ffill()
        day_map = {"ראשון": "ראשון", "שני": "שני", "שלישי": "שלישי", "רביעי": "רביעי", "חמישי": "חמישי", "שישי": "שישי"}
        search_day = day_map.get(day_of_week, day_of_week)
        today_t = teachers_df[teachers_df.iloc[:, 0].astype(str).str.contains(search_day, na=False)].copy()

        # עיבוד קלטים
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

        # מיפוי מורים חוקיים
        valid_t = {}
        for i, col in enumerate(teachers_df.columns):
            t_name = str(teachers_df.iloc[0, i]).strip()
            if t_name not in ["nan", "חווה חקלאית", ""] and "Unnamed" not in t_name:
                valid_t[col] = t_name

        # מציאת יום חופשי (לפי קובץ המורים בלבד כפי שביקשת)
        day_off_teachers = set()
        for col, t_name in valid_t.items():
            if today_t[col].isnull().all() or (today_t[col].astype(str).str.strip() == "nan").all():
                day_off_teachers.add(t_name)

        # חישוב צרכי מילוי מקום
        covers = []
        for _, row in today_c.iterrows():
            try:
                hour_val = str(row.iloc[1]).strip()
                hour = int(float(hour_val))
            except:
                continue
            if hour > 6: continue
            
            for col in today_c.columns[2:]:
                teacher_cell = str(row[col]).strip()
                if teacher_cell == "nan" or teacher_cell == "": continue
                
                needs_cover = any(m in teacher_cell for m in full_absent)
                if not needs_cover:
                    for m, hours in partial_absent.items():
                        if m in teacher_cell and hour in hours:
                            needs_cover = True
                            break
                
                if needs_cover:
                    # בדיקת מורה נוסף בכיתה
                    parts = teacher_cell.replace("+", "/").split("/")
                    present_teacher = False
                    if len(parts) > 1:
                        for p in parts:
                            p_name = p.strip()
                            is_p_missing = any(m in p_name for m in full_absent)
                            for m, hours in partial_absent.items():
                                if m in p_name and hour in hours: is_p_missing = True
                            if not is_p_missing: present_teacher = True
                    
                    assigned = "(אין צורך במחליף)" if present_teacher else None
                    covers.append({"שעה": hour, "כיתה": col, "מורה חסרה": teacher_cell, "מחליף ששובץ": assigned, "הערות": ""})

        if not covers:
            st.warning("לא נמצאו מורים שזקוקים למילוי מקום לפי הנתונים שהוזנו.")
        else:
            # בניית פול מורים זמינים
            teaching_schedule = {h: [] for h in range(1, 7)}
            for _, row in today_c.iterrows():
                try: hr = int(float(row.iloc[1]))
                except: continue
                if hr <= 6:
                    for col in today_c.columns[2:]:
                        t = str(row[col]).strip()
                        if t != "nan": teaching_schedule[hr].append(t)

            internal_availability = {h: [] for h in range(1, 7)}
            for _, row in today_t.iterrows():
                try: h_val = str(row.iloc[1]).strip()
                hour = int(float(h_val))
                except: continue
                if hour > 6: continue
                
                for col, t_name in valid_t.items():
                    if t_name in day_off_teachers or any(m in t_name for m in full_absent + no_sub_list): continue
                    if any(m in t_name and hour in hours for m, hours in partial_absent.items()): continue
                    
                    teaching_now = any(t_name in c_t for c_t in teaching_schedule[hour])
                    if not teaching_now:
                        val = str(row[col]).strip().lower()
                        if val == "nan" or val == "": internal_availability[hour].append({"name": t_name, "type": "חלון"})
                        elif "פרטני" in val: internal_availability[hour].append({"name": t_name, "type": "פרטני"})

            # שיבוץ
            assigned_externals = {s: [] for s in external_subs}
            assigned_internals = {t: 0 for t in valid_t.values()}
            
            for cover in covers:
                if cover["מחליף ששובץ"]: continue
                hr = cover["שעה"]
                assigned = False
                
                for sub, h_list in external_subs.items():
                    if hr in h_list and hr not in assigned_externals[sub]:
                        cover["מחליף ששובץ"] = sub
                        cover["הערות"] = "מחליף חיצוני"
                        assigned_externals[sub].append(hr)
                        assigned = True
                        break
                if assigned: continue
                
                avails = sorted(internal_availability[hr], key=lambda x: 0 if x["type"] == "חלון" else 1)
                for av in avails:
                    t_name, t_type = av["name"], av["type"]
                    if assigned_internals[t_name] < 1:
                        already_in_hour = any(c.get("מחליף ששובץ") == t_name for c in covers if c["שעה"] == hr)
                        if not already_in_hour:
                            cover["מחליף ששובץ"] = t_name
                            cover["הערות"] = f"מתוך הצוות ({t_type})"
                            assigned_internals[t_name] += 1
                            assigned = True
                            break
                if not assigned: cover["מחליף ששובץ"] = "⚠️ חסר מורה!"

            # הצגת תוצאות
            df_final = pd.DataFrame(covers)
            for teacher in df_final["מורה חסרה"].unique():
                st.subheader(f"מורה חסרה: {teacher}")
                temp_df = df_final[df_final["מורה חסרה"] == teacher][["שעה", "כיתה", "מחליף ששובץ", "הערות"]]
                st.table(temp_df)

            # הורדה
            output = io.BytesIO()
            df_final.to_excel(output, index=False)
            st.download_button(label="📥 הורד דוח אקסל", data=output.getvalue(), file_name="replacement_report.xlsx")
            st.success("השיבוץ הסתיים!")

    except Exception as e:
        st.error(f"שגיאה בעיבוד הנתונים: {e}")
