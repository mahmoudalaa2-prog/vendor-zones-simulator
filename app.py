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
from datetime import datetime

# ==========================================
# 1. إعدادات الصفحة
# ==========================================
st.set_page_config(layout="wide", page_title="Vendor & Zones Management System", page_icon="🔒")

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
def clean_wkt(polygon_str):
    if not isinstance(polygon_str, str):
        return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 # نصف قطر الأرض بالكيلومتر
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c

@st.cache_data
def load_data():
    file_path = "Dataaa.xlsx"
    df_v = pd.read_excel(file_path, sheet_name="Vendor Location")
    coords = df_v["Vendor Attributes Vendor Map Location"].str.split(",", expand=True)
    df_v["lat"] = pd.to_numeric(coords[0], errors="coerce")
    df_v["lng"] = pd.to_numeric(coords[1], errors="coerce")
    df_v = df_v.dropna(subset=["lat", "lng"])
    df_v["Vendor Attributes Vendor Id"] = df_v["Vendor Attributes Vendor Id"].astype(str)
    df_v["Chain Attributes Chain ID"] = df_v["Chain Attributes Chain ID"].astype(str)

    df_a = pd.read_excel(file_path, sheet_name="Area")
    df_a["cleaned_wkt"] = df_a["Delivery Location Area Polygon"].apply(clean_wkt)
    
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
    
    # استبعاد مضلعات ماكدونالدز فقط ومضلعات الجمهورية العامة (> 0.5)
    mask_mcd = gdf_a["Delivery Location Area Name"].str.contains(r"^mcd|^mcdonald", case=False, na=False)
    gdf_a = gdf_a[(~mask_mcd) & (gdf_a["area_size"] < 0.5)].copy()
    
    gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
    
    centroids = gdf_a.geometry.centroid
    gdf_a["centroid_lat"] = centroids.y
    gdf_a["centroid_lng"] = centroids.x
    gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
    return df_v, gdf_a

df_vendors, gdf_areas = load_data()

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

# ==========================================
# 5. الشريط الجانبي وتسجيل الخروج
# ==========================================
current_user = st.session_state["current_user"]
is_admin = current_user["role"] == "admin"

with st.sidebar:
    st.write(f"👤 **مرحباً:** `{current_user['email']}`")
    st.write(f"🛡️ **الصلاحية:** `{current_user['role'].upper()}`")
    if not is_admin:
        st.write(f"📌 **نوع الصلاحية:** `{current_user['access_type']}`")
    st.markdown("---")
    if st.button("🚪 تسجيل الخروج (Logout)", use_container_width=True):
        st.session_state["logged_in"] = False
        st.session_state["current_user"] = None
        st.session_state.clear()
        st.rerun()

# ==========================================
# 6. توزيع الصفحات حسب الدور (Role-Based Routing)
# ==========================================
if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs([
        "🗺️ Overview Map (Admin)",
        "🛒 Vendor Portal",
        "📥 Change Requests (Admin)",
        "👥 User Management (Admin)"
    ])
else:
    # الفيندور يرى فقط صفحة Vendor Portal
    tab2 = st.container()

# ==========================================
# Tab 1: Admin Map (لوحة المراقبة العامة - للأدمن فقط)
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
                all_cities = ["All"] + sorted(df_vendors["Vendor Attributes Vendor City"].dropna().unique().tolist())
                selected_city = st.selectbox("1. Select City:", options=all_cities, key="dash_city")
                st.markdown("---")
                
                temp_df = df_vendors if selected_city == "All" else df_vendors[df_vendors["Vendor Attributes Vendor City"] == selected_city]
                vendor_names = ["All"] + sorted(temp_df["Vendor Attributes Vendor Name (English)"].dropna().unique().tolist())
                selected_name = st.selectbox("Search by Vendor Name:", options=vendor_names, key="dash_name")
                vendor_ids = ["All"] + sorted(temp_df["Vendor Attributes Vendor Id"].dropna().unique().tolist())
                selected_v_id = st.selectbox("Search by Vendor ID:", options=vendor_ids, key="dash_vid")
                chain_ids = ["All"] + sorted(temp_df["Chain Attributes Chain ID"].dropna().unique().tolist())
                selected_chain = st.selectbox("Search by Chain ID:", options=chain_ids, key="dash_chain")
                st.markdown("---")
                show_zones = st.checkbox("Show Area Polygons", value=True, key="dash_zones")
                
                if st.button("Reset Filters", key="reset_btn"):
                    st.session_state.clear()
                    st.rerun()
                    
            with col2:
                filtered_v = df_vendors
                if selected_city != "All":
                    filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor City"] == selected_city]
                if selected_name != "All":
                    filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor Name (English)"] == selected_name]
                if selected_v_id != "All":
                    filtered_v = filtered_v[filtered_v["Vendor Attributes Vendor Id"] == selected_v_id]
                if selected_chain != "All":
                    filtered_v = filtered_v[filtered_v["Chain Attributes Chain ID"] == selected_chain]
                    
                if not filtered_v.empty:
                    center = [filtered_v["lat"].mean(), filtered_v["lng"].mean()]
                    zoom = 14 if (selected_name != "All" or selected_v_id != "All") else 12 if selected_chain != "All" else 11 if selected_city != "All" else 6
                else:
                    center = [30.0444, 31.2357]
                    zoom = 6
                    
                m = folium.Map(location=center, zoom_start=zoom)
                
                css_no_box = """
                <style>
                .leaflet-interactive:focus,
                path.leaflet-interactive:focus,
                .leaflet-container :focus,
                svg:focus {
                    outline: none !important;
                    box-shadow: none !important;
                }
                </style>
                """
                m.get_root().html.add_child(folium.Element(css_no_box))
                
                if show_zones and not gdf_areas.empty:
                    folium.GeoJson(
                        gdf_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                        name="Delivery Zones",
                        style_function=lambda feature: {
                            "fillColor": "#0055ff",
                            "color": "#002266",
                            "weight": 1.0,
                            "fillOpacity": 0.15
                        },
                        tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Area Name: "])
                    ).add_to(m)
                    
                if not filtered_v.empty:
                    cluster = MarkerCluster().add_to(m)
                    is_searched = (selected_name != "All" or selected_v_id != "All" or selected_chain != "All")
                    icon_color = "green" if is_searched else "red"
                    icon_shape = "star" if is_searched else "shopping-cart"
                    for _, row in filtered_v.iterrows():
                        popup_html = f"<b>{row['Vendor Attributes Vendor Name (English)']}</b><br><b>Vendor ID:</b> {row['Vendor Attributes Vendor Id']}<br><b>Chain ID:</b> {row['Chain Attributes Chain ID']}<br><b>Chain Name:</b> {row['Chain Attributes Chain Name']}<br><b>City:</b> {row['Vendor Attributes Vendor City']}"
                        folium.Marker(
                            location=[row['lat'], row['lng']],
                            popup=folium.Popup(popup_html, max_width=300),
                            tooltip=row["Vendor Attributes Vendor Name (English)"],
                            icon=folium.Icon(color=icon_color, icon=icon_shape, prefix="fa")
                        ).add_to(cluster)
                        
                st_folium(m, width="100%", height=650, key="main_map_admin", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal (مقيد بالصلاحيات)
# ==========================================
with tab2:
    st.header("Vendor Portal - Coverage & Pricing Management")
    
    # تحديد الفيندور المتاح حسب الصلاحية
    if is_admin:
        vendor_input_id = st.text_input("Enter Vendor ID:", placeholder="اكتب رقم الفيندور هنا...")
    else:
        allowed_raw = str(current_user["access_ids"]).split(",")
        allowed_ids = [x.strip() for x in allowed_raw if x.strip()]
        
        if current_user["access_type"] == "Chain ID":
            permitted_vendors = df_vendors[df_vendors["Chain Attributes Chain ID"].isin(allowed_ids)]
        else:
            permitted_vendors = df_vendors[df_vendors["Vendor Attributes Vendor Id"].isin(allowed_ids)]
            
        if permitted_vendors.empty:
            st.warning("⚠️ لا توجد فروع أو فيندورز مربوطة بحسابك حتى الآن. يرجى التواصل مع الإدارة.")
            vendor_input_id = ""
        else:
            options_dict = dict(zip(
                permitted_vendors["Vendor Attributes Vendor Id"],
                permitted_vendors["Vendor Attributes Vendor Name (English)"] + " (" + permitted_vendors["Vendor Attributes Vendor Id"] + ")"
            ))
            selected_v_tuple = st.selectbox(
                "اختر الفرع / الفيندور الذي تريد تعديل مناطقه:",
                options=list(options_dict.keys()),
                format_func=lambda x: options_dict[x]
            )
            vendor_input_id = selected_v_tuple

    if vendor_input_id:
        v_id_clean = str(vendor_input_id).strip()
        vendor_data = df_vendors[df_vendors["Vendor Attributes Vendor Id"] == v_id_clean]
        
        if vendor_data.empty:
            st.error("Invalid Vendor ID.")
        else:
            v_row = vendor_data.iloc[0]
            v_name = v_row["Vendor Attributes Vendor Name (English)"]
            v_city = v_row["Vendor Attributes Vendor City"]
            st.success(f"Welcome: **{v_name}** | City: {v_city}")

            map_radius_km = st.slider("Map View Radius (km):", min_value=3, max_value=35, value=10, step=1)
            portal_areas = get_nearby_polygons(v_row["lat"], v_row["lng"], map_radius_km)
            portal_areas = portal_areas.sort_values(by="area_size", ascending=False)
            all_available_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist())

            if "vendor_portal_id" not in st.session_state or st.session_state["vendor_portal_id"] != v_id_clean:
                st.session_state["vendor_portal_id"] = v_id_clean
                initial_covered = [z for z in portal_areas["Delivery Location Area Name"].head(2).tolist() if z in all_available_zones]
                st.session_state["vendor_multiselect"] = list(initial_covered)
                st.session_state["applied_zones"] = list(initial_covered)
                st.session_state["last_click_sig"] = None
                st.session_state["ms_version"] = 0
                st.session_state["show_pricing_table"] = False

            valid_selected = [z for z in st.session_state.get("vendor_multiselect", []) if z in all_available_zones]
            st.session_state["vendor_multiselect"] = valid_selected

            valid_applied = [z for z in st.session_state.get("applied_zones", []) if z in all_available_zones]
            st.session_state["applied_zones"] = valid_applied
            current_applied = valid_applied

            st.markdown("---")
            col_map, col_form = st.columns([6, 4])

            # ---------------- عمود الخريطة ----------------
            with col_map:
                st.subheader(f"🗺️ Map ({len(current_applied)} Zones Applied)")
                st.caption("Click any zone directly on the map to add it to the search box.")

                v_map = folium.Map(location=[v_row["lat"], v_row["lng"]], zoom_start=13)
                folium.Marker(
                    location=[v_row["lat"], v_row["lng"]],
                    popup=f"<b>{v_name}</b>",
                    tooltip="Store Location",
                    icon=folium.Icon(color="green", icon="star")
                ).add_to(v_map)

                applied_set = set(current_applied)

                def vendor_zone_style(feature):
                    name = feature["properties"]["Delivery Location Area Name"]
                    if name in applied_set:
                        return {"fillColor": "#28a745", "color": "#155724", "weight": 2.5, "fillOpacity": 0.55}
                    else:
                        return {"fillColor": "#3388ff", "color": "#004085", "weight": 1.2, "fillOpacity": 0.18}

                css_fix_box = """
                <style>
                .leaflet-interactive:focus,
                path.leaflet-interactive:focus,
                .leaflet-container :focus,
                svg:focus {
                    outline: none !important;
                    box-shadow: none !important;
                }
                path.leaflet-interactive:hover {
                    cursor: pointer;
                }
                path.leaflet-interactive:focus {
                    outline: none !important;
                    stroke: #e74c3c !important;
                    stroke-width: 3.5px !important;
                    stroke-opacity: 1 !important;
                }
                </style>
                """
                v_map.get_root().html.add_child(folium.Element(css_fix_box))

                folium.GeoJson(
                    portal_areas[["Delivery Location Area Name", "geometry"]].to_json(),
                    name="Delivery Zones",
                    style_function=vendor_zone_style,
                    highlight_function=lambda feature: {
                        "color": "#e74c3c",
                        "weight": 3.5,
                        "fillOpacity": 0.35
                    },
                    tooltip=folium.GeoJsonTooltip(fields=["Delivery Location Area Name"], aliases=["Zone: "])
                ).add_to(v_map)

                map_data = st_folium(
                    v_map,
                    width="100%",
                    height=500,
                    key=f"vmap_{v_id_clean}_{map_radius_km}",
                    returned_objects=["last_clicked", "last_object_clicked"]
                )

                if map_data:
                    clicked_zone = None
                    sig = None

                    if map_data.get("last_clicked"):
                        c = map_data["last_clicked"]
                        if isinstance(c, dict) and "lat" in c and "lng" in c:
                            sig = f"coords_{c['lat']:.5f}_{c['lng']:.5f}"
                            pt = Point(c["lng"], c["lat"])
                            matches = portal_areas[portal_areas.geometry.contains(pt)].sort_values(by="area_size", ascending=True)
                            if matches.empty:
                                dists = portal_areas.geometry.distance(pt)
                                if not dists.empty and dists.min() < 0.003:
                                    matches = portal_areas.loc[[dists.idxmin()]]
                            if not matches.empty:
                                clicked_zone = matches.iloc[0]["Delivery Location Area Name"]

                    if not clicked_zone and map_data.get("last_object_clicked"):
                        obj_clicked = map_data.get("last_object_clicked")
                        if obj_clicked and isinstance(obj_clicked, dict) and "properties" in obj_clicked:
                            clicked_zone = obj_clicked["properties"].get("Delivery Location Area Name")
                            sig = f"obj_{clicked_zone}"

                    if clicked_zone and sig != st.session_state.get("last_click_sig"):
                        st.session_state["last_click_sig"] = sig
                        curr_search = list(st.session_state.get("vendor_multiselect", []))
                        if clicked_zone in curr_search:
                            curr_search.remove(clicked_zone)
                        else:
                            curr_search.append(clicked_zone)
                            
                        st.session_state["vendor_multiselect"] = [z for z in curr_search if z in all_available_zones]
                        st.session_state["ms_version"] += 1
                        st.session_state["show_pricing_table"] = False
                        st.rerun()

            # ---------------- عمود مربع البحث ----------------
            with col_form:
                st.subheader("📝 Selected Zones")
                st.caption("Zones you click on the map will automatically appear here:")

                widget_key = f"ms_box_{st.session_state.get('ms_version', 0)}"
                chosen_zones = st.multiselect(
                    "Service Areas:",
                    options=all_available_zones,
                    default=st.session_state.get("vendor_multiselect", []),
                    key=widget_key
                )

                if chosen_zones != st.session_state.get("vendor_multiselect", []):
                    st.session_state["vendor_multiselect"] = chosen_zones

                btn_col1, btn_col2 = st.columns([1, 1])
                
                with btn_col1:
                    if st.button("👁️ Apply to Map", type="secondary", use_container_width=True):
                        st.session_state["applied_zones"] = list(st.session_state["vendor_multiselect"])
                        st.session_state["show_pricing_table"] = False
                        st.rerun()
                        
                with btn_col2:
                    if st.button("🚀 Submit Selection", type="primary", use_container_width=True):
                        if not st.session_state.get("applied_zones"):
                            st.warning("Please select and 'Apply to Map' at least one zone first.")
                        elif set(st.session_state.get("applied_zones", [])) != set(st.session_state.get("vendor_multiselect", [])):
                            st.warning("You have unapplied changes! Please click 'Apply to Map' first.")
                        else:
                            st.session_state["show_pricing_table"] = True
                            st.rerun()

            # ==========================================
            # 4. جدول التسعير والمسافات
            # ==========================================
            if st.session_state.get("show_pricing_table", False):
                st.markdown("---")
                st.subheader("💰 Set Delivery Pricing & Time")
                st.info("Please fill in the estimated delivery time and fees for each selected zone based on the distance.")

                current_applied_hash = ",".join(sorted(st.session_state["applied_zones"]))
                
                if st.session_state.get("pricing_hash") != current_applied_hash:
                    pricing_data = []
                    for zone in st.session_state["applied_zones"]:
                        zone_row = gdf_areas[gdf_areas["Delivery Location Area Name"] == zone]
                        if not zone_row.empty:
                            z_lat = zone_row.iloc[0]["centroid_lat"]
                            z_lng = zone_row.iloc[0]["centroid_lng"]
                            dist = haversine_km(v_row["lat"], v_row["lng"], z_lat, z_lng)
                        else:
                            dist = 0.0
                            
                        pricing_data.append({
                            "Zone": zone,
                            "Distance (km)": round(dist, 1),
                            "Delivery Time": "",
                            "Delivery Fees": None
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
# Tab 3: Admin Review (للأدمن فقط)
# ==========================================
if is_admin:
    with tab3:
        st.header("📥 Vendor Pricing & Coverage Requests")
        
        file_path = "vendor_pricing_requests.csv"
        if os.path.exists(file_path):
            try:
                raw_df = pd.read_csv(file_path)
                
                if "Zone" not in raw_df.columns:
                    st.warning("⚠️ Legacy data format detected. The old database format is incompatible and has been cleared.")
                    os.remove(file_path)
                    st.rerun()
                else:
                    raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                    
                    st.write("### 🔍 Filter Requests")
                    f_col1, f_col2 = st.columns(2)
                    
                    all_req_names = ["All"] + sorted(raw_df["Vendor Name"].dropna().unique().tolist())
                    filter_name = f_col1.selectbox("Filter by Vendor Name:", all_req_names, key="admin_req_name")
                    
                    if filter_name != "All":
                        temp_req_ids = raw_df[raw_df["Vendor Name"] == filter_name]["Vendor ID"].dropna().unique().tolist()
                    else:
                        temp_req_ids = raw_df["Vendor ID"].dropna().unique().tolist()
                        
                    all_req_ids = ["All"] + sorted(temp_req_ids)
                    filter_id = f_col2.selectbox("Filter by Vendor ID:", all_req_ids, key="admin_req_id")
                    
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
                    
                    st.markdown("---")
                    display_df.insert(0, "Select", False)
                    
                    st.write(f"### 📋 Incoming Requests Overview ({len(display_df)} requests)")
                    st.caption("Check the boxes to select requests. The downloaded file will contain detailed row-by-row data for each zone.")
                    
                    edited_display_df = st.data_editor(
                        display_df,
                        column_config={
                            "Select": st.column_config.CheckboxColumn("Select", help="Select to download", default=False),
                            "Date": st.column_config.TextColumn(disabled=True),
                            "Vendor ID": st.column_config.TextColumn(disabled=True),
                            "Vendor Name": st.column_config.TextColumn(disabled=True),
                            "Total Zones Count": st.column_config.NumberColumn(disabled=True),
                            "Zones Overview": st.column_config.TextColumn(disabled=True),
                            "Status": st.column_config.TextColumn(disabled=True)
                        },
                        hide_index=True,
                        use_container_width=True,
                        key="admin_requests_editor"
                    )
                    
                    selected_displays = edited_display_df[edited_display_df["Select"] == True]
                    
                    st.markdown("---")
                    col_down1, col_down2 = st.columns([7, 3])
                    
                    with col_down1:
                        st.write("#### 💾 Download Selected Requests")
                        if selected_displays.empty:
                            st.info("Select one or more requests from the table above to download the detailed CSV.")
                        else:
                            selected_vendors_dates = selected_displays[["Vendor ID", "Date"]].apply(tuple, axis=1).tolist()
                            download_df = raw_df[raw_df[["Vendor ID", "Date"]].apply(tuple, axis=1).isin(selected_vendors_dates)]
                            
                            csv_data = download_df.to_csv(index=False).encode('utf-8-sig')
                            
                            if len(selected_displays) == 1:
                                v_name = selected_displays.iloc[0]['Vendor Name']
                                file_name = f"Detailed_Pricing_{v_name}.csv"
                                st.success(f"1 Request selected. The file contains {len(download_df)} detailed zone rows.")
                            else:
                                file_name = "Combined_Detailed_Pricing.csv"
                                st.success(f"{len(selected_displays)} Requests selected. The file contains {len(download_df)} combined zone rows.")
                                
                            st.download_button(
                                label="📥 Download Detailed CSV (Row per Zone)",
                                data=csv_data,
                                file_name=file_name,
                                mime="text/csv",
                                type="primary"
                            )
                            
                    with col_down2:
                        st.write("#### 🗑️ Clear Database")
                        st.warning("Delete all requests permanently.")
                        if st.button("Delete All Requests Data", type="secondary"):
                            os.remove("vendor_pricing_requests.csv")
                            st.rerun()

            except Exception as e:
                st.error("A critical format error occurred with the database file.")
                if st.button("Force Clear Corrupted Data", type="primary"):
                    os.remove("vendor_pricing_requests.csv")
                    st.rerun()
        else:
            st.info("No detailed requests received yet. Wait for vendors to submit.")

# ==========================================
# Tab 4: User Management (إدارة المستخدمين - للأدمن فقط)
# ==========================================
if is_admin:
    with tab4:
        st.header("👥 User Management (إدارة المستخدمين والصلاحيات)")
        st.caption("من هنا يمكنك إضافة مسؤولين جدد (Admins) أو إنشاء حسابات للفيندورز وتحديد السلاسل/الفروع المسموح لهم برؤيتها فقط.")
        
        tab_u1, tab_u2 = st.tabs(["➕ إضافة مستخدم جديد", "📋 قائمة المستخدمين الحالية"])
        
        with tab_u1:
            st.subheader("إنشاء حساب مستخدم جديد")
            
            u_role = st.selectbox("نوع الحساب (Role):", ["vendor", "admin"], format_func=lambda x: "مسؤول نظام (Admin)" if x == "admin" else "مستخدم فيندور (Vendor User)")
            
            with st.form("add_user_form"):
                new_email = st.text_input("البريد الإلكتروني (Email):").strip().lower()
                new_password = st.text_input("كلمة المرور (Password):").strip()
                
                access_type = "all"
                selected_access_ids_str = "all"
                
                if u_role == "vendor":
                    st.markdown("---")
                    st.write("**تحديد صلاحية الوصول للفيندور:**")
                    access_choice = st.radio(
                        "طريقة ربط الصلاحية:",
                        ["سلسلة كاملة (Chain ID)", "فروع محددة (Vendor ID)"]
                    )
                    
                    if access_choice == "سلسلة كاملة (Chain ID)":
                        access_type = "Chain ID"
                        chains_df = df_vendors[["Chain Attributes Chain ID", "Chain Attributes Chain Name"]].drop_duplicates()
                        chain_options = dict(zip(
                            chains_df["Chain Attributes Chain ID"],
                            chains_df["Chain Attributes Chain Name"] + " (" + chains_df["Chain Attributes Chain ID"] + ")"
                        ))
                        chosen_chains = st.multiselect("اختر السلسلة / السلاسل المسموح بها:", options=list(chain_options.keys()), format_func=lambda x: chain_options[x])
                        selected_access_ids_str = ", ".join(chosen_chains)
                    else:
                        access_type = "Vendor ID"
                        vendors_df = df_vendors[["Vendor Attributes Vendor Id", "Vendor Attributes Vendor Name (English)"]].drop_duplicates()
                        vendor_options = dict(zip(
                            vendors_df["Vendor Attributes Vendor Id"],
                            vendors_df["Vendor Attributes Vendor Name (English)"] + " (" + vendors_df["Vendor Attributes Vendor Id"] + ")"
                        ))
                        chosen_vendors = st.multiselect("اختر الفروع / الفيندورز المسموح بها:", options=list(vendor_options.keys()), format_func=lambda x: vendor_options[x])
                        selected_access_ids_str = ", ".join(chosen_vendors)
                
                submit_user = st.form_submit_button("💾 إنشاء الحساب وحفظ الصلاحيات", type="primary")
                
                if submit_user:
                    if not new_email or not new_password:
                        st.error("⚠️ يرجى إدخال البريد الإلكتروني وكلمة المرور.")
                    elif u_role == "vendor" and not selected_access_ids_str:
                        st.error("⚠️ يرجى تحديد فرع أو سلسلة واحدة على الأقل لهذا الفيندور.")
                    else:
                        success, msg = add_user(new_email, new_password, u_role, access_type, selected_access_ids_str)
                        if success:
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(f"❌ {msg}")

        with tab_u2:
            st.subheader("المستخدمون المسجلون حالياً")
            users_list_df = get_users_df()
            
            st.dataframe(
                users_list_df[["email", "role", "access_type", "access_ids"]],
                use_container_width=True,
                column_config={
                    "email": "البريد الإلكتروني",
                    "role": "الصلاحية",
                    "access_type": "نوع الربط",
                    "access_ids": "المعرفات المصرح بها"
                }
            )
            
            st.markdown("---")
            st.write("#### 🗑️ حذف مستخدم")
            deletable_users = users_list_df[users_list_df["email"].str.lower() != "mahmoud.alaa.2@talabat.com"]["email"].tolist()
            if deletable_users:
                user_to_delete = st.selectbox("اختر المستخدم للحذف:", deletable_users)
                if st.button("حذف هذا الحساب نهائياً", type="secondary"):
                    ok, d_msg = delete_user(user_to_delete)
                    if ok:
                        st.success(f"✅ {d_msg}")
                        st.rerun()
                    else:
                        st.error(d_msg)
            else:
                st.caption("لا يوجد مستخدمون إضافيون لحذفهم حالياً.")
