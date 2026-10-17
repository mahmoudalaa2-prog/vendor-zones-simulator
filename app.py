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

    # معالجة شيت الفيندورز
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

    # معالجة وتصفية شيت التوصيل
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

    # معالجة شيت المناطق
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

def build_vendor_popup_html(v_row, df_delivery):
    v_id = str(v_row["clean_vid"])
    c_id = str(v_row.get("clean_cid", ""))
    v_name = v_row.get("clean_name", "")
    c_name = v_row.get("clean_chain_name", "")
    v_city = v_row.get("clean_city", "")

    match_d = pd.DataFrame()
    if not df_delivery.empty:
        match_d = df_delivery[df_delivery["clean_vid"] == v_id]
        if match_d.empty and c_id:
            match_d = df_delivery[df_delivery["clean_cid"] == c_id]

    html = f"""<div style='font-family: Arial, sans-serif; width: 280px; font-size: 13px;'>
<h4 style='margin:0 0 5px 0; color:#0d6efd;'>🏬 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code><br>
<b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>City:</b> {v_city}<br>
<hr style='margin:6px 0; border:0; border-top:1px solid #ddd;'>"""

    if not match_d.empty and "clean_zone" in match_d.columns:
        zone_count = len(match_d["clean_zone"].dropna().unique())
        html += f"<b style='color:#198754;'>🛵 مناطق التوصيل ({zone_count}):</b>"
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
        html += "<div style='color:#6c757d; font-size:12px; margin-top:4px;'>لا توجد مناطق توصيل مسجلة لهذا الفرع.</div>"

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
    st.write(f"👤 **مرحباً:** `{current_user['email']}`")
    st.write(f"🛡️ **الصلاحية:** `{current_user['role'].upper()}`")
    if not is_admin:
        st.write(f"📌 **نوع الصلاحية:** `{current_user['access_type']}`")
    st.markdown("---")
    st.metric("🏬 إجمالي الفيندورز", len(df_vendors))
    st.metric("🗺️ إجمالي المناطق", len(gdf_areas))
    if st.button("🔄 مزامنة وتحديث الشيتات الآن", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج (Logout)", use_container_width=True):
        st.session_state.clear()
        st.rerun()

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Overview Map", "🛒 Vendor Portal", "📥 Incoming Requests", "👥 Users"])
else:
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map (سريعة، تدعم السلاسل، وتعرض مناطق التوصيل)
# ==========================================
if is_admin:
    with tab1:
        st.header("🗺️ Admin Overview & Simulation Map")
        st.caption("خريطة تفاعلية خفيفة وسريعة: اضغط على أي فيندور لعرض مناطق توصيله، أو اختر سلسلة بالكامل لعرض فروعها ومناطقها.")
        
        f_col1, f_col2, f_col3 = st.columns([1.5, 1.5, 2])
        
        with f_col1:
            all_cities = ["All Cities"] + sorted([c for c in df_vendors["clean_city"].unique() if c])
            selected_city = st.selectbox("1. تصفية بالمحافظة/المدينة:", options=all_cities, key="admin_map_city")

        city_df = df_vendors if selected_city == "All Cities" else df_vendors[df_vendors["clean_city"] == selected_city]

        with f_col2:
            chains_in_city = city_df[["clean_cid", "clean_chain_name"]].drop_duplicates()
            chains_in_city = chains_in_city[chains_in_city["clean_cid"] != ""]
            chain_map = dict(zip(chains_in_city["clean_cid"], chains_in_city["clean_chain_name"] + " (" + chains_in_city["clean_cid"] + ")"))
            chain_options = ["All Chains (كل السلاسل)"] + list(chain_map.keys())
            
            selected_chain = st.selectbox(
                "2. إظهار Chain كاملة بمفردها:",
                options=chain_options,
                format_func=lambda x: "All Chains (كل السلاسل)" if x == "All Chains (كل السلاسل)" else chain_map.get(x, x),
                key="admin_map_chain"
            )

        if selected_chain != "All Chains (كل السلاسل)":
            filtered_vendors = city_df[city_df["clean_cid"] == selected_chain]
        else:
            filtered_vendors = city_df

        with f_col3:
            vendor_opts = dict(zip(
                filtered_vendors["clean_vid"],
                filtered_vendors["clean_name"] + " (ID: " + filtered_vendors["clean_vid"] + ")"
            ))
            focus_vendor_options = ["None (عرض كل فروع التصفية)"] + list(vendor_opts.keys())
            
            focused_vid = st.selectbox(
                "3. تحديد فيندور لرسم مضلعات مناطقه والتركيز عليه:",
                options=focus_vendor_options,
                format_func=lambda x: "None (عرض كل فروع التصفية)" if x == "None (عرض كل فروع التصفية)" else vendor_opts.get(x, x),
                key="admin_map_focus_vid"
            )

        # خيار إظهار مضلعات التوصيل للسلسلة
        c_chk1, c_chk2 = st.columns([2, 3])
        show_chain_polygons = False
        with c_chk1:
            if selected_chain != "All Chains (كل السلاسل)" and focused_vid == "None (عرض كل فروع التصفية)":
                show_chain_polygons = st.checkbox("🗺️ رسم كل مضلعات مناطق توصيل فروع هذه السلسلة", value=True)

        plot_vendors = filtered_vendors.dropna(subset=["lat", "lng"]).copy()

        # حساب مركز الخريطة ومستوى الزووم
        if focused_vid != "None (عرض كل فروع التصفية)":
            f_v_row = plot_vendors[plot_vendors["clean_vid"] == focused_vid]
            if not f_v_row.empty:
                map_center = [f_v_row.iloc[0]["lat"], f_v_row.iloc[0]["lng"]]
                zoom_lvl = 13
            else:
                map_center = [30.0444, 31.2357]
                zoom_lvl = 11
        elif not plot_vendors.empty:
            map_center = [plot_vendors["lat"].mean(), plot_vendors["lng"].mean()]
            zoom_lvl = 12 if selected_chain != "All Chains (كل السلاسل)" else 10 if selected_city != "All Cities" else 7
        else:
            map_center = [30.0444, 31.2357]
            zoom_lvl = 7

        m_admin = folium.Map(location=map_center, zoom_start=zoom_lvl)
        css_style = "<style>.leaflet-interactive:focus, path.leaflet-interactive:focus, svg:focus {outline: none !important; box-shadow: none !important;} path.leaflet-interactive:hover {cursor: pointer;}</style>"
        m_admin.get_root().html.add_child(folium.Element(css_style))

        # -------------------------------------------------------------
        # رسم مضلعات التوصيل المستهدفة فقط (سرعة فائقة وخفة تامة)
        # -------------------------------------------------------------
        if not gdf_areas.empty and not df_delivery.empty:
            target_zones = []
            
            # 1. إذا تم تحديد فيندور بعينه
            if focused_vid != "None (عرض كل فروع التصفية)":
                v_row_f = plot_vendors[plot_vendors["clean_vid"] == focused_vid].iloc[0]
                m_del = df_delivery[df_delivery["clean_vid"] == focused_vid]
                if m_del.empty and v_row_f["clean_cid"]:
                    m_del = df_delivery[df_delivery["clean_cid"] == v_row_f["clean_cid"]]
                if not m_del.empty and "clean_zone" in m_del.columns:
                    target_zones = m_del["clean_zone"].dropna().unique().tolist()
                    
            # 2. إذا تم اختيار سلسلة كاملة مع خيار رسم مضلعاتها
            elif selected_chain != "All Chains (كل السلاسل)" and show_chain_polygons:
                chain_vids = plot_vendors["clean_vid"].unique().tolist()
                m_del = df_delivery[(df_delivery["clean_cid"] == selected_chain) | (df_delivery["clean_vid"].isin(chain_vids))]
                if not m_del.empty and "clean_zone" in m_del.columns:
                    target_zones = m_del["clean_zone"].dropna().unique().tolist()

            if target_zones:
                zone_lookup = {z.strip().lower(): z for z in gdf_areas["Delivery Location Area Name"]}
                canonical_targets = [zone_lookup[t.strip().lower()] for t in target_zones if t.strip().lower() in zone_lookup]
                
                matched_polygons = gdf_areas[gdf_areas["Delivery Location Area Name"].isin(canonical_targets)]
                
                if not matched_polygons.empty:
                    folium.GeoJson(
                        matched_polygons[["Delivery Location Area Name", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style_function=lambda feature: {
                            "fillColor": "#28a745",
                            "color": "#155724",
                            "weight": 2.0,
                            "fillOpacity": 0.45
                        },
                        highlight_function=lambda feature: {"color": "#ffc107", "weight": 3.5, "fillOpacity": 0.65},
                        tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["منطقة توصيل: "]),
                        popup=folium.GeoJsonPopup(fields=["Delivery Location Area Name"], aliases=["Zone: "])
                    ).add_to(m_admin)

        # -------------------------------------------------------------
        # رسم الفيندورز عبر MarkerCluster
        # -------------------------------------------------------------
        if not plot_vendors.empty:
            cluster = MarkerCluster().add_to(m_admin)
            
            for _, row in plot_vendors.iterrows():
                is_focused = (focused_vid != "None (عرض كل فروع التصفية)" and row["clean_vid"] == focused_vid)
                popup_content = build_vendor_popup_html(row, df_delivery)
                
                if is_focused:
                    folium.Marker(
                        location=[row['lat'], row['lng']],
                        popup=folium.Popup(popup_content, max_width=320),
                        tooltip=f"⭐ {row['clean_name']} (اضغط لعرض مناطق التوصيل)",
                        icon=folium.Icon(color="green", icon="star", prefix="fa")
                    ).add_to(m_admin)
                else:
                    folium.Marker(
                        location=[row['lat'], row['lng']],
                        popup=folium.Popup(popup_content, max_width=320),
                        tooltip=f"{row['clean_name']} ({row['clean_vid']})",
                        icon=folium.Icon(color="blue", icon="cutlery", prefix="fa")
                    ).add_to(cluster)

        st_folium(m_admin, width="100%", height=620, key=f"admin_overview_map_{selected_city}_{selected_chain}_{focused_vid}", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal (100% مطابق لشيت Vendor Location)
# ==========================================
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    
    target_vid = ""

    if is_admin:
        vendor_input_raw = st.text_input(
            "Enter Vendor ID:",
            placeholder="اكتب رقم الفيندور المسجل في شيت Vendor Location...",
            key="admin_vendor_input_field"
        ).strip()

        if vendor_input_raw:
            clean_search = normalize_id(vendor_input_raw)
            match_vid = df_vendors[df_vendors["clean_vid"] == clean_search]
            
            if not match_vid.empty:
                target_vid = clean_search
            else:
                st.error(f"❌ هذا الرقم `{vendor_input_raw}` غير موجود في شيت Vendor Location نهائياً.")
    else:
        allowed_raw = str(current_user["access_ids"]).split(",")
        allowed_ids = [normalize_id(x) for x in allowed_raw if x.strip()]
        
        if current_user["access_type"] == "Chain ID":
            permitted_vendors = df_vendors[df_vendors["clean_cid"].isin(allowed_ids)]
        else:
            permitted_vendors = df_vendors[df_vendors["clean_vid"].isin(allowed_ids)]
            
        if permitted_vendors.empty:
            st.warning("⚠️ لا توجد فروع أو فيندورز مربوطة بحسابك حتى الآن. يرجى التواصل مع الإدارة.")
        else:
            options_dict = dict(zip(
                permitted_vendors["clean_vid"],
                permitted_vendors["clean_name"] + " (" + permitted_vendors["clean_vid"] + ")"
            ))
            target_vid = st.selectbox(
                "اختر الفرع / الفيندور الذي تريد تعديل مناطقه:",
                options=list(options_dict.keys()),
                format_func=lambda x: options_dict[x]
            )

    if target_vid:
        v_id_clean = normalize_id(target_vid)
        vendor_data = df_vendors[df_vendors["clean_vid"] == v_id_clean]
        
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
                st.warning("⚠️ هذا الفرع مسجل في شيت Vendor Location ولكن ليس لديه إحداثيات موقع (Latitude/Longitude) مسجلة في الشيت. يرجى إضافة إحداثياته في الشيت لحساب المسافات بدقة 100%.")

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
            if not df_delivery.empty:
                d_vid_col = get_col(df_delivery, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
                d_cid_col = get_col(df_delivery, ["Chain ID", "Chain Id", "ChainID", "chain_id"])
                d_zone_col = get_col(df_delivery, ["Area Name", "Delivery Area Name", "Zone", "Delivery Location Area Name", "Area", "Delivery Zone"])
                d_time_col = get_col(df_delivery, ["Delivery Time", "Time", "Duration"])
                d_fee_col = get_col(df_delivery, ["Delivery Fees", "Fee", "Delivery Fee", "Price"])

                my_del_df = pd.DataFrame()

                if d_vid_col:
                    my_del_df = df_delivery[df_delivery[d_vid_col].apply(normalize_id) == v_id_clean]
                elif d_cid_col and v_chain_id:
                    my_del_df = df_delivery[df_delivery[d_cid_col].apply(normalize_id) == v_chain_id]

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
                initial_covered = pre_filled_zones if pre_filled_zones else ([z for z in portal_areas["Delivery Location Area Name"].head(2).tolist() if z in all_available_zones] if not portal_areas.empty else [])
                st.session_state["ms_zones_input"] = list(initial_covered)
                st.session_state["applied_zones"] = list(initial_covered)
                st.session_state["pre_filled_data"] = pre_filled_data
                st.session_state["last_click_sig"] = None
                st.session_state["show_pricing_table"] = False

            valid_selected = [z for z in st.session_state.get("ms_zones_input", []) if z in all_available_zones]
            st.session_state["ms_zones_input"] = valid_selected

            valid_applied = [z for z in st.session_state.get("applied_zones", []) if z in all_available_zones]
            st.session_state["applied_zones"] = valid_applied
            current_applied = valid_applied

            if pre_filled_zones:
                st.info(f"✨ تم استرجاع ({len(pre_filled_zones)}) منطقة مسجلة مسبقاً لهذا الفرع من شيت التوصيل.")

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            # ---------------- عمود الخريطة ----------------
            with col_map:
                st.subheader(f"🗺️ Map ({len(current_applied)} Zones Applied)")
                st.caption("Click any small sub-zone to automatically copy its name, then paste it in the search box.")

                map_center = [v_row["lat"], v_row["lng"]] if has_real_coords else [30.0444, 31.2357]
                v_map = folium.Map(location=map_center, zoom_start=13 if has_real_coords else 11)
                
                if has_real_coords:
                    folium.Marker(location=[v_row["lat"], v_row["lng"]], popup=f"<b>{v_name}</b>", icon=folium.Icon(color="green", icon="star")).add_to(v_map)

                applied_set = set(current_applied)

                def vendor_zone_style(feature):
                    name = feature["properties"]["Delivery Location Area Name"]
                    if name in applied_set:
                        return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                    else:
                        return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.2, "fillOpacity": 0.18}

                css_fix_box = "<style>.leaflet-interactive:focus, path.leaflet-interactive:focus, svg:focus { outline: none !important; box-shadow: none !important; } path.leaflet-interactive:hover { cursor: pointer; } path.leaflet-interactive:focus { stroke: #e74c3c !important; stroke-width: 3.5px !important; stroke-opacity: 1 !important; }</style>"
                v_map.get_root().html.add_child(folium.Element(css_fix_box))

                if not portal_areas.empty:
                    folium.GeoJson(
                        portal_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style_function=vendor_zone_style,
                        highlight_function=lambda feature: {"color": "#e74c3c", "weight": 3.5, "fillOpacity": 0.35},
                        tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Click to Copy: "]),
                        popup=folium.GeoJsonPopup(fields=["Delivery Location Area Name"], aliases=["Zone: "])
                    ).add_to(v_map)

                copy_script = """
                <script>
                document.addEventListener('DOMContentLoaded', function() {
                    var observer = new MutationObserver(function(mutations) {
                        mutations.forEach(function(mutation) {
                            mutation.addedNodes.forEach(function(node) {
                                if (node.classList && node.classList.contains('leaflet-popup')) {
                                    var content = node.querySelector('.leaflet-popup-content');
                                    if (content && !content.querySelector('.copy-btn')) {
                                        var td = content.querySelector('td') || content;
                                        var zoneName = td.innerText.replace('Zone:', '').trim();
                                        try { navigator.clipboard.writeText(zoneName); } catch(e) {}
                                        var btn = document.createElement('button');
                                        btn.className = 'copy-btn';
                                        btn.innerHTML = '📋 Click to Copy: ' + zoneName;
                                        btn.style = 'margin-top:8px; padding:6px 12px; background:#28a745; color:white; border:none; border-radius:4px; cursor:pointer; width:100%; font-weight:bold; font-size:12px;';
                                        btn.onclick = function() {
                                            navigator.clipboard.writeText(zoneName);
                                            btn.innerHTML = '✅ Copied to Clipboard!';
                                            setTimeout(function(){ btn.innerHTML = '📋 Click to Copy: ' + zoneName; }, 1800);
                                        };
                                        content.appendChild(btn);
                                    }
                                }
                            });
                        });
                    });
                    observer.observe(document.body, { childList: true, subtree: true });
                });
                </script>
                """
                v_map.get_root().html.add_child(folium.Element(copy_script))

                st_folium(v_map, width="100%", height=500, key=f"vmap_{v_id_clean}_{map_radius_km}", returned_objects=[])

            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("Paste (Ctrl+V) the zone names you copied from the map here:")

                chosen_zones = st.multiselect(
                    "Service Areas:",
                    options=all_available_zones,
                    default=st.session_state.get("ms_zones_input", []),
                    key="vendor_multiselect_box"
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
                        if not chosen_zones:
                            st.warning("Please select at least one zone.")
                        else:
                            st.session_state["applied_zones"] = chosen_zones.copy()
                            st.session_state["ms_zones_input"] = chosen_zones.copy()
                            st.session_state["show_pricing_table"] = True
                            st.rerun()

            if st.session_state.get("show_pricing_table", False):
                st.markdown("---")
                st.subheader("💰 Set Delivery Pricing & Time")

                current_applied_hash = ",".join(sorted(st.session_state["applied_zones"]))
                if st.session_state.get("pricing_hash") != current_applied_hash:
                    pricing_data = []
                    pre_data = st.session_state.get("pre_filled_data", {})
                    
                    for zone in st.session_state["applied_zones"]:
                        zone_row = gdf_areas[gdf_areas["Delivery Location Area Name"] == zone] if not gdf_areas.empty else pd.DataFrame()
                        if not zone_row.empty and has_real_coords:
                            dist = haversine_km(v_row["lat"], v_row["lng"], zone_row.iloc[0]["centroid_lat"], zone_row.iloc[0]["centroid_lng"])
                        else:
                            dist = 0.0
                            
                        def_time = pre_data.get(zone, {}).get("time", "")
                        def_fee = pre_data.get(zone, {}).get("fees", None)
                            
                        pricing_data.append({
                            "Zone": zone,
                            "Distance (km)": round(dist, 1) if has_real_coords else 0.0,
                            "Delivery Time": def_time,
                            "Delivery Fees": def_fee
                        })
                    
                    st.session_state["pricing_df"] = pd.DataFrame(pricing_data)
                    st.session_state["pricing_hash"] = current_applied_hash

                edited_pricing_df = st.data_editor(
                    st.session_state["pricing_df"],
                    column_config={
                        "Zone": st.column_config.TextColumn("Zone Name", disabled=True),
                        "Distance (km)": st.column_config.NumberColumn("Distance (km)", disabled=True),
                        "Delivery Time": st.column_config.TextColumn("Delivery Time (e.g., 45 mins)", required=True),
                        "Delivery Fees": st.column_config.NumberColumn("Delivery Fees (EGP)", required=True)
                    },
                    use_container_width=True,
                    hide_index=True,
                    key="pricing_editor"
                )

                if st.button("✅ Finalize & Send to Admin", type="primary"):
                    if edited_pricing_df["Delivery Time"].eq("").any() or edited_pricing_df["Delivery Fees"].isnull().any():
                        st.error("⚠️ Please fill in the Delivery Time and Delivery Fees for all zones before saving.")
                    else:
                        save_detailed_request(v_id_clean, v_name, edited_pricing_df)
                        st.success("🎉 Success! Your zones, delivery times, and fees have been submitted to Admin.")

# ==========================================
# Tab 3 & 4: Admin Sections
# ==========================================
if is_admin:
    with tab3:
        st.header("📥 Vendor Pricing & Coverage Requests")
        file_path = "vendor_pricing_requests.csv"
        if os.path.exists(file_path):
            try:
                raw_df = pd.read_csv(file_path)
                if "Zone" not in raw_df.columns:
                    st.warning("⚠️ Legacy data format detected. Rebuilding DB...")
                    os.remove(file_path)
                    st.rerun()
                else:
                    raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                    
                    f_col1, f_col2 = st.columns(2)
                    all_req_names = ["All"] + sorted(raw_df["Vendor Name"].dropna().unique().tolist())
                    filter_name = f_col1.selectbox("Filter by Vendor Name:", all_req_names, key="admin_req_name")
                    
                    temp_req_ids = raw_df[raw_df["Vendor Name"] == filter_name]["Vendor ID"].dropna().unique().tolist() if filter_name != "All" else raw_df["Vendor ID"].dropna().unique().tolist()
                    filter_id = f_col2.selectbox("Filter by Vendor ID:", ["All"] + sorted(temp_req_ids), key="admin_req_id")
                    
                    filtered_raw = raw_df.copy()
                    if filter_name != "All":
                        filtered_raw = filtered_raw[filtered_raw["Vendor Name"] == filter_name]
                    if filter_id != "All":
                        filtered_raw = filtered_raw[filtered_raw["Vendor ID"] == filter_id]
                        
                    display_df = filtered_raw.groupby(["Date", "Vendor ID", "Vendor Name", "Status"]).agg(
                        Total_Zones=("Zone", "count"),
                        Zones_Preview=("Zone", lambda x: ", ".join(x.head(3)) + ("..." if len(x) > 3 else ""))
                    ).reset_index()
                    display_df.rename(columns={"Total_Zones": "Total Zones Count", "Zones_Preview": "Zones Overview"}, inplace=True)
                    
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
                        if st.button("Delete All Requests Data", type="secondary"):
                            os.remove(file_path)
                            st.rerun()
            except:
                st.error("Database error.")
                if st.button("Force Clear"):
                    os.remove(file_path)
                    st.rerun()

    with tab4:
        st.header("👥 User Management (إدارة المستخدمين والصلاحيات)")
        tab_u1, tab_u2 = st.tabs(["➕ إضافة مستخدم جديد", "📋 قائمة المستخدمين"])
        
        with tab_u1:
            u_role = st.selectbox("نوع الحساب:", ["vendor", "admin"])
            with st.form("add_user_form"):
                new_email = st.text_input("البريد الإلكتروني:").strip().lower()
                new_password = st.text_input("كلمة المرور:").strip()
                access_type, selected_access_ids_str = "all", "all"
                
                if u_role == "vendor":
                    access_choice = st.radio("طريقة ربط الصلاحية:", ["Chain ID", "Vendor ID"])
                    if access_choice == "Chain ID":
                        access_type = "Chain ID"
                        if not df_vendors.empty and "clean_cid" in df_vendors.columns:
                            chains_df = df_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                            chains_df = chains_df[chains_df["clean_cid"] != ""]
                            chain_opts = dict(zip(chains_df["clean_cid"], chains_df["clean_chain_name"] + " (" + chains_df["clean_cid"] + ")"))
                            chosen_chains = st.multiselect("اختر السلاسل:", options=list(chain_opts.keys()), format_func=lambda x: chain_opts[x])
                            selected_access_ids_str = ", ".join(chosen_chains)
                        else:
                            st.warning("بيانات السلاسل غير متوفرة حالياً.")
                            selected_access_ids_str = ""
                    else:
                        access_type = "Vendor ID"
                        if not df_vendors.empty and "clean_vid" in df_vendors.columns:
                            vendors_df = df_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                            vendors_df = vendors_df[vendors_df["clean_vid"] != ""]
                            vendor_opts = dict(zip(vendors_df["clean_vid"], vendors_df["clean_name"] + " (" + vendors_df["clean_vid"] + ")"))
                            chosen_vendors = st.multiselect("اختر الفروع:", options=list(vendor_opts.keys()), format_func=lambda x: vendor_opts[x])
                            selected_access_ids_str = ", ".join(chosen_vendors)
                        else:
                            st.warning("بيانات الفروع غير متوفرة حالياً.")
                            selected_access_ids_str = ""
                
                if st.form_submit_button("💾 إنشاء الحساب", type="primary"):
                    if not new_email or not new_password:
                        st.error("إملأ البيانات.")
                    elif u_role == "vendor" and not selected_access_ids_str:
                        st.error("اختر الصلاحيات.")
                    else:
                        ok, msg = add_user(new_email, new_password, u_role, access_type, selected_access_ids_str)
                        st.success(msg) if ok else st.error(msg)
                        if ok:
                            st.rerun()

        with tab_u2:
            users_list_df = get_users_df()
            st.dataframe(users_list_df, use_container_width=True)
            deletable = users_list_df[users_list_df["email"].str.lower() != "mahmoud.alaa.2@talabat.com"]["email"].tolist()
            if deletable:
                to_del = st.selectbox("اختر المستخدم للحذف:", deletable)
                if st.button("حذف الحساب", type="secondary"):
                    ok, msg = delete_user(to_del)
                    st.success(msg) if ok else st.error(msg)
                    if ok:
                        st.rerun()
