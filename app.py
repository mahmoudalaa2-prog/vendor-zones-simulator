import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point, box, MultiPoint
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import numpy as np
import re
import os
import io
import json
import copy
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

# مكتبات فايربيز الرسمية
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 1. إعدادات الصفحة والتصميم واللغة بهوية طلبات
# ==========================================
st.set_page_config(layout="wide", page_title="Pharmacy & Zones Management", page_icon="💊")

st.markdown("""
<style>
div[data-testid="stMetric"] {
    background: rgba(255, 255, 255, 0.02) !important;
    border: 1px solid rgba(255, 90, 0, 0.22) !important;
    border-top: 3.5px solid #ff5a00 !important;
    border-radius: 12px !important;
    padding: 12px 16px !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15) !important;
}
div[data-testid="stMetricValue"] {
    font-size: 22px !important;
    font-weight: 800 !important;
    color: #ff5a00 !important;
}
div[data-testid="stMetricLabel"] {
    font-size: 13px !important;
    color: #c9d1d9 !important;
    font-weight: 600 !important;
}
button[kind="primary"], .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #ff5a00 0%, #ff7700 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 9px !important;
    font-weight: 700 !important;
    padding: 8px 18px !important;
    box-shadow: 0 4px 14px rgba(255, 90, 0, 0.35) !important;
}
button[kind="secondary"], .stButton > button[kind="secondary"] {
    border: 1px solid rgba(255, 90, 0, 0.4) !important;
    border-radius: 9px !important;
    color: #e2e8f0 !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: #ff5a00 !important;
    font-weight: 800 !important;
    border-bottom: 3.5px solid #ff5a00 !important;
    background: rgba(255, 90, 0, 0.08) !important;
}
section[data-testid="stSidebar"] {
    border-left: 1px solid rgba(255, 90, 0, 0.2) !important;
    border-right: 1px solid rgba(255, 90, 0, 0.2) !important;
    background: linear-gradient(180deg, rgba(255, 90, 0, 0.06) 0%, rgba(14, 17, 23, 0) 100%) !important;
}
</style>
""", unsafe_allow_html=True)

if "lang" not in st.session_state:
    st.session_state["lang"] = "ar"

def T(ar_text, en_text):
    return ar_text if st.session_state.get("lang", "ar") == "ar" else en_text

BRANCH_PALETTE = [
    {"hex": "#28a745", "folium": "green", "name": "أخضر"},
    {"hex": "#e67e22", "folium": "orange", "name": "برتقالي"},
    {"hex": "#9b59b6", "folium": "purple", "name": "بنفسجي"},
    {"hex": "#e74c3c", "folium": "red", "name": "أحمر"},
    {"hex": "#17a2b8", "cadetblue": "cadetblue", "name": "تركواز"},
    {"hex": "#d63384", "folium": "pink", "name": "وردي"},
    {"hex": "#0dcaf0", "folium": "lightblue", "name": "سماوي"},
    {"hex": "#198754", "darkgreen": "darkgreen", "name": "أخضر داكن"},
    {"hex": "#8540f5", "darkpurple": "darkpurple", "name": "أرجواني"},
    {"hex": "#a52a2a", "darkred": "darkred", "name": "بني"},
    {"hex": "#ffc107", "orange": "orange", "name": "أصفر ذهبي"},
    {"hex": "#20c997", "cadetblue": "cadetblue", "name": "تيل"},
    {"hex": "#6610f2", "darkpurple": "darkpurple", "name": "نيلي"},
    {"hex": "#fd7e14", "orange": "orange", "name": "برتقالي فاقع"},
    {"hex": "#007bff", "blue": "blue", "name": "أزرق"}
]

DELIVERY_TIME_CHOICES = ["20 mins", "25 mins", "30 mins", "35 mins", "40 mins", "45 mins", "50 mins", "55 mins", "60 mins"]

# ==========================================
# 2. إدارة الاتصال بـ Firebase Firestore
# ==========================================
USERS_FILE = "users.csv"
REQUESTS_FILE = "vendor_pricing_requests.csv"
SMTP_CONFIG_FILE = "smtp_config.json"
MASTER_ADMIN_EMAIL = "mahmoud.alaa.2@talabat.com"

REQUESTS_COLUMNS = [
    "Date", "Vendor ID", "Vendor Name", "Zone", "Classification", 
    "Action", "Distance (km)", "Delivery Time", "Delivery Fees", "Minimum Order Amount", "Final_Status", "Status"
]

@st.cache_resource
def get_db():
    if not firebase_admin._apps:
        try:
            if "firebase" in st.secrets:
                key_dict = dict(st.secrets["firebase"])
                if "private_key" in key_dict:
                    key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(key_dict)
                firebase_admin.initialize_app(cred)
            elif os.path.exists("firebase_key.json"):
                cred = credentials.Certificate("firebase_key.json")
                firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"⚠️ فشل الاتصال بقاعدة بيانات Firebase: {e}")
            return None
    try:
        return firestore.client()
    except Exception:
        return None

db = get_db()

def test_firebase_connection():
    if db is None:
        return False, "الاتصال غير مهيأ. تأكد من ضبط إعدادات [firebase] في Streamlit Secrets."
    try:
        test_ref = db.collection("_ping").document("test")
        test_ref.set({"timestamp": firestore.SERVER_TIMESTAMP})
        return True, "الاتصال بـ Firebase Firestore يعمل بنجاح فائق! القراءة والكتابة نشطة بنسبة 100%."
    except Exception as e:
        return False, f"فشل الاتصال بـ Firebase: {e}"

def load_smtp_config():
    cfg = {
        "server": "smtp.gmail.com",
        "port": 587,
        "sender_email": "",
        "sender_password": "",
        "admin_email": MASTER_ADMIN_EMAIL
    }
    if os.path.exists(SMTP_CONFIG_FILE):
        try:
            with open(SMTP_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception: pass
    try:
        if "smtp" in st.secrets:
            cfg["server"] = st.secrets["smtp"].get("server", cfg["server"])
            cfg["port"] = int(st.secrets["smtp"].get("port", cfg["port"]))
            cfg["sender_email"] = st.secrets["smtp"].get("sender_email", cfg["sender_email"])
            cfg["sender_password"] = st.secrets["smtp"].get("sender_password", cfg["sender_password"])
            cfg["admin_email"] = st.secrets["smtp"].get("recipient_email", cfg["admin_email"])
    except Exception: pass
    return cfg

def save_smtp_config(server, port, sender_email, sender_password, admin_email):
    data = {
        "server": str(server).strip(),
        "port": int(port),
        "sender_email": str(sender_email).strip(),
        "sender_password": str(sender_password).strip(),
        "admin_email": str(admin_email).strip()
    }
    try:
        with open(SMTP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True, "تم حفظ إعدادات خادم البريد بنجاح!"
    except Exception as e:
        return False, f"فشل حفظ الإعدادات: {e}"

def test_smtp_connection(server_host, port_num, sender, password, recipient):
    if not sender or not password:
        return False, "بيانات الراسل ناقصة: يرجى إدخال البريد الإلكتروني وكلمة مرور التطبيق."
    try:
        msg = MIMEText("This is a test notification from Talabat Operations Platform.", "plain", "utf-8")
        msg["Subject"] = "🧪 Test Email - Talabat Operations Hub"
        msg["From"] = f"Talabat Operations Hub <{sender}>"
        msg["To"] = recipient

        if int(port_num) == 465:
            server = smtplib.SMTP_SSL(server_host, int(port_num), timeout=12)
        else:
            server = smtplib.SMTP(server_host, int(port_num), timeout=12)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())
        server.quit()
        return True, f"نجح الاتصال! تم إرسال إيميل تجريبي بنجاح إلى: {recipient}"
    except Exception as e:
        return False, f"فشل الاتصال بخادم البريد: {e}"

def init_users_db():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame([{
            "email": MASTER_ADMIN_EMAIL,
            "password": "123456",
            "role": "admin",
            "access_type": "all",
            "access_ids": "all"
        }]).to_csv(USERS_FILE, index=False)

def get_users_df():
    required_cols = ["email", "password", "role", "access_type", "access_ids"]
    if db is not None:
        try:
            docs = db.collection("users").stream()
            records = [d.to_dict() for d in docs]
            if records:
                df = pd.DataFrame(records)
                for c in required_cols:
                    if c not in df.columns: df[c] = ""
                has_admin = (df["email"].astype(str).str.lower() == MASTER_ADMIN_EMAIL.lower()).any()
                if not has_admin:
                    admin_row = {
                        "email": MASTER_ADMIN_EMAIL,
                        "password": "123456",
                        "role": "admin",
                        "access_type": "all",
                        "access_ids": "all"
                    }
                    db.collection("users").document(MASTER_ADMIN_EMAIL.lower()).set(admin_row)
                    df = pd.concat([pd.DataFrame([admin_row]), df], ignore_index=True)
                return df[required_cols]
            else:
                admin_row = {
                    "email": MASTER_ADMIN_EMAIL,
                    "password": "123456",
                    "role": "admin",
                    "access_type": "all",
                    "access_ids": "all"
                }
                db.collection("users").document(MASTER_ADMIN_EMAIL.lower()).set(admin_row)
                return pd.DataFrame([admin_row])[required_cols]
        except Exception: pass

    init_users_db()
    try:
        df_local = pd.read_csv(USERS_FILE)
        for c in required_cols:
            if c not in df_local.columns: df_local[c] = ""
        return df_local[required_cols]
    except Exception:
        return pd.DataFrame([{
            "email": MASTER_ADMIN_EMAIL,
            "password": "123456",
            "role": "admin",
            "access_type": "all",
            "access_ids": "all"
        }])

def check_is_master_admin(user_dict):
    if not user_dict:
        return False
    return user_dict.get("email", "").strip().lower() == MASTER_ADMIN_EMAIL.lower()

def add_user(email, password, role, access_type="all", access_ids="all", current_user_dict=None):
    if not check_is_master_admin(current_user_dict):
        return False, T("⛔ عذراً، إضافة وتعديل المستخدمين مقتصر حصرياً على الأدمن الرئيسي!", "⛔ Unauthorized: Only Master Admin can add or edit users!")
        
    email_clean = email.strip().lower()
    user_dict = {
        "email": email_clean,
        "password": str(password).strip(),
        "role": role,
        "access_type": access_type,
        "access_ids": str(access_ids)
    }

    if db is not None:
        try:
            doc_ref = db.collection("users").document(email_clean)
            if doc_ref.get().exists:
                return False, T("هذا البريد مسجل بالفعل في قاعدة البيانات!", "Email already registered!")
            doc_ref.set(user_dict)
            return True, T("تم إنشاء الحساب وحفظه في Firebase بنجاح فائق!", "User saved directly to Firebase!")
        except Exception as e:
            return False, f"خطأ Firebase: {e}"

    df = get_users_df()
    if email_clean in df["email"].str.lower().values:
        return False, T("هذا البريد مسجل بالفعل!", "This email already exists!")
    new_user = pd.DataFrame([user_dict])
    df = pd.concat([df, new_user], ignore_index=True)
    try: df.to_csv(USERS_FILE, index=False)
    except Exception: pass
    return True, T("تم حفظ الحساب محلياً.", "Saved locally.")

def update_user_permissions(email, role, access_type, access_ids, new_password=None, current_user_dict=None):
    if not check_is_master_admin(current_user_dict):
        return False, T("⛔ عذراً، تعديل الصلاحيات مقتصر حصرياً على الأدمن الرئيسي!", "⛔ Unauthorized: Only Master Admin can edit permissions!"), None
        
    email_clean = email.strip().lower()
    final_role = "admin" if email_clean == MASTER_ADMIN_EMAIL.lower() else role
    final_acc_type = "all" if email_clean == MASTER_ADMIN_EMAIL.lower() else access_type
    final_acc_ids = "all" if email_clean == MASTER_ADMIN_EMAIL.lower() else str(access_ids)
    
    update_data = {
        "email": email_clean,
        "role": final_role,
        "access_type": final_acc_type,
        "access_ids": final_acc_ids
    }
    if new_password and str(new_password).strip():
        update_data["password"] = str(new_password).strip()

    if db is not None:
        try:
            doc_ref = db.collection("users").document(email_clean)
            doc_ref.set(update_data, merge=True)
            res_dict = doc_ref.get().to_dict()
            return True, T("تم تحديث البيانات وكلمة المرور في Firebase فوراً!", "User updated in Firebase!"), res_dict
        except Exception as e:
            return False, f"خطأ Firebase: {e}", None

    df = get_users_df()
    idx = df[df["email"].str.lower() == email_clean].index
    if not idx.empty:
        df.loc[idx, "role"] = final_role
        df.loc[idx, "access_type"] = final_acc_type
        df.loc[idx, "access_ids"] = final_acc_ids
        if new_password and str(new_password).strip():
            df.loc[idx, "password"] = str(new_password).strip()
        try: df.to_csv(USERS_FILE, index=False)
        except Exception: pass
        return True, T("تم تحديث البيانات محلياً!", "Updated locally!"), df.iloc[idx[0]].to_dict()
    return False, T("المستخدم غير موجود.", "User not found."), None

def delete_user(email, current_user_dict=None):
    if not check_is_master_admin(current_user_dict):
        return False, T("⛔ عذراً، حذف الحسابات مقتصر حصرياً على الأدمن الرئيسي!", "⛔ Unauthorized: Only Master Admin can delete users!")
    if email.strip().lower() == MASTER_ADMIN_EMAIL.lower():
        return False, T("لا يمكن حذف الأدمن الرئيسي!", "Cannot delete master admin!")
        
    email_clean = email.strip().lower()
    if db is not None:
        try:
            db.collection("users").document(email_clean).delete()
            return True, T("تم حذف الحساب من Firebase بنجاح!", "User deleted from Firebase successfully!")
        except Exception as e:
            return False, f"خطأ Firebase: {e}"

    df = get_users_df()
    df = df[df["email"].str.lower() != email_clean]
    try: df.to_csv(USERS_FILE, index=False)
    except Exception: pass
    return True, T("تم حذف الحساب محلياً!", "User deleted locally!")

# ==========================================
# 3. دوال المعالجة والمسافات
# ==========================================
def normalize_id(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    return re.sub(r"\.0+$", "", s)

def parse_yes_no(val, default="Yes"):
    if pd.isna(val): return default
    s = str(val).strip().lower()
    if s in ["", "none", "nan", "null"]: return default
    if s in ["yes", "y", "true", "1", "نعم", "نشط", "مفعل"]: return "Yes"
    if s in ["no", "n", "false", "0", "لا", "غير نشط", "معطل"]: return "No"
    return default

def is_valid_am_name(val):
    if pd.isna(val): return False
    s = str(val).strip()
    if s in ["", "-", "nan", "None", "null", "0"]: return False
    if s.replace(".", "").isdigit(): return False
    return True

def clean_wkt(polygon_str):
    if pd.isna(polygon_str) or not str(polygon_str).strip():
        return None
    s = str(polygon_str).strip()
    s = re.sub(r'^SRID=\d+;', '', s, flags=re.IGNORECASE).strip()
    s = re.sub(r',\s*\)', ')', s)
    s = re.sub(r',\s*\)', ')', s)
    s = re.sub(r'\(\s*,', '(', s)
    s = re.sub(r'\s+', ' ', s)
    return s

def normalize_zone_key(name):
    if not name: return ""
    s = str(name).strip().lower()
    s = re.sub(r'^(al[\s\-_]+|el[\s\-_]+|ال)', '', s)
    s = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', s)
    return s

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def calc_vendor_zone_distance(vid, zone_name, df_v, gdf_a):
    if df_v.empty or gdf_a.empty or not vid or not zone_name:
        return "-"
    v_row = df_v[df_v["clean_vid"].astype(str) == str(vid).strip()]
    if v_row.empty:
        return "-"
    v_lat = v_row.iloc[0].get("lat")
    v_lng = v_row.iloc[0].get("lng")
    if pd.isna(v_lat) or pd.isna(v_lng):
        return "-"
        
    z_clean = str(zone_name).strip().lower()
    z_match = gdf_a[gdf_a["Delivery Location Area Name"].astype(str).str.strip().str.lower() == z_clean]
    if z_match.empty and "norm_key" in gdf_a.columns:
        z_match = gdf_a[gdf_a["norm_key"] == normalize_zone_key(zone_name)]
            
    if z_match.empty:
        return "-"
        
    z_row = z_match.iloc[0]
    z_lat = z_row.get("centroid_lat")
    z_lng = z_row.get("centroid_lng")
    if pd.isna(z_lat) or pd.isna(z_lng):
        try:
            centroid = z_row.geometry.centroid
            z_lat, z_lng = centroid.y, centroid.x
        except Exception:
            return "-"
            
    if pd.isna(z_lat) or pd.isna(z_lng):
        return "-"
        
    dist = haversine_km(float(v_lat), float(v_lng), float(z_lat), float(z_lng))
    return f"{dist:.2f}"

def robust_get_col(df, possible_names):
    if len(df.columns) == 0: return None
    for name in possible_names:
        for col in df.columns:
            if str(name).strip().lower() == str(col).strip().lower():
                return col
    for name in possible_names:
        name_clean = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', str(name)).lower()
        for col in df.columns:
            col_clean = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', str(col)).lower()
            if name_clean == col_clean:
                return col
    for name in possible_names:
        name_clean = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', str(name)).lower()
        if len(name_clean) >= 3:
            for col in df.columns:
                col_clean = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', str(col)).lower()
                if name_clean in col_clean or col_clean in name_clean:
                    return col
    return None

def convert_to_csv_url(url):
    if not isinstance(url, str): return url
    url = url.strip()
    if "output=csv" in url or "export?format=csv" in url: return url
    m_id = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    m_gid = re.search(r"[#&?]gid=([0-9]+)", url)
    if m_id:
        sheet_id = m_id.group(1)
        gid = m_gid.group(1) if m_gid else "0"
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return url

def read_google_sheet_csv(url):
    csv_url = convert_to_csv_url(url)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(csv_url, headers=headers, timeout=15)
        if res.status_code == 200:
            text_sample = res.text[:500].lower()
            if "<!doctype" in text_sample or "<html" in text_sample or "google accounts" in text_sample:
                return pd.DataFrame()
            return pd.read_csv(io.StringIO(res.text))
    except Exception: pass
    try: return pd.read_csv(csv_url)
    except Exception: return pd.DataFrame()

# ==========================================
# 4. جلب وتجهيز البيانات مع كاش 24 ساعة للسرعة الفائقة
# ==========================================
@st.cache_data(ttl=86400) # كاش ذكي لمدة 24 ساعة كاملة لحفظ البيانات بالرامات
def load_data():
    url_vendors = "https://docs.google.com/spreadsheets/d/12SSMW20Two2hRpHOuIXXifweJI82bZpJClhUAWSuYHk/export?format=csv&gid=0"
    url_areas = "https://docs.google.com/spreadsheets/d/1Y3AlqaHjp4nZup6QwOBgl6CT5z3XHjfzpRSx5Yw5byk/export?format=csv&gid=0"
    url_delivery = "https://docs.google.com/spreadsheets/d/1Gh6xnGNn7yx2g-bdIHC4DvHIMzVkOnh3Fdy6AhQtTmM/export?format=csv&gid=540443526"
    url_performance = "https://docs.google.com/spreadsheets/d/1u_VDm8bejb8gpooW7hqSCUNQ8ZqJ-4myQ_cTvqUfRZQ/export?format=csv&gid=0"

    pub_url_vendors = "https://docs.google.com/spreadsheets/d/e/2PACX-1vROpaDpyPadT9VreMa8FCxbBwvfzBxLjkEh8AtLyzQXgbVf3SAheyIjhYexiaVo8LLdjp58Z2DePKZ1/pub?gid=1243657258&single=true&output=csv"
    pub_url_areas = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSKMfgg92gyhtKgILJ_IMknkhC7HdjEnvUGu4ef09pEsQmndf2NtYIGlT9RavgA14zT38NMYNoI4OVt/pub?gid=298729660&single=true&output=csv"
    pub_url_delivery = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR4BDgzbQgwjMgUIl9egw_OzUfT-2NZfQQqGmw6Xzk25NXC6F_8ZQk3JX6xIEkOUgAu7ZDqNe-FnzpY/pub?gid=29074284&single=true&output=csv"

    df_v = read_google_sheet_csv(url_vendors)
    if df_v.empty: df_v = read_google_sheet_csv(pub_url_vendors)

    df_a = read_google_sheet_csv(url_areas)
    if df_a.empty: df_a = read_google_sheet_csv(pub_url_areas)

    df_d = read_google_sheet_csv(url_delivery)
    if df_d.empty: df_d = read_google_sheet_csv(pub_url_delivery)

    df_p = read_google_sheet_csv(url_performance)

    if not df_v.empty:
        vid_col = robust_get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID", "vendor_id"])
        cid_col = robust_get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID", "chain_id"])
        name_col = robust_get_col(df_v, ["Vendor Attributes Vendor Name (English)", "Vendor Name", "Name", "vendor_name"])
        cname_col = robust_get_col(df_v, ["Chain Attributes Chain Name", "Chain Name", "chain_name"])
        city_col = robust_get_col(df_v, ["Vendor Attributes Vendor City", "City", "Vendor City"])

        am_col = None
        for candidate in ["Chain Attributes Latest Chain AM Name", "Latest Chain AM Name", "Vendor Attributes Account Manager", "Account Manager Name", "Account Manager"]:
            for c in df_v.columns:
                if candidate.lower() == str(c).strip().lower():
                    am_col = c
                    break
            if am_col: break
        if not am_col:
            for c in df_v.columns:
                cl = str(c).lower()
                if "chain am name" in cl or "latest chain am" in cl or "account manager" in cl:
                    am_col = c
                    break

        active_col = robust_get_col(df_v, ["Vendor Attributes Is Active (Yes / No)", "Vendor Attributes Is Active", "Is Active", "Active", "IsActive", "is_active", "نشط"])
        hidden_col = robust_get_col(df_v, ["Vendor Attributes Is Hidden (Yes / No)", "Vendor Attributes Is Hidden", "Is Hidden", "Hidden", "IsHidden", "is_hidden", "مخفي"])

        df_v["clean_vid"] = df_v[vid_col].apply(normalize_id) if vid_col else ""
        df_v["clean_cid"] = df_v[cid_col].apply(normalize_id) if cid_col else ""
        df_v["clean_name"] = df_v[name_col].astype(str).str.strip() if name_col else ("Vendor " + df_v["clean_vid"])
        df_v["clean_chain_name"] = df_v[cname_col].astype(str).str.strip() if cname_col else ""
        df_v["clean_city"] = df_v[city_col].astype(str).str.strip() if city_col else ""
        df_v["clean_am"] = df_v[am_col].fillna("").astype(str).str.strip() if am_col else "-"

        df_v["clean_active"] = df_v[active_col].apply(lambda x: parse_yes_no(x, "Yes")) if active_col else "Yes"
        df_v["clean_hidden"] = df_v[hidden_col].apply(lambda x: parse_yes_no(x, "No")) if hidden_col else "No"

        loc_col = robust_get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location", "Coordinates"])
        lat_col = robust_get_col(df_v, ["Latitude", "lat", "Lat"])
        lng_col = robust_get_col(df_v, ["Longitude", "lng", "Lng", "Long", "lon"])

        if loc_col:
            coords = df_v[loc_col].astype(str).str.split(r'[,;]+', expand=True)
            df_v["lat"] = pd.to_numeric(coords[0].str.strip(), errors="coerce")
            df_v["lng"] = pd.to_numeric(coords[1].str.strip(), errors="coerce")
        elif lat_col and lng_col:
            df_v["lat"] = pd.to_numeric(df_v[lat_col], errors="coerce")
            df_v["lng"] = pd.to_numeric(df_v[lng_col], errors="coerce")
        else:
            df_v["lat"] = np.nan
            df_v["lng"] = np.nan

        df_v = df_v[df_v["clean_vid"] != ""].copy()

    if not df_p.empty:
        p_vid_col = robust_get_col(df_p, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
        p_cid_col = robust_get_col(df_p, ["Chain ID", "Chain Id", "ChainID", "chain_id"])

        df_p["clean_vid"] = df_p[p_vid_col].apply(normalize_id) if p_vid_col else ""
        df_p["clean_cid"] = df_p[p_cid_col].apply(normalize_id) if p_cid_col else ""

        col_qc = robust_get_col(df_p, ["QC Net Orders", "Net Orders", "Orders", "QC_Net_Orders"])
        col_fail_ord = robust_get_col(df_p, ["Vendor Net Failed Orders", "Failed Orders", "Net Failed Orders"])
        col_fail_rate = robust_get_col(df_p, ["Vendor Net Fail Rate", "Fail Rate", "Net Fail Rate", "Fail_Rate"])
        col_cr = robust_get_col(df_p, ["Contact Rate", "CR", "Contact_Rate"])
        col_fault_cr = robust_get_col(df_p, ["Vendor Fault Customer Contact Rate", "Vendor Fault CR", "Fault Contact Rate"])

        df_p["qc_orders"] = df_p[col_qc] if col_qc else "-"
        df_p["fail_orders"] = df_p[col_fail_ord] if col_fail_ord else "-"
        df_p["fail_rate"] = df_p[col_fail_rate] if col_fail_rate else "-"
        df_p["contact_rate"] = df_p[col_cr] if col_cr else "-"
        df_p["fault_cr"] = df_p[col_fault_cr] if col_fault_cr else "-"

    if not df_d.empty and not df_v.empty:
        d_vid_col = robust_get_col(df_d, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
        d_cid_col = robust_get_col(df_d, ["Chain ID", "Chain Id", "ChainID", "chain_id"])
        d_zone_col = robust_get_col(df_d, ["Area Name", "Delivery Area Name", "Zone", "Delivery Location Area Name", "Area", "Delivery Zone"])
        d_time_col = robust_get_col(df_d, ["Delivery Time", "Time", "Duration"])
        d_fee_col = robust_get_col(df_d, ["Delivery Fees", "Fee", "Delivery Fee", "Price"])
        d_min_col = robust_get_col(df_d, ["Minimum Amount", "Minimum Order", "Min Order", "Min Amount", "الحد الادنى", "الحد الأدنى"])

        df_d["clean_vid"] = df_d[d_vid_col].apply(normalize_id) if d_vid_col else ""
        df_d["clean_cid"] = df_d[d_cid_col].apply(normalize_id) if d_cid_col else ""
        df_d["clean_zone"] = df_d[d_zone_col].astype(str).str.strip() if d_zone_col else ""
        df_d["clean_time"] = df_d[d_time_col].astype(str).str.strip() if d_time_col else ""
        df_d["clean_fee"] = df_d[d_fee_col].astype(str).str.strip() if d_fee_col else ""
        df_d["clean_min_order"] = df_d[d_min_col].astype(str).str.strip() if d_min_col else "0.0"

        mask_charity = df_d["clean_zone"].str.contains(r"charit|charities", case=False, na=False)
        df_d = df_d[~mask_charity].copy()

    if not df_a.empty:
        poly_col = robust_get_col(df_a, ["Delivery Location Area Polygon", "Polygon", "WKT", "Area Polygon", "geometry", "geom", "the_geom"])
        if poly_col:
            df_a["cleaned_wkt"] = df_a[poly_col].apply(clean_wkt)
            geometries, valid_indices = [], []
            for idx, wkt_str in df_a["cleaned_wkt"].items():
                if pd.notnull(wkt_str):
                    try:
                        geometries.append(wkt.loads(wkt_str))
                        valid_indices.append(idx)
                    except Exception: pass
                        
            if valid_indices:
                gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
                gdf_a["area_size"] = gdf_a["geometry"].area
                area_name_col = robust_get_col(gdf_a, ["Delivery Location Area Name", "Area Name", "Name", "Zone", "Area", "Zone Name"])
                if area_name_col:
                    gdf_a["Delivery Location Area Name"] = gdf_a[area_name_col].astype(str).str.strip()
                    mask_exclude = gdf_a["Delivery Location Area Name"].str.contains(r"mcd|mcdonald|charit|charities", case=False, na=False)
                    gdf_a = gdf_a[~mask_exclude].copy()
                    
                gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
                centroids = gdf_a.geometry.centroid
                gdf_a["centroid_lat"] = centroids.y
                gdf_a["centroid_lng"] = centroids.x
                gdf_a["norm_key"] = gdf_a["Delivery Location Area Name"].apply(normalize_zone_key)
                gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.0008, preserve_topology=True)
            else: gdf_a = gpd.GeoDataFrame()
        else: gdf_a = gpd.GeoDataFrame()
    else: gdf_a = gpd.GeoDataFrame()

    return df_v, gdf_a, df_d, df_p

df_vendors, gdf_areas, df_delivery, df_performance = load_data()

def get_user_vendors(user_dict, df_v):
    if df_v.empty:
        return pd.DataFrame(columns=["clean_vid", "clean_cid", "clean_name", "clean_chain_name", "clean_city", "clean_am", "clean_active", "clean_hidden", "lat", "lng"])
    access_type = user_dict.get("access_type", "all")
    access_ids_raw = str(user_dict.get("access_ids", "all")).split(",")
    allowed_ids = [normalize_id(x) for x in access_ids_raw if x.strip()]
    
    if access_type == "all" or "all" in allowed_ids:
        return df_v.copy()
    elif access_type == "Chain ID":
        return df_v[df_v["clean_cid"].isin(allowed_ids)].copy()
    elif access_type == "Vendor ID":
        return df_v[df_v["clean_vid"].isin(allowed_ids)].copy()
    return df_v.copy()

def get_performance_kpis(df_disp, df_p):
    cnt_total = len(df_disp)
    cnt_active = len(df_disp[df_disp["clean_active"] == "Yes"]) if ("clean_active" in df_disp.columns and not df_disp.empty) else 0
    cnt_inactive = cnt_total - cnt_active
    
    if df_disp.empty or df_p.empty:
        return cnt_total, cnt_active, cnt_inactive, 0, 0, "0.0%"
        
    vids = set(df_disp["clean_vid"].dropna().unique())
    matched = df_p[df_p["clean_vid"].isin(vids)].copy()
    
    if matched.empty:
        cids = set(df_disp["clean_cid"].dropna().unique())
        matched = df_p[df_p["clean_cid"].isin(cids)].copy()
        
    if matched.empty:
        return cnt_total, cnt_active, cnt_inactive, 0, 0, "0.0%"
        
    def to_num(val):
        if pd.isna(val): return 0.0
        s = str(val).strip().replace(",", "").replace("%", "")
        try: return float(s)
        except: return 0.0

    matched["qc_num"] = matched["qc_orders"].apply(to_num)
    matched["fail_num"] = matched["fail_orders"].apply(to_num)
    
    tot_orders = int(matched["qc_num"].sum())
    tot_failed = int(matched["fail_num"].sum())
    
    if tot_orders > 0:
        overall_rate = (tot_failed / tot_orders) * 100
        rate_str = f"{overall_rate:.2f}%"
    else:
        rates = matched["fail_rate"].apply(to_num)
        pos_rates = rates[rates > 0]
        rate_str = f"{pos_rates.mean():.2f}%" if not pos_rates.empty else "0.0%"
        
    return cnt_total, cnt_active, cnt_inactive, tot_orders, tot_failed, rate_str

def get_vendor_and_chain_perf(vid, cid, df_p):
    v_perf, c_perf = {}, {}
    if df_p.empty: return v_perf, c_perf
    
    v_match = df_p[df_p["clean_vid"] == str(vid)]
    if not v_match.empty: v_perf = v_match.iloc[0].to_dict()
        
    if cid:
        c_match = df_p[df_p["clean_cid"] == str(cid)]
        if not c_match.empty:
            c_summary = c_match[c_match["clean_vid"] == ""]
            if not c_summary.empty:
                c_perf = c_summary.iloc[0].to_dict()
            else:
                try:
                    qc_sum = pd.to_numeric(c_match["qc_orders"], errors="coerce").sum()
                    fail_sum = pd.to_numeric(c_match["fail_orders"], errors="coerce").sum()
                    c_perf = {
                        "qc_orders": int(qc_sum) if pd.notna(qc_sum) else "-",
                        "fail_orders": int(fail_sum) if pd.notna(fail_sum) else "-",
                        "fail_rate": f"{(fail_sum / qc_sum * 100):.1f}%" if (qc_sum and qc_sum > 0) else "-",
                        "contact_rate": c_match["contact_rate"].iloc[0] if "contact_rate" in c_match.columns else "-",
                        "fault_cr": c_match["fault_cr"].iloc[0] if "fault_cr" in c_match.columns else "-"
                    }
                except:
                    c_perf = c_match.iloc[0].to_dict()
    return v_perf, c_perf

# ==========================================
# نظام حفظ واسترجاع الطلبات عبر Firestore
# ==========================================
def save_detailed_request(vendor_id, vendor_name, edited_df):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_records = []
    
    for _, r in edited_df.iterrows():
        z_name = str(r.get("Zone", "")).strip()
        classification = str(r.get("Classification", "Vendor Zone Update")).strip()
        action = str(r.get("Action", "Active")).strip()
        
        dist_val = str(r.get("Distance (km)", "-")).strip()
        if dist_val in ["-", "", "nan", "None"]:
            dist_val = calc_vendor_zone_distance(vendor_id, z_name, df_vendors, gdf_areas)
            
        d_time = str(r.get("Delivery Time", "45 mins")).strip()
        try: fee_val = float(r.get("Delivery Fees") or 25.0)
        except: fee_val = 25.0
        try: min_val = float(r.get("Minimum Order Amount") or 0.0)
        except: min_val = 0.0
        
        row_dict = {
            "Date": date_str,
            "Vendor ID": str(vendor_id),
            "Vendor Name": str(vendor_name),
            "Zone": z_name,
            "Classification": classification,
            "Action": action,
            "Distance (km)": dist_val,
            "Delivery Time": d_time,
            "Delivery Fees": fee_val,
            "Minimum Order Amount": min_val,
            "Final_Status": str(r.get("Final_Status", "Active (Existing)")).strip(),
            "Status": "Pending"
        }
        new_records.append(row_dict)

    if db is not None:
        try:
            batch = db.batch()
            coll = db.collection("pricing_requests")
            for rec in new_records:
                doc_ref = coll.document()
                batch.set(doc_ref, rec)
            batch.commit()
        except Exception: pass

    if "session_requests_list" not in st.session_state:
        st.session_state["session_requests_list"] = []
    st.session_state["session_requests_list"].extend(new_records)
    
    try:
        save_df = pd.DataFrame(new_records, columns=REQUESTS_COLUMNS)
        save_df.to_csv(REQUESTS_FILE, mode="a", header=False, index=False)
    except Exception: pass

    return pd.DataFrame(new_records, columns=REQUESTS_COLUMNS)

def get_all_requests_df():
    if db is not None:
        try:
            docs = db.collection("pricing_requests").stream()
            records = [d.to_dict() for d in docs]
            if records:
                df = pd.DataFrame(records)
                for c in REQUESTS_COLUMNS:
                    if c not in df.columns: df[c] = ""
                return df[REQUESTS_COLUMNS].sort_values(by="Date", ascending=False)
        except Exception: pass

    file_records = []
    if os.path.exists(REQUESTS_FILE):
        try:
            fdf = pd.read_csv(REQUESTS_FILE, on_bad_lines='skip')
            if not fdf.empty and "Zone" in fdf.columns:
                file_records = fdf.to_dict('records')
        except Exception: pass

    mem_records = st.session_state.get("session_requests_list", [])
    all_recs = file_records + mem_records
    if not all_recs:
        return pd.DataFrame(columns=REQUESTS_COLUMNS)
    return pd.DataFrame(all_recs, columns=REQUESTS_COLUMNS)

def send_request_emails(vendor_id, vendor_name, records_df, submitted_by_email):
    smtp_cfg = load_smtp_config()
    sender_email = smtp_cfg.get("sender_email", "").strip()
    sender_password = smtp_cfg.get("sender_password", "").strip()
    smtp_server = smtp_cfg.get("server", "smtp.gmail.com")
    smtp_port = int(smtp_cfg.get("port", 587))
    admin_recipient = smtp_cfg.get("admin_email", MASTER_ADMIN_EMAIL)

    if not sender_email or not sender_password:
        return False, "⚠️ تم حفظ الطلب، ولكن لم يتم إرسال الإيميل لعدم ضبط بيانات الراسل."

    try:
        date_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            records_df.to_excel(writer, index=False, sheet_name=f"Vendor_{str(vendor_id)[:10]}")
        excel_bytes = excel_buffer.getvalue()

        safe_name = re.sub(r'[^\w\s-]', '', str(vendor_name)).strip().replace(" ", "_")
        filename = f"Pricing_Request_{vendor_id}_{safe_name}.xlsx"

        total_count = len(records_df)
        add_count = len(records_df[records_df["Action"].astype(str).str.contains("نشط|Active|New", case=False)])
        edit_count = len(records_df[records_df["Action"].astype(str).str.contains("Edit|تعديل", case=False)])
        deact_count = len(records_df[records_df["Action"].astype(str).str.contains("إلغاء|Deactivate", case=False)])

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=12)
        else:
            server = smtplib.SMTP(server_host, smtp_port, timeout=12)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(sender_email, sender_password)

        recipients_status = []

        admin_subject = f"🔔 [Action Required] Pricing & Coverage Request - {vendor_name} (ID: {vendor_id})"
        admin_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; }}
                .card {{ max-width: 620px; margin: auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
                .header {{ background: linear-gradient(135deg, #ff5a00 0%, #ff7700 100%); color: #ffffff; padding: 24px 28px; text-align: left; }}
                .header h1 {{ margin: 0; font-size: 20px; font-weight: 800; }}
                .header p {{ margin: 6px 0 0 0; font-size: 13px; opacity: 0.9; letter-spacing: 0.3px; }}
                .content {{ padding: 28px; line-height: 1.6; text-align: left; }}
                .box {{ background: #fff7ed; border-left: 4px solid #ff5a00; padding: 14px 18px; border-radius: 6px; margin: 18px 0; }}
                .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                .table th, .table td {{ padding: 10px 14px; border-bottom: 1px solid #edf2f7; font-size: 13px; text-align: left; }}
                .table th {{ background: #f8fafc; color: #64748b; font-weight: 600; width: 50%; }}
                .notice {{ background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; padding: 12px 16px; border-radius: 8px; font-size: 13px; margin: 20px 0; }}
                .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center; padding: 14px; font-size: 11.5px; color: #94a3b8; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">
                    <h1>💊 New Pricing & Coverage Submission</h1>
                    <p>Talabat Pharmacy Operations & Logistics Platform</p>
                </div>
                <div class="content">
                    <p style="font-size: 15px; margin-top: 0;">Dear <b>Mahmoud Alaa</b>,</p>
                    <p>A new delivery zone & pricing configuration has just been submitted via the <b>Vendor Portal</b>. Please find the operational details below:</p>
                    
                    <div class="box">
                        <div style="font-size: 16px; font-weight: 800; color: #ea580c;">🏬 {vendor_name}</div>
                        <div style="font-size: 13px; color: #334155; margin-top: 4px;"><b>Vendor ID:</b> <code>{vendor_id}</code></div>
                        <div style="font-size: 13px; color: #334155; margin-top: 2px;"><b>Submitted By:</b> {submitted_by_email}</div>
                        <div style="font-size: 12px; color: #64748b; margin-top: 2px;">🕒 <b>Timestamp:</b> {date_str}</div>
                    </div>

                    <h4 style="margin: 22px 0 8px 0; font-size: 14px; color: #0f172a;">📊 Submission Summary:</h4>
                    <table class="table">
                        <tr><th>Total Zones in Request</th><td><b>{total_count}</b> zones</td></tr>
                        <tr><th>Newly Added Zones</th><td style="color:#16a34a; font-weight:bold;">+{add_count}</td></tr>
                        <tr><th>Updated Zones (Fee / SLA / Min Order)</th><td style="color:#ea580c; font-weight:bold;">{edit_count}</td></tr>
                        <tr><th>Deactivated Zones</th><td style="color:#dc2626; font-weight:bold;">-{deact_count}</td></tr>
                    </table>

                    <div class="notice">
                        📎 <b>Attachment:</b> Complete Excel workbook <code>{filename}</code> is attached containing exact polygon coordinates, computed distance (km), delivery fees, delivery SLAs, and Minimum Order Amount.
                    </div>
                </div>
                <div class="footer">
                    Automated System Notification • Talabat Logistics & Operations Engine
                </div>
            </div>
        </body>
        </html>
        """

        msg_admin = MIMEMultipart()
        msg_admin['Subject'] = admin_subject
        msg_admin['From'] = f"Talabat Operations Hub <{sender_email}>"
        msg_admin['To'] = admin_recipient
        msg_admin.attach(MIMEText(admin_html, 'html', 'utf-8'))

        part_admin = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        part_admin.set_payload(excel_bytes)
        encoders.encode_base64(part_admin)
        part_admin.add_header('Content-Disposition', f'attachment; filename="{filename}"')
        msg_admin.attach(part_admin)

        server.sendmail(sender_email, [admin_recipient], msg_admin.as_string())
        recipients_status.append(admin_recipient)

        if submitted_by_email and str(submitted_by_email).strip() and "@" in str(submitted_by_email):
            vendor_subject = f"✅ تم استلام طلبكم بنجاح: تحديث أسعار وتغطية - {vendor_name} (ID: {vendor_id})"
            vendor_html = f"""
            <!DOCTYPE html>
            <html dir="rtl" lang="ar">
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Tahoma, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b; direction: rtl; text-align: right; }}
                    .card {{ max-width: 620px; margin: auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.06); border: 1px solid #e2e8f0; }}
                    .header {{ background: linear-gradient(135deg, #ff5a00 0%, #ff7700 100%); color: #ffffff; padding: 24px 28px; text-align: center; }}
                    .header h1 {{ margin: 0; font-size: 21px; font-weight: 800; }}
                    .header p {{ margin: 6px 0 0 0; font-size: 13px; opacity: 0.9; letter-spacing: 0.3px; }}
                    .content {{ padding: 28px; line-height: 1.7; }}
                    .box {{ background: #f0fdf4; border-right: 4px solid #16a34a; padding: 14px 18px; border-radius: 6px; margin: 18px 0; }}
                    .table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
                    .table th, .table td {{ padding: 10px 14px; border-bottom: 1px solid #edf2f7; font-size: 13px; text-align: right; }}
                    .table th {{ background: #f8fafc; color: #64748b; font-weight: 600; width: 50%; }}
                    .notice {{ background: #eff6ff; border: 1px solid #bfdbfe; color: #1e40af; padding: 12px 16px; border-radius: 8px; font-size: 13px; margin: 20px 0; }}
                    .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center; padding: 14px; font-size: 11.5px; color: #94a3b8; }}
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="header">
                        <h1>✅ تم استلام طلبكم بنجاح</h1>
                        <p>بوابة شركاء وخدمات صيدليات طلبات • Talabat Vendor Portal</p>
                    </div>
                    <div class="content">
                        <p style="font-size: 15px; margin-top: 0;">عزيزنا شريك النجاح / <b>فريق {vendor_name}</b>،</p>
                        <p>نشكركم على استخدام بوابة الفيندور. نود إحاطتكم بأنه تم استلام وتوثيق طلب تعديل مناطق التغطية وأسعار التوصيل والحد الأدنى للطلب بنجاح، وجارٍ مراجعته وتدقيقه من قبل فريق العمليات واللوجستيات.</p>
                        
                        <div class="box">
                            <div style="font-size: 16px; font-weight: 800; color: #15803d;">🏬 {vendor_name}</div>
                            <div style="font-size: 13px; color: #334155; margin-top: 4px;"><b>كود الفرع (Vendor ID):</b> <code>{vendor_id}</code></div>
                            <div style="font-size: 12px; color: #64748b; margin-top: 2px;">🕒 <b>تاريخ ووقت الإرسال:</b> {date_str}</div>
                        </div>

                        <h4 style="margin: 22px 0 8px 0; font-size: 14px; color: #0f172a;">📋 ملخص التعديلات المرسلة في هذا الطلب:</h4>
                        <table class="table">
                            <tr><th>إجمالي المناطق في الطلب</th><td><b>{total_count}</b> مناطق</td></tr>
                            <tr><th>مناطق جديدة مضافة</th><td style="color:#16a34a; font-weight:bold;">+{add_count} منطقة</td></tr>
                            <tr><th>مناطق تم تعديل سعرها أو وقتها أو حدها الأدنى</th><td style="color:#ea580c; font-weight:bold;">{edit_count} منطقة</td></tr>
                            <tr><th>مناطق ملغاة التفعيل</th><td style="color:#dc2626; font-weight:bold;">-{deact_count} منطقة</td></tr>
                        </table>

                        <div class="notice">
                            📎 <b>نسخة من طلبكم:</b> مرفق بهذه الرسالة ملف إكسيل كامل <code>{filename}</code> يتضمن كافة تفاصيل المناطق التي قمتم بتعديلها مع المسافات المحسوبة وأوقات ورسوم التوصيل والحد الأدنى للطلب المقترح للاحتفاظ بها في سجلاتكم.
                        </div>
                    </div>
                    <div class="footer">
                        فريق دعم شركاء وعمليات صيدليات طلبات • جمهورية مصر العربية
                    </div>
                </div>
            </body>
            </html>
            """

            msg_vendor = MIMEMultipart()
            msg_vendor['Subject'] = vendor_subject
            msg_vendor['From'] = f"Talabat Vendor Portal <{sender_email}>"
            msg_vendor['To'] = submitted_by_email
            msg_vendor.attach(MIMEText(vendor_html, 'html', 'utf-8'))

            part_vendor = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            part_vendor.set_payload(excel_bytes)
            encoders.encode_base64(part_vendor)
            part_vendor.add_header('Content-Disposition', f'attachment; filename="{filename}"')
            msg_vendor.attach(part_vendor)

            if str(submitted_by_email).lower() != admin_recipient.lower():
                server.sendmail(sender_email, [submitted_by_email], msg_vendor.as_string())
                recipients_status.append(submitted_by_email)

        server.quit()
        return True, "تم الإرسال بنجاح"
    except Exception as e:
        return False, f"فشل الإرسال: {e}"

def build_zone_popup_card(area_name, info_list):
    if not info_list:
        return (
            "<div style='font-family: Arial, sans-serif; font-size: 10.5px; width: 200px; padding: 3px; direction: rtl; text-align: right;'>"
            + "<b style='color: #ff5a00;'>📍 " + str(area_name) + "</b><br>"
            + "<span style='color: #6c757d; font-size: 9.5px;'>منطقة عامة (غير مغطاة حالياً)</span>"
            + "</div>"
        )
    
    branch_count = len(info_list)
    parts = [
        "<div style='font-family: Arial, sans-serif; width: 255px; max-height: 175px; overflow-y: auto; padding: 2px; direction: rtl; text-align: right;'>",
        "<div style='position: sticky; top: 0; background: #ffffff; padding-bottom: 3px; border-bottom: 1.5px solid #ff5a00; margin-bottom: 4px; z-index: 10;'>",
        "<b style='color: #ff5a00; font-size: 11.5px;'>📍 " + str(area_name) + "</b> <span style='color: #198754; font-size: 9.5px; font-weight: bold;'>(" + str(branch_count) + " فروع)</span>",
        "</div>",
        "<div style='display: flex; flex-direction: column; gap: 3px;'>"
    ]
    for b in info_list:
        b_name = b.get("name", "")
        b_hex = b.get("hex", "#28a745")
        b_time = b.get("time", "-")
        b_fee = b.get("fee", "-")
        b_min = b.get("min_order", "-")
        parts.append(
            "<div style='border-right: 3px solid " + str(b_hex) + "; padding: 2px 5px; background: #f8f9fa; border-radius: 3px; font-size: 10px; line-height: 1.25;'>"
            + "<b style='color: #212529;'>" + str(b_name) + "</b><br>"
            + "<span style='color: #6c757d; font-size: 9px;'>⏱️ " + str(b_time) + " | 💵 " + str(b_fee) + " EGP | 🛒 أدنى طلب: " + str(b_min) + " EGP</span>"
            + "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)

def build_vendor_popup_html(v_row, df_delivery, df_p):
    v_id = str(v_row.get("clean_vid", ""))
    c_id = str(v_row.get("clean_cid", ""))
    v_name = v_row.get("clean_name", "")
    c_name = v_row.get("clean_chain_name", "")
    v_city = v_row.get("clean_city", "")
    v_am = v_row.get("clean_am", "-")
    is_act = v_row.get("clean_active", "Yes")
    is_hid = v_row.get("clean_hidden", "No")

    status_badge = "<span style='color:#198754; font-weight:bold;'>🟢 " + T("نشط", "Active") + "</span>" if is_act == "Yes" else "<span style='color:#dc3545; font-weight:bold;'>🔴 " + T("غير نشط", "Inactive") + "</span>"
    hidden_badge = (" | <span style='color:#fd7e14; font-weight:bold;'>👁️ " + T("مخفي", "Hidden") + "</span>") if is_hid == "Yes" else ""

    v_perf, _ = get_vendor_and_chain_perf(v_id, c_id, df_p)

    match_d = pd.DataFrame()
    if not df_delivery.empty and "clean_vid" in df_delivery.columns:
        match_d = df_delivery[df_delivery["clean_vid"] == v_id]

    html = f"""<div style='font-family: Arial, sans-serif; width: 280px; font-size: 11px;'>
<h4 style='margin:0 0 4px 0; color:#ff5a00; font-size: 12.5px;'>💊 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code> | <b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>{T("المدينة", "City")}:</b> {v_city} | <b>AM:</b> <b>{v_am}</b><br>
<b>{T("الحالة", "Status")}:</b> {status_badge}{hidden_badge}<br>
<hr style='margin:5px 0; border:0; border-top:1px solid #ddd;'>"""

    if v_perf:
        html += f"""<div style='background:#f8f9fa; border:1px solid #dee2e6; border-radius:4px; padding:5px; margin-bottom:5px;'>
<b style='color:#ff5a00; font-size: 11px;'>📊 {T("مؤشرات الأداء", "Performance")}:</b>
<table style='width:100%; font-size:10.5px; margin-top:2px;'>
<tr><td><b>QC Net Orders:</b></td><td style='text-align:right;'><b>{v_perf.get('qc_orders', '-')}</b></td></tr>
<tr><td><b>Failed Orders:</b></td><td style='text-align:right;'>{v_perf.get('fail_orders', '-')} ({v_perf.get('fail_rate', '-')})</td></tr>
<tr><td><b>Contact Rate:</b></td><td style='text-align:right;'>{v_perf.get('contact_rate', '-')}</td></tr>
<tr><td><b>Fault Contact Rate:</b></td><td style='text-align:right;'>{v_perf.get('fault_cr', '-')}</td></tr>
</table></div>"""

    if not match_d.empty and "clean_zone" in match_d.columns:
        zone_count = len(match_d["clean_zone"].dropna().unique())
        html += f"<b style='color:#198754; font-size: 11px;'>🛵 {T('مناطق التوصيل', 'Delivery Zones')} ({zone_count}):</b>"
        html += "<div style='max-height:100px; overflow-y:auto; margin-top:3px; border:1px solid #dee2e6; border-radius:4px;'>"
        html += "<table style='width:100%; font-size:10px; border-collapse:collapse;'>"
        html += f"<tr style='background:#f8f9fa; text-align:left; position:sticky; top:0;'><th style='padding:2px; border-bottom:1px solid #ddd;'>{T('المنطقة', 'Zone')}</th><th style='padding:2px; border-bottom:1px solid #ddd;'>{T('الوقت', 'Time')}</th><th style='padding:2px; border-bottom:1px solid #ddd;'>{T('السعر', 'Fee')}</th></tr>"
        for _, r in match_d.iterrows():
            z = r.get("clean_zone", "")
            t = r.get("clean_time", "-")
            f = r.get("clean_fee", "-")
            if z:
                html += f"<tr style='border-bottom:1px solid #f1f1f1;'><td style='padding:2px;'>{z}</td><td style='padding:2px;'>{t}</td><td style='padding:2px;'>{f}</td></tr>"
        html += "</table></div>"
    else:
        html += f"<div style='color:#6c757d; font-size:10px; margin-top:3px;'>{T('لا توجد مناطق توصيل مخصصة لهذا الفرع.', 'No dedicated delivery zones.')}</div>"

    html += "</div>"
    return html

def extract_clicked_zone_direct(mcd, pa_gdf, all_zones_list):
    if not mcd:
        return None, None
        
    obj = mcd.get("last_object_clicked")
    if obj and isinstance(obj, dict):
        props = obj.get("properties") or {}
        poly_name = props.get("Delivery Location Area Name") or props.get("name")
        if poly_name and poly_name in all_zones_list:
            sig = f"obj_{poly_name}_{obj.get('lat')}_{obj.get('lng')}"
            return poly_name, sig

        lat, lng = obj.get("lat"), obj.get("lng")
        if lat is not None and lng is not None and pa_gdf is not None and not pa_gdf.empty:
            pt = Point(lng, lat)
            matching = pa_gdf[pa_gdf.geometry.contains(pt)]
            if not matching.empty:
                smallest = matching.sort_values(by="area_size", ascending=True).iloc[0] if "area_size" in matching.columns else matching.iloc[0]
                poly_name = smallest["Delivery Location Area Name"]
                sig = f"pt_{poly_name}_{lat}_{lng}"
                return poly_name, sig

    return None, None

# ==========================================
# 5. شاشة تسجيل الدخول المطورة كبوابة داشبورد متكاملة
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["current_user"] = None

if not st.session_state["logged_in"]:
    top_c1, top_c2 = st.columns([8, 2])
    with top_c1:
        st.markdown("""
        <div style="display: flex; align-items: center; gap: 10px; padding: 5px 0;">
            <span style="font-size: 24px;">💊</span>
            <span style="font-weight: 800; font-size: 16px; color: #ff5a00; letter-spacing: 0.5px;">TALABAT OPERATIONS</span>
            <span style="color: #6e7681;">|</span>
            <span style="font-size: 13px; color: #8b949e;">Pharmacy & Geospatial Zones Platform</span>
        </div>
        """, unsafe_allow_html=True)
    with top_c2:
        lang_choice = st.radio(
            "Language",
            options=["العربية", "English"],
            index=0 if st.session_state["lang"] == "ar" else 1,
            horizontal=True,
            label_visibility="collapsed",
            key="login_lang_toggle"
        )
        new_lang = "ar" if lang_choice == "العربية" else "en"
        if new_lang != st.session_state["lang"]:
            st.session_state["lang"] = new_lang
            st.rerun()

    st.markdown("<hr style='margin: 10px 0 25px 0; border: 0; border-top: 1px solid rgba(255,255,255,0.08);'>", unsafe_allow_html=True)

    col_hero, col_card = st.columns([1.3, 1.0], gap="large")

    with col_hero:
        st.markdown(f"""
        <div style="padding: 10px 5px;">
            <div style="display: inline-block; background: rgba(255, 90, 0, 0.15); color: #ff5a00; border: 1px solid rgba(255, 90, 0, 0.3); padding: 4px 12px; border-radius: 20px; font-size: 11px; font-weight: 700; margin-bottom: 12px;">
                ⚡ {T("المنصة الموحدة لمحاكاة العمليات والتسعير", "Unified Logistics & Pricing Engine")}
            </div>
            <h1 style="font-size: 32px; font-weight: 900; line-height: 1.25; margin-bottom: 24px; color: #ffffff;">
                {T("لوحة تحكم الصيدليات ومناطق التغطية الجغرافية", "Pharmacy Operations & Zones Management Dashboard")}
            </h1>
        </div>
        """, unsafe_allow_html=True)

        kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
        with kpi_c1:
            st.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 90, 0, 0.2); border-top: 3px solid #ff5a00; border-radius: 12px; padding: 16px 12px; text-align: center;">
                <div style="font-size: 22px; font-weight: 900; color: #ff5a00;">1,200+</div>
                <div style="font-size: 12px; font-weight: 700; color: #c9d1d9; margin-top: 4px;">{T("مضلع جغرافي", "Geospatial Zones")}</div>
                <div style="font-size: 10.5px; color: #8b949e; margin-top: 2px;">{T("خرائط دقيقة لحظية", "Polygons simulator")}</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_c2:
            st.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 90, 0, 0.2); border-top: 3px solid #28a745; border-radius: 12px; padding: 16px 12px; text-align: center;">
                <div style="font-size: 22px; font-weight: 900; color: #28a745;">400+</div>
                <div style="font-size: 12px; font-weight: 700; color: #c9d1d9; margin-top: 4px;">{T("فرع وسلسلة صيدليات", "Pharmacy Branches")}</div>
                <div style="font-size: 10.5px; color: #8b949e; margin-top: 2px;">{T("تغطية شاملة للمحافظات", "Nationwide coverage")}</div>
            </div>
            """, unsafe_allow_html=True)
        with kpi_c3:
            st.markdown(f"""
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 90, 0, 0.2); border-top: 3px solid #ff7700; border-radius: 12px; padding: 16px 12px; text-align: center;">
                <div style="font-size: 22px; font-weight: 900; color: #ff7700;">Live GPS</div>
                <div style="font-size: 12px; font-weight: 700; color: #c9d1d9; margin-top: 4px;">{T("حساب المسافات بدقة", "Distance Engine")}</div>
                <div style="font-size: 10.5px; color: #8b949e; margin-top: 2px;">{T("تعديل فوري وسريع", "Haversine & Edit tag")}</div>
            </div>
            """, unsafe_allow_html=True)

    with col_card:
        with st.form("login_form"):
            st.markdown(f"""
            <div style="text-align: center; margin-bottom: 20px;">
                <div style="width: 52px; height: 52px; background: rgba(255, 90, 0, 0.15); border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 10px; border: 1px solid rgba(255, 90, 0, 0.3);">
                    <span style="font-size: 24px;">🔐</span>
                </div>
                <h3 style="margin: 0; font-size: 19px; font-weight: 800; color: #ffffff;">
                    {T("تسجيل الدخول للنظام", "Portal Access Login")}
                </h3>
                <p style="margin: 4px 0 0 0; font-size: 12px; color: #8b949e;">
                    {T("أدخل البريد الإلكتروني وكلمة المرور للمتابعة", "Enter corporate credentials to access dashboard")}
                </p>
            </div>
            """, unsafe_allow_html=True)

            email_input = st.text_input(
                T("البريد الإلكتروني (Email):", "Email Address:"),
                placeholder="name@talabat.com"
            ).strip().lower()

            password_input = st.text_input(
                T("كلمة المرور (Password):", "Password:"),
                type="password",
                placeholder="••••••••"
            ).strip()

            st.write("")
            login_btn = st.form_submit_button(
                T("🚀 الدخول إلى الداشبورد (Enter Dashboard)", "🚀 Enter Dashboard"),
                type="primary",
                use_container_width=True
            )

            if login_btn:
                users_df = get_users_df()
                match = users_df[(users_df["email"].str.lower() == email_input) & (users_df["password"].astype(str) == password_input)]

                if not match.empty:
                    user_row = match.iloc[0].to_dict()
                    st.session_state["logged_in"] = True
                    st.session_state["current_user"] = user_row
                    st.success(T(f"تم تسجيل الدخول بنجاح كـ {user_row['role']}!", f"Logged in successfully as {user_row['role']}!"))
                    st.rerun()
                else:
                    st.error(T("❌ البريد الإلكتروني أو كلمة المرور غير صحيحة.", "❌ Invalid email or password."))

        st.markdown(f"""
        <div style="text-align: center; margin-top: 15px; font-size: 11px; color: #6e7681;">
            🔒 {T("نظام مشفر ومحمي • Talabat Q-Commerce & Logistics Platform", "Encrypted & Authorized • Talabat Logistics Platform")}
        </div>
        """, unsafe_allow_html=True)

    st.stop()

current_user = st.session_state["current_user"]
is_admin = current_user["role"] == "admin"
is_master_admin = check_is_master_admin(current_user)

user_vendors = get_user_vendors(current_user, df_vendors)
total_user_branches = len(user_vendors) if not user_vendors.empty else 0
active_user_branches = len(user_vendors[user_vendors["clean_active"] == "Yes"]) if (not user_vendors.empty and "clean_active" in user_vendors.columns) else 0
inactive_user_branches = total_user_branches - active_user_branches
hidden_user_branches = len(user_vendors[user_vendors["clean_hidden"] == "Yes"]) if (not user_vendors.empty and "clean_hidden" in user_vendors.columns) else 0

with st.sidebar:
    lang_choice = st.radio(
        "🌐 Language / اللغة",
        options=["العربية", "English"],
        index=0 if st.session_state["lang"] == "ar" else 1,
        horizontal=True
    )
    new_lang = "ar" if lang_choice == "العربية" else "en"
    if new_lang != st.session_state["lang"]:
        st.session_state["lang"] = new_lang
        st.rerun()

    st.markdown("---")
    st.write(f"👤 **{T('المستخدم', 'User')}:** `{current_user['email']}`")
    role_badge = "👑 MASTER ADMIN" if is_master_admin else current_user['role'].upper()
    st.write(f"🛡️ **{T('الصلاحية', 'Role')}:** `{role_badge}`")
    if current_user.get("access_type") != "all":
        st.write(f"📌 **{T('نطاق الربط', 'Scope')}:** `{current_user['access_type']}`")
    
    st.markdown("""
    <div style="background: rgba(255, 90, 0, 0.15); border: 1px solid #ff5a00; padding: 4px 8px; border-radius: 6px; font-size: 11px; color: #ff5a00; font-weight: bold; text-align: center; margin: 8px 0;">
        ⚡ Firebase Firestore Live Cloud
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    
    st.metric(
        label=T("🏬 الفروع التابعة لك", "Your Assigned Branches"),
        value=f"{total_user_branches:,}",
        delta=f"🟢 {active_user_branches} " + T("نشط", "Active") if total_user_branches > 0 else "0"
    )
    st.caption(T(
        f"📊 تفاصيل: نشط: {active_user_branches} | غير نشط: {inactive_user_branches} | مخفي: {hidden_user_branches}",
        f"📊 Details: Active: {active_user_branches} | Inactive: {inactive_user_branches} | Hidden: {hidden_user_branches}"
    ))
    
    if is_admin:
        st.metric(T("🗺️ إجمالي المناطق الجغرافية", "Total Geographic Zones"), f"{len(gdf_areas):,}")

    if "last_sync_time" not in st.session_state:
        st.session_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        
    if st.button(T("🔄 مزامنة وتحديث البيانات الآن", "🔄 Sync Live Data Now"), use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        st.rerun()
        
    st.caption(f"🕒 **{T('تاريخ آخر مزامنة', 'Last Synced')}:** `{st.session_state['last_sync_time']}`")
    st.markdown("---")
    if st.button(T("🚪 تسجيل الخروج (Logout)", "🚪 Logout"), use_container_width=True):
        st.session_state.clear()
        st.rerun()

if is_master_admin:
    tab1, tab2, tab3, tab4 = st.tabs([
        T("🗺️ Overview Map", "🗺️ Overview Map"),
        T("🛒 Vendor Portal", "🛒 Vendor Portal"),
        T("📥 Incoming Requests", "📥 Incoming Requests"),
        T("👥 Users & Access", "👥 Users & Access")
    ])
elif is_admin:
    tab1, tab2, tab3 = st.tabs([
        T("🗺️ Overview Map", "🗺️ Overview Map"),
        T("🛒 Vendor Portal", "🛒 Vendor Portal"),
        T("📥 Incoming Requests", "📥 Incoming Requests")
    ])
else:
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map
# ==========================================
if is_admin:
    with tab1:
        st.header(T("🗺️ خريطة الإدارة العامة والمحاكاة", "🗺️ Admin Overview & Simulation Map"))
        
        map_active = st.toggle(T("⚡ تفعيل خريطة الإدارة العامة (Admin Map)", "⚡ Activate Admin Map"), value=False, key="toggle_admin_map")
        
        if not map_active:
            st.info(T(
                "⏸️ خريطة المراقبة العامة معطلة لتوفير أقصى سرعة لبوابة الفيندورز. فَعِّل المفتاح أعلاه عند الحاجة لاستعراض التغطية العامة.",
                "⏸️ Admin overview map is disabled to maximize Vendor Portal speed. Toggle switch above when you need to view the map."
            ))
        else:
            if "admin_filter_ver" not in st.session_state:
                st.session_state["admin_filter_ver"] = 0
            ver = st.session_state["admin_filter_ver"]

            f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.4, 1.4, 1.2])
            
            with f_col1:
                if not user_vendors.empty and "clean_city" in user_vendors.columns:
                    all_cities = sorted([c for c in user_vendors["clean_city"].dropna().unique() if c and c != "-"])
                else: all_cities = []
                
                curr_city_k = f"admin_map_cities_{ver}"
                if curr_city_k in st.session_state:
                    st.session_state[curr_city_k] = [c for c in st.session_state[curr_city_k] if c in all_cities]

                selected_cities = st.multiselect(
                    T("1. المدينة / المحافظة:", "1. City:"),
                    options=all_cities,
                    placeholder=T("الكل (أو اختر مدن)", "All (or select cities)"),
                    key=curr_city_k
                )

            city_subset = user_vendors[user_vendors["clean_city"].isin(selected_cities)] if selected_cities else user_vendors.copy()

            with f_col2:
                if not city_subset.empty and "clean_am" in city_subset.columns:
                    valid_ams = sorted([a for a in city_subset["clean_am"].dropna().unique() if is_valid_am_name(a)])
                else: valid_ams = []
                
                curr_am_k = f"admin_map_ams_{ver}"
                if curr_am_k in st.session_state:
                    st.session_state[curr_am_k] = [a for a in st.session_state[curr_am_k] if a in valid_ams]

                selected_ams = st.multiselect(
                    T("2. مسؤول الحساب (AM):", "2. Account Manager (AM):"),
                    options=valid_ams,
                    placeholder=T("الكل (أو اختر AMs)", "All (or select AMs)"),
                    key=curr_am_k
                )

            am_subset = city_subset[city_subset["clean_am"].isin(selected_ams)] if selected_ams else city_subset.copy()

            with f_col3:
                if not am_subset.empty and "clean_cid" in am_subset.columns and "clean_chain_name" in am_subset.columns:
                    chains_in_subset = am_subset[["clean_cid", "clean_chain_name"]].drop_duplicates()
                    chains_in_subset = chains_in_subset[chains_in_subset["clean_cid"] != ""]
                    chain_map = dict(zip(chains_in_subset["clean_cid"], chains_in_subset["clean_chain_name"] + " (" + chains_in_subset["clean_cid"] + ")"))
                    chain_options = sorted(list(chain_map.keys()), key=lambda x: chain_map.get(x, x))
                else:
                    chain_map = {}
                    chain_options = []
                    
                curr_chain_k = f"admin_map_chains_{ver}"
                if curr_chain_k in st.session_state:
                    st.session_state[curr_chain_k] = [c for c in st.session_state[curr_chain_k] if c in chain_options]

                selected_chains = st.multiselect(
                    T("3. السلسلة (Chain):", "3. Chain:"),
                    options=chain_options,
                    format_func=lambda x: chain_map.get(x, x),
                    placeholder=T("الكل (أو اختر سلاسل)", "All (or select chains)"),
                    key=curr_chain_k
                )

            chain_subset = am_subset[am_subset["clean_cid"].isin(selected_chains)] if selected_chains else am_subset.copy()

            with f_col4:
                if not chain_subset.empty and "clean_vid" in chain_subset.columns and "clean_name" in chain_subset.columns:
                    vendor_opts = dict(zip(
                        chain_subset["clean_vid"],
                        chain_subset["clean_name"] + " (ID: " + chain_subset["clean_vid"] + ")"
                    ))
                    vendor_options = sorted(list(vendor_opts.keys()), key=lambda x: vendor_opts.get(x, x))
                else:
                    vendor_opts = {}
                    vendor_options = []
                    
                curr_vendor_k = f"admin_map_vendors_{ver}"
                if curr_vendor_k in st.session_state:
                    st.session_state[curr_vendor_k] = [v for v in st.session_state[curr_vendor_k] if v in vendor_options]

                selected_vendors = st.multiselect(
                    T("4. الفرع (Vendor):", "4. Vendor:"),
                    options=vendor_options,
                    format_func=lambda x: vendor_opts.get(x, x),
                    placeholder=T("الكل (أو اختر فروع)", "All (or select vendors)"),
                    key=curr_vendor_k
                )

            df_disp = chain_subset[chain_subset["clean_vid"].isin(selected_vendors)] if selected_vendors else chain_subset.copy()

            f2_col1, f2_col2, f2_col3 = st.columns([1.5, 1.5, 1.8])
            with f2_col1:
                selected_active = st.selectbox(
                    T("5. حالة التفعيل (Is Active):", "5. Active Status (Is Active):"),
                    options=[T("الكل", "All"), T("نشط فقط (Yes)", "Active Only (Yes)"), T("غير نشط (No)", "Inactive Only (No)")],
                    key=f"admin_filter_active_{ver}"
                )
            with f2_col2:
                selected_hidden = st.selectbox(
                    T("6. حالة الظهور (Is Hidden):", "6. Visibility (Is Hidden):"),
                    options=[T("الكل", "All"), T("الظاهر فقط (No)", "Visible Only (No)"), T("المخفي فقط (Yes)", "Hidden Only (Yes)")],
                    key=f"admin_filter_hidden_{ver}"
                )
            with f2_col3:
                st.write("")
                st.write("")
                def reset_admin_filters_callback():
                    st.session_state["admin_filter_ver"] = st.session_state.get("admin_filter_ver", 0) + 1

                st.button(
                    T("🔄 إعادة ضبط الفلاتر", "🔄 Reset Filters"), 
                    key=f"admin_reset_filters_btn_{ver}", 
                    on_click=reset_admin_filters_callback,
                    use_container_width=True
                )

            if not df_disp.empty and "clean_active" in df_disp.columns:
                if "Yes" in selected_active or "نشط" in selected_active:
                    df_disp = df_disp[df_disp["clean_active"] == "Yes"]
                elif "No" in selected_active or "غير نشط" in selected_active:
                    df_disp = df_disp[df_disp["clean_active"] == "No"]
                    
            if not df_disp.empty and "clean_hidden" in df_disp.columns:
                if "Visible" in selected_hidden or "الظاهر" in selected_hidden:
                    df_disp = df_disp[df_disp["clean_hidden"] == "No"]
                elif "Hidden" in selected_hidden or "المخفي" in selected_hidden:
                    df_disp = df_disp[df_disp["clean_hidden"] == "Yes"]

            if not df_disp.empty and "lat" in df_disp.columns and "lng" in df_disp.columns:
                plot_vendors = df_disp.dropna(subset=["lat", "lng"]).copy()
            else:
                plot_vendors = pd.DataFrame()

            cnt_total, cnt_active, cnt_inactive, tot_orders, tot_failed, rate_str = get_performance_kpis(df_disp, df_performance)

            card_col1, card_col2, card_col3, card_col4 = st.columns(4)
            card_col1.metric(
                T("🏬 إجمالي الفروع", "🏬 Total Branches"),
                f"{cnt_total:,}",
                delta=f"{cnt_inactive} " + T("غير نشط", "Inactive") if cnt_inactive > 0 else None,
                delta_color="off"
            )
            card_col2.metric(
                T("🟢 الفروع النشطة", "🟢 Active Branches"),
                f"{cnt_active:,}",
                delta=f"{(cnt_active / cnt_total * 100):.1f}%" if cnt_total > 0 else "0%"
            )
            card_col3.metric(
                T("📦 إجمالي عدد الأوردرات", "📦 Total Orders"),
                f"{tot_orders:,}",
                delta=T("QC Net Orders", "QC Net Orders"),
                delta_color="off"
            )
            card_col4.metric(
                T("⚠️ إجمالي Vendor Fail Rate", "⚠️ Total Vendor Fail Rate"),
                rate_str,
                delta=f"{tot_failed:,} " + T("أوردر ملغي", "Failed Orders") if tot_failed > 0 else None,
                delta_color="inverse"
            )

            try:
                vendor_color_map = {}
                distinct_branches = df_disp[["clean_vid", "clean_name", "clean_chain_name"]].drop_duplicates()
                for idx, (_, b_row) in enumerate(distinct_branches.iterrows()):
                    pal_entry = BRANCH_PALETTE[idx % len(BRANCH_PALETTE)]
                    vendor_color_map[b_row["clean_vid"]] = {
                        "name": b_row["clean_name"],
                        "hex": pal_entry.get("hex", "#28a745"),
                        "folium": pal_entry.get("folium", "green"),
                        "chain": b_row["clean_chain_name"],
                        "color_name": pal_entry.get("name", "أخضر")
                    }

                disp_vids = set(df_disp["clean_vid"].dropna().unique())
                rel_del = df_delivery[df_delivery["clean_vid"].isin(disp_vids)] if not df_delivery.empty else pd.DataFrame()

                zone_to_vendor_info = {}
                if not rel_del.empty:
                    for _, r in rel_del.iterrows():
                        z_norm = str(r.get("clean_zone", "")).strip().lower()
                        if not z_norm: continue
                        vid = str(r.get("clean_vid", ""))
                        v_info = vendor_color_map.get(vid, {"name": vid, "hex": "#28a745", "folium": "green"})
                        if z_norm not in zone_to_vendor_info:
                            zone_to_vendor_info[z_norm] = []
                        zone_to_vendor_info[z_norm].append({
                            "vid": vid,
                            "name": v_info.get("name", vid),
                            "hex": v_info.get("hex", "#28a745"),
                            "time": r.get("clean_time", "-"),
                            "fee": r.get("clean_fee", "-"),
                            "min_order": r.get("clean_min_order", "-")
                        })

                if (selected_chains or selected_vendors or (len(vendor_color_map) <= 15 and len(vendor_color_map) > 1)):
                    st.write(T("🎨 **دليل تمييز ألوان الفروع ومناطق توصيلها:**", "🎨 **Branch Color Legend & Delivery Areas:**"))
                    n_cols = min(max(len(vendor_color_map), 1), 4)
                    leg_cols = st.columns(n_cols)
                    for idx, (b_vid, b_info) in enumerate(vendor_color_map.items()):
                        with leg_cols[idx % n_cols]:
                            st.markdown(
                                f"<div style='padding:5px 8px; border-radius:5px; margin-bottom:5px; border-left: 5px solid {b_info.get('hex', '#28a745')}; background: #f8f9fa; font-size:11.5px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>"
                                f"<b>{b_info.get('name', b_vid)}</b><br><span style='color:gray;'>Vendor ID: {b_vid}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )

                gdf_areas_to_render = gpd.GeoDataFrame()
                if not gdf_areas.empty:
                    if selected_cities and not plot_vendors.empty:
                        minx, miny, maxx, maxy = plot_vendors["lng"].min(), plot_vendors["lat"].min(), plot_vendors["lng"].max(), plot_vendors["lat"].max()
                        bbox = box(minx - 0.25, miny - 0.25, maxx + 0.25, maxy + 0.25)
                        nearby_mask = gdf_areas.geometry.intersects(bbox)
                        gdf_areas_to_render = gdf_areas[nearby_mask].copy()
                        if gdf_areas_to_render.empty:
                            gdf_areas_to_render = gdf_areas.copy()
                    else:
                        gdf_areas_to_render = gdf_areas.copy()

                if not gdf_areas_to_render.empty:
                    gdf_areas_to_render = gdf_areas_to_render.sort_values(by="area_size", ascending=False)
                    def assign_zone_styling_and_popup(area_name):
                        z_clean = str(area_name).strip().lower()
                        if z_clean in zone_to_vendor_info:
                            info_list = zone_to_vendor_info[z_clean]
                            primary_info = info_list[0]
                            prim_hex = primary_info.get("hex", "#ff5a00")
                            card_html = build_zone_popup_card(area_name, info_list)
                            return prim_hex, prim_hex, 0.45, 2.0, card_html, True
                        
                        card_html = build_zone_popup_card(area_name, [])
                        return "#a0aec0", "#4a5568", 0.08, 1.2, card_html, False

                    props = gdf_areas_to_render["Delivery Location Area Name"].apply(assign_zone_styling_and_popup)
                    gdf_areas_to_render["fill_color"] = [p[0] for p in props]
                    gdf_areas_to_render["border_color"] = [p[1] for p in props]
                    gdf_areas_to_render["fill_opacity"] = [p[2] for p in props]
                    gdf_areas_to_render["weight"] = [p[3] for p in props]
                    gdf_areas_to_render["popup_html"] = [p[4] for p in props]

                if selected_vendors and not plot_vendors.empty:
                    map_center = [float(plot_vendors.iloc[0]["lat"]), float(plot_vendors.iloc[0]["lng"])]
                    zoom_lvl = 13
                elif not plot_vendors.empty:
                    mean_lat = float(plot_vendors["lat"].mean())
                    mean_lng = float(plot_vendors["lng"].mean())
                    map_center = [mean_lat, mean_lng] if (pd.notna(mean_lat) and pd.notna(mean_lng)) else [30.0444, 31.2357]
                    zoom_lvl = 12 if selected_chains else (10 if selected_cities else 7)
                else:
                    map_center = [30.0444, 31.2357]
                    zoom_lvl = 7

                m_admin = folium.Map(location=map_center, zoom_start=zoom_lvl)
                
                map_custom_css = (
                    "<style>"
                    ".leaflet-interactive:focus {outline: none !important;}"
                    "path.leaflet-interactive:hover {cursor: pointer; stroke: #ffc107 !important; stroke-width: 3.5px !important;}"
                    "</style>"
                )
                m_admin.get_root().html.add_child(folium.Element(map_custom_css))

                if not gdf_areas_to_render.empty:
                    folium.GeoJson(
                        gdf_areas_to_render[["Delivery Location Area Name", "popup_html", "fill_color", "border_color", "fill_opacity", "weight", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style_function=lambda feature: {
                            "fillColor": feature["properties"].get("fill_color", "#3388ff"),
                            "color": feature["properties"].get("border_color", "#002266"),
                            "weight": feature["properties"].get("weight", 1.0),
                            "fillOpacity": feature["properties"].get("fill_opacity", 0.08)
                        },
                        highlight_function=lambda feature: {
                            "color": "#ffc107",
                            "weight": 3.5,
                            "fillOpacity": 0.65
                        },
                        tooltip=folium.GeoJsonTooltip(
                            fields=["Delivery Location Area Name"],
                            aliases=[T("المنطقة: ", "Zone: ")]
                        ),
                        popup=folium.GeoJsonPopup(
                            fields=["popup_html"],
                            labels=False,
                            max_width=280
                        )
                    ).add_to(m_admin)

                if not plot_vendors.empty:
                    cluster = MarkerCluster().add_to(m_admin)
                    for _, row in plot_vendors.iterrows():
                        popup_content = build_vendor_popup_html(row, df_delivery, df_performance)
                        vid_str = row["clean_vid"]
                        b_color_info = vendor_color_map.get(vid_str, {})
                        pin_color = b_color_info.get("folium", "blue")
                        is_single_focus = (len(selected_vendors) == 1 and vid_str in selected_vendors)

                        if is_single_focus:
                            folium.Marker(
                                location=[row['lat'], row['lng']],
                                popup=folium.Popup(popup_content, max_width=300),
                                tooltip=f"💊 {row['clean_name']} (ID: {vid_str})",
                                icon=folium.Icon(color="green", icon="medkit", prefix="fa")
                            ).add_to(m_admin)
                        else:
                            folium.Marker(
                                location=[row['lat'], row['lng']],
                                popup=folium.Popup(popup_content, max_width=300),
                                tooltip=f"💊 {row['clean_name']} ({vid_str})",
                                icon=folium.Icon(color=pin_color, icon="medkit", prefix="fa")
                            ).add_to(cluster)

                st_folium(m_admin, width="100%", height=620, key="admin_overview_map_folium", returned_objects=[])
            except Exception as e:
                st.warning(f"ملاحظة: تعذر عرض بعض عناصر الخريطة: {e}")

# ==========================================
# Tab 2: Vendor Portal
# ==========================================
with tab2:
    st.header(T("بوابة الفيندور - التغطية والتسعير والأداء", "Vendor Portal - Coverage, Pricing & Performance"))
    
    if "submission_success_msg" in st.session_state:
        st.success(st.session_state.pop("submission_success_msg"))

    t_vid = ""
    p_vends = pd.DataFrame()

    if is_admin:
        v_inp = st.text_input(
            T("أدخل كود الفرع (Vendor ID) أو السلسلة (Chain ID):", "Enter Vendor or Chain ID:"),
            placeholder=T("أدخل كود الفرع أو السلسلة...", "Enter ID..."),
            key="vendor_portal_search_input"
        ).strip()

        if v_inp:
            cid = normalize_id(v_inp)
            m_v = user_vendors[user_vendors["clean_vid"] == cid] if not user_vendors.empty else pd.DataFrame()
            m_c = user_vendors[user_vendors["clean_cid"] == cid] if not user_vendors.empty else pd.DataFrame()
            p_vends = m_v if not m_v.empty else (m_c if not m_c.empty else pd.DataFrame())
            if p_vends.empty:
                err_msg = T("❌ الكود غير صحيح أو لا تملك صلاحية لإدارته.", "❌ ID not found in database or not in your scope.")
                st.error(err_msg)
        else:
            info_msg = T("ℹ️ يرجى إدخال كود الفرع (Vendor ID) أو السلسلة (Chain ID) أعلاه للبدء.", "ℹ️ Please enter a Vendor ID or Chain ID above to begin.")
            st.info(info_msg)
    else:
        p_vends = user_vendors.copy() if not user_vendors.empty else pd.DataFrame()
        if p_vends.empty:
            st.warning(T("⚠️ لا توجد فروع مربوطة بحسابك حتى الآن.", "⚠️ No branches linked to your account."))

    if not p_vends.empty:
        found_cid = p_vends.iloc[0].get("clean_cid", "")
        chain_siblings = user_vendors[user_vendors["clean_cid"] == found_cid] if found_cid and not user_vendors.empty else p_vends
        
        select_entire_chain = False
        if len(chain_siblings) > 1:
            st.markdown("---")
            select_entire_chain = st.checkbox(
                T(f"☑️ تحديد كامل فروع السلسلة ({len(chain_siblings)} فرع) لتوزيع المناطق عليها معاً", f"☑️ Select Entire Chain ({len(chain_siblings)} branches) for allocation"),
                value=False,
                key="select_entire_chain_chk"
            )

        if select_entire_chain:
            is_multi = True
            vd = chain_siblings
            portal_session_key = "MULTI_" + str(found_cid)
            st.success(T(f"✨ تم تفعيل وضع السلسلة بالكامل ({len(vd)} فرع) مع التمييز اللوني لكل فرع!", f"✨ Multi-branch chain mode active for ({len(vd)}) branches!"))
        else:
            is_multi = False
            opt = dict(zip(p_vends["clean_vid"], p_vends["clean_name"] + " (" + p_vends["clean_vid"] + ")"))
            single_chosen_vid = st.selectbox(
                T("اختر الفرع الرئيسي:", "Select Main Branch:"),
                list(opt.keys()),
                format_func=lambda x: opt[x],
                key="single_vendor_select"
            )
            vd = p_vends[p_vends["clean_vid"] == single_chosen_vid]
            portal_session_key = "SINGLE_" + str(single_chosen_vid)

        if not vd.empty:
            has_real_coords = pd.notna(vd["lat"]).any() and pd.notna(vd["lng"]).any()
            has_loc = has_real_coords

            branch_color_map = {}
            branch_names = {}
            for idx, (_, b_row) in enumerate(vd.iterrows()):
                pal_entry = BRANCH_PALETTE[idx % len(BRANCH_PALETTE)]
                b_vid = str(b_row["clean_vid"])
                branch_names[b_vid] = b_row["clean_name"]
                branch_color_map[b_vid] = {
                    "name": b_row["clean_name"],
                    "hex": pal_entry.get("hex", "#28a745"),
                    "folium": pal_entry.get("folium", "green"),
                    "chain": b_row.get("clean_chain_name", "")
                }

            all_known_zones = sorted([
                z for z in gdf_areas["Delivery Location Area Name"].dropna().unique() 
                if not re.search(r"charit|charities", str(z), re.IGNORECASE)
            ]) if not gdf_areas.empty else []
            
            zlk_exact = {z.strip().lower(): z for z in all_known_zones}
            zlk_norm = {normalize_zone_key(z): z for z in all_known_zones}

            def resolve_zone_name(raw_name):
                if not raw_name: return ""
                raw_str = str(raw_name).strip()
                low = raw_str.lower()
                if low in zlk_exact: return zlk_exact[low]
                norm = normalize_zone_key(raw_str)
                if norm in zlk_norm: return zlk_norm[norm]
                for k, v in zlk_exact.items():
                    if k in low or low in k: return v
                for k, v in zlk_norm.items():
                    if k in norm or norm in k: return v
                return raw_str

            if st.session_state.get("portal_session_id") != portal_session_key:
                st.session_state["portal_session_id"] = portal_session_key
                original_alloc = {str(b_vid): {} for b_vid in branch_names.keys()}
                
                vids_in_scope = set(branch_names.keys())
                if not df_delivery.empty:
                    mask_vid = df_delivery["clean_vid"].isin(vids_in_scope)
                    mask_cid = (df_delivery["clean_cid"] == str(found_cid)) & ((df_delivery["clean_vid"] == "") | (~df_delivery["clean_vid"].isin(df_vendors["clean_vid"].unique())))
                    m_del = df_delivery[mask_vid | mask_cid].copy()

                    for _, r in m_del.iterrows():
                        row_vid = str(r.get("clean_vid", "")).strip()
                        target_vid = row_vid if row_vid in vids_in_scope else list(vids_in_scope)[0]
                        
                        raw_z = str(r.get("clean_zone", "")).strip()
                        zn = resolve_zone_name(raw_z)
                        
                        if zn and target_vid in original_alloc:
                            fee_val = 0.0
                            raw_fee = str(r.get("clean_fee", "")).strip()
                            try: fee_val = float(raw_fee)
                            except: fee_val = 0.0
                            raw_t = str(r.get("clean_time", "45 mins")).strip()
                            final_t = raw_t if (raw_t and raw_t.lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                            
                            raw_min = str(r.get("clean_min_order", "0.0")).strip()
                            try: min_order_val = float(raw_min)
                            except: min_order_val = 0.0

                            original_alloc[target_vid][zn] = {
                                "time": final_t,
                                "fee": min(fee_val, 35.0),
                                "min_order": min_order_val
                            }
                
                st.session_state["portal_orig_alloc"] = copy.deepcopy(original_alloc)
                st.session_state["portal_working_alloc"] = copy.deepcopy(original_alloc)
                st.session_state["portal_active_vid"] = list(branch_names.keys())[0] if branch_names else ""
                st.session_state["portal_show_diff"] = False
                st.session_state["portal_selected_zone"] = ""
                st.session_state["just_clicked_map_zone"] = None

            working_alloc = st.session_state.get("portal_working_alloc", {})
            orig_alloc = st.session_state.get("portal_orig_alloc", {})

            active_vid = st.session_state.get("portal_active_branch_select") or st.session_state.get("portal_active_vid") or (list(branch_names.keys())[0] if branch_names else "")
            if active_vid not in branch_names and branch_names:
                active_vid = list(branch_names.keys())[0]
            st.session_state["portal_active_vid"] = active_vid

            active_branch_color = branch_color_map.get(active_vid, {}).get("hex", "#28a745")
            active_branch_name = branch_names.get(active_vid, active_vid)

            st.markdown("---")
            v_perf, c_perf = get_vendor_and_chain_perf(active_vid, found_cid, df_performance)

            chain_label_name = vd.iloc[0].get("clean_chain_name", f"Chain {found_cid}")
            st.markdown(f"<div style='font-size: 15px; font-weight: 800; color: #ff5a00; margin-bottom: 8px;'>🏢 {T('أداء السلسلة بالكامل', 'Entire Chain Performance')}: <span style='color: #ffffff;'>{chain_label_name} (ID: {found_cid})</span></div>", unsafe_allow_html=True)
            
            c_kpi1, c_kpi2, c_kpi3 = st.columns(3)
            with c_kpi1:
                st.metric(
                    label=T("📦 QC Net Orders (السلسلة)", "QC Net Orders (Chain)"),
                    value=str(c_perf.get("qc_orders", "-"))
                )
            with c_kpi2:
                st.metric(
                    label=T("⚠️ Vendor Net Failed Orders (السلسلة)", "Failed Orders (Chain)"),
                    value=str(c_perf.get("fail_orders", "-")),
                    delta=T("ملغاة", "failed"),
                    delta_color="inverse"
                )
            with c_kpi3:
                st.metric(
                    label=T("📉 Vendor Net Fail Rate (السلسلة)", "Fail Rate (Chain)"),
                    value=str(c_perf.get("fail_rate", "-")),
                    delta_color="inverse"
                )

            st.write("")
            st.markdown(f"<div style='font-size: 15px; font-weight: 800; color: #28a745; margin-bottom: 8px;'>💊 {T('أداء الفرع المحدد حالياً', 'Selected Branch Performance')}: <span style='color: #ffffff;'>{active_branch_name} (ID: {active_vid})</span></div>", unsafe_allow_html=True)
            
            v_kpi1, v_kpi2, v_kpi3, v_kpi4 = st.columns(4)
            with v_kpi1:
                st.metric(
                    label=T("📦 QC Net Orders (الفرع)", "QC Net Orders (Vendor)"),
                    value=str(v_perf.get("qc_orders", "-"))
                )
            with v_kpi2:
                st.metric(
                    label=T("⚠️ Vendor Net Failed Orders (الفرع)", "Failed Orders (Vendor)"),
                    value=str(v_perf.get("fail_orders", "-")),
                    delta=T("ملغاة", "failed"),
                    delta_color="inverse"
                )
            with v_kpi3:
                st.metric(
                    label=T("📉 Vendor Net Fail Rate (الفرع)", "Fail Rate (Vendor)"),
                    value=str(v_perf.get("fail_rate", "-")),
                    delta_color="inverse"
                )
            with v_kpi4:
                st.metric(
                    label=T("📞 Vendor Fault Customer CR", "Vendor Fault CR"),
                    value=str(v_perf.get("fault_cr", "-")),
                    delta_color="inverse"
                )
            st.markdown("---")

            if len(vd) > 1:
                st.write(T("🎨 **دليل تمييز ألوان الفروع في السلسلة:**", "🎨 **Branch Colors in Chain:**"))
                n_cols = min(max(len(vd), 1), 4)
                leg_cols = st.columns(n_cols)
                for idx, (b_vid, b_info) in enumerate(branch_color_map.items()):
                    with leg_cols[idx % n_cols]:
                        zone_count = len(working_alloc.get(b_vid, {}))
                        is_active_card = (b_vid == active_vid)
                        border_highlight = f"3px solid {b_info['hex']}" if is_active_card else "1px solid #dee2e6"
                        bg_highlight = "#e8f4fd" if is_active_card else "#f8f9fa"
                        badge_tag = "<b style='color:#ff5a00;'>🎯 الفرع المحدد</b><br>" if is_active_card else "<br>"
                        st.markdown(
                            f"<div style='padding:5px 8px; border-radius:5px; margin-bottom:5px; border-left: 6px solid {b_info['hex']}; border: {border_highlight}; background: {bg_highlight}; font-size:11.5px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>"
                            f"<b>{b_info['name']}</b> ({zone_count} منطقة){badge_tag}"
                            f"<span style='color:gray;'>Vendor ID: {b_vid}</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )

            rad = st.slider(T("نطاق الخريطة (كم):", "Radius (km):"), 3, 50, 15, key="portal_radius_slider")

            all_chain_covered_zones = set()
            for v_id, z_dict in working_alloc.items():
                for z in z_dict:
                    all_chain_covered_zones.add(z.strip().lower())
                    all_chain_covered_zones.add(normalize_zone_key(z))

            covered_mask = (gdf_areas["Delivery Location Area Name"].astype(str).str.strip().str.lower().isin(all_chain_covered_zones)) | (gdf_areas["norm_key"].isin(all_chain_covered_zones)) if not gdf_areas.empty else pd.Series(dtype=bool)
            covered_gdf = gdf_areas[covered_mask].copy() if not gdf_areas.empty else gpd.GeoDataFrame()

            if has_loc and not gdf_areas.empty:
                valid_coords = vd.dropna(subset=["lat", "lng"])
                if not valid_coords.empty:
                    branch_pts = MultiPoint([Point(r['lng'], r['lat']) for _, r in valid_coords.iterrows()])
                    nearby_mask = gdf_areas.geometry.intersects(branch_pts.buffer(rad / 111.0))
                    nearby_gdf = gdf_areas[nearby_mask].copy()
                    pa = pd.concat([covered_gdf, nearby_gdf]).drop_duplicates(subset=["Delivery Location Area Name"])
                else:
                    pa = gdf_areas.copy()
            else:
                pa = gdf_areas.copy()

            if not pa.empty and "area_size" in pa.columns:
                pa = pa.sort_values(by="area_size", ascending=False)

            zone_to_branch_owner = {}
            for v_id, z_dict in working_alloc.items():
                for z in z_dict:
                    zone_to_branch_owner[z.strip().lower()] = v_id
                    zone_to_branch_owner[normalize_zone_key(z)] = v_id

            cm, cf = st.columns([6, 4])

            with cm:
                st.subheader(f"🗺️ Map ({len([z for v in working_alloc.values() for z in v])} {T('منطقة مغطاة للسلسلة', 'Covered Zones')})")
                st.caption(T("💡 انقر على أي منطقة على الخريطة ليتم اختيارها مباشرة في خانة التعديل أو الإضافة أو الإزالة.", "💡 Click any zone on the map to select it directly in the control panel."))

                # ضبط مركز الخريطة ومستوى الزوم الواسع (11) كالصورة الثانية بدلاً من 14
                active_row = vd[vd["clean_vid"] == active_vid]
                if not active_row.empty and pd.notna(active_row.iloc[0]["lat"]) and pd.notna(active_row.iloc[0]["lng"]):
                    mcnt = [float(active_row.iloc[0]["lat"]), float(active_row.iloc[0]["lng"])]
                    zoom_lvl = 12  # زوم واسع وشامل
                elif not valid_coords.empty:
                    mcnt = [float(valid_coords["lat"].mean()), float(valid_coords["lng"].mean())]
                    zoom_lvl = 12
                else:
                    mcnt = [30.0444, 31.2357]
                    zoom_lvl = 12

                vmap = folium.Map(location=mcnt, zoom_start=zoom_lvl, prefer_canvas=True)

                if not valid_coords.empty:
                    for _, rv in valid_coords.iterrows():
                        b_id_str = str(rv["clean_vid"])
                        b_info = branch_color_map.get(b_id_str, {"hex": "#28a745", "folium": "green"})
                        is_active_b = (b_id_str == active_vid)
                        
                        target_tag = '<span style="color: red; font-weight: bold;">(🎯 الفرع المحدد حالياً للتعديل)</span>' if is_active_b else ''
                        popup_html = f"""<div style='font-family: Arial, sans-serif; font-size: 11px; width: 210px;'>
                        <b style='color: #ff5a00;'>💊 {rv['clean_name']}</b><br>
                        <b>Vendor ID:</b> <code>{b_id_str}</code><br>
                        <b>{T('المناطق المغطاة', 'Covered Zones')}:</b> {len(working_alloc.get(b_id_str, {}))}<br>
                        {target_tag}
                        </div>"""

                        folium.Marker(
                            [rv["lat"], rv["lng"]],
                            tooltip=f"💊 {rv['clean_name']} (ID: {b_id_str})",
                            popup=folium.Popup(popup_html, max_width=250),
                            icon=folium.Icon(color="red" if is_active_b else b_info.get("folium", "green"), icon="medkit", prefix="fa")
                        ).add_to(vmap)

                vmap.get_root().html.add_child(folium.Element("<style>.leaflet-interactive:focus{outline:none;} path.leaflet-interactive:hover{stroke:#ffc107 !important; stroke-width:3.5px !important; cursor:pointer;}</style>"))

                selected_zone_in_state = st.session_state.get("portal_selected_zone", "").strip().lower()

                if not pa.empty:
                    def get_portal_zone_styling(feature):
                        z_name = str(feature["properties"].get("Delivery Location Area Name", "")).strip()
                        z_low = z_name.lower()
                        z_norm = normalize_zone_key(z_name)
                        is_clicked_target = (z_low == selected_zone_in_state or z_norm == selected_zone_in_state) and selected_zone_in_state != ""
                        
                        owner_vid = zone_to_branch_owner.get(z_low) or zone_to_branch_owner.get(z_norm)
                        if owner_vid:
                            b_hex = branch_color_map.get(owner_vid, {}).get("hex", "#28a745")
                            is_active_owner = (owner_vid == active_vid)
                            
                            return {
                                "fillColor": "#ff5a00" if is_clicked_target else b_hex,
                                "color": "#000000" if is_clicked_target else b_hex,
                                "weight": 4.5 if is_clicked_target else (3.0 if is_active_owner else 1.2),
                                "fillOpacity": 0.85 if is_clicked_target else (0.6 if is_active_owner else 0.3)
                            }
                        return {
                            "fillColor": "#ff5a00" if is_clicked_target else "#a0aec0",
                            "color": "#000000" if is_clicked_target else "#4a5568",
                            "weight": 3.5 if is_clicked_target else 1.0,
                            "fillOpacity": 0.75 if is_clicked_target else 0.08
                        }

                    folium.GeoJson(
                        pa[["Delivery Location Area Name", "geometry"]].to_json(),
                        style_function=get_portal_zone_styling,
                        tooltip=folium.GeoJsonTooltip(
                            fields=["Delivery Location Area Name"],
                            aliases=[T("المنطقة: ", "Zone: ")]
                        )
                    ).add_to(vmap)

                # قفل الـ returned_objects على النقر فقط لمنع الريفريش التلقائي عند تحريك الخريطة
                mcd = st_folium(
                    vmap,
                    width="100%",
                    height=540,
                    key=f"vmap_portal_{portal_session_key}_{active_vid}_{rad}",
                    returned_objects=["last_object_clicked"]
                )

                clicked_zone, click_sig = extract_clicked_zone_direct(mcd, pa, all_known_zones)
                if click_sig and click_sig != st.session_state.get("last_poly_click_sig"):
                    st.session_state["last_poly_click_sig"] = click_sig
                    if clicked_zone:
                        st.session_state["portal_selected_zone"] = clicked_zone
                        st.session_state["just_clicked_map_zone"] = clicked_zone
                        st.session_state["portal_show_diff"] = False
                        st.rerun()

            with cf:
                st.subheader(T("🛠️ لوحة تعديل المناطق والتسعير", "🛠️ Zone & Pricing Control Panel"))
                
                if len(vd) > 1:
                    branch_select_opts = {v: f"{branch_names[v]} ({v})" for v in branch_names.keys()}
                    branch_keys_list = list(branch_select_opts.keys())
                    current_idx = branch_keys_list.index(active_vid) if active_vid in branch_keys_list else 0
                    
                    selected_branch_key = st.selectbox(
                        T("🏬 اختر الفرع المستهدف للتعديل (تتحرك الخريطة عليه فوراً):", "🏬 Target Branch (Map auto-centers here):"),
                        options=branch_keys_list,
                        index=current_idx,
                        format_func=lambda x: branch_select_opts[x],
                        key="portal_active_branch_select"
                    )
                    if selected_branch_key != active_vid:
                        st.session_state["portal_active_vid"] = selected_branch_key
                        st.session_state["portal_selected_zone"] = ""
                        st.rerun()
                else:
                    st.markdown(
                        f"""
                        <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 90, 0, 0.35); border-right: 4.5px solid #ff5a00; border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                <div>
                                    <span style="font-size: 12.5px; color: #8b949e; font-weight: 600;">🎯 {T("الفرع المستهدف حالياً:", "Target Branch:")}</span>
                                    <div style="font-size: 16px; font-weight: 800; color: #ffffff; margin-top: 3px;">
                                        {active_branch_name}
                                    </div>
                                </div>
                                <div style="text-align: left; background: rgba(255, 90, 0, 0.12); padding: 5px 11px; border-radius: 8px; border: 1px solid rgba(255, 90, 0, 0.3);">
                                    <div style="font-size: 10px; color: #8b949e; text-transform: uppercase; font-weight: 600;">Vendor ID</div>
                                    <div style="font-size: 14px; font-weight: 900; color: #ff5a00; font-family: monospace;">{active_vid}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                # ========================================================
                # ميزة رفع ملف إكسيل / CSV مجمع (Bulk Upload)
                # ========================================================
                with st.expander(T("📂 رفع ملف إكسيل / CSV مجمع للمناطق (Bulk Upload)", "📂 Bulk Upload CSV / Excel"), expanded=False):
                    st.caption(T(
                        "ارفع ملف إكسيل أو CSV يحتوي على أعمدة: (Zone, Delivery Time, Delivery Fees, Minimum Order Amount) مع إمكانية إضافة كود الفرع (Vendor ID) لتوزيع عدة فروع بالسلسلة.",
                        "Upload Excel or CSV file containing: (Zone, Delivery Time, Delivery Fees, Minimum Order Amount) with optional (Vendor ID)."
                    ))
                    
                    sample_template_df = pd.DataFrame([
                        {"Vendor ID": active_vid, "Zone": all_known_zones[0] if all_known_zones else "Dokki", "Delivery Time": "45 mins", "Delivery Fees": 25.0, "Minimum Order Amount": 0.0},
                        {"Vendor ID": active_vid, "Zone": all_known_zones[1] if len(all_known_zones) > 1 else "Mohandessin", "Delivery Time": "30 mins", "Delivery Fees": 20.0, "Minimum Order Amount": 50.0}
                    ])
                    csv_template_bytes = sample_template_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        T("📥 تحميل نموذج ملف فارغ (Download Template)", "📥 Download Template CSV"),
                        data=csv_template_bytes,
                        file_name="zones_upload_template.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                    
                    uploaded_bulk_file = st.file_uploader(
                        T("اختر ملف الإكسيل أو الـ CSV:", "Choose File:"),
                        type=["csv", "xlsx", "xls"],
                        key=f"bulk_upload_file_input_{portal_session_key}"
                    )
                    
                    if uploaded_bulk_file is not None:
                        if st.button(T("🚀 استيراد وتحديث الخريطة فوراً", "🚀 Import & Update Map"), type="primary", use_container_width=True):
                            try:
                                if uploaded_bulk_file.name.endswith(".csv"):
                                    up_df = pd.read_csv(uploaded_bulk_file)
                                else:
                                    up_df = pd.read_excel(uploaded_bulk_file)
                                    
                                if up_df.empty:
                                    st.error(T("الملف المرفوع فارغ!", "Uploaded file is empty!"))
                                else:
                                    c_vid = robust_get_col(up_df, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id", "كود الفرع", "رقم الفرع"])
                                    c_zone = robust_get_col(up_df, ["Zone", "Zone Name", "Area", "Area Name", "Delivery Location Area Name", "اسم المنطقة", "المنطقة"])
                                    c_time = robust_get_col(up_df, ["Delivery Time", "Time", "Duration", "وقت التوصيل", "الوقت"])
                                    c_fee = robust_get_col(up_df, ["Delivery Fees", "Delivery Fee", "Fee", "Fees", "Price", "رسوم التوصيل", "السعر"])
                                    c_min = robust_get_col(up_df, ["Minimum Order Amount", "Minimum Amount", "Min Order", "Min Amount", "الحد الادنى", "الحد الأدنى"])
                                    
                                    if not c_zone:
                                        st.error(T("لم يتم العثور على عمود اسم المنطقة (Zone) في الملف المرفوع!", "Zone column not found!"))
                                    else:
                                        allowed_vids = set(branch_names.keys())
                                        imported_count = 0
                                        
                                        for _, r_up in up_df.iterrows():
                                            target_row_vid = active_vid
                                            if c_vid and pd.notna(r_up[c_vid]):
                                                candidate_vid = normalize_id(r_up[c_vid])
                                                if candidate_vid in allowed_vids:
                                                    target_row_vid = candidate_vid
                                            
                                            raw_z = str(r_up[c_zone]).strip()
                                            matched_zone = resolve_zone_name(raw_z)
                                            
                                            if matched_zone:
                                                r_t = str(r_up[c_time]).strip() if (c_time and pd.notna(r_up[c_time])) else "45 mins"
                                                if not r_t or r_t.lower() in ["nan", "none", "null", "-"]:
                                                    r_t = "45 mins"
                                                if r_t not in DELIVERY_TIME_CHOICES:
                                                    r_t_digits = re.findall(r'\d+', r_t)
                                                    if r_t_digits:
                                                        closest_val = min(max(int(r_t_digits[0]), 20), 60)
                                                        closest_5 = 5 * round(closest_val / 5.0)
                                                        r_t = f"{closest_5} mins"
                                                    else:
                                                        r_t = "45 mins"
                                                
                                                try: r_f = float(r_up[c_fee]) if (c_fee and pd.notna(r_up[c_fee])) else 25.0
                                                except: r_f = 25.0
                                                r_f = min(max(r_f, 0.0), 35.0)
                                                
                                                try: r_m = float(r_up[c_min]) if (c_min and pd.notna(r_up[c_min])) else 0.0
                                                except: r_m = 0.0
                                                r_m = max(r_m, 0.0)
                                                
                                                for other_v in working_alloc:
                                                    if other_v != target_row_vid and matched_zone in working_alloc[other_v]:
                                                        del working_alloc[other_v][matched_zone]
                                                        
                                                if target_row_vid not in working_alloc:
                                                    working_alloc[target_row_vid] = {}
                                                    
                                                working_alloc[target_row_vid][matched_zone] = {
                                                    "time": r_t,
                                                    "fee": r_f,
                                                    "min_order": r_m
                                                }
                                                imported_count += 1
                                        
                                        st.session_state["portal_working_alloc"] = working_alloc
                                        st.session_state["portal_show_diff"] = True
                                        st.success(T(
                                            f"🎉 تم استيراد وتحديث {imported_count} منطقة بنجاح على الخريطة! انزل لأسفل لمراجعة جدول التعديلات وتأكيدها ⬇️",
                                            f"🎉 Imported & updated {imported_count} zones! Scroll down to review and submit ⬇️"
                                        ))
                                        st.rerun()
                            except Exception as e:
                                st.error(f"خطأ أثناء قراءة الملف: {e}")

                st.markdown("---")

                opt_edit = T("✏️ تعديل الوقت والرسوم لمناطق حالية", "✏️ Edit Time & Fees")
                opt_add = T("➕ إضافة منطقة لهذا الفرع", "➕ Add Zone to Branch")
                opt_del = T("🗑️ إزالة منطقة من هذا الفرع", "🗑️ Remove Zone from Branch")

                active_branch_zones = working_alloc.get(active_vid, {})
                active_zones_keys = sorted(list(active_branch_zones.keys()))
                available_to_add = sorted([z for z in all_known_zones if z not in active_zones_keys])

                just_clicked = st.session_state.pop("just_clicked_map_zone", None)
                if just_clicked:
                    if just_clicked in active_zones_keys:
                        curr_m = st.session_state.get("portal_action_mode_radio", opt_edit)
                        if "إزالة" in curr_m or "Remove" in curr_m:
                            st.session_state["portal_action_mode_radio"] = opt_del
                            st.session_state["portal_remove_zone_select"] = just_clicked
                        else:
                            st.session_state["portal_action_mode_radio"] = opt_edit
                            st.session_state["portal_edit_zone_select"] = just_clicked
                    elif just_clicked in available_to_add:
                        st.session_state["portal_action_mode_radio"] = opt_add
                        st.session_state["portal_add_zone_select"] = just_clicked

                action_mode = st.radio(
                    T("أو اختر تعديلاً يدوياً:", "Or Select Manual Action:"),
                    options=[opt_edit, opt_add, opt_del],
                    key="portal_action_mode_radio"
                )

                if "تعديل" in action_mode or "Edit" in action_mode:
                    if not active_zones_keys:
                        st.info(T("لا توجد مناطق مسجلة لهذا الفرع حالياً لتعديلها.", "No zones assigned to this branch to edit."))
                    else:
                        if "portal_edit_zone_select" in st.session_state and st.session_state["portal_edit_zone_select"] not in active_zones_keys:
                            del st.session_state["portal_edit_zone_select"]

                        selected_edit_zone = st.selectbox(
                            T("اسم المنطقة المراد تعديلها:", "Zone to Edit:"),
                            options=active_zones_keys,
                            key="portal_edit_zone_select"
                        )
                        st.session_state["portal_selected_zone"] = selected_edit_zone

                        cur_z_info = active_branch_zones.get(selected_edit_zone, {})
                        raw_t = cur_z_info.get("time", "45 mins")
                        curr_time = str(raw_t).strip() if (raw_t and str(raw_t).strip().lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                        
                        raw_f = cur_z_info.get("fee", 25.0)
                        try: curr_fee = float(raw_f)
                        except: curr_fee = 25.0
                        curr_fee = min(max(curr_fee, 0.0), 35.0)

                        raw_min = cur_z_info.get("min_order", 0.0)
                        try: curr_min = float(raw_min)
                        except: curr_min = 0.0
                        curr_min = max(curr_min, 0.0)

                        time_idx = DELIVERY_TIME_CHOICES.index(curr_time) if curr_time in DELIVERY_TIME_CHOICES else 5

                        c_t1, c_t2, c_t3 = st.columns(3)
                        with c_t1:
                            edit_time_val = st.selectbox(
                                T("وقت التوصيل المقترح (20-60 دقيقة):", "Delivery Time (20-60m):"),
                                options=DELIVERY_TIME_CHOICES,
                                index=time_idx,
                                key=f"edit_time_{selected_edit_zone}"
                            )
                        with c_t2:
                            edit_fee_val = st.number_input(
                                T("رسوم التوصيل (أقل من 35 EGP):", "Delivery Fee (<35 EGP):"),
                                min_value=0.0,
                                max_value=35.0,
                                value=curr_fee,
                                step=1.0,
                                key=f"edit_fee_{selected_edit_zone}"
                            )
                        with c_t3:
                            edit_min_order_val = st.number_input(
                                T("الحد الأدنى للطلب (EGP):", "Min Order Amount (EGP):"),
                                min_value=0.0,
                                value=curr_min,
                                step=5.0,
                                key=f"edit_min_order_{selected_edit_zone}"
                            )

                        if st.button(T("💾 حفظ تعديل المنطقة", "💾 Save Zone Update"), type="primary", use_container_width=True):
                            working_alloc[active_vid][selected_edit_zone] = {
                                "time": str(edit_time_val).strip(),
                                "fee": float(edit_fee_val),
                                "min_order": float(edit_min_order_val)
                            }
                            st.session_state["portal_working_alloc"] = working_alloc
                            st.session_state["portal_show_diff"] = True
                            st.success(T(f"تم حفظ تعديل منطقة {selected_edit_zone}، انزل لأسفل لتأكيد الإرسال للإدارة ⬇️", f"Saved {selected_edit_zone}! Scroll down to submit ⬇️"))
                            st.rerun()

                elif "إضافة" in action_mode or "Add" in action_mode:
                    if not available_to_add:
                        st.info(T("كافة المناطق المتاحة مضافة بالفعل لهذا الفرع.", "All zones are already added to this branch."))
                    else:
                        if "portal_add_zone_select" in st.session_state and st.session_state["portal_add_zone_select"] not in available_to_add:
                            del st.session_state["portal_add_zone_select"]

                        selected_add_zone = st.selectbox(
                            T("اسم المنطقة المراد إضافتها:", "Zone to Add:"),
                            options=available_to_add,
                            key="portal_add_zone_select"
                        )
                        st.session_state["portal_selected_zone"] = selected_add_zone

                        other_owner_vid = zone_to_branch_owner.get(selected_add_zone.strip().lower()) or zone_to_branch_owner.get(normalize_zone_key(selected_add_zone))
                        if other_owner_vid and other_owner_vid != active_vid:
                            other_b_name = branch_names.get(other_owner_vid, other_owner_vid)
                            st.warning(T(
                                f"⚠️ تنبيه: هذه المنطقة مسجلة حالياً لفرع ({other_b_name}). إضافتها هنا ستنقل تغطيتها تلقائياً إلى ({active_branch_name}).",
                                f"⚠️ Note: This zone is currently assigned to ({other_b_name}). Adding it here will transfer it to ({active_branch_name})."
                            ))
                            raw_ot = working_alloc[other_owner_vid].get(selected_add_zone, {}).get("time", "45 mins")
                            raw_of = working_alloc[other_owner_vid].get(selected_add_zone, {}).get("fee", 25.0)
                            raw_om = working_alloc[other_owner_vid].get(selected_add_zone, {}).get("min_order", 0.0)
                            default_time = str(raw_ot).strip() if (raw_ot and str(raw_ot).strip().lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                            try: default_fee = float(raw_of)
                            except: default_fee = 25.0
                            try: default_min = float(raw_om)
                            except: default_min = 0.0
                        else:
                            default_time = "45 mins"
                            default_fee = 25.0
                            default_min = 0.0

                        default_fee = min(max(default_fee, 0.0), 35.0)
                        add_time_idx = DELIVERY_TIME_CHOICES.index(default_time) if default_time in DELIVERY_TIME_CHOICES else 5

                        c_a1, c_a2, c_a3 = st.columns(3)
                        with c_a1:
                            add_time_val = st.selectbox(
                                T("وقت التوصيل المقترح (20-60 دقيقة):", "Delivery Time (20-60m):"),
                                options=DELIVERY_TIME_CHOICES,
                                index=add_time_idx,
                                key=f"add_time_{selected_add_zone}"
                            )
                        with c_a2:
                            add_fee_val = st.number_input(
                                T("رسوم التوصيل (أقل من 35 EGP):", "Delivery Fee (<35 EGP):"),
                                min_value=0.0,
                                max_value=35.0,
                                value=default_fee,
                                step=1.0,
                                key=f"add_fee_{selected_add_zone}"
                            )
                        with c_a3:
                            add_min_order_val = st.number_input(
                                T("الحد الأدنى للطلب (EGP):", "Min Order Amount (EGP):"),
                                min_value=0.0,
                                value=default_min,
                                step=5.0,
                                key=f"add_min_order_{selected_add_zone}"
                            )

                        if st.button(T("➕ تأكيد إضافة المنطقة لهذا الفرع", "➕ Add Zone to Branch"), type="primary", use_container_width=True):
                            if other_owner_vid and other_owner_vid in working_alloc and selected_add_zone in working_alloc[other_owner_vid]:
                                del working_alloc[other_owner_vid][selected_add_zone]
                            
                            working_alloc[active_vid][selected_add_zone] = {
                                "time": str(add_time_val).strip(),
                                "fee": float(add_fee_val),
                                "min_order": float(add_min_order_val)
                            }
                            st.session_state["portal_working_alloc"] = working_alloc
                            st.session_state["portal_show_diff"] = True
                            st.session_state["portal_selected_zone"] = selected_add_zone
                            if "portal_add_zone_select" in st.session_state:
                                del st.session_state["portal_add_zone_select"]
                            st.success(T(f"تمت إضافة منطقة {selected_add_zone}، انزل لأسفل لتأكيد الإرسال للإدارة ⬇️", f"Added {selected_add_zone}! Scroll down to submit ⬇️"))
                            st.rerun()

                elif "إزالة" in action_mode or "Remove" in action_mode:
                    if not active_zones_keys:
                        st.info(T("لا توجد مناطق مسجلة لهذا الفرع لإزالتها.", "No zones assigned to remove."))
                    else:
                        if "portal_remove_zone_select" in st.session_state and st.session_state["portal_remove_zone_select"] not in active_zones_keys:
                            del st.session_state["portal_remove_zone_select"]

                        selected_remove_zone = st.selectbox(
                            T("اسم المنطقة المراد إزالتها:", "Zone to Remove:"),
                            options=active_zones_keys,
                            key="portal_remove_zone_select"
                        )
                        st.session_state["portal_selected_zone"] = selected_remove_zone

                        if st.button(T(f"🗑️ تأكيد إزالة ({selected_remove_zone}) من هذا الفرع", f"🗑️ Remove ({selected_remove_zone})"), type="secondary", use_container_width=True):
                            if selected_remove_zone in working_alloc[active_vid]:
                                del working_alloc[active_vid][selected_remove_zone]
                            st.session_state["portal_working_alloc"] = working_alloc
                            st.session_state["portal_show_diff"] = True
                            st.session_state["portal_selected_zone"] = ""
                            if "portal_remove_zone_select" in st.session_state:
                                del st.session_state["portal_remove_zone_select"]
                            st.success(T(f"تمت إزالة منطقة {selected_remove_zone}، انزل لأسفل لتأكيد الإرسال للإدارة ⬇️", f"Removed {selected_remove_zone}! Scroll down to submit ⬇️"))
                            st.rerun()

                st.markdown("---")
                btn_c1, btn_c2 = st.columns(2)
                with btn_c1:
                    if st.button(T("👁️ تحديث الخريطة (Apply)", "👁️ Apply to Map"), use_container_width=True):
                        st.session_state["portal_show_diff"] = False
                        st.rerun()
                with btn_c2:
                    if st.button(T("🚀 تأكيد وتسعير (Submit)", "🚀 Submit Selection"), type="primary", use_container_width=True):
                        st.session_state["portal_show_diff"] = True
                        st.rerun()

            # جدول مراجعة التعديلات مع خاصية استبعاد وحذف المناطق
            if st.session_state.get("portal_show_diff"):
                st.markdown("---")
                st.subheader(T("💰 جدول مراجعة المناطق المعدلة فقط (Modifications Only)", "💰 Review Table - Modified Zones Only"))
                st.caption(T(
                    "يعرض هذا الجدول حصرياً المناطق التي طرأ عليها تعديل مع حساب المسافة والحد الأدنى للطلب ونوع الإجراء. يمكنك تحديد أي منطقة لاستبعادها أو التراجع عن تعديلها تماماً:",
                    "This table shows exclusively modified zones with distances & min order amounts. You can discard or revert any zone below:"
                ))

                diff_rows = []
                all_vids_eval = set(orig_alloc.keys()) | set(working_alloc.keys())

                for v_id in all_vids_eval:
                    b_lbl = f"{branch_names.get(v_id, v_id)} ({v_id})"
                    o_zones = orig_alloc.get(v_id, {})
                    w_zones = working_alloc.get(v_id, {})

                    for z in o_zones:
                        if z not in w_zones:
                            dist_calc = calc_vendor_zone_distance(v_id, z, df_vendors, gdf_areas)
                            diff_rows.append({
                                "Discard": False,
                                "Vendor ID": v_id,
                                "Branch Name": branch_names.get(v_id, v_id),
                                "Assigned Branch": b_lbl,
                                "Zone": z,
                                "Distance (km)": dist_calc,
                                "Change Type": T("🗑️ إزالة منطقة", "🗑️ Removal"),
                                "Status": T("مسجلة سابقاً", "Existing"),
                                "Action": T("إلغاء التفعيل", "Deactivate"),
                                "Delivery Time": o_zones[z].get("time", "-"),
                                "Delivery Fees (EGP)": float(o_zones[z].get("fee", 0.0) or 0.0),
                                "Minimum Order (EGP)": float(o_zones[z].get("min_order", 0.0) or 0.0)
                            })

                    for z in w_zones:
                        w_item = w_zones[z]
                        dist_calc = calc_vendor_zone_distance(v_id, z, df_vendors, gdf_areas)
                        if z not in o_zones:
                            diff_rows.append({
                                "Discard": False,
                                "Vendor ID": v_id,
                                "Branch Name": branch_names.get(v_id, v_id),
                                "Assigned Branch": b_lbl,
                                "Zone": z,
                                "Distance (km)": dist_calc,
                                "Change Type": T("✨ إضافة جديدة", "✨ New Addition"),
                                "Status": T("منطقة جديدة", "New Zone"),
                                "Action": T("نشط", "Active"),
                                "Delivery Time": str(w_item.get("time", "45 mins")),
                                "Delivery Fees (EGP)": float(w_item.get("fee", 25.0) or 0.0),
                                "Minimum Order (EGP)": float(w_item.get("min_order", 0.0) or 0.0)
                            })
                        else:
                            o_item = o_zones[z]
                            t_chg = str(o_item.get("time", "")).strip() != str(w_item.get("time", "")).strip()
                            f_chg = float(o_item.get("fee", 0.0) or 0.0) != float(w_item.get("fee", 0.0) or 0.0)
                            m_chg = float(o_item.get("min_order", 0.0) or 0.0) != float(w_item.get("min_order", 0.0) or 0.0)
                            if t_chg or f_chg or m_chg:
                                diff_rows.append({
                                    "Discard": False,
                                    "Vendor ID": v_id,
                                    "Branch Name": branch_names.get(v_id, v_id),
                                    "Assigned Branch": b_lbl,
                                    "Zone": z,
                                    "Distance (km)": dist_calc,
                                    "Change Type": T("✏️ تعديل سعر / وقت / حد أدنى", "✏️ Update Time/Fee/Min Order"),
                                    "Status": T("تعديل بيانات", "Updated"),
                                    "Action": "Edit",
                                    "Delivery Time": str(w_item.get("time", "")),
                                    "Delivery Fees (EGP)": float(w_item.get("fee", 0.0) or 0.0),
                                    "Minimum Order (EGP)": float(w_item.get("min_order", 0.0) or 0.0)
                                })

                if not diff_rows:
                    st.info(T("ℹ️ لم يتم العثور على أي تعديلات جديدة مقارنة بالبيانات الأصلية.", "ℹ️ No modifications found compared to original allocations."))
                else:
                    diff_df = pd.DataFrame(diff_rows)

                    column_configs = {
                        "Discard": st.column_config.CheckboxColumn(
                            T("🗑️ استبعاد", "🗑️ Discard"),
                            default=False,
                            help=T("حدد هذا المربع بجانب أي منطقة تريد إلغاء تعديلها وحذفها تماماً من الجدول", "Check to discard this change")
                        ),
                        "Assigned Branch": st.column_config.TextColumn(T("الفرع المسؤول", "Assigned Branch"), disabled=True),
                        "Zone": st.column_config.TextColumn(T("اسم المنطقة", "Zone Name"), disabled=True),
                        "Distance (km)": st.column_config.TextColumn(T("المسافة (كم)", "Distance (km)"), disabled=True),
                        "Change Type": st.column_config.TextColumn(T("نوع التعديل", "Change Type"), disabled=True),
                        "Status": st.column_config.TextColumn(T("حالة السجل", "Record Status"), disabled=True),
                        "Action": st.column_config.SelectboxColumn(
                            T("الإجراء", "Action"),
                            options=[T("نشط", "Active"), "Edit", T("إلغاء التفعيل", "Deactivate")],
                            required=True
                        ),
                        "Delivery Time": st.column_config.TextColumn(T("وقت التوصيل المقدر", "Delivery Time")),
                        "Delivery Fees (EGP)": st.column_config.NumberColumn(T("رسوم التوصيل (EGP)", "Fees (EGP)"), max_value=35.0),
                        "Minimum Order (EGP)": st.column_config.NumberColumn(T("الحد الأدنى للطلب (EGP)", "Min Order (EGP)"))
                    }

                    display_diff_df = diff_df.drop(columns=["Vendor ID", "Branch Name"], errors="ignore")

                    edited_diff = st.data_editor(
                        display_diff_df,
                        column_config=column_configs,
                        use_container_width=True,
                        hide_index=True,
                        key="portal_diff_editor"
                    )

                    c_act1, c_act2, c_act3 = st.columns([1.6, 1.4, 1.0])

                    with c_act1:
                        if st.button(T("✅ اعتماد التعديلات وإرسالها للإدارة", "✅ Finalize & Send Modifications to Admin"), type="primary", use_container_width=True):
                            valid_indices = [idx_r for idx_r, r in edited_diff.iterrows() if not r.get("Discard", False)]
                            filtered_diff_df = diff_df.loc[valid_indices].copy()

                            if filtered_diff_df.empty:
                                st.warning(T("كافة المناطق مستبعدة، لا توجد تعديلات لإرسالها.", "All zones were marked for discard."))
                            else:
                                for v_id in filtered_diff_df["Vendor ID"].unique():
                                    b_vname = filtered_diff_df[filtered_diff_df["Vendor ID"] == v_id]["Branch Name"].iloc[0]
                                    branch_indices = filtered_diff_df[filtered_diff_df["Vendor ID"] == v_id].index
                                    b_sub_df = edited_diff.loc[branch_indices].copy()

                                    def determine_final_status_and_action(r):
                                        act = str(r.get("Action", "")).strip()
                                        stat = str(r.get("Status", "")).strip()
                                        chg = str(r.get("Change Type", "")).strip()
                                        if "Deactivate" in act or "إلغاء" in act:
                                            return "Deactivated", "إلغاء التفعيل"
                                        elif "جديدة" in stat or "New" in stat or "إضافة" in chg:
                                            return "Active (New)", "نشط"
                                        elif "edit" in act.lower() or "تعديل" in act.lower() or "تحديث" in stat.lower() or "تعديل" in chg.lower():
                                            return "Edit", "Edit"
                                        else:
                                            return "Active (Existing)", act

                                    statuses_and_actions = b_sub_df.apply(determine_final_status_and_action, axis=1)
                                    b_sub_df["Final_Status"] = [sa[0] for sa in statuses_and_actions]
                                    b_sub_df["Action"] = [sa[1] for sa in statuses_and_actions]
                                    b_sub_df["Classification"] = "Vendor Zone Update"

                                    saved_records_df = save_detailed_request(v_id, b_vname, b_sub_df)
                                    
                                    send_request_emails(
                                        vendor_id=v_id, 
                                        vendor_name=b_vname, 
                                        records_df=saved_records_df,
                                        submitted_by_email=current_user.get("email", "")
                                    )

                                st.session_state["submission_success_msg"] = T("🎉 تم توثيق واعتماد التعديلات بنجاح في قاعدة البيانات!", "🎉 Modifications saved successfully!")
                                st.session_state["portal_show_diff"] = False
                                st.session_state["portal_orig_alloc"] = copy.deepcopy(st.session_state["portal_working_alloc"])
                                st.rerun()

                    with c_act2:
                        if st.button(T("🗑️ حذف المناطق المحددة بالصح", "🗑️ Discard Selected Zones"), type="secondary", use_container_width=True):
                            discarded_count = 0
                            for idx_row, r_edit in edited_diff.iterrows():
                                if r_edit.get("Discard", False):
                                    row_vid = diff_df.loc[idx_row, "Vendor ID"]
                                    row_zone = diff_df.loc[idx_row, "Zone"]
                                    if row_vid in orig_alloc and row_zone in orig_alloc[row_vid]:
                                        working_alloc[row_vid][row_zone] = copy.deepcopy(orig_alloc[row_vid][row_zone])
                                    else:
                                        if row_vid in working_alloc and row_zone in working_alloc[row_vid]:
                                            del working_alloc[row_vid][row_zone]
                                    discarded_count += 1
                            if discarded_count > 0:
                                st.session_state["portal_working_alloc"] = working_alloc
                                st.success(T(f"✅ تم حذف {discarded_count} منطقة وإلغاء تعديلها بنجاح!", f"✅ Discarded {discarded_count} zones successfully!"))
                                st.rerun()
                            else:
                                st.warning(T("يرجى تحديد خانة '🗑️ استبعاد' بجانب المنطقة المراد حذفها من الجدول أولاً.", "Please check 'Discard' column first."))

                    with c_act3:
                        if st.button(T("🔄 تراجع عن الكل", "🔄 Revert All"), use_container_width=True):
                            st.session_state["portal_working_alloc"] = copy.deepcopy(orig_alloc)
                            st.session_state["portal_show_diff"] = False
                            st.rerun()

# ==========================================
# Tab 3: Incoming Requests
# ==========================================
if is_admin:
    with tab3:
        st.header(T("📥 طلبات التسعير والتغطية الواردة من الفروع", "📥 Pricing & Coverage Requests"), anchor="pricing-requests")
        raw_df = get_all_requests_df()
        has_requests = not raw_df.empty and "Zone" in raw_df.columns

        if has_requests:
            try:
                raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                raw_df["Action"] = raw_df.get("Action", "").astype(str)

                for idx, r in raw_df.iterrows():
                    v_id_val = str(r["Vendor ID"]).strip()
                    z_val = str(r.get("Zone", "")).strip()
                    d_val = str(r.get("Distance (km)", "-")).strip()
                    if d_val in ["-", "", "nan", "None"]:
                        computed_d = calc_vendor_zone_distance(v_id_val, z_val, df_vendors, gdf_areas)
                        raw_df.at[idx, "Distance (km)"] = computed_d

                    f_stat = str(r.get("Final_Status", "")).strip()
                    act_val = str(r.get("Action", "")).strip()
                    if f_stat == "Active (Existing)" or act_val.lower() in ["edit", "تعديل"]:
                        raw_df.at[idx, "Action"] = "Edit"
                        raw_df.at[idx, "Final_Status"] = "Edit"

                f_c1, f_c2 = st.columns([1.5, 1.5])
                with f_c1:
                    all_vn = [T("كل الفروع", "All Vendors")] + sorted(raw_df["Vendor Name"].dropna().unique().tolist())
                    f_vname = st.selectbox(T("تصفية باسم الفرع:", "Filter by Vendor Name:"), all_vn, key="req_filter_name")
                with f_c2:
                    subset_for_id = raw_df[raw_df["Vendor Name"] == f_vname] if f_vname != T("كل الفروع", "All Vendors") else raw_df
                    all_vi = [T("كل الأكواد", "All IDs")] + sorted(subset_for_id["Vendor ID"].dropna().unique().tolist())
                    f_vid = st.selectbox(T("تصفية بكود الفرع:", "Filter by Vendor ID:"), all_vi, key="req_filter_id")

                filtered_req = raw_df.copy()
                if f_vname != T("كل الفروع", "All Vendors"):
                    filtered_req = filtered_req[filtered_req["Vendor Name"] == f_vname]
                if f_vid != T("كل الأكواد", "All IDs"):
                    filtered_req = filtered_req[filtered_req["Vendor ID"] == f_vid]

                summary_df = filtered_req.groupby(["Date", "Vendor ID", "Vendor Name"]).agg(
                    Total_Zones=("Zone", "count"),
                    Active_Zones=("Action", lambda s: (s.str.contains("Active|نشط|Edit", case=False)).sum()),
                    Deact_Zones=("Action", lambda s: (s.str.contains("Deactivate|إلغاء", case=False)).sum()),
                    Zones_Preview=("Zone", lambda s: ", ".join(s.head(3)) + ("..." if len(s) > 3 else ""))
                ).reset_index()

                summary_df.rename(columns={
                    "Date": T("تاريخ الإرسال", "Submission Date"),
                    "Vendor ID": T("كود الفرع", "Vendor ID"),
                    "Vendor Name": T("اسم الفرع", "Vendor Name"),
                    "Total_Zones": T("إجمالي المناطق", "Total Zones"),
                    "Active_Zones": T("المناطق النشطة والمعدلة", "Active & Edited Zones"),
                    "Deact_Zones": T("المناطق الملغاة", "Deactivated Zones"),
                    "Zones_Preview": T("معاينة المناطق", "Zones Overview (Preview)")
                }, inplace=True)

                summary_df.insert(0, "Select", True)

                st.write(T("📋 **حدد الطلبات المطلوبة من الجدول أدناه لتحميلها كملف أو استعراضها:**", "📋 **Select submissions from table below to download or view:**"))

                edited_summary = st.data_editor(
                    summary_df,
                    column_config={
                        "Select": st.column_config.CheckboxColumn(T("تحديد", "Select"), default=True),
                        T("تاريخ الإرسال", "Submission Date"): st.column_config.TextColumn(disabled=True),
                        T("كود الفرع", "Vendor ID"): st.column_config.TextColumn(disabled=True),
                        T("اسم الفرع", "Vendor Name"): st.column_config.TextColumn(disabled=True),
                        T("إجمالي المناطق", "Total Zones"): st.column_config.NumberColumn(disabled=True),
                        T("المناطق النشطة والمعدلة", "Active & Edited Zones"): st.column_config.NumberColumn(disabled=True),
                        T("المناطق الملغاة", "Deactivated Zones"): st.column_config.NumberColumn(disabled=True),
                        T("معاينة المناطق", "Zones Overview (Preview)"): st.column_config.TextColumn(disabled=True),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="requests_summary_editor"
                )

                selected_rows = edited_summary[edited_summary["Select"] == True]

                col_d1, col_d2, col_d3 = st.columns([2, 1.5, 1])

                with col_d1:
                    if not selected_rows.empty:
                        sel_keys = set(zip(selected_rows[T("تاريخ الإرسال", "Submission Date")], selected_rows[T("كود الفرع", "Vendor ID")]))
                        mask = [(d, str(v)) in sel_keys for d, v in zip(raw_df["Date"], raw_df["Vendor ID"])]
                        download_df = raw_df[mask].copy()

                        if len(selected_rows) == 1:
                            vname_clean = re.sub(r'[^\w\s-]', '', str(selected_rows.iloc[0][T("اسم الفرع", "Vendor Name")]).strip()).replace(" ", "_")
                            filename = f"Pricing_Request_{vname_clean}.csv"
                        else:
                            filename = f"Combined_Pricing_Requests_{len(selected_rows)}_Vendors.csv"

                        csv_bytes = download_df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(
                            T(f"📥 تحميل ملف CSV مفصل ({len(download_df)} منطقة)", f"📥 Download Detailed CSV ({len(download_df)} zones)"),
                            data=csv_bytes,
                            file_name=filename,
                            mime="text/csv",
                            type="primary",
                            use_container_width=True
                        )
                    else:
                        st.warning(T("يرجى تحديد طلب واحد على الأقل للتحميل.", "Please select at least one request to download."))

                with col_d2:
                    show_details = st.checkbox(T("👁️ استعراض تفاصيل المناطق المسجلة", "👁️ View Detailed Zones Table"), value=True)

                with col_d3:
                    if st.button(T("🗑️ مسح السجلات", "🗑️ Clear Records"), type="secondary", use_container_width=True):
                        st.session_state["session_requests_list"] = []
                        if os.path.exists(REQUESTS_FILE):
                            os.remove(REQUESTS_FILE)
                        st.rerun()

                if show_details and not selected_rows.empty:
                    st.markdown("---")
                    st.subheader(T("🔍 جدول تفاصيل المناطق للطلبات المحددة", "🔍 Detailed Zones for Selected Requests"))
                    st.dataframe(download_df, hide_index=True, use_container_width=True)
            except Exception as e:
                st.error(f"حدث خطأ أثناء قراءة الطلبات: {e}")

        if not has_requests:
            st.info(T("📭 لا توجد طلبات تعديل واردة حالياً من الفروع. (عند إرسال أي تعديل من Vendor Portal سيظهر هنا فوراً)", "📭 No incoming requests found. Submit modifications in Vendor Portal to view them here."))

# ==========================================
# Tab 4: Users Management & Email/Cloud Settings
# ==========================================
if is_master_admin:
    with tab4:
        st.header(T("👥 إدارة المستخدمين والصلاحيات وإعدادات البريد (الأدمن الرئيسي)", "👥 User Management & Email Settings (Master Admin Only)"))
        st.caption(T(f"🔒 صلاحية الوصول لهذه الشاشة محصورة ببريد: `{MASTER_ADMIN_EMAIL}`", f"🔒 Access strictly restricted to: `{MASTER_ADMIN_EMAIL}`"))
        
        valid_chains_data = df_vendors[df_vendors["clean_cid"] != ""].copy()
        chain_opts_map = {}
        if not valid_chains_data.empty:
            for cid_val, c_group in valid_chains_data.groupby("clean_cid"):
                names = [str(n).strip() for n in c_group["clean_chain_name"].unique() if str(n).strip() not in ["", "nan", "None", "-"]]
                c_display_name = names[0] if names else f"Chain {cid_val}"
                branch_count = len(c_group)
                chain_opts_map[str(cid_val)] = f"🏢 {c_display_name} (ID: {cid_val} - {branch_count} {T('فروع', 'branches')})"

        valid_vendors_data = df_vendors[df_vendors["clean_vid"] != ""].copy()
        vendor_opts_map = {}
        if not valid_vendors_data.empty:
            for _, v_row in valid_vendors_data.iterrows():
                vid_val = str(v_row["clean_vid"]).strip()
                v_display_name = str(v_row["clean_name"]).strip()
                v_chain_name = str(v_row["clean_chain_name"]).strip()
                chain_suffix = f" [سلسلة: {v_chain_name}]" if v_chain_name and v_chain_name not in ["", "nan", "None", "-"] else ""
                vendor_opts_map[vid_val] = f"💊 {v_display_name} (ID: {vid_val}{chain_suffix})"

        tab_u1, tab_u2, tab_u3, tab_u4 = st.tabs([
            T("➕ إضافة مستخدم جديد", "➕ Add New User"),
            T("✏️ تعديل صلاحيات وكلمة مرور مستخدم", "✏️ Edit Permissions & Password"),
            T("📋 قائمة المستخدمين", "📋 Users List"),
            T("⚡ إعدادات واختبار Firebase و SMTP", "⚡ Firebase & SMTP Settings")
        ])
        
        with tab_u1:
            st.markdown(f"#### {T('بيانات الحساب الجديد', 'New Account Details')}")
            
            if "user_created_alert" in st.session_state:
                alert_type, alert_txt = st.session_state.pop("user_created_alert")
                if alert_type == "success": st.success(alert_txt)
                else: st.error(alert_txt)

            col_u1, col_u2 = st.columns(2)
            with col_u1:
                u_role = st.selectbox(
                    T("نوع الحساب:", "Role:"), 
                    ["vendor", "admin"], 
                    format_func=lambda x: T("مستخدم فيندور (Vendor User)", "Vendor User") if x == "vendor" else T("مسؤول نظام (Admin)", "Admin"),
                    key="add_user_role_select"
                )
                new_email = st.text_input(T("البريد الإلكتروني:", "Email:"), key="add_user_email_input").strip().lower()
            with col_u2:
                new_password = st.text_input(T("كلمة المرور:", "Password:"), type="password", key="add_user_password_input").strip()

            st.markdown("---")
            access_choice = st.radio(
                T("اختر نطاق الربط والفروع التابعة:", "Assigned Scope:"),
                [
                    T("سلاسل محددة (Chain ID)", "Specific Chains (Chain ID)"),
                    T("فروع محددة (Vendor ID)", "Specific Branches (Vendor ID)"),
                    T("كل فروع القسم (Master Access)", "All Branches (Master Access)")
                ],
                key="add_user_scope_radio"
            )

            access_type = "all"
            selected_access_ids_str = "all"

            if "Chain" in access_choice or "سلاسل" in access_choice:
                access_type = "Chain ID"
                st.info(T("🏢 حدد السلسلة أو السلاسل المطلوبة:", "🏢 Select chain(s):"))
                chosen_chains = st.multiselect(
                    T("اختر من قائمة السلاسل (Chains List):", "Select from Chains:"),
                    options=list(chain_opts_map.keys()),
                    format_func=lambda x: chain_opts_map.get(x, x),
                    key="add_user_chains_multiselect"
                )
                selected_access_ids_str = ", ".join(chosen_chains)

            elif "Vendor" in access_choice or "فروع" in access_choice:
                access_type = "Vendor ID"
                st.info(T("💊 حدد الفروع المستقلة المطلوبة:", "💊 Select individual branch(es):"))
                chosen_vendors = st.multiselect(
                    T("اختر من قائمة الفروع (Vendors List):", "Select from Vendors:"),
                    options=list(vendor_opts_map.keys()),
                    format_func=lambda x: vendor_opts_map.get(x, x),
                    key="add_user_vendors_multiselect"
                )
                selected_access_ids_str = ", ".join(chosen_vendors)
            else:
                access_type = "all"
                selected_access_ids_str = "all"

            st.write("")
            if st.button(T("💾 إنشاء الحساب الآن", "💾 Create User Now"), type="primary", use_container_width=True, key="btn_create_user_submit"):
                if not new_email or not new_password:
                    st.error(T("يرجى إدخال البريد الإلكتروني وكلمة المرور."))
                elif ("Chain" in access_choice or "Vendor" in access_choice) and not selected_access_ids_str.strip():
                    st.error(T("يرجى اختيار سلسلة أو فرع واحد على الأقل من القائمة."))
                else:
                    with st.spinner(T("جارٍ إنشاء الحساب وحفظه في Firebase...", "Creating and saving user to Firebase...")):
                        ok, msg = add_user(new_email, new_password, u_role, access_type, selected_access_ids_str, current_user_dict=current_user)
                        st.session_state["user_created_alert"] = ("success" if ok else "error", msg)
                        st.rerun()

        with tab_u2:
            st.subheader(T("تعديل صلاحيات ومحفظة فروع وكلمة مرور مستخدم مسجل", "Edit User Permissions, Portfolio & Password"))
            users_list_df = get_users_df()
            selected_edit_user = st.selectbox(
                T("اختر المستخدم للتعديل:", "Select User to Edit:"), 
                options=users_list_df["email"].tolist(),
                key="select_user_to_edit"
            )
            user_current_row = users_list_df[users_list_df["email"] == selected_edit_user].iloc[0]

            col_e1, col_e2 = st.columns(2)
            with col_e1:
                e_role = st.selectbox(
                    T("نوع الحساب:", "Role:"),
                    options=["vendor", "admin"],
                    index=0 if user_current_row["role"] == "vendor" else 1,
                    format_func=lambda x: T("مستخدم فيندور (Vendor User)", "Vendor User") if x == "vendor" else T("مسؤول نظام (Admin)", "Admin"),
                    key="edit_user_role_select"
                )
            with col_e2:
                edit_password_val = st.text_input(
                    T("🔑 كلمة المرور الجديدة (اتركه فارغاً للإبقاء على الحالية دون تغيير):", "🔑 New Password (leave blank to keep current):"),
                    type="password",
                    key="edit_user_password_input"
                )

            st.markdown("---")
            current_scope = user_current_row["access_type"]
            default_scope_idx = 0 if current_scope == "Chain ID" else (1 if current_scope == "Vendor ID" else 2)
            
            e_access_choice = st.radio(
                T("اختر نطاق الربط والفروع التابعة:", "Assigned Scope:"),
                [
                    T("سلاسل محددة (Chain ID)", "Specific Chains (Chain ID)"),
                    T("فروع محددة (Vendor ID)", "Specific Branches (Vendor ID)"),
                    T("كل فروع القسم (Master Access)", "All Branches (Master Access)")
                ],
                index=default_scope_idx,
                key="edit_user_scope_radio"
            )

            e_access_type = "all"
            e_selected_access_ids_str = "all"

            if "Chain" in e_access_choice or "سلاسل" in e_access_choice:
                e_access_type = "Chain ID"
                curr_cids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in chain_opts_map]
                st.info(T("🏢 اختر السلاسل التابعة لهذا المستخدم:", "🏢 Select assigned chains:"))
                chosen_chains = st.multiselect(
                    T("قائمة السلاسل (Chains List):", "Chains List:"),
                    options=list(chain_opts_map.keys()),
                    default=curr_cids,
                    format_func=lambda x: chain_opts_map.get(x, x),
                    key="edit_user_chains_multiselect"
                )
                e_selected_access_ids_str = ", ".join(chosen_chains)

            elif "Vendor" in e_access_choice or "فروع" in e_access_choice:
                e_access_type = "Vendor ID"
                curr_vids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in vendor_opts_map]
                st.info(T("💊 اختر الفروع الفردية التابعة لهذا المستخدم:", "💊 Select assigned individual branches:"))
                chosen_vendors = st.multiselect(
                    T("قائمة الفروع (Vendors List):", "Vendors List:"),
                    options=list(vendor_opts_map.keys()),
                    default=curr_vids,
                    format_func=lambda x: vendor_opts_map.get(x, x),
                    key="edit_user_vendors_multiselect"
                )
                e_selected_access_ids_str = ", ".join(chosen_vendors)
            else:
                e_access_type = "all"
                e_selected_access_ids_str = "all"

            st.write("")
            if st.button(T("💾 حفظ التعديلات وتحديث الصلاحيات", "💾 Save Changes & Permissions"), type="primary", use_container_width=True, key="btn_edit_user_submit"):
                with st.spinner(T("جارٍ تحديث البيانات في Firebase...", "Updating user in Firebase...")):
                    ok, msg, updated_row = update_user_permissions(
                        selected_edit_user, 
                        e_role, 
                        e_access_type, 
                        e_selected_access_ids_str, 
                        edit_password_val, 
                        current_user_dict=current_user
                    )
                    if ok:
                        if selected_edit_user.lower() == current_user["email"].lower():
                            st.session_state["current_user"] = updated_row
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_u3:
            users_list_df = get_users_df()
            display_users_df = users_list_df.copy()
            if "password" in display_users_df.columns:
                display_users_df["password"] = "••••••••"
            st.dataframe(display_users_df, use_container_width=True)
            
            deletable = users_list_df[users_list_df["email"].str.lower() != MASTER_ADMIN_EMAIL.lower()]["email"].tolist()
            if deletable:
                st.markdown("---")
                to_del = st.selectbox(T("اختر المستخدم للحذف:", "Select User to Delete:"), deletable, key="delete_user_select")
                if st.button(T("حذف الحساب نهائياً", "Delete User"), type="secondary", key="btn_delete_user"):
                    with st.spinner(T("جارٍ حذف الحساب من Firebase...", "Deleting from Firebase...")):
                        ok, msg = delete_user(to_del, current_user_dict=current_user)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with tab_u4:
            st.subheader(T("⚡ فحص اتصال Firebase Firestore", "⚡ Test Firebase Firestore Connection"))
            
            if st.button(T("🧪 اختبار الاتصال بـ Firebase الآن", "🧪 Test Firebase Connection Now"), type="primary", use_container_width=True, key="btn_test_firebase"):
                with st.spinner(T("جارٍ اختبار الاتصال المباشر بـ Firestore...", "Testing connection to Firebase...")):
                    ok_db, msg_db = test_firebase_connection()
                    if ok_db:
                        st.success(f"✅ {msg_db}")
                    else:
                        st.error(f"❌ {msg_db}")

            st.markdown("---")
            st.subheader(T("⚙️ إعدادات واختبار خادم البريد الإلكتروني (SMTP Settings)", "⚙️ SMTP Settings & Live Test"))
            st.caption(T(
                "اضبط بريد الراسل وكلمة مرور التطبيق هنا لكي يقوم النظام بإرسال الإيميلات وشيتات الإكسيل تلقائياً لك وللفيندور عند تقديم أي طلب.",
                "Configure sender email & App Password to automatically dispatch notification emails with Excel attachments."
            ))
            
            curr_smtp = load_smtp_config()
            
            sc1, sc2 = st.columns(2)
            with sc1:
                cfg_server = st.text_input("SMTP Server:", value=curr_smtp.get("server", "smtp.gmail.com"), key="smtp_cfg_server")
                cfg_sender = st.text_input(T("بريد الراسل (Sender Email):", "Sender Email:"), value=curr_smtp.get("sender_email", ""), placeholder="e.g. yourname@gmail.com", key="smtp_cfg_sender")
                cfg_admin = st.text_input(T("بريد استلام الإشعارات (Admin Recipient):", "Admin Recipient:"), value=curr_smtp.get("admin_email", MASTER_ADMIN_EMAIL), key="smtp_cfg_admin")
            with sc2:
                cfg_port = st.selectbox("SMTP Port:", [587, 465], index=0 if curr_smtp.get("port", 587) == 587 else 1, key="smtp_cfg_port")
                cfg_pass = st.text_input(
                    T("كلمة مرور التطبيقات (App Password - 16 حرفاً):", "Sender App Password (16 chars):"),
                    value=curr_smtp.get("sender_password", ""),
                    type="password",
                    placeholder="xxxx xxxx xxxx xxxx",
                    help=T("استخرج كلمة مرور تطبيقات مكونة من 16 حرفاً من إعدادات أمان حساب جوجل.", "Generate a 16-character App Password from Google Account Security."),
                    key="smtp_cfg_pass"
                )

            st.write("")
            btn_save_col, btn_test_col = st.columns(2)
            
            with btn_save_col:
                if st.button(T("💾 حفظ إعدادات البريد", "💾 Save SMTP Settings"), type="primary", use_container_width=True, key="btn_save_smtp"):
                    ok_s, msg_s = save_smtp_config(cfg_server, cfg_port, cfg_sender, cfg_pass, cfg_admin)
                    if ok_s: st.success(msg_s)
                    else: st.error(msg_s)

            with btn_test_col:
                if st.button(T("🧪 إرسال إيميل تجريبي الآن (Send Test Email)", "🧪 Send Test Email Now"), type="secondary", use_container_width=True, key="btn_test_smtp"):
                    with st.spinner(T("جارٍ الاتصال بخادم البريد وإرسال الرسالة التجريبية...", "Connecting and sending test email...")):
                        test_ok, test_msg = test_smtp_connection(cfg_server, cfg_port, cfg_sender, cfg_pass, cfg_admin)
                        if test_ok:
                            st.success(f"✅ {test_msg}")
                        else:
                            st.error(f"❌ {test_msg}")
