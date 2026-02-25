import streamlit as st
import pandas as pd
import io
from typing import List, Dict, Set, Any, Tuple

# ==========================================
# 1. Configuration & Setup
# ==========================================
st.set_page_config(page_title="מערכת שיבוץ מילוי מקום", layout="wide", page_icon="📅")

# ==========================================
# 2. Utility Functions
# ==========================================
def parse_comma_separated(text: str) -> List[str]:
    if not text: return []
    result = []
    for x in text.split(","):
        if x.strip(): result.append(x.strip())
    return result

def parse_time_constraints(text: str) -> Dict[str, List[int]]:
    constraints = {}
    if not text: return constraints
    for line in text.split("\n"):
        if ":" not in line: continue
        name, hours_str = line.split(":", 1)
        hours = []
        for h in hours_str.split(","):
            if h.strip().isdigit(): hours.append(int(h.strip()))
        constraints[name.strip()] = hours
    return constraints

def is_empty_cell(val: Any) -> bool:
    if pd.isna(val): return True
    if str(val).strip().lower() in ["nan", "", "none"]: return True
    return False

# ==========================================
# 3. Data Processing Functions
# ==========================================
def load_and_clean_data(classes_file, teachers_file, day_of_week: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    if classes_file.name.endswith('.csv'): df_classes = pd.read_csv(classes_file)
    else: df_classes = pd.read_excel(classes_file)
    
    if teachers_file.name.endswith('.csv'): df_teachers = pd.read_csv(teachers_file)
    else: df_teachers = pd.read_excel(teachers_file)

    df_classes.columns = [str(c).strip() for c in df_classes.columns]
    df_teachers.columns = [str(c).strip() for c in df_teachers.columns]

    df_classes.iloc[:, 0] = df_classes.iloc[:, 0].ffill()
    df_teachers.iloc[:, 0] = df_teachers.iloc[:, 0].ffill()

    df_classes = df_classes.replace(r'\n', ' ', regex=True)
    df_teachers = df_teachers.replace(r'\n', ' ', regex=True)

    day_map = {"ראשון": "ראשון", "שני": "שני", "שלישי": "שלישי", "רביעי": "רביעי", "חמישי": "חמישי", "שישי": "שישי"}
    search_day = day_map.get(day_of_week, day_of_week)
    
    today_c = df_classes[df_classes.iloc[:, 0].astype(str).str.contains(search_day, na=False, regex=False)].copy()
    today_t = df_teachers[df_teachers.iloc[:, 0].astype(str).str.contains(search_day, na=False, regex=False)].copy()

    valid_t = {}
    for col in df_teachers.columns:
        t_name = str(df_teachers.iloc[0][col]).strip()
        if not is_empty_cell(t_name) and "Unnamed" not in t_name and t_name != "חווה חקלאית":
            valid_t[col] = t_name

    return today_c, today_t, valid_t

def get_day_off_teachers(today_t: pd.DataFrame, valid_t: Dict[str, str]) -> Set[str]:
    day_off = set()
    for col, t_name in valid_t.items():
        if today_t[col].apply(is_empty_cell).all(): day_off.add(t_name)
    return day_off

def is_teacher_missing(teacher_name: str, hour: int, full_absent: List[str], partial_absent: Dict[str, List[int]]) -> bool:
    for m in full_absent:
        if m in teacher_name: return True
    for m, hours in partial_absent.items():
        if m in teacher_name and hour in hours: return True
    return False

# ==========================================
# 4. Core Engine
# ==========================================
def generate_schedule(today_c: pd.DataFrame, today_t: pd.DataFrame, valid_t: Dict[str, str], day_off_teachers: Set[str], full_absent: List[str], partial_absent: Dict[str, List[int]], external_subs: Dict[str, List[int]], no_sub_list: List[str]) -> pd.DataFrame:
    covers = []
    teaching_schedule = {}
    for h in range(1, 8): teaching_schedule[h] = []

    for _, row in today_c.iterrows():
        try: hour = int(float(str(row.iloc[1]).strip()))
        except ValueError: continue
        
        if hour > 7: continue

        for col in today_c.columns[2:]:
            cell_val = str(row[col]).strip()
            if is_empty_cell(cell_val): continue
            
            teaching_schedule[hour].append(cell_val)

            if hour > 6: continue 
            if not is_teacher_missing(cell_val, hour, full_absent, partial_absent): continue
                
            parts = []
            for p in cell_val.replace("+", "/").split("/"):
                if p.strip(): parts.append(p.strip())
                        
            present_teacher = False
            if len(parts) > 1:
                for p in parts:
                    if not is_teacher_missing(p, hour, full_absent, partial_absent):
                        present_teacher = True
                        break
            
            assigned = "(אין צורך במחליף)" if present_teacher else None
            
            cover_item = {}
            cover_item["שעה"] = hour
            cover_item["כיתה"] = col
            cover_item["מורה חסרה"] = cell_val
            cover_item["מחליף ששובץ"] = assigned
            cover_item["הערות"] = ""
            covers.append(cover_item)

    internal_availability = {}
    for h in range(1, 7): internal_availability[h] = []
        
    for _, row in today_t.iterrows():
        try: hour = int(float(str(row.iloc[1]).strip()))
        except ValueError: continue
        
        if hour > 6: continue

        for col, t_name in valid_t.items():
            if t_name in day_off_teachers: continue
                
            skip_teacher = False
            for m in full_absent + no_sub_list:
                if m in t_name: skip_teacher = True
            if skip_teacher: continue
                
            if is_teacher_missing(t_name, hour, [], partial_absent): continue
            
            is_busy = False
            for c_t in teaching_schedule.get(hour, []):
                if t_name in c_t: is_busy = True
            if is_busy: continue
            
            val = str(row[col]).strip()
            if is_empty_cell(val):
                av_item = {}
                av_item["name"] = t_name
                av_item["type"] = "חלון"
                internal_availability[hour].append(av_item)
            elif "פרטני" in val.lower():
                av_item = {}
                av_item["name"] = t_name
                av_item["type"] = "פרטני"
                internal_availability[hour].append(av_item)

    assigned_externals = {}
    for s in external_subs: assigned_externals[s] = []
        
    assigned_internals = {}
    for t in valid_t.values(): assigned_internals[t] = 0

    for cover in covers:
        if cover["מחליף ששובץ"]: continue
        
        hr = cover["שעה"]
        found_sub = False

        for sub, h_list in external_subs.items():
            if hr in h_list and hr not in assigned_externals[sub]:
                cover["מחליף ששובץ"] = sub
                cover["הערות"] = "מחליף חיצוני"
                assigned_externals[sub].append(hr)
                found_sub = True
                break
        
        if found_sub: continue

        avails = sorted(internal_availability.get(hr, []), key=lambda x: 0 if x["type"] == "חלון" else 1)
        for av in avails:
            t_name = av["name"]
            t_type = av["type"]
            
            if assigned_internals.get(t_name, 0) < 1:
                already_assigned_here = False
                for c in covers:
                    if c["שעה"] == hr and c.get("מחליף ששובץ") == t_name:
                        already_assigned_here = True
                
                if not already_assigned_here:
                    cover["מחליף ששובץ"] = t_name
                    cover["הערות"] = f"מתוך הצוות ({t_type})"
                    assigned_internals[t_name] += 1
                    found_sub = True
                    break
        
        if not found_sub: cover["מחליף ששובץ"] = "⚠️ חסר מורה!"

    return pd.DataFrame(covers)

# ==========================================
# 5. UI Layer
# ==========================================
def main():
    st.title("🎯 מערכת שיבוץ אוטומטית - מילוי מקום")

    st.sidebar.header("1. העלאת נתונים")
    classes_file = st.sidebar.file_uploader("העלה קובץ כיתות (CSV/Excel)", type=["csv", "xlsx"])
    teachers_file = st.sidebar.file_uploader("העלה קובץ מורים (CSV/Excel)", type=["csv", "xlsx"])

    day_of_week = st.sidebar.selectbox("בחר יום לשיבוץ", ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי"])

    st.sidebar.header("2. אילוצים יומיים")
    full_absent_input = st.sidebar.text_input("מורים חסרים (יום שלם) - מופרדים בפסיק", "דליה, נועה, רותם, דקלה")
    partial_absent_input = st.sidebar.text_area("היעדרויות חלקיות (פורמט: שם:שעות)", "נדין:3,4,5\nסתיו:3,4,5,6\nלירון צדוביץ:5,6\nרחל נוב:5,6\nאביטל:2,3,4,5,6")
    external_subs_input = st.sidebar.text_area("מחליפים חיצוניים (פורמט: שם:שעות)", "יואב:1,2,3,4,5,6\nגלית:1,2,3,4,5\nאירית:3,4,5,6")
    no_sub_input = st.sidebar.text_input("מורים שלא משבצים כמחליפים בכלל", "ספיר, לילך")

    if st.sidebar.button("⚙️ הפק שיבוץ יומי"):
        if not classes_file or not teachers_file:
            st.warning("אנא העלה את שני הקבצים לפני הפקת השיבוץ.")
            return

        with st.spinner("מעבד נתונים ומרכיב מערכת..."):
            try:
                full_absent = parse_comma_separated(full_absent_input)
                no_sub_list = parse_comma_separated(no_sub_input)
                partial_absent = parse_time_constraints(partial_absent_input)
                external_subs = parse_time_constraints(external_subs_input)

                today_c, today_t, valid_t = load_and_clean_data(classes_file, teachers_file, day_of_week)
                day_off_teachers = get_day_off_teachers(today_t, valid_t)
                
                df_results = generate_schedule(
                    today_c, today_t, valid_t, day_off_teachers,
                    full_absent, partial_absent, external_subs, no_sub_list
                )

                if df_results.empty:
                    st.success("לא נמצאו היעדרויות שדורשות מילוי מקום היום!")
                else:
                    for teacher in df_results["מורה חסרה"].unique():
                        st.subheader(f"מורה חסרה: {teacher}")
                        display_df = df_results[df_results["מורה חסרה"] == teacher][["שעה", "כיתה", "מחליף ששובץ", "הערות"]]
                        st.table(display_df)

                    output = io.BytesIO()
                    df_results.to_excel(output, index=False)
                    st.download_button(
                        label="📥 הורד דוח שיבוץ ל-Excel", 
                        data=output.getvalue(), 
                        file_name=f"Sub_Schedule_{day_of_week}.xlsx",
                        type="primary"
                    )
                    st.success("השיבוץ הושלם בהצלחה!")
                    
            except Exception as e:
                st.error(f"שגיאה מערכתית: {e}")

if __name__ == "__main__":
    main()
