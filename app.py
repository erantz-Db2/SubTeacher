import os
import re
import io
import pandas as pd
import streamlit as st
from typing import List, Dict, Set, Any, Tuple, Optional
from pathlib import Path
from dataclasses import dataclass

# ==========================================
# 1. Configuration & Constants
# ==========================================
st.set_page_config(page_title="מערכת שיבוץ מילוי מקום", layout="wide", page_icon="📅")

SAVE_DIR = Path("saved_files")
SAVE_DIR.mkdir(exist_ok=True)

DAYS_ALIASES = {
    "ראשון": ["ראשון", "א'", "יום א"],
    "שני": ["שני", "ב'", "יום ב"],
    "שלישי": ["שלישי", "ג'", "יום ג"],
    "רביעי": ["רביעי", "ד'", "יום ד"],
    "חמישי": ["חמישי", "ה'", "יום ה"],
    "שישי": ["שישי", "ו'", "יום ו"]
}

@dataclass
class CoverRecord:
    hour: int
    room: str
    missing_teacher: str
    substitute: Optional[str] = None
    notes: str = ""

# ==========================================
# 2. Data Access Layer (File IO)
# ==========================================
class DataAccess:
    @staticmethod
    def save_file(uploaded_file, prefix: str) -> Path:
        for f in SAVE_DIR.glob(f"{prefix}_*"):
            f.unlink()
        file_path = SAVE_DIR / f"{prefix}_{uploaded_file.name}"
        file_path.write_bytes(uploaded_file.getbuffer())
        return file_path

    @staticmethod
    def get_file(prefix: str) -> Optional[Path]:
        files = list(SAVE_DIR.glob(f"{prefix}_*"))
        return files[0] if files else None

    @staticmethod
    def read_spreadsheet(file_path: Path) -> pd.DataFrame:
        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
            if len(df.columns) <= 1: df = pd.read_csv(file_path, sep=';')
            if len(df.columns) <= 1: df = pd.read_csv(file_path, sep='\t')
            return df
        
        sheets = pd.read_excel(file_path, sheet_name=None)
        return max(sheets.values(), key=lambda d: len(d.columns))

# ==========================================
# 3. Core Engine (Business Logic)
# ==========================================
class ScheduleEngine:
    @staticmethod
    def parse_csv_string(text: str) -> List[str]:
        return [x.strip() for x in text.split(",") if x.strip()] if text else []

    @staticmethod
    def parse_time_rules(text: str) -> Dict[str, List[int]]:
        rules = {}
        if not text: return rules
        for line in text.splitlines():
            if ":" not in line: continue
            name, hours_str = line.split(":", 1)
            hours = [int(h.strip()) for h in hours_str.split(",") if h.strip().isdigit()]
            if hours: rules[name.strip()] = hours
        return rules

    @staticmethod
    def is_empty(val: Any) -> bool:
        return pd.isna(val) or str(val).strip().lower() in ["nan", "", "none"]

    @staticmethod
    def is_teacher_absent(name: str, hour: int, full_absent: List[str], partial_absent: Dict[str, List[int]]) -> bool:
        if any(m in name for m in full_absent): return True
        if any(m in name and hour in hours for m, hours in partial_absent.items()): return True
        return False

    @staticmethod
    def prepare_daily_data(classes_path: Path, teachers_path: Path, day: str) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, str], pd.DataFrame]:
        df_c = DataAccess.read_spreadsheet(classes_path)
        df_t = DataAccess.read_spreadsheet(teachers_path)

        if len(df_c.columns) < 2 or len(df_t.columns) < 2 or df_t.empty:
            raise ValueError("Data Integrity Error: One or both Excel files are empty or malformed.")

        df_c.columns = [str(c).strip() for c in df_c.columns]
        df_t.columns = [str(c).strip() for c in df_t.columns]
        df_c.iloc[:, 0] = df_c.iloc[:, 0].ffill()
        df_t.iloc[:, 0] = df_t.iloc[:, 0].ffill()
        df_c.replace(r'\n', ' ', regex=True, inplace=True)
        df_t.replace(r'\n', ' ', regex=True, inplace=True)

        pattern = "|".join(DAYS_ALIASES.get(day, [day]))
        daily_c = df_c[df_c.iloc[:, 0].astype(str).str.contains(pattern, na=False, regex=True)].copy()
        daily_t = df_t[df_t.iloc[:, 0].astype(str).str.contains(pattern, na=False, regex=True)].copy()

        valid_teachers = {}
        for col in df_t.columns:
            t_name = str(df_t.iloc[0][col]).strip()
            if not ScheduleEngine.is_empty(t_name) and "Unnamed" not in t_name and t_name != "חווה חקלאית":
                valid_teachers[col] = t_name

        return daily_c, daily_t, valid_teachers, df_c

    @classmethod
    def generate_schedule(cls, daily_c: pd.DataFrame, daily_t: pd.DataFrame, valid_t: Dict[str, str], 
                          f_abs: List[str], p_abs: Dict[str, List[int]], 
                          ext_subs: Dict[str, List[int]], no_sub: List[str]) -> pd.DataFrame:
        
        day_off_teachers = {tn for col, tn in valid_t.items() if daily_t[col].apply(cls.is_empty).all()}
        covers: List[CoverRecord] = []
        teaching_map = {h: [] for h in range(1, 10)}

        # 1. Identify needs
        for _, row in daily_c.iterrows():
            hour_match = re.search(r'\b([1-9])\b', str(row.iloc[1]).strip().replace(".0", ""))
            if not hour_match: continue
            hr = int(hour_match.group(1))
            if hr > 7: continue

            for col in daily_c.columns[2:]:
                cell_val = str(row[col]).strip()
                if cls.is_empty(cell_val): continue
                
                teaching_map[hr].append(cell_val)
                if hr > 6: continue 
                if not cls.is_teacher_absent(cell_val, hr, f_abs, p_abs): continue
                    
                parts = [p.strip() for p in cell_val.replace("+", "/").split("/") if p.strip()]
                present = any(not cls.is_teacher_absent(p, hr, f_abs, p_abs) for p in parts) if len(parts) > 1 else False
                
                record = CoverRecord(hour=hr, room=col, missing_teacher=cell_val)
                if present: record.substitute = "(אין צורך במחליף)"
                covers.append(record)

        # 2. Map availability
        avail_map = {h: [] for h in range(1, 7)}
        for _, row in daily_t.iterrows():
            hour_match = re.search(r'\b([1-9])\b', str(row.iloc[1]).strip().replace(".0", ""))
            if not hour_match: continue
            hr = int(hour_match.group(1))
            if hr > 6: continue

            for col, t_name in valid_t.items():
                if t_name in day_off_teachers or any(m in t_name for m in f_abs + no_sub) or cls.is_teacher_absent(t_name, hr, [], p_abs): continue
                if any(t_name in c_t for c_t in teaching_map.get(hr, [])): continue
                
                val = str(row[col]).strip()
                if cls.is_empty(val): avail_map[hr].append({"name": t_name, "type": "חלון"})
                elif "פרטני" in val.lower(): avail_map[hr].append({"name": t_name, "type": "פרטני"})

        # 3. Assign substitutes
        assigned_ext = {s: [] for s in ext_subs}
        assigned_int = {t: 0 for t in valid_t.values()}

        for c in covers:
            if c.substitute: continue
            hr = c.hour
            found = False

            # Try externals
            for s, hs in ext_subs.items():
                if hr in hs and hr not in assigned_ext[s]:
                    c.substitute, c.notes, found = s, "מחליף חיצוני", True
                    assigned_ext[s].append(hr)
                    break
            if found: continue

            # Try internals
            avails = sorted(avail_map.get(hr, []), key=lambda x: 0 if x["type"] == "חלון" else 1)
            for av in avails:
                tn, tp = av["name"], av["type"]
                if assigned_int.get(tn, 0) < 1 and not any(cv.substitute == tn for cv in covers if cv.hour == hr):
                    c.substitute, c.notes, found = tn, f"מתוך הצוות ({tp})", True
                    assigned_int[tn] += 1
                    break
            
            if not found: c.substitute = "⚠️ חסר מורה!"

        # Convert dataclasses to DataFrame
        return pd.DataFrame([{"שעה": c.hour, "כיתה": c.room, "מורה חסרה": c.missing_teacher, "מחליף ששובץ": c.substitute, "הערות": c.notes} for c in covers])

# ==========================================
# 4. Presentation Layer (UI)
# ==========================================
def render_ui():
    st.title("🎯 מערכת שיבוץ אוטומטית - מילוי מקום (גרסת Pro)")

    st.sidebar.header("1. קובצי מערכת השעות")
    c_path = DataAccess.get_file("classes")
    t_path = DataAccess.get_file("teachers")
    
    if c_path: st.sidebar.success(f"✅ כיתות: {c_path.name.replace('classes_', '')}")
    cf = st.sidebar.file_uploader("העלה קובץ כיתות חדש", type=["csv", "xlsx"])
    if cf: 
        DataAccess.save_file(cf, "classes")
        st.rerun()

    if t_path: st.sidebar.success(f"✅ מורים: {t_path.name.replace('teachers_', '')}")
    tf = st.sidebar.file_uploader("העלה קובץ מורים חדש", type=["csv", "xlsx"])
    if tf: 
        DataAccess.save_file(tf, "teachers")
        st.rerun()

    day_of_week = st.sidebar.selectbox("בחר יום לשיבוץ", list(DAYS_ALIASES.keys()))

    st.sidebar.header("2. אילוצים יומיים")
    f_abs_in = st.sidebar.text_input("חסרים יום שלם (מופרדים בפסיק)", "דליה, נועה, רותם, דקלה")
    p_abs_in = st.sidebar.text_area("היעדרויות חלקיות (שם:שעות)", "נדין:3,4,5\nסתיו:3,4,5,6\nלירון צדוביץ:5,6\nרחל נוב:5,6\nאביטל:2,3,4,5,6")
    ext_in = st.sidebar.text_area("מחליפים חיצוניים (שם:שעות)", "יואב:1,2,3,4,5,6\nגלית:1,2,3,4,5\nאירית:3,4,5,6")
    no_sub_in = st.sidebar.text_input("לא משבצים כמחליפים", "ספיר, לילך")

    if st.sidebar.button("⚙️ הפק שיבוץ יומי", type="primary"):
        if not c_path or not t_path:
            st.error("שגיאה: חסרים קובצי נתונים. אנא העלה את קובצי הכיתות והמורים.")
            return

        with st.spinner("מעבד נתונים ומפיק שיבוצים..."):
            try:
                engine = ScheduleEngine()
                f_abs = engine.parse_csv_string(f_abs_in)
                no_sub = engine.parse_csv_string(no_sub_in)
                p_abs = engine.parse_time_rules(p_abs_in)
                ext_subs = engine.parse_time_rules(ext_in)

                daily_c, daily_t, valid_t, raw_df = engine.prepare_daily_data(c_path, t_path, day_of_week)
                df_results = engine.generate_schedule(daily_c, daily_t, valid_t, f_abs, p_abs, ext_subs, no_sub)

                if df_results.empty:
                    st.warning(f"לא נמצאו היעדרויות שדורשות מילוי מקום ביום {day_of_week}.")
                    with st.expander("🛠️ מצב אבחון (Diagnostic Mode)"):
                        st.write(f"רשומות שאותרו ליום זה: {len(daily_c)}")
                        st.dataframe(raw_df.head(10))
                else:
                    for t in df_results["מורה חסרה"].unique():
                        st.subheader(f"מורה חסרה: {t}")
                        st.table(df_results[df_results["מורה חסרה"] == t][["שעה", "כיתה", "מחליף ששובץ", "הערות"]])

                    out = io.BytesIO()
                    df_results.to_excel(out, index=False)
                    st.download_button("📥 הורד דוח מילוי מקום (Excel)", out.getvalue(), f"Schedule_{day_of_week}.xlsx", "primary")
                    st.success("תהליך השיבוץ הסתיים בהצלחה!")

            except Exception as e:
                st.error(f"System Exception: {str(e)}")

if __name__ == "__main__":
    render_ui()
