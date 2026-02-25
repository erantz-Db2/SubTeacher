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
    result = []
    for x in text.split(","):
        clean_x = x.strip()
        if clean_x:
            result.append(clean_x)
    return result

def parse_time_constraints(text: str) -> Dict[str, List[int]]:
    constraints = {}
    if text:
        for line in text.split("\n"):
            if ":" in line:
                name, hours_str = line.split(":", 1)
                hours = []
                for h in hours_str.split(","):
                    h_clean = h.strip()
                    if h_clean.isdigit():
                        hours.append(int(h_clean))
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
    for m in full_absent:
        if m in teacher_name:
            return True
    for m, hours in partial_absent.items():
        if m in teacher_name and hour in hours:
