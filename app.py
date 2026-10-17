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
st.set_page_config(layout="wide", page_title="Vendor & Zones Management", page_icon="🔒")

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

def delete_user(email):
    df = get_users_df()
    if email.strip().lower() == "mahmoud.alaa.2@talabat.com":
        return False, "Cannot delete master admin!"
    df = df[df["email"].str.lower() != email.strip().lower()]
    df.to_csv(USERS_FILE, index=False)
    return True, "User deleted successfully!"

# ==========================================
# 3. دوال المعالجة وجلب البيانات من Google Sheets
# ==========================================
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
    for name in possible_names:
        for col in df.columns:
            if str(name).strip().lower() == str(col).strip().lower():
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
            return pd.read_csv(io.StringIO(res.text))
    except Exception:
        pass
    try:
        return pd.read_csv(csv_url)
    except Exception:
        return pd.DataFrame()

# جلب البيانات وتحديثها دورياً
@st.cache_data(ttl=3600)
def load_data():
    url_areas = "https://docs.google.com/spreadsheets/d/1Y3AlqaHjp4nZup6QwOBgl6CT5z3XHjfzpRSx5Yw5byk/export?format=csv&gid=0"
    url_vendors = "https://docs.google.com/spreadsheets/d/12SSMW20Two2hRpHOuIXXifweJI82bZpJClhUAWSuYHk/export?format=csv&gid=0"
    url_delivery = "https://docs.google.com/spreadsheets/d/1Gh6xnGNn7yx2g-bdIHC4DvHIMzVkOnh3Fdy6AhQtTmM/export?format=csv&gid=540443526"
    
    df_v = read_google_sheet_csv(url_vendors)
    df_a = read_google_sheet_csv(url_areas)
    df_d = read_google_sheet_csv(url_delivery)

    if df_v.empty:
        st.warning("⚠️ تعذر تحميل شيت الفيندورز. تأكد من إعدادات المشاركة (Anyone with the link can view).")
    if df_a.empty:
        st.warning("⚠️ تعذر تحميل شيت المناطق. تأكد من إعدادات المشاركة (Anyone with the link can view).")

    if not df_v.empty:
        map_loc_col = get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location"])
        if map_loc_col:
            coords = df_v[map_loc_col].str.split(",", expand=True)
            df_v["lat"] = pd.to_numeric(coords[0], errors="coerce")
            df_v["lng"] = pd.to_numeric(coords[1], errors="coerce")
            df_v = df_v.dropna(subset=["lat", "lng"])
        
        vid_col = get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID"])
        cid_col = get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID"])
        if vid_col: df_v["Vendor Attributes Vendor Id"] = df_v[vid_col].astype(str)
        if cid_col: df_v["Chain Attributes Chain ID"] = df_v[cid_col].astype(str)

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
                gdf_a["Delivery Location Area Name"] = gdf_a[area_name_col]
                mask_mcd = gdf_a["Delivery Location Area Name"].str.contains(r"^mcd|^mcdonald", case=False, na=False)
                # استبعاد مضلعات ماكدونالدز والمضلعات الكبيرة جداً
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

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    v_point = Point(lng, lat)
    radius_deg = radius_km / 111.0
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(radius_deg))
    return gdf_areas[nearby_mask].copy()

def save_detailed_request(vendor_id, vendor_name, edited_df):
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_df = edited_df.copy()
    save_df.insert(0, "Date", date_str)
    save_df.insert(1, "Vendor ID", str(vendor_id))
    save_df.insert(2, "Vendor Name", vendor_name)
    save_df["Status"] = "Pending"
    
    file_name = "vendor_pricing_requests.csv"
    if os.path.exists(file_name):
        old_df = pd.read_csv(file_name)
        if "Zone" not in old_df.columns:
            save_df.to_csv(file_name, index=False)
        else:
            save_df.to_csv(file_name, mode="a", header=False, index=False)
    else:
        save_df.to_csv(file_name, index=False)

# ==========================================
# 4. شاشة تسجيل الدخول (Authentication)
# ==========================================
init_users_db()

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

with st.sidebar:
    st.write(f"👤 **مرحباً:** `{current_user['email']}`")
    st.write(f"🛡️ **الصلاحية:** `{current_user['role'].upper()}`")
    if not is_admin:
        st.write(f"📌 **نوع الصلاحية:** `{current_user['access_type']}`")
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج (Logout)", use_container_width=True):
        st.session_state.clear()
        st.rerun()

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Overview Map", "🛒 Vendor Portal", "📥 Incoming Requests", "👥 Users"])
else:
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map
# ==========================================
if is_admin:
    with tab1:
        st.header("Zones & Vendors Simulation Dashboard")
        map_active = st.toggle("⚡ Activate Admin Map (تشغيل الخريطة الكبيرة)", value=False, key="toggle_admin_map")
        
        if not map_active:
            st.info("⏸️ **خريطة المراقبة الكبيرة معطلة لتسريع الموقع بنسبة 100%.** فَعِّل الزر بالأعلى عندما تحتاج لمراجعة الخريطة العامة.")
        else:
            col1, col2 = st.columns([1, 4])
            with col1:
                st.subheader("Filter Controls")
                city_col = get_col(df_vendors, ["Vendor Attributes Vendor City", "City", "Vendor City"])
                all_cities = ["All"] + sorted(df_vendors[city_col].dropna().unique().tolist()) if (city_col and not df_vendors.empty) else ["All"]
                selected_city = st.selectbox("1. Select City:", options=all_cities, key="dash_city")
                st.markdown("---")
                
                temp_df = df_vendors if (selected_city == "All" or df_vendors.empty or not city_col) else df_vendors[df_vendors[city_col] == selected_city]
                name_col = get_col(temp_df, ["Vendor Attributes Vendor Name (English)", "Vendor Name"])
                vendor_names = ["All"] + sorted(temp_df[name_col].dropna().unique().tolist()) if (name_col and not temp_df.empty) else ["All"]
                selected_name = st.selectbox("Search by Vendor Name:", options=vendor_names, key="dash_name")
                
                vid_col = get_col(temp_df, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID"])
                vendor_ids = ["All"] + sorted(temp_df[vid_col].dropna().unique().tolist()) if (vid_col and not temp_df.empty) else ["All"]
                selected_v_id = st.selectbox("Search by Vendor ID:", options=vendor_ids, key="dash_vid")
                
                cid_col = get_col(temp_df, ["Chain Attributes Chain ID", "Chain Id", "Chain ID"])
                chain_ids = ["All"] + sorted(temp_df[cid_col].dropna().unique().tolist()) if (cid_col and not temp_df.empty) else ["All"]
                selected_chain = st.selectbox("Search by Chain ID:", options=chain_ids, key="dash_chain")
                
                show_zones = st.checkbox("Show Area Polygons", value=True, key="dash_zones")
                if st.button("Reset Filters", key="reset_btn"):
                    st.session_state.clear()
                    st.rerun()
                    
            with col2:
                filtered_v = df_vendors.copy() if not df_vendors.empty else pd.DataFrame()
                if not filtered_v.empty:
                    if selected_city != "All" and city_col: filtered_v = filtered_v[filtered_v[city_col] == selected_city]
                    if selected_name != "All" and name_col: filtered_v = filtered_v[filtered_v[name_col] == selected_name]
                    if selected_v_id != "All" and vid_col: filtered_v = filtered_v[filtered_v[vid_col] == selected_v_id]
                    if selected_chain != "All" and cid_col: filtered_v = filtered_v[filtered_v[cid_col] == selected_chain]
                    
                if not filtered_v.empty and "lat" in filtered_v.columns and "lng" in filtered_v.columns:
                    center = [filtered_v["lat"].mean(), filtered_v["lng"].mean()]
                    zoom = 14 if (selected_name != "All" or selected_v_id != "All") else 12 if selected_chain != "All" else 11 if selected_city != "All" else 6
                else:
                    center = [30.0444, 31.2357]
                    zoom = 6
                    
                m = folium.Map(location=center, zoom_start=zoom)
                css_no_box = "<style>.leaflet-interactive:focus, path.leaflet-interactive:focus, svg:focus {outline: none !important; box-shadow: none !important;}</style>"
                m.get_root().html.add_child(folium.Element(css_no_box))
                
                if show_zones and not gdf_areas.empty:
                    folium.GeoJson(
                        gdf_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style
