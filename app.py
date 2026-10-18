import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely import wkt
from shapely.geometry import Point
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import numpy as np
import re
import os
import io
import requests
from datetime import datetime

# ==========================================
# 1. إعدادات الصفحة
# ==========================================
st.set_page_config(layout="wide", page_title="Pharmacy & Zones Management", page_icon="💊")

BRANCH_PALETTE = [
    {"hex": "#28a745", "folium": "green", "name": "أخضر"},
    {"hex": "#e67e22", "folium": "orange", "name": "برتقالي"},
    {"hex": "#9b59b6", "folium": "purple", "name": "بنفسجي"},
    {"hex": "#e74c3c", "folium": "red", "name": "أحمر"},
    {"hex": "#17a2b8", "folium": "cadetblue", "name": "تركواز"},
    {"hex": "#d63384", "folium": "pink", "name": "وردي"},
    {"hex": "#0dcaf0", "folium": "lightblue", "name": "سماوي"},
    {"hex": "#198754", "folium": "darkgreen", "name": "أخضر داكن"},
    {"hex": "#8540f5", "folium": "darkpurple", "name": "أرجواني"},
    {"hex": "#a52a2a", "folium": "darkred", "name": "بني"}
]

# ==========================================
# 2. إدارة المستخدمين وقاعدة البيانات الأمنية
# ==========================================
USERS_FILE = "users.csv"

def init_users_db():
    if not os.path.exists(USERS_FILE):
        df_init = pd.DataFrame([{
            "email": "mahmoud.alaa.2@talabat.com",
            "password": "123456",
            "role": "admin",
            "access_type": "all",
            "access_ids": "all"
        }])
        df_init.to_csv(USERS_FILE, index=False)

def get_users_df():
    init_users_db()
    return pd.read_csv(USERS_FILE)

def add_user(email, password, role, access_type="all", access_ids="all"):
    df = get_users_df()
    email_clean = email.strip().lower()
    if email_clean in df["email"].str.lower().values:
        return False, "This email already exists!"
    new_user = pd.DataFrame([{
        "email": email_clean,
        "password": str(password).strip(),
        "role": role,
        "access_type": access_type,
        "access_ids": access_ids
    }])
    df = pd.concat([df, new_user], ignore_index=True)
    df.to_csv(USERS_FILE, index=False)
    return True, "User created successfully!"

def update_user_permissions(email, role, access_type, access_ids):
    df = get_users_df()
    email_clean = email.strip().lower()
    idx = df[df["email"].str.lower() == email_clean].index
    if not idx.empty:
        df.loc[idx, "role"] = role
        df.loc[idx, "access_type"] = access_type
        df.loc[idx, "access_ids"] = access_ids
        df.to_csv(USERS_FILE, index=False)
        return True, "تم تحديث الصلاحيات بنجاح!", df.iloc[idx[0]].to_dict()
    return False, "المستخدم غير موجود.", None

def delete_user(email):
    df = get_users_df()
    if email.strip().lower() == "mahmoud.alaa.2@talabat.com":
        return False, "Cannot delete master admin!"
    df = df[df["email"].str.lower() != email.strip().lower()]
    df.to_csv(USERS_FILE, index=False)
    return True, "User deleted successfully!"

# ==========================================
# 3. دوال المعالجة والمسافات
# ==========================================
def normalize_id(val):
    if pd.isna(val):
        return ""
    s = str(val).strip()
    s = re.sub(r"\.0+$", "", s)
    return s

def parse_yes_no(val, default="Yes"):
    if pd.isna(val) or str(val).strip().lower() in ["", "none", "nan", "null"]:
        return default
    v = str(val).strip().lower()
    return "Yes" if v in ["yes", "y", "true", "1"] else "No"

def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

def get_col(df, possible_names):
    if df.empty:
        return None
    for name in possible_names:
        for col in df.columns:
            if str(name).strip().lower() == str(col).strip().lower():
                return col
    for name in possible_names:
        name_clean = re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()
        for col in df.columns:
            col_clean = re.sub(r'[^a-zA-Z0-9]', '', str(col)).lower()
            if name_clean == col_clean or name_clean in col_clean:
                return col
    return None

def convert_to_csv_url(url):
    if not isinstance(url, str):
        return url
    url = url.strip()
    if "output=csv" in url or "export?format=csv" in url:
        return url
    m_id = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    m_gid = re.search(r"[#&?]gid=([0-9]+)", url)
    if m_id:
        sheet_id = m_id.group(1)
        gid = m_gid.group(1) if m_gid else "0"
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    return url

def read_google_sheet_csv(url):
    csv_url = convert_to_csv_url(url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(csv_url, headers=headers, timeout=15)
        if res.status_code == 200:
            text_sample = res.text[:500].lower()
            if "<!doctype" in text_sample or "<html" in text_sample or "google accounts" in text_sample:
                return pd.DataFrame()
            return pd.read_csv(io.StringIO(res.text))
    except Exception:
        pass
    try:
        return pd.read_csv(csv_url)
    except Exception:
        return pd.DataFrame()

# ==========================================
# 4. جلب وتجهيز البيانات
# ==========================================
@st.cache_data(ttl=1800)
def load_data():
    url_areas = "https://docs.google.com/spreadsheets/d/1Y3AlqaHjp4nZup6QwOBgl6CT5z3XHjfzpRSx5Yw5byk/export?format=csv&gid=0"
    url_vendors = "https://docs.google.com/spreadsheets/d/12SSMW20Two2hRpHOuIXXifweJI82bZpJClhUAWSuYHk/export?format=csv&gid=0"
    url_delivery = "https://docs.google.com/spreadsheets/d/1Gh6xnGNn7yx2g-bdIHC4DvHIMzVkOnh3Fdy6AhQtTmM/export?format=csv&gid=540443526"
    
    # الروابط الاحتياطية المنشورة في حال كانت الشيتات الجديدة مغلقة
    pub_url_areas = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSKMfgg92gyhtKgILJ_IMknkhC7HdjEnvUGu4ef09pEsQmndf2NtYIGlT9RavgA14zT38NMYNoI4OVt/pub?gid=298729660&single=true&output=csv"
    pub_url_vendors = "https://docs.google.com/spreadsheets/d/e/2PACX-1vROpaDpyPadT9VreMa8FCxbBwvfzBxLjkEh8AtLyzQXgbVf3SAheyIjhYexiaVo8LLdjp58Z2DePKZ1/pub?gid=1243657258&single=true&output=csv"
    pub_url_delivery = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR4BDgzbQgwjMgUIl9egw_OzUfT-2NZfQQqGmw6Xzk25NXC6F_8ZQk3JX6xIEkOUgAu7ZDqNe-FnzpY/pub?gid=29074284&single=true&output=csv"

    df_v = read_google_sheet_csv(url_vendors)
    if df_v.empty:
        df_v = read_google_sheet_csv(pub_url_vendors)

    df_a = read_google_sheet_csv(url_areas)
    if df_a.empty:
        df_a = read_google_sheet_csv(pub_url_areas)

    df_d = read_google_sheet_csv(url_delivery)
    if df_d.empty:
        df_d = read_google_sheet_csv(pub_url_delivery)

    # معالجة بيانات الفيندورز
    if not df_v.empty:
        vid_col = get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID", "vendor_id"])
        cid_col = get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID", "chain_id"])
        name_col = get_col(df_v, ["Vendor Attributes Vendor Name (English)", "Vendor Name", "Name", "vendor_name"])
        cname_col = get_col(df_v, ["Chain Attributes Chain Name", "Chain Name", "chain_name"])
        city_col = get_col(df_v, ["Vendor Attributes Vendor City", "City", "Vendor City"])

        active_col = get_col(df_v, ["Vendor Attributes Is Active", "Is Active", "Active", "IsActive", "is_active"])
        hidden_col = get_col(df_v, ["Vendor Attributes Is Hidden", "Is Hidden", "Hidden", "IsHidden", "is_hidden"])

        df_v["clean_vid"] = df_v[vid_col].apply(normalize_id) if vid_col else ""
        df_v["clean_cid"] = df_v[cid_col].apply(normalize_id) if cid_col else ""
        df_v["clean_name"] = df_v[name_col].astype(str).str.strip() if name_col else ("Vendor " + df_v["clean_vid"])
        df_v["clean_chain_name"] = df_v[cname_col].astype(str).str.strip() if cname_col else ""
        df_v["clean_city"] = df_v[city_col].astype(str).str.strip() if city_col else ""

        df_v["clean_active"] = df_v[active_col].apply(lambda x: parse_yes_no(x, "Yes")) if active_col else "Yes"
        df_v["clean_hidden"] = df_v[hidden_col].apply(lambda x: parse_yes_no(x, "No")) if hidden_col else "No"

        map_loc_col = get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location", "Coordinates"])
        lat_col = get_col(df_v, ["Latitude", "lat", "Lat"])
        lng_col = get_col(df_v, ["Longitude", "lng", "Lng", "Long", "lon"])

        if map_loc_col:
            coords = df_v[map_loc_col].astype(str).str.split(r'[,;]+', expand=True)
            df_v["lat"] = pd.to_numeric(coords[0].str.strip(), errors="coerce")
            df_v["lng"] = pd.to_numeric(coords[1].str.strip(), errors="coerce")
        elif lat_col and lng_col:
            df_v["lat"] = pd.to_numeric(df_v[lat_col], errors="coerce")
            df_v["lng"] = pd.to_numeric(df_v[lng_col], errors="coerce")
        else:
            df_v["lat"] = np.nan
            df_v["lng"] = np.nan

        df_v = df_v[df_v["clean_vid"] != ""].copy()

    # معالجة بيانات التوصيل
    if not df_d.empty and not df_v.empty:
        d_vid_col = get_col(df_d, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
        d_cid_col = get_col(df_d, ["Chain ID", "Chain Id", "ChainID", "chain_id"])
        d_zone_col = get_col(df_d, ["Area Name", "Delivery Area Name", "Zone", "Delivery Location Area Name", "Area", "Delivery Zone"])
        d_time_col = get_col(df_d, ["Delivery Time", "Time", "Duration"])
        d_fee_col = get_col(df_d, ["Delivery Fees", "Fee", "Delivery Fee", "Price"])

        df_d["clean_vid"] = df_d[d_vid_col].apply(normalize_id) if d_vid_col else ""
        df_d["clean_cid"] = df_d[d_cid_col].apply(normalize_id) if d_cid_col else ""
        df_d["clean_zone"] = df_d[d_zone_col].astype(str).str.strip() if d_zone_col else ""
        df_d["clean_time"] = df_d[d_time_col].astype(str).str.strip() if d_time_col else ""
        df_d["clean_fee"] = df_d[d_fee_col].astype(str).str.strip() if d_fee_col else ""

        valid_vids = set(df_v["clean_vid"].unique()) - {""}
        valid_cids = set(df_v["clean_cid"].unique()) - {""}

        mask = (df_d["clean_vid"].isin(valid_vids)) | (df_d["clean_cid"].isin(valid_cids))
        df_d = df_d[mask].copy()

    # معالجة المناطق الجغرافية
    if not df_a.empty:
        poly_col = get_col(df_a, ["Delivery Location Area Polygon", "Polygon", "WKT", "Area Polygon"])
        if poly_col:
            df_a["cleaned_wkt"] = df_a[poly_col].apply(clean_wkt)
            
            geometries, valid_indices = [], []
            for idx, wkt_str in df_a["cleaned_wkt"].items():
                if pd.notnull(wkt_str):
                    try:
                        geometries.append(wkt.loads(wkt_str))
                        valid_indices.append(idx)
                    except Exception:
                        pass
                        
            gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
            gdf_a["area_size"] = gdf_a["geometry"].area
            
            area_name_col = get_col(gdf_a, ["Delivery Location Area Name", "Area Name", "Name"])
            if area_name_col:
                gdf_a["Delivery Location Area Name"] = gdf_a[area_name_col].astype(str).str.strip()
                mask_mcd = gdf_a["Delivery Location Area Name"].str.contains(r"mcd|mcdonald", case=False, na=False)
                gdf_a = gdf_a[(~mask_mcd) & (gdf_a["area_size"] < 0.5)].copy()
                
            gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
            centroids = gdf_a.geometry.centroid
            gdf_a["centroid_lat"] = centroids.y
            gdf_a["centroid_lng"] = centroids.x
            gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
        else:
            gdf_a = gpd.GeoDataFrame()
    else:
        gdf_a = gpd.GeoDataFrame()

    return df_v, gdf_a, df_d

df_vendors, gdf_areas, df_delivery = load_data()

def get_user_vendors(user_dict, df_v):
    if df_v.empty:
        return pd.DataFrame(columns=["clean_vid", "clean_cid", "clean_name", "clean_chain_name", "clean_city", "clean_active", "clean_hidden", "lat", "lng"])
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

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    if gdf_areas.empty or pd.isna(lat) or pd.isna(lng):
        return gpd.GeoDataFrame()
    v_point = Point(lng, lat)
    radius_deg = radius_km / 111.0
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(radius_deg))
    return gdf_areas[nearby_mask].copy()

REQUESTS_FILE = "vendor_pricing_requests.csv"

def init_requests_db():
    if not os.path.exists(REQUESTS_FILE):
        empty_df = pd.DataFrame(columns=[
            "Date", "Vendor ID", "Vendor Name", "Zone", "Classification", 
            "Action", "Distance (km)", "Delivery Time", "Delivery Fees", "Final_Status", "Status"
        ])
        empty_df.to_csv(REQUESTS_FILE, index=False)

def save_detailed_request(vendor_id, vendor_name, edited_df):
    init_requests_db()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_df = edited_df.copy()
    save_df.insert(0, "Date", date_str)
    save_df.insert(1, "Vendor ID", str(vendor_id))
    save_df.insert(2, "Vendor Name", vendor_name)
    save_df["Status"] = "Pending"
    
    save_df.to_csv(REQUESTS_FILE, mode="a", header=False, index=False)

def build_vendor_popup_html(v_row, df_delivery):
    v_id = str(v_row.get("clean_vid", ""))
    c_id = str(v_row.get("clean_cid", ""))
    v_name = v_row.get("clean_name", "")
    c_name = v_row.get("clean_chain_name", "")
    v_city = v_row.get("clean_city", "")
    is_act = v_row.get("clean_active", "Yes")
    is_hid = v_row.get("clean_hidden", "No")

    status_badge = "<span style='color:#198754; font-weight:bold;'>🟢 نشط (Active)</span>" if is_act == "Yes" else "<span style='color:#dc3545; font-weight:bold;'>🔴 غير نشط (Inactive)</span>"
    hidden_badge = "<span style='color:#fd7e14; font-weight:bold;'> | 👁️ مخفي (Hidden)</span>" if is_hid == "Yes" else ""

    match_d = pd.DataFrame()
    if not df_delivery.empty and "clean_vid" in df_delivery.columns:
        match_d = df_delivery[df_delivery["clean_vid"] == v_id]

    html = f"""<div style='font-family: Arial, sans-serif; width: 280px; font-size: 13px;'>
<h4 style='margin:0 0 5px 0; color:#0d6efd;'>💊 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code><br>
<b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>City:</b> {v_city}<br>
<b>الحالة:</b> {status_badge}{hidden_badge}<br>
<hr style='margin:6px 0; border:0; border-top:1px solid #ddd;'>"""

    if not match_d.empty and "clean_zone" in match_d.columns:
        zone_count = len(match_d["clean_zone"].dropna().unique())
        html += f"<b style='color:#198754;'>🛵 مناطق توصيل الفرع ({zone_count}):</b>"
        html += "<div style='max-height:150px; overflow-y:auto; margin-top:5px; border:1px solid #dee2e6; border-radius:4px;'>"
        html += "<table style='width:100%; font-size:11px; border-collapse:collapse;'>"
        html += "<tr style='background:#f8f9fa; text-align:left; position:sticky; top:0;'><th style='padding:4px; border-bottom:1px solid #ddd;'>المنطقة</th><th style='padding:4px; border-bottom:1px solid #ddd;'>الوقت</th><th style='padding:4px; border-bottom:1px solid #ddd;'>السعر</th></tr>"
        for _, r in match_d.iterrows():
            z = r.get("clean_zone", "")
            t = r.get("clean_time", "-")
            f = r.get("clean_fee", "-")
            if z:
                html += f"<tr style='border-bottom:1px solid #f1f1f1;'><td style='padding:3px;'>{z}</td><td style='padding:3px;'>{t}</td><td style='padding:3px;'>{f}</td></tr>"
        html += "</table></div>"
    else:
        html += "<div style='color:#6c757d; font-size:12px; margin-top:4px;'>لا توجد مناطق توصيل مخصصة لهذا الفرع بشكل فردي.</div>"

    html += "</div>"
    return html

# ==========================================
# 5. شاشة تسجيل الدخول (Authentication)
# ==========================================
init_users_db()
init_requests_db()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["current_user"] = None

if not st.session_state["logged_in"]:
    st.markdown("<h2 style='text-align: center;'>🔐 تسجيل الدخول إلى النظام</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray;'>يرجى إدخال البريد الإلكتروني وكلمة المرور للمتابعة</p>", unsafe_allow_html=True)
    
    _, col_form, _ = st.columns([1, 1.5, 1])
    with col_form:
        with st.form("login_form"):
            email_input = st.text_input("البريد الإلكتروني (Email):").strip().lower()
            password_input = st.text_input("كلمة المرور (Password):", type="password").strip()
            login_btn = st.form_submit_button("تسجيل الدخول", type="primary", use_container_width=True)
            
            if login_btn:
                users_df = get_users_df()
                match = users_df[(users_df["email"].str.lower() == email_input) & (users_df["password"].astype(str) == password_input)]
                
                if not match.empty:
                    user_row = match.iloc[0].to_dict()
                    st.session_state["logged_in"] = True
                    st.session_state["current_user"] = user_row
                    st.success(f"تم تسجيل الدخول بنجاح كـ {user_row['role']}!")
                    st.rerun()
                else:
                    st.error("❌ البريد الإلكتروني أو كلمة المرور غير صحيحة.")
    st.stop()

current_user = st.session_state["current_user"]
is_admin = current_user["role"] == "admin"

user_vendors = get_user_vendors(current_user, df_vendors)
total_user_branches = len(user_vendors) if not user_vendors.empty else 0
active_user_branches = len(user_vendors[user_vendors["clean_active"] == "Yes"]) if (not user_vendors.empty and "clean_active" in user_vendors.columns) else 0
inactive_user_branches = total_user_branches - active_user_branches
hidden_user_branches = len(user_vendors[user_vendors["clean_hidden"] == "Yes"]) if (not user_vendors.empty and "clean_hidden" in user_vendors.columns) else 0

with st.sidebar:
    st.write(f"👤 **المستخدم:** `{current_user['email']}`")
    st.write(f"🛡️ **الصلاحية:** `{current_user['role'].upper()}`")
    if current_user.get("access_type") != "all":
        st.write(f"📌 **نطاق الربط:** `{current_user['access_type']}`")
    st.markdown("---")
    
    st.metric(
        label="🏬 الفروع التابعة لك",
        value=f"{total_user_branches}",
        delta=f"🟢 {active_user_branches} فرع نشط (Active)" if total_user_branches > 0 else "0 نشط"
    )
    st.caption(f"📊 تفاصيل فروعك: نشط: {active_user_branches} | غير نشط: {inactive_user_branches} | مخفي: {hidden_user_branches}")
    
    st.metric("🗺️ إجمالي المناطق الجغرافية", len(gdf_areas))
    
    if "last_sync_time" not in st.session_state:
        st.session_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        
    if st.button("🔄 مزامنة وتحديث البيانات الآن", use_container_width=True):
        st.cache_data.clear()
        st.session_state["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        st.rerun()
        
    st.caption(f"🕒 **تاريخ آخر مزامنة:** `{st.session_state['last_sync_time']}`")
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج (Logout)", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# تنبيه في حال كانت الشيتات فارغة أو مغلقة
if df_vendors.empty:
    st.warning("⚠️ **تنبيه:** لم يتم تحميل بيانات الفيندورز من شيت Google Sheets. يرجى التأكد من ضبط إعدادات المشاركة للشيتات على **'Anyone with the link can view'**.")

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Overview Map", "🛒 Vendor Portal", "📥 Incoming Requests", "👥 Users"])
else:
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map (محمية بالكامل ضد أي بيانات فارغة)
# ==========================================
if is_admin:
    with tab1:
        st.header("🗺️ Admin Overview & Simulation Map")
        
        map_active = st.toggle("⚡ تفعيل خريطة الإدارة العامة (Admin Map)", value=False, key="toggle_admin_map")
        
        if not map_active:
            st.info("⏸️ خريطة المراقبة العامة معطلة لتوفير أقصى سرعة لبوابة الفيندورز. فَعِّل الزر أعلاه عند الحاجة لاستعراض التغطية العامة.")
        else:
            f_col1, f_col2, f_col3 = st.columns([1.5, 1.5, 1.8])
            
            with f_col1:
                if not user_vendors.empty and "clean_city" in user_vendors.columns:
                    all_cities = ["All Cities"] + sorted([c for c in user_vendors["clean_city"].unique() if c])
                else:
                    all_cities = ["All Cities"]
                selected_city = st.selectbox("1. المدينة / المحافظة:", options=all_cities, key="admin_map_city")

            if not user_vendors.empty and "clean_city" in user_vendors.columns and selected_city != "All Cities":
                city_df = user_vendors[user_vendors["clean_city"] == selected_city]
            else:
                city_df = user_vendors.copy() if not user_vendors.empty else pd.DataFrame()

            with f_col2:
                if not city_df.empty and "clean_cid" in city_df.columns and "clean_chain_name" in city_df.columns:
                    chains_in_city = city_df[["clean_cid", "clean_chain_name"]].drop_duplicates()
                    chains_in_city = chains_in_city[chains_in_city["clean_cid"] != ""]
                    chain_map = dict(zip(chains_in_city["clean_cid"], chains_in_city["clean_chain_name"] + " (" + chains_in_city["clean_cid"] + ")"))
                    chain_options = ["All Chains (كل السلاسل)"] + list(chain_map.keys())
                else:
                    chain_map = {}
                    chain_options = ["All Chains (كل السلاسل)"]
                    
                selected_chain = st.selectbox(
                    "2. السلسلة (Chain):",
                    options=chain_options,
                    format_func=lambda x: "All Chains (كل السلاسل)" if x == "All Chains (كل السلاسل)" else chain_map.get(x, x),
                    key="admin_map_chain"
                )

            if not city_df.empty and "clean_cid" in city_df.columns and selected_chain != "All Chains (كل السلاسل)":
                chain_filtered_vendors = city_df[city_df["clean_cid"] == selected_chain]
            else:
                chain_filtered_vendors = city_df.copy()

            with f_col3:
                if not chain_filtered_vendors.empty and "clean_vid" in chain_filtered_vendors.columns and "clean_name" in chain_filtered_vendors.columns:
                    vendor_opts = dict(zip(
                        chain_filtered_vendors["clean_vid"],
                        chain_filtered_vendors["clean_name"] + " (ID: " + chain_filtered_vendors["clean_vid"] + ")"
                    ))
                    vendor_options = ["All Vendors (كل الفروع)"] + list(vendor_opts.keys())
                else:
                    vendor_opts = {}
                    vendor_options = ["All Vendors (كل الفروع)"]
                    
                selected_vendor = st.selectbox(
                    "3. الفرع (Vendor):",
                    options=vendor_options,
                    format_func=lambda x: "All Vendors (كل الفروع)" if x == "All Vendors (كل الفروع)" else vendor_opts.get(x, x),
                    key="admin_map_vendor"
                )

            f2_col1, f2_col2, f2_col3 = st.columns([1.5, 1.5, 1.8])
            with f2_col1:
                selected_active = st.selectbox(
                    "4. حالة التفعيل (Is Active):",
                    options=["All (الكل)", "Active Only (نشط فقط - Yes)", "Inactive Only (غير نشط - No)"],
                    key="admin_filter_active"
                )
            with f2_col2:
                selected_hidden = st.selectbox(
                    "5. حالة الظهور (Is Hidden):",
                    options=["All (الكل)", "Visible Only (الظاهر فقط - No)", "Hidden Only (المخفي فقط - Yes)"],
                    key="admin_filter_hidden"
                )
            with f2_col3:
                st.write("")
                st.write("")
                if st.button("🔄 إعادة ضبط الفلاتر", key="admin_reset_filters", use_container_width=True):
                    st.rerun()

            display_vendors = chain_filtered_vendors.copy()
            if not display_vendors.empty and "clean_vid" in display_vendors.columns and selected_vendor != "All Vendors (كل الفروع)":
                display_vendors = display_vendors[display_vendors["clean_vid"] == selected_vendor]
                
            if not display_vendors.empty and "clean_active" in display_vendors.columns:
                if selected_active == "Active Only (نشط فقط - Yes)":
                    display_vendors = display_vendors[display_vendors["clean_active"] == "Yes"]
                elif selected_active == "Inactive Only (غير نشط - No)":
                    display_vendors = display_vendors[display_vendors["clean_active"] == "No"]
                    
            if not display_vendors.empty and "clean_hidden" in display_vendors.columns:
                if selected_hidden == "Visible Only (الظاهر فقط - No)":
                    display_vendors = display_vendors[display_vendors["clean_hidden"] == "No"]
                elif selected_hidden == "Hidden Only (المخفي فقط - Yes)":
                    display_vendors = display_vendors[display_vendors["clean_hidden"] == "Yes"]

            if not display_vendors.empty and "lat" in display_vendors.columns and "lng" in display_vendors.columns:
                plot_vendors = display_vendors.dropna(subset=["lat", "lng"]).copy()
            else:
                plot_vendors = pd.DataFrame()

            cnt_total = len(display_vendors)
            cnt_active = len(display_vendors[display_vendors["clean_active"] == "Yes"]) if ("clean_active" in display_vendors.columns and not display_vendors.empty) else 0
            cnt_inactive = cnt_total - cnt_active
            cnt_hidden = len(display_vendors[display_vendors["clean_hidden"] == "Yes"]) if ("clean_hidden" in display_vendors.columns and not display_vendors.empty) else 0

            card_col1, card_col2, card_col3, card_col4 = st.columns(4)
            card_col1.metric("الفروع المعروضة", cnt_total)
            card_col2.metric("🟢 النشطة (Active)", cnt_active)
            card_col3.metric("🔴 غير النشطة (Inactive)", cnt_inactive)
            card_col4.metric("👁️ المخفية (Hidden)", cnt_hidden)

            vendor_color_map = {}
            if not chain_filtered_vendors.empty and selected_chain != "All Chains (كل السلاسل)":
                chain_branches = chain_filtered_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                for idx, (_, b_row) in enumerate(chain_branches.iterrows()):
                    pal_entry = BRANCH_PALETTE[idx % len(BRANCH_PALETTE)]
                    vendor_color_map[b_row["clean_vid"]] = {
                        "name": b_row["clean_name"],
                        "hex": pal_entry["hex"],
                        "folium": pal_entry["folium"],
                        "color_name": pal_entry["name"]
                    }
            elif not display_vendors.empty and selected_vendor != "All Vendors (كل الفروع)":
                v_name_sel = display_vendors.iloc[0]["clean_name"]
                vendor_color_map[selected_vendor] = {
                    "name": v_name_sel,
                    "hex": "#28a745",
                    "folium": "green",
                    "color_name": "أخضر"
                }

            zone_to_vendor_info = {}
            if not df_delivery.empty and vendor_color_map:
                relevant_vids = set(vendor_color_map.keys())
                rel_del = df_delivery[df_delivery["clean_vid"].isin(relevant_vids)]

                for _, r in rel_del.iterrows():
                    z_norm = str(r.get("clean_zone", "")).strip().lower()
                    if not z_norm:
                        continue
                    vid = str(r.get("clean_vid", ""))
                    v_info = vendor_color_map.get(vid)
                    
                    if v_info:
                        if z_norm not in zone_to_vendor_info:
                            zone_to_vendor_info[z_norm] = []
                        zone_to_vendor_info[z_norm].append({
                            "vid": vid,
                            "name": v_info["name"],
                            "hex": v_info["hex"],
                            "time": r.get("clean_time", "-"),
                            "fee": r.get("clean_fee", "-")
                        })

            if selected_chain != "All Chains (كل السلاسل)" and vendor_color_map:
                st.write("🎨 **دليل تمييز ألوان الفروع ومناطق توصيلها:**")
                n_cols = min(max(len(vendor_color_map), 1), 4)
                leg_cols = st.columns(n_cols)
                for idx, (b_vid, b_info) in enumerate(vendor_color_map.items()):
                    with leg_cols[idx % n_cols]:
                        st.markdown(
                            f"<div style='padding:6px 10px; border-radius:5px; margin-bottom:6px; border-left: 6px solid {b_info['hex']}; background: #f8f9fa; font-size:12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>"
                            f"<b>{b_info['name']}</b><br><span style='color:gray;'>Vendor ID: {b_vid}</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )

            if not gdf_areas.empty:
                gdf_areas_plot = gdf_areas[["Delivery Location Area Name", "geometry"]].copy()

                def assign_zone_styling(area_name):
                    z_clean = str(area_name).strip().lower()
                    if z_clean in zone_to_vendor_info:
                        info_list = zone_to_vendor_info[z_clean]
                        primary_info = info_list[0]
                        branch_labels = [f"{x['name']} ({x['vid']})" for x in info_list]
                        desc = " | ".join(branch_labels)
                        return primary_info["hex"], primary_info["hex"], 0.55, 2.2, desc, True
                    return "#3388ff", "#002266", 0.12, 1.0, "منطقة عامة (غير مسجلة لتوصيل هذا الفرع)", False

                props = gdf_areas_plot["Delivery Location Area Name"].apply(assign_zone_styling)
                gdf_areas_plot["fill_color"] = [p[0] for p in props]
                gdf_areas_plot["border_color"] = [p[1] for p in props]
                gdf_areas_plot["fill_opacity"] = [p[2] for p in props]
                gdf_areas_plot["weight"] = [p[3] for p in props]
                gdf_areas_plot["coverage_info"] = [p[4] for p in props]

            if selected_vendor != "All Vendors (كل الفروع)" and not plot_vendors.empty:
                map_center = [plot_vendors.iloc[0]["lat"], plot_vendors.iloc[0]["lng"]]
                zoom_lvl = 13
            elif not plot_vendors.empty:
                map_center = [plot_vendors["lat"].mean(), plot_vendors["lng"].mean()]
                zoom_lvl = 12 if selected_chain != "All Chains (كل السلاسل)" else 10 if selected_city != "All Cities" else 7
            else:
                map_center = [30.0444, 31.2357]
                zoom_lvl = 7

            m_admin = folium.Map(location=map_center, zoom_start=zoom_lvl)
            css_style = "<style>.leaflet-interactive:focus, path.leaflet-interactive:focus, svg:focus {outline: none !important; box-shadow: none !important;} path.leaflet-interactive:hover {cursor: pointer;}</style>"
            m_admin.get_root().html.add_child(folium.Element(css_style))

            if not gdf_areas.empty:
                folium.GeoJson(
                    gdf_areas_plot[["Delivery Location Area Name", "coverage_info", "fill_color", "border_color", "fill_opacity", "weight", "geometry"]].to_json(),
                    name="Delivery Zones",
                    style_function=lambda feature: {
                        "fillColor": feature["properties"].get("fill_color", "#3388ff"),
                        "color": feature["properties"].get("border_color", "#002266"),
                        "weight": feature["properties"].get("weight", 1.0),
                        "fillOpacity": feature["properties"].get("fill_opacity", 0.12)
                    },
                    highlight_function=lambda feature: {
                        "color": "#ffc107",
                        "weight": 3.2,
                        "fillOpacity": 0.65
                    },
                    tooltip=folium.GeoJsonTooltip(
                        fields=["Delivery Location Area Name", "coverage_info"],
                        aliases=["المنطقة: ", "تغطية الفرع: "]
                    ),
                    popup=folium.GeoJsonPopup(
                        fields=["Delivery Location Area Name", "coverage_info"],
                        aliases=["اسم المنطقة: ", "الفروع المسؤولة عن التوصيل: "]
                    )
                ).add_to(m_admin)

            if not plot_vendors.empty:
                cluster = MarkerCluster().add_to(m_admin)
                
                for _, row in plot_vendors.iterrows():
                    popup_content = build_vendor_popup_html(row, df_delivery)
                    vid_str = row["clean_vid"]
                    b_color_info = vendor_color_map.get(vid_str)
                    pin_color = b_color_info.get("folium", "green") if b_color_info else "blue"
                    is_single_focus = (selected_vendor != "All Vendors (كل الفروع)" and vid_str == selected_vendor)
                    
                    if is_single_focus:
                        folium.Marker(
                            location=[row['lat'], row['lng']],
                            popup=folium.Popup(popup_content, max_width=320),
                            tooltip=f"💊 {row['clean_name']} (ID: {vid_str})",
                            icon=folium.Icon(color="green", icon="medkit", prefix="fa")
                        ).add_to(m_admin)
                    else:
                        folium.Marker(
                            location=[row['lat'], row['lng']],
                            popup=folium.Popup(popup_content, max_width=320),
                            tooltip=f"💊 {row['clean_name']} ({vid_str})",
                            icon=folium.Icon(color=pin_color, icon="medkit", prefix="fa")
                        ).add_to(cluster)

            st_folium(m_admin, width="100%", height=620, key=f"admin_overview_map_{selected_city}_{selected_chain}_{selected_vendor}_{selected_active}_{selected_hidden}", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal
# ==========================================
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    
    target_vid = ""

    if is_admin:
        vendor_input_raw = st.text_input(
            "Enter Vendor ID:",
            placeholder="أدخل كود الفرع / Vendor ID...",
            key="admin_vendor_input_field"
        ).strip()

        if vendor_input_raw:
            clean_search = normalize_id(vendor_input_raw)
            if not user_vendors.empty and "clean_vid" in user_vendors.columns:
                match_vid = user_vendors[user_vendors["clean_vid"] == clean_search]
            else:
                match_vid = pd.DataFrame()
            
            if not match_vid.empty:
                target_vid = clean_search
            else:
                st.error("❌ كود الفرع غير مسجل في قاعدة البيانات أو غير مصرح لك بإدارته.")
    else:
        allowed_raw = str(current_user["access_ids"]).split(",")
        allowed_ids = [normalize_id(x) for x in allowed_raw if x.strip()]
        
        if not user_vendors.empty:
            if current_user["access_type"] == "Chain ID":
                permitted_vendors = user_vendors[user_vendors["clean_cid"].isin(allowed_ids)]
            else:
                permitted_vendors = user_vendors[user_vendors["clean_vid"].isin(allowed_ids)]
        else:
            permitted_vendors = pd.DataFrame()
            
        if permitted_vendors.empty:
            st.warning("⚠️ لا توجد فروع أو فيندورز مربوطة بحسابك حتى الآن. يرجى مراجعة إدارة النظام.")
        else:
            options_dict = dict(zip(
                permitted_vendors["clean_vid"],
                permitted_vendors["clean_name"] + " (" + permitted_vendors["clean_vid"] + ")"
            ))
            target_vid = st.selectbox(
                "اختر الفرع الذي تريد تعديل مناطقه:",
                options=list(options_dict.keys()),
                format_func=lambda x: options_dict[x]
            )

    if target_vid and not user_vendors.empty:
        v_id_clean = normalize_id(target_vid)
        vendor_data = user_vendors[user_vendors["clean_vid"] == v_id_clean]
        
        if vendor_data.empty:
            st.error("Invalid Vendor ID.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row["clean_name"]
            v_chain_id = v_row["clean_cid"]
            v_city = v_row["clean_city"]
            
            has_real_coords = pd.notna(v_row["lat"]) and pd.notna(v_row["lng"])
            
            st.success(f"Welcome: **{v_name}** | City: {v_city} | Vendor ID: `{v_id_clean}` | Chain ID: `{v_chain_id}`")

            if not has_real_coords:
                st.warning("⚠️ لم يتم العثور على إحداثيات جغرافية لهذا الفرع في قاعدة البيانات. يرجى تحديث الإحداثيات لحساب المسافات آلياً.")

            map_radius_km = st.slider("Map View Radius (km):", min_value=3, max_value=40, value=10, step=1)
            
            if has_real_coords:
                portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km)
            else:
                portal_areas = gdf_areas.head(30).copy() if not gdf_areas.empty else gpd.GeoDataFrame()
                
            if not portal_areas.empty:
                portal_areas = portal_areas.sort_values(by="area_size", ascending=False)
            
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist()) if not gdf_areas.empty else []
            zone_lookup = {z.strip().lower(): z for z in all_available_zones}

            pre_filled_zones = []
            pre_filled_data = {}
            if not df_delivery.empty and "clean_vid" in df_delivery.columns:
                d_zone_col = get_col(df_delivery, ["Area Name", "Delivery Area Name", "Zone", "Delivery Location Area Name", "Area", "Delivery Zone"])
                d_time_col = get_col(df_delivery, ["Delivery Time", "Time", "Duration"])
                d_fee_col = get_col(df_delivery, ["Delivery Fees", "Fee", "Delivery Fee", "Price"])

                my_del_df = df_delivery[df_delivery["clean_vid"] == v_id_clean]

                if not my_del_df.empty and d_zone_col:
                    for _, d_row in my_del_df.iterrows():
                        raw_z_name = str(d_row[d_zone_col]).strip()
                        canonical_zone = zone_lookup.get(raw_z_name.lower())
                        
                        if canonical_zone:
                            if canonical_zone not in pre_filled_zones:
                                pre_filled_zones.append(canonical_zone)
                            pre_filled_data[canonical_zone] = {
                                "time": str(d_row[d_time_col]) if d_time_col and pd.notna(d_row[d_time_col]) else "",
                                "fees": float(d_row[d_fee_col]) if d_fee_col and pd.notna(d_row[d_fee_col]) else None
                            }

            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                initial_covered = list(pre_filled_zones)
                st.session_state["ms_zones_input"] = list(initial_covered)
                st.session_state["applied_zones"] = list(initial_covered)
                st.session_state["pre_filled_zones"] = list(pre_filled_zones)
                st.session_state["pre_filled_data"] = pre_filled_data
                st.session_state["last_click_sig"] = None
                st.session_state["ms_version"] = 0
                st.session_state["show_pricing_table"] = False

            valid_selected = [z for z in st.session_state.get("ms_zones_input", []) if z in all_available_zones]
            st.session_state["ms_zones_input"] = valid_selected

            valid_applied = [z for z in st.session_state.get("applied_zones", []) if z in all_available_zones]
            st.session_state["applied_zones"] = valid_applied
            current_applied = valid_applied

            if pre_filled_zones:
                st.info(f"✨ تم استرجاع ({len(pre_filled_zones)}) منطقة مسجلة حالياً لهذا الفرع في قاعدة البيانات.")

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            with col_map:
                st.subheader(f"🗺️ Map ({len(current_applied)} Zones Applied)")
                st.caption("💡 انقر على المناطق التي تريد إضافتها/إزالتها، ثم اضغط 'Apply to Map' بالأعلى لترقية الخريطة.")

                map_center = [v_row["lat"], v_row["lng"]] if has_real_coords else [30.0444, 31.2357]
                v_map = folium.Map(location=map_center, zoom_start=13 if has_real_coords else 11)
                
                if has_real_coords:
                    folium.Marker(location=[v_row["lat"], v_row["lng"]], popup=f"<b>{v_name}</b>", icon=folium.Icon(color="green", icon="medkit", prefix="fa")).add_to(v_map)

                applied_set = set(current_applied)

                def vendor_zone_style(feature):
                    name = feature["properties"]["Delivery Location Area Name"]
                    if name in applied_set:
                        return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                    else:
                        return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.2, "fillOpacity": 0.18}

                css_fix_box = "<style>.leaflet-interactive:focus, path.leaflet-interactive:focus, svg:focus { outline: none !important; box-shadow: none !important; } path.leaflet-interactive:hover { cursor: pointer; stroke: #ffc107 !important; stroke-width: 3.5px !important; }</style>"
                v_map.get_root().html.add_child(folium.Element(css_fix_box))

                if not portal_areas.empty:
                    folium.GeoJson(
                        portal_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style_function=vendor_zone_style,
                        highlight_function=lambda feature: {"color": "#ffc107", "weight": 3.5, "fillOpacity": 0.40},
                        tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["انقر لتحديد المنطقة: "])
                    ).add_to(v_map)

                map_click_data = st_folium(
                    v_map,
                    width="100%",
                    height=500,
                    key=f"vmap_interactive_{v_id_clean}_{map_radius_km}",
                    returned_objects=["last_active_drawing", "last_object_clicked"]
                )

                if map_click_data:
                    clicked_feature = map_click_data.get("last_active_drawing") or map_click_data.get("last_object_clicked")
                    if clicked_feature and isinstance(clicked_feature, dict) and "properties" in clicked_feature:
                        zone_clicked = clicked_feature["properties"].get("Delivery Location Area Name")
                        if zone_clicked and zone_clicked in all_available_zones:
                            click_sig = f"{zone_clicked}_{str(clicked_feature.get('id', ''))}"
                            if click_sig != st.session_state.get("last_click_sig"):
                                st.session_state["last_click_sig"] = click_sig
                                curr_selected = list(st.session_state.get("ms_zones_input", []))
                                if zone_clicked in curr_selected:
                                    curr_selected.remove(zone_clicked)
                                else:
                                    curr_selected.append(zone_clicked)
                                st.session_state["ms_zones_input"] = curr_selected
                                st.session_state["ms_version"] = st.session_state.get("ms_version", 0) + 1
                                st.session_state["show_pricing_table"] = False
                                st.rerun()

            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("المناطق المحددة تتجمع هنا، وعند الانتهاء اضغط Apply to Map:")

                widget_key = f"vendor_multiselect_box_{st.session_state.get('ms_version', 0)}"
                chosen_zones = st.multiselect(
                    "Service Areas:",
                    options=all_available_zones,
                    default=st.session_state.get("ms_zones_input", []),
                    key=widget_key
                )

                btn_col1, btn_col2 = st.columns([1, 1])
                with btn_col1:
                    if st.button("👁️ Apply to Map", type="secondary", use_container_width=True):
                        st.session_state["applied_zones"] = chosen_zones.copy()
                        st.session_state["ms_zones_input"] = chosen_zones.copy()
                        st.session_state["show_pricing_table"] = False
                        st.rerun()
                        
                with btn_col2:
                    if st.button("🚀 Submit Selection", type="primary", use_container_width=True):
                        st.session_state["applied_zones"] = chosen_zones.copy()
                        st.session_state["ms_zones_input"] = chosen_zones.copy()
                        st.session_state["show_pricing_table"] = True
                        st.rerun()

            if st.session_state.get("show_pricing_table", False):
                st.markdown("---")
                st.subheader("💰 إدارة تسعير وحالات التوصيل (Action & Pricing)")
                st.caption("يوضح الجدول المناطق المضافة حديثاً والمناطق المسجلة مسبقاً، مع إمكانية إلغاء تفعيل أي منطقة:")

                original_registered = set(st.session_state.get("pre_filled_zones", []))
                currently_chosen = set(st.session_state.get("applied_zones", []))
                
                all_relevant_zones = list(st.session_state.get("applied_zones", []))
                for pz in st.session_state.get("pre_filled_zones", []):
                    if pz not in all_relevant_zones:
                        all_relevant_zones.append(pz)
                
                table_hash = ",".join(sorted(all_relevant_zones)) + f"_{len(currently_chosen)}"
                
                if st.session_state.get("pricing_hash") != table_hash:
                    pricing_rows = []
                    pre_data = st.session_state.get("pre_filled_data", {})
                    
                    for zone in all_relevant_zones:
                        is_existing = (zone in original_registered)
                        is_selected_now = (zone in currently_chosen)
                        
                        zone_row = gdf_areas[gdf_areas["Delivery Location Area Name"] == zone] if not gdf_areas.empty else pd.DataFrame()
                        if not zone_row.empty and has_real_coords:
                            dist = haversine_km(v_row["lat"], v_row["lng"], zone_row.iloc[0]["centroid_lat"], zone_row.iloc[0]["centroid_lng"])
                        else:
                            dist = 0.0
                            
                        def_time = pre_data.get(zone, {}).get("time", "")
                        def_fee = pre_data.get(zone, {}).get("fees", None)
                        
                        if is_existing and is_selected_now:
                            z_type = "📌 منطقة حالية مسجلة"
                            default_action = "نشط (Active)"
                        elif is_existing and not is_selected_now:
                            z_type = "📌 منطقة حالية مسجلة"
                            default_action = "إلغاء التفعيل (Deactivate)"
                            def_time = "ملغاة"
                            def_fee = 0.0
                        else:
                            z_type = "✨ منطقة جديدة مضافة"
                            default_action = "نشط (Active)"

                        pricing_rows.append({
                            "Zone": zone,
                            "Classification": z_type,
                            "Action": default_action,
                            "Distance (km)": round(dist, 1) if has_real_coords else 0.0,
                            "Delivery Time": def_time,
                            "Delivery Fees": def_fee
                        })
                    
                    st.session_state["pricing_df"] = pd.DataFrame(pricing_rows)
                    st.session_state["pricing_hash"] = table_hash

                edited_pricing_df = st.data_editor(
                    st.session_state["pricing_df"],
                    column_config={
                        "Zone": st.column_config.TextColumn("اسم المنطقة", disabled=True),
                        "Classification": st.column_config.TextColumn("نوع المنطقة", disabled=True),
                        "Action": st.column_config.SelectboxColumn(
                            "الحالة / الإجراء",
                            options=["نشط (Active)", "إلغاء التفعيل (Deactivate)"],
                            required=True
                        ),
                        "Distance (km)": st.column_config.NumberColumn("المسافة (كم)", disabled=True),
                        "Delivery Time": st.column_config.TextColumn("وقت التوصيل المقدر (e.g., 45 mins)"),
                        "Delivery Fees": st.column_config.NumberColumn("رسوم التوصيل (EGP)")
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="pricing_editor"
                )

                if st.button("✅ Finalize & Send to Admin", type="primary"):
                    active_items = edited_pricing_df[edited_pricing_df["Action"] == "نشط (Active)"]
                    if active_items["Delivery Time"].eq("").any() or active_items["Delivery Fees"].isnull().any():
                        st.error("⚠️ يرجى تحديد وقت التوصيل ورسوم التوصيل لجميع المناطق النشطة (Active) قبل التأكيد.")
                    else:
                        submission_df = edited_pricing_df.copy()
                        submission_df["Final_Status"] = submission_df.apply(
                            lambda r: "Deactivated" if r["Action"] == "إلغاء التفعيل (Deactivate)" else (
                                "Active (New)" if "جديدة" in r["Classification"] else "Active (Existing)"
                            ),
                            axis=1
                        )
                        save_detailed_request(v_id_clean, v_name, submission_df)
                        st.success(f"🎉 تم إرسال الطلب بنجاح! تم اعتماد ({len(active_items)}) منطقة نشطة و({len(edited_pricing_df) - len(active_items)}) منطقة ملغاة.")

# ==========================================
# Tab 3 & 4: Admin Sections (Incoming Requests & User Management)
# ==========================================
if is_admin:
    with tab3:
        st.header("📥 Vendor Pricing & Coverage Requests")
        init_requests_db()
        
        has_data = False
        if os.path.exists(REQUESTS_FILE):
            try:
                raw_df = pd.read_csv(REQUESTS_FILE)
                if not raw_df.empty and "Zone" in raw_df.columns:
                    has_data = True
                    raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                    
                    f_col1, f_col2 = st.columns(2)
                    all_req_names = ["All"] + sorted(raw_df["Vendor Name"].dropna().unique().tolist())
                    filter_name = f_col1.selectbox("تصفية باسم الفرع:", all_req_names, key="admin_req_name")
                    
                    temp_req_ids = raw_df[raw_df["Vendor Name"] == filter_name]["Vendor ID"].dropna().unique().tolist() if filter_name != "All" else raw_df["Vendor ID"].dropna().unique().tolist()
                    filter_id = f_col2.selectbox("تصفية بكود الفرع:", ["All"] + sorted(temp_req_ids), key="admin_req_id")
                    
                    filtered_raw = raw_df.copy()
                    if filter_name != "All":
                        filtered_raw = filtered_raw[filtered_raw["Vendor Name"] == filter_name]
                    if filter_id != "All":
                        filtered_raw = filtered_raw[filtered_raw["Vendor ID"] == filter_id]
                        
                    display_df = filtered_raw.groupby(["Date", "Vendor ID", "Vendor Name"]).agg(
                        Total_Zones=("Zone", "count"),
                        Zones_Preview=("Zone", lambda x: ", ".join(x.head(3)) + ("..." if len(x) > 3 else ""))
                    ).reset_index()
                    display_df.rename(columns={"Total_Zones": "إجمالي المناطق", "Zones_Preview": "نظرة عامة على المناطق"}, inplace=True)
                    
                    display_df.insert(0, "Select", False)
                    edited_display_df = st.data_editor(display_df, hide_index=True, use_container_width=True)
                    selected_displays = edited_display_df[edited_display_df["Select"] == True]
                    
                    col_down1, col_down2 = st.columns([7, 3])
                    with col_down1:
                        if not selected_displays.empty:
                            selected_vendors_dates = selected_displays[["Vendor ID", "Date"]].apply(tuple, axis=1).tolist()
                            download_df = raw_df[raw_df[["Vendor ID", "Date"]].apply(tuple, axis=1).isin(selected_vendors_dates)]
                            csv_data = download_df.to_csv(index=False).encode('utf-8-sig')
                            
                            file_name = f"Pricing_Request_{selected_displays.iloc[0]['Vendor Name']}.csv" if len(selected_displays) == 1 else "Combined_Detailed_Pricing.csv"
                            st.download_button("📥 Download Detailed CSV", data=csv_data, file_name=file_name, mime="text/csv", type="primary")
                    with col_down2:
                        if st.button("حذف جميع طلبات التعديل المسجلة", type="secondary"):
                            os.remove(REQUESTS_FILE)
                            init_requests_db()
                            st.rerun()
            except Exception as e:
                st.error(f"حدث خطأ أثناء قراءة سجلات الطلبات: {e}")
                if st.button("إعادة تعيين قاعدة البيانات"):
                    if os.path.exists(REQUESTS_FILE):
                        os.remove(REQUESTS_FILE)
                    init_requests_db()
                    st.rerun()
                    
        if not has_data:
            st.info("📭 **لا توجد طلبات تعديل واردة حالياً.** في انتظار إرسال الفروع لطلبات تحديث المناطق والتسعير عبر بوابة الفيندور.")

    with tab4:
        st.header("👥 User Management (إدارة المستخدمين والصلاحيات)")
        tab_u1, tab_u2, tab_u3 = st.tabs(["➕ إضافة مستخدم جديد", "✏️ تعديل صلاحيات مستخدم", "📋 قائمة المستخدمين"])
        
        with tab_u1:
            u_role = st.selectbox("نوع الحساب:", ["admin", "vendor"], format_func=lambda x: "مسؤول نظام (Admin)" if x == "admin" else "مستخدم فيندور (Vendor User)")
            with st.form("add_user_form"):
                new_email = st.text_input("البريد الإلكتروني:").strip().lower()
                new_password = st.text_input("كلمة المرور:").strip()
                
                access_choice = st.radio(
                    "نطاق الصلاحيات والفروع التابعة:",
                    ["كل فروع القسم (All Branches - Master Access)", "سلاسل محددة (Chain ID)", "فروع محددة (Vendor ID)"]
                )
                
                access_type, selected_access_ids_str = "all", "all"
                if access_choice == "سلاسل محددة (Chain ID)":
                    access_type = "Chain ID"
                    if not df_vendors.empty and "clean_cid" in df_vendors.columns:
                        chains_df = df_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                        chains_df = chains_df[chains_df["clean_cid"] != ""]
                        chain_opts = dict(zip(chains_df["clean_cid"], chains_df["clean_chain_name"] + " (" + chains_df["clean_cid"] + ")"))
                        chosen_chains = st.multiselect("اختر السلاسل التابعة له:", options=list(chain_opts.keys()), format_func=lambda x: chain_opts[x])
                        selected_access_ids_str = ", ".join(chosen_chains)
                    else:
                        selected_access_ids_str = ""
                elif access_choice == "فروع محددة (Vendor ID)":
                    access_type = "Vendor ID"
                    if not df_vendors.empty and "clean_vid" in df_vendors.columns:
                        vendors_df = df_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                        vendors_df = vendors_df[vendors_df["clean_vid"] != ""]
                        vendor_opts = dict(zip(vendors_df["clean_vid"], vendors_df["clean_name"] + " (" + vendors_df["clean_vid"] + ")"))
                        chosen_vendors = st.multiselect("اختر الفروع التابعة له:", options=list(vendor_opts.keys()), format_func=lambda x: vendor_opts[x])
                        selected_access_ids_str = ", ".join(chosen_vendors)
                    else:
                        selected_access_ids_str = ""
                
                if st.form_submit_button("💾 إنشاء الحساب", type="primary"):
                    if not new_email or not new_password:
                        st.error("يرجى ملء جميع الحقول المطلوبة.")
                    elif access_choice != "كل فروع القسم (All Branches - Master Access)" and not selected_access_ids_str:
                        st.error("يرجى اختيار فرع أو سلسلة واحدة على الأقل.")
                    else:
                        ok, msg = add_user(new_email, new_password, u_role, access_type, selected_access_ids_str)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with tab_u2:
            st.subheader("تعديل صلاحيات ومحفظة فروع مستخدم مسجل")
            users_list_df = get_users_df()
            all_user_emails = users_list_df["email"].tolist()
            
            selected_edit_user = st.selectbox("اختر المستخدم للتعديل:", options=all_user_emails)
            user_current_row = users_list_df[users_list_df["email"] == selected_edit_user].iloc[0]
            
            with st.form("edit_user_perm_form"):
                e_role = st.selectbox(
                    "نوع الحساب:",
                    options=["admin", "vendor"],
                    index=0 if user_current_row["role"] == "admin" else 1,
                    format_func=lambda x: "مسؤول نظام (Admin)" if x == "admin" else "مستخدم فيندور (Vendor User)"
                )
                
                default_scope_idx = 0 if user_current_row["access_type"] == "all" else (1 if user_current_row["access_type"] == "Chain ID" else 2)
                e_access_choice = st.radio(
                    "نطاق الصلاحيات والفروع التابعة:",
                    ["كل فروع القسم (All Branches - Master Access)", "سلاسل محددة (Chain ID)", "فروع محددة (Vendor ID)"],
                    index=default_scope_idx
                )
                
                e_access_type, e_selected_access_ids_str = "all", "all"
                if e_access_choice == "سلاسل محددة (Chain ID)":
                    e_access_type = "Chain ID"
                    if not df_vendors.empty and "clean_cid" in df_vendors.columns:
                        chains_df = df_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                        chains_df = chains_df[chains_df["clean_cid"] != ""]
                        chain_opts = dict(zip(chains_df["clean_cid"], chains_df["clean_chain_name"] + " (" + chains_df["clean_cid"] + ")"))
                        curr_ids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in chain_opts]
                        chosen_chains = st.multiselect("اختر السلاسل التابعة له:", options=list(chain_opts.keys()), default=curr_ids, format_func=lambda x: chain_opts[x])
                        e_selected_access_ids_str = ", ".join(chosen_chains)
                    else:
                        e_selected_access_ids_str = ""
                elif e_access_choice == "فروع محددة (Vendor ID)":
                    e_access_type = "Vendor ID"
                    if not df_vendors.empty and "clean_vid" in df_vendors.columns:
                        vendors_df = df_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                        vendors_df = vendors_df[vendors_df["clean_vid"] != ""]
                        vendor_opts = dict(zip(vendors_df["clean_vid"], vendors_df["clean_name"] + " (" + vendors_df["clean_vid"] + ")"))
                        curr_vids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in vendor_opts]
                        chosen_vendors = st.multiselect("اختر الفروع التابعة له:", options=list(vendor_opts.keys()), default=curr_vids, format_func=lambda x: vendor_opts[x])
                        e_selected_access_ids_str = ", ".join(chosen_vendors)
                    else:
                        e_selected_access_ids_str = ""
                    
                if st.form_submit_button("💾 حفظ التعديلات وتحديث الصلاحيات", type="primary"):
                    ok, msg, updated_row = update_user_permissions(selected_edit_user, e_role, e_access_type, e_selected_access_ids_str)
                    if ok:
                        if selected_edit_user.lower() == current_user["email"].lower():
                            st.session_state["current_user"] = updated_row
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

        with tab_u3:
            users_list_df = get_users_df()
            st.dataframe(users_list_df, use_container_width=True)
            deletable = users_list_df[users_list_df["email"].str.lower() != "mahmoud.alaa.2@talabat.com"]["email"].tolist()
            if deletable:
                to_del = st.selectbox("اختر المستخدم للحذف:", deletable)
                if st.button("حذف الحساب", type="secondary"):
                    ok, msg = delete_user(to_del)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
