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
    if not text:
        return []
    return [x.strip() for x in text.split(",") if x.strip()]

def parse_time_constraints(text: str) -> Dict[str, List[int]]:
    constraints = {}
    if text:
        for line in text.split("\n"):
            if ":" in line:
                name, hours_str = line.split(":", 1)
                hours = [int(h.strip()) for h in hours_str.split(",") if h.strip().isdigit()]
                constraints[name.strip()] = hours
    return constraints

def is_empty_cell(val: Any) -> bool:
    if pd.isna(val):
        return True
    if str(val).strip().lower() in ["nan", "", "none"]:
        return True
    return False

# ==========================================
# 3. Data Processing Functions
# ==========================================
def load_and_clean_data(classes_file, teachers_file, day_of_week: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str]]:
    read_func_c = pd.read_csv if classes_file.name.endswith('.csv') else pd.read_excel
    read_func_t = pd.read_csv if teachers_file.name.endswith('.csv') else pd.read_excel
    
    df_classes = read_func_c(classes_file)
    df_teachers = read_func_t(teachers_file)

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
        if today_t[col].apply(is_empty_cell).all():
            day_off.add(t_name)
    return day_off

def is_teacher_missing(teacher_name: str, hour: int, full_absent: List[str], partial_absent: Dict[str, List[int]]) -> bool:
    if any(m in teacher_name for m in full_absent):
        return True
    for m, hours in partial_absent.items():
        if m in teacher_name and hour in hours:
            return True
    return False

# ==========================================
# 4. Core Engine
# ==========================================
def generate_schedule(today_c: pd.DataFrame, today_t: pd.DataFrame, valid_t: Dict[str, str], day_off_teachers: Set[str], 
                      full_absent: List[str], partial_absent: Dict[str, List[int]], 
                      external_subs: Dict[str, List[int]], no_sub_list: List[str]) -> pd.DataFrame:
    
    covers = []
    teaching_schedule = {h: [] for h in range(1, 8)}

    # שלב א': מיפוי כיתות ומציאת חוסרים
    for _, row in today_c.iterrows():
        try:
            hour = int(float(str(row.iloc[1]).strip()))
        except ValueError:
            continue
        
        if hour > 7: continue

        for col in today_c.columns[2:]:
            cell_val = str(row[col]).strip()
            if is_empty_cell(cell_val): 
                continue
            
            teaching_schedule[hour].append(cell_val)

            if hour > 6: continue 

            if is_teacher_missing(cell_val, hour, full_absent, partial_absent):
                
                # פיצול בטוח כדי למנוע שגיאות שבירת שורה
                raw_parts = cell_val.replace("+", "/").split("/")
                parts = []
                for p in raw_parts:
                    clean_p = p.strip()
                    if clean_p:
                        parts.append(clean_p)
                        
                present_teacher = False
                
                if len(parts) > 1:
                    for p in parts:
                        if not is_teacher_missing(p, hour, full_absent, partial_absent):
                            present_teacher = True
                            break
                
                assigned = "(אין צורך במחליף)" if present_teacher else None
                covers.append({
