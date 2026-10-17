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

# لوحة ألوان لتمييز فروع السلسلة الواحدة
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
    
    df_v = read_google_sheet_csv(url_vendors)
    df_a = read_google_sheet_csv(url_areas)
    df_d = read_google_sheet_csv(url_delivery)

    # معالجة بيانات الفيندورز
    if not df_v.empty:
        vid_col = get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID", "vendor_id"])
        cid_col = get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID", "chain_id"])
        name_col = get_col(df_v, ["Vendor Attributes Vendor Name (English)", "Vendor Name", "Name", "vendor_name"])
        cname_col = get_col(df_v, ["Chain Attributes Chain Name", "Chain Name", "chain_name"])
        city_col = get_col(df_v, ["Vendor Attributes Vendor City", "City", "Vendor City"])

        df_v["clean_vid"] = df_v[vid_col].apply(normalize_id) if vid_col else ""
        df_v["clean_cid"] = df_v[cid_col].apply(normalize_id) if cid_col else ""
        df_v["clean_name"] = df_v[name_col].astype(str).str.strip() if name_col else ("Vendor " + df_v["clean_vid"])
        df_v["clean_chain_name"] = df_v[cname_col].astype(str).str.strip() if cname_col else ""
        df_v["clean_city"] = df_v[city_col].astype(str).str.strip() if city_col else ""

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

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    if gdf_areas.empty or pd.isna(lat) or pd.isna(lng):
        return gpd.GeoDataFrame()
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
    
    file_name = "vendor_pricing_requests.csv"
    if os.path.exists(file_name):
        old_df = pd.read_csv(file_name)
        if "Zone" not in old_df.columns:
            save_df.to_csv(file_name, index=False)
        else:
            save_df.to_csv(file_name, mode="a", header=False, index=False)
    else:
        save_df.to_csv(file_name, index=False)

def build_vendor_popup_html(v_row, df_delivery):
    v_id = str(v_row["clean_vid"])
    c_id = str(v_row.get("clean_cid", ""))
    v_name = v_row.get("clean_name", "")
    c_name = v_row.get("clean_chain_name", "")
    v_city = v_row.get("clean_city", "")

    # مطابقة مناطق الفرع فقط بدقة بناءً على Vendor ID
    match_d = pd.DataFrame()
    if not df_delivery.empty and "clean_vid" in df_delivery.columns:
        match_d = df_delivery[df_delivery["clean_vid"] == v_id]

    html = f"""<div style='font-family: Arial, sans-serif; width: 280px; font-size: 13px;'>
<h4 style='margin:0 0 5px 0; color:#0d6efd;'>🏬 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code><br>
<b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>City:</b> {v_city}<br>
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
    st.write(f"👤 **المستخدم:** `{current_user['email']}`")
    st.write(f"🛡️ **الصلاحية:** `{current_user['role'].upper()}`")
    if not is_admin:
        st.write(f"📌 **نطاق الربط:** `{current_user['access_type']}`")
    st.markdown("---")
    st.metric("🏬 إجمالي الفروع المسجلة", len(df_vendors))
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

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Overview Map", "🛒 Vendor Portal", "📥 Incoming Requests", "👥 Users"])
else:
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map (سريعة، دقيقة للفروع، تدعم الألوان المستقلة)
# ==========================================
if is_admin:
    with tab1:
        st.header("🗺️ Admin Overview & Simulation Map")
        
        map_active = st.toggle("⚡ تفعيل خريطة الإدارة العامة (Admin Map)", value=False, key="toggle_admin_map")
        
        if not map_active:
            st.info("⏸️ خريطة المراقبة العامة معطلة لتوفير أقصى سرعة لبوابة الفيندورز. فَعِّل الزر أعلاه عند الحاجة لاستعراض التغطية العامة.")
        else:
            f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.5, 1.8, 0.8])
            
            with f_col1:
                all_cities = ["All Cities"] + sorted([c for c in df_vendors["clean_city"].unique() if c])
                selected_city = st.selectbox("1. المدينة / المحافظة:", options=all_cities, key="admin_map_city")

            city_df = df_vendors if selected_city == "All Cities" else df_vendors[df_vendors["clean_city"] == selected_city]

            with f_col2:
                chains_in_city = city_df[["clean_cid", "clean_chain_name"]].drop_duplicates()
                chains_in_city = chains_in_city[chains_in_city["clean_cid"] != ""]
                chain_map = dict(zip(chains_in_city["clean_cid"], chains_in_city["clean_chain_name"] + " (" + chains_in_city["clean_cid"] + ")"))
                chain_options = ["All Chains (كل السلاسل)"] + list(chain_map.keys())
                
                selected_chain = st.selectbox(
                    "2. السلسلة (Chain):",
                    options=chain_options,
                    format_func=lambda x: "All Chains (كل السلاسل)" if x == "All Chains (كل السلاسل)" else chain_map.get(x, x),
                    key="admin_map_chain"
                )

            chain_filtered_vendors = city_df if selected_chain == "All Chains (كل السلاسل)" else city_df[city_df["clean_cid"] == selected_chain]

            with f_col3:
                vendor_opts = dict(zip(
                    chain_filtered_vendors["clean_vid"],
                    chain_filtered_vendors["clean_name"] + " (ID: " + chain_filtered_vendors["clean_vid"] + ")"
                ))
                vendor_options = ["All Vendors (كل الفروع)"] + list(vendor_opts.keys())
                
                selected_vendor = st.selectbox(
                    "3. الفرع (Vendor):",
                    options=vendor_options,
                    format_func=lambda x: "All Vendors (كل الفروع)" if x == "All Vendors (كل الفروع)" else vendor_opts.get(x, x),
                    key="admin_map_vendor"
                )
                
            with f_col4:
                st.write("")
                st.write("")
                if st.button("🔄 إعادة ضبط", key="admin_reset_filters", use_container_width=True):
                    st.rerun()

            if selected_vendor != "All Vendors (كل الفروع)":
                display_vendors = chain_filtered_vendors[chain_filtered_vendors["clean_vid"] == selected_vendor]
            else:
                display_vendors = chain_filtered_vendors

            plot_vendors = display_vendors.dropna(subset=["lat", "lng"]).copy()

            # تخصيص لون فريد لكل فرع
            vendor_color_map = {}
            if selected_chain != "All Chains (كل السلاسل)":
                chain_branches = chain_filtered_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                for idx, (_, b_row) in enumerate(chain_branches.iterrows()):
                    pal_entry = BRANCH_PALETTE[idx % len(BRANCH_PALETTE)]
                    vendor_color_map[b_row["clean_vid"]] = {
                        "name": b_row["clean_name"],
                        "hex": pal_entry["hex"],
                        "folium": pal_entry["folium"],
                        "color_name": pal_entry["name"]
                    }
            elif selected_vendor != "All Vendors (كل الفروع)":
                v_name_sel = display_vendors.iloc[0]["clean_name"]
                vendor_color_map[selected_vendor] = {
                    "name": v_name_sel,
                    "hex": "#28a745",
                    "folium": "green",
                    "color_name": "أخضر"
                }

            # مطابقة مناطق التوصيل فقط للـ Vendor ID بدقة
            zone_to_vendor_info = {}
            if not df_delivery.empty and vendor_color_map:
                relevant_vids = set(vendor_
