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
    # بحث مرن بدون فراغات
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

    if not df_v.empty:
        map_loc_col = get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location"])
        if map_loc_col:
            coords = df_v[map_loc_col].str.split(",", expand=True)
            df_v["lat"] = pd.to_numeric(coords[0], errors="coerce")
            df_v["lng"] = pd.to_numeric(coords[1], errors="coerce")
            df_v = df_v.dropna(subset=["lat", "lng"])
        
        vid_col = get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID"])
        cid_col = get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID"])
        if vid_col:
            df_v["Vendor Attributes Vendor Id"] = df_v[vid_col].apply(normalize_id)
        if cid_col:
            df_v["Chain Attributes Chain ID"] = df_v[cid_col].apply(normalize_id)

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
                # استبعاد مضلعات ماكدونالدز بدقة حتى مع وجود مسافات
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
                    if selected_city != "All" and city_col:
                        filtered_v = filtered_v[filtered_v[city_col] == selected_city]
                    if selected_name != "All" and name_col:
                        filtered_v = filtered_v[filtered_v[name_col] == selected_name]
                    if selected_v_id != "All" and vid_col:
                        filtered_v = filtered_v[filtered_v[vid_col] == selected_v_id]
                    if selected_chain != "All" and cid_col:
                        filtered_v = filtered_v[filtered_v[cid_col] == selected_chain]
                    
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
                        style_function=lambda feature: {"fillColor": "#0055ff", "color": "#002266", "weight": 1.0, "fillOpacity": 0.15},
                        tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Area Name: "])
                    ).add_to(m)
                    
                if not filtered_v.empty and "lat" in filtered_v.columns:
                    cluster = MarkerCluster().add_to(m)
                    is_searched = (selected_name != "All" or selected_v_id != "All" or selected_chain != "All")
                    for _, row in filtered_v.iterrows():
                        popup_html = f"<b>{row.get(name_col, '')}</b><br><b>Vendor ID:</b> {row.get(vid_col, '')}"
                        folium.Marker(
                            location=[row['lat'], row['lng']],
                            popup=folium.Popup(popup_html, max_width=300),
                            tooltip=row.get(name_col, ""),
                            icon=folium.Icon(color="green" if is_searched else "red", icon="star" if is_searched else "shopping-cart", prefix="fa")
                        ).add_to(cluster)
                        
                st_folium(m, width="100%", height=650, key="main_map_admin", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal
# ==========================================
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    
    vid_col = get_col(df_vendors, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID"])
    name_col = get_col(df_vendors, ["Vendor Attributes Vendor Name (English)", "Vendor Name"])
    cid_col = get_col(df_vendors, ["Chain Attributes Chain ID", "Chain Id", "Chain ID"])
    city_col = get_col(df_vendors, ["Vendor Attributes Vendor City", "City", "Vendor City"])

    if is_admin:
        vendor_input_id = st.text_input("Enter Vendor ID:", placeholder="اكتب رقم الفيندور هنا...")
    else:
        allowed_raw = str(current_user["access_ids"]).split(",")
        allowed_ids = [normalize_id(x) for x in allowed_raw if x.strip()]
        
        if not df_vendors.empty and cid_col and current_user["access_type"] == "Chain ID":
            permitted_vendors = df_vendors[df_vendors[cid_col].isin(allowed_ids)]
        elif not df_vendors.empty and vid_col:
            permitted_vendors = df_vendors[df_vendors[vid_col].isin(allowed_ids)]
        else:
            permitted_vendors = pd.DataFrame()
            
        if permitted_vendors.empty:
            st.warning("⚠️ لا توجد فروع أو فيندورز مربوطة بحسابك حتى الآن. يرجى التواصل مع الإدارة.")
            vendor_input_id = ""
        else:
            options_dict = dict(zip(
                permitted_vendors[vid_col],
                permitted_vendors[name_col] + " (" + permitted_vendors[vid_col] + ")"
            ))
            vendor_input_id = st.selectbox(
                "اختر الفرع / الفيندور الذي تريد تعديل مناطقه:",
                options=list(options_dict.keys()),
                format_func=lambda x: options_dict[x]
            )

    if vendor_input_id and not df_vendors.empty and vid_col:
        v_id_clean = normalize_id(vendor_input_id)
        vendor_data = df_vendors[df_vendors[vid_col] == v_id_clean]
        
        if vendor_data.empty:
            st.error("Invalid Vendor ID.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row[name_col]
            v_chain_id = normalize_id(v_row.get(cid_col, ""))
            st.success(f"Welcome: **{v_name}** | City: {v_row.get(city_col, '')}")

            map_radius_km = st.slider("Map View Radius (km):", min_value=3, max_value=40, value=10, step=1)
            portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km) if not gdf_areas.empty else gpd.GeoDataFrame()
            if not portal_areas.empty:
                portal_areas = portal_areas.sort_values(by="area_size", ascending=False)
            
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist()) if not gdf_areas.empty else []
            # خريطة لمطابقة أسماء المناطق بدون حساسية للمسافات أو حالة الأحرف
            zone_lookup = {z.strip().lower(): z for z in all_available_zones}

            # -------------------------------------------------------------
            # استرجاع البيانات المحفوظة مسبقاً من شيت الـ Delivery
            # -------------------------------------------------------------
            pre_filled_zones = []
            pre_filled_data = {}
            if not df_delivery.empty:
                d_vid_col = get_col(df_delivery, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
                d_cid_col = get_col(df_delivery, ["Chain ID", "Chain Id", "ChainID", "chain_id"])
                d_zone_col = get_col(df_delivery, ["Area Name", "Delivery Area Name", "Zone", "Delivery Location Area Name", "Area", "Delivery Zone"])
                d_time_col = get_col(df_delivery, ["Delivery Time", "Time", "Duration"])
                d_fee_col = get_col(df_delivery, ["Delivery Fees", "Fee", "Delivery Fee", "Price"])

                my_del_df = pd.DataFrame()

                # 1. البحث أولاً بواسطة Vendor ID
                if d_vid_col:
                    norm_vids = df_delivery[d_vid_col].apply(normalize_id)
                    my_del_df = df_delivery[norm_vids == v_id_clean]

                # 2. إذا لم نجد تطابق، نبحث بـ Chain ID
                if my_del_df.empty and d_cid_col and v_chain_id:
                    norm_cids = df_delivery[d_cid_col].apply(normalize_id)
                    my_del_df = df_delivery[norm_cids == v_chain_id]

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
                st.info(f"✨ تم العثور على {len(pre_filled_zones)} منطقة مسجلة مسبقاً لهذا الفيندور في شيت التوصيل وتطبيقها تلقائياً.")

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            # ---------------- عمود الخريطة ----------------
            with col_map:
                st.subheader(f"🗺️ Map ({len(current_applied)} Zones Applied)")
                st.caption("Click any small sub-zone to automatically copy its name, then paste it in the search box.")

                v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=13)
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
                        if not zone_row.empty:
                            dist = haversine_km(v_row["lat"], v_row["lng"], zone_row.iloc[0]["centroid_lat"], zone_row.iloc[0]["centroid_lng"])
                        else:
                            dist = 0.0
                            
                        def_time = pre_data.get(zone, {}).get("time", "")
                        def_fee = pre_data.get(zone, {}).get("fees", None)
                            
                        pricing_data.append({
                            "Zone": zone,
                            "Distance (km)": round(dist, 1),
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
                        if not df_vendors.empty and "Chain Attributes Chain ID" in df_vendors.columns:
                            chains_df = df_vendors[["Chain Attributes Chain ID", "Chain Attributes Chain Name"]].drop_duplicates()
                            chain_opts = dict(zip(chains_df["Chain Attributes Chain ID"], chains_df["Chain Attributes Chain Name"] + " (" + chains_df["Chain Attributes Chain ID"] + ")"))
                            chosen_chains = st.multiselect("اختر السلاسل:", options=list(chain_opts.keys()), format_func=lambda x: chain_opts[x])
                            selected_access_ids_str = ", ".join(chosen_chains)
                        else:
                            st.warning("بيانات السلاسل غير متوفرة حالياً.")
                            selected_access_ids_str = ""
                    else:
                        access_type = "Vendor ID"
                        if not df_vendors.empty and "Vendor Attributes Vendor Id" in df_vendors.columns:
                            vendors_df = df_vendors[["Vendor Attributes Vendor Id", "Vendor Attributes Vendor Name (English)"]].drop_duplicates()
                            vendor_opts = dict(zip(vendors_df["Vendor Attributes Vendor Id"], vendors_df["Vendor Attributes Vendor Name (English)"] + " (" + vendors_df["Vendor Attributes Vendor Id"] + ")"))
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
