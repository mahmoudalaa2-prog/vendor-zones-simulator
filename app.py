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
import requests
from datetime import datetime

# ==========================================
# 1. إعدادات الصفحة والتصميم واللغة
# ==========================================
st.set_page_config(layout="wide", page_title="Pharmacy & Zones Management", page_icon="💊")

st.markdown("""
<style>
div[data-testid="stMetricValue"] {
    font-size: 21px !important;
    font-weight: 700 !important;
}
div[data-testid="stMetricLabel"] {
    font-size: 13px !important;
}
div[data-testid="stMetricDelta"] {
    font-size: 12px !important;
}

/* ضبط حجم النوافذ المنبثقة على الخريطة لتكون مدمجة وتدعم التمرير */
.leaflet-popup-content-wrapper {
    border-radius: 8px !important;
    padding: 2px !important;
    box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
}
.leaflet-popup-content {
    margin: 6px 8px !important;
    line-height: 1.3 !important;
    max-height: 190px !important;
    overflow-y: auto !important;
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
    {"hex": "#17a2b8", "folium": "cadetblue", "name": "تركواز"},
    {"hex": "#d63384", "folium": "pink", "name": "وردي"},
    {"hex": "#0dcaf0", "folium": "lightblue", "name": "سماوي"},
    {"hex": "#198754", "folium": "darkgreen", "name": "أخضر داكن"},
    {"hex": "#8540f5", "folium": "darkpurple", "name": "أرجواني"},
    {"hex": "#a52a2a", "folium": "darkred", "name": "بني"},
    {"hex": "#ffc107", "folium": "orange", "name": "أصفر ذهبي"},
    {"hex": "#20c997", "folium": "cadetblue", "name": "تيل"},
    {"hex": "#6610f2", "folium": "darkpurple", "name": "نيلي"},
    {"hex": "#fd7e14", "folium": "orange", "name": "برتقالي فاقع"},
    {"hex": "#007bff", "folium": "blue", "name": "أزرق"}
]

# ==========================================
# 2. إدارة المستخدمين وقاعدة البيانات الأمنية
# ==========================================
USERS_FILE = "users.csv"
REQUESTS_FILE = "vendor_pricing_requests.csv"

REQUESTS_COLUMNS = [
    "Date", "Vendor ID", "Vendor Name", "Zone", "Classification", 
    "Action", "Distance (km)", "Delivery Time", "Delivery Fees", "Final_Status", "Status"
]

def init_users_db():
    if not os.path.exists(USERS_FILE):
        pd.DataFrame([{
            "email": "mahmoud.alaa.2@talabat.com",
            "password": "123456",
            "role": "admin",
            "access_type": "all",
            "access_ids": "all"
        }]).to_csv(USERS_FILE, index=False)

def get_users_df():
    init_users_db()
    return pd.read_csv(USERS_FILE)

def add_user(email, password, role, access_type="all", access_ids="all"):
    df = get_users_df()
    email_clean = email.strip().lower()
    if email_clean in df["email"].str.lower().values:
        return False, T("هذا البريد مسجل بالفعل!", "This email already exists!")
    new_user = pd.DataFrame([{
        "email": email_clean,
        "password": str(password).strip(),
        "role": role,
        "access_type": access_type,
        "access_ids": access_ids
    }])
    df = pd.concat([df, new_user], ignore_index=True)
    df.to_csv(USERS_FILE, index=False)
    return True, T("تم إنشاء الحساب بنجاح!", "User created successfully!")

def update_user_permissions(email, role, access_type, access_ids, new_password=None):
    df = get_users_df()
    email_clean = email.strip().lower()
    idx = df[df["email"].str.lower() == email_clean].index
    if not idx.empty:
        df.loc[idx, "role"] = role
        df.loc[idx, "access_type"] = access_type
        df.loc[idx, "access_ids"] = str(access_ids)
        if new_password and str(new_password).strip():
            df.loc[idx, "password"] = str(new_password).strip()
        df.to_csv(USERS_FILE, index=False)
        return True, T("تم تحديث البيانات وكلمة المرور بنجاح!", "User details and password updated successfully!"), df.iloc[idx[0]].to_dict()
    return False, T("المستخدم غير موجود.", "User not found."), None

def delete_user(email):
    df = get_users_df()
    if email.strip().lower() == "mahmoud.alaa.2@talabat.com":
        return False, T("لا يمكن حذف الأدمن الرئيسي!", "Cannot delete master admin!")
    df = df[df["email"].str.lower() != email.strip().lower()]
    df.to_csv(USERS_FILE, index=False)
    return True, T("تم حذف الحساب بنجاح!", "User deleted successfully!")

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
    if not isinstance(polygon_str, str): return None
    return re.sub(r',\s*\)\)', '))', re.sub(r'polygon\(\(\s*,\s*', 'polygon((', polygon_str.strip(), flags=re.IGNORECASE))

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
# 4. جلب وتجهيز البيانات
# ==========================================
@st.cache_data(ttl=1800)
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

        df_d["clean_vid"] = df_d[d_vid_col].apply(normalize_id) if d_vid_col else ""
        df_d["clean_cid"] = df_d[d_cid_col].apply(normalize_id) if d_cid_col else ""
        df_d["clean_zone"] = df_d[d_zone_col].astype(str).str.strip() if d_zone_col else ""
        df_d["clean_time"] = df_d[d_time_col].astype(str).str.strip() if d_time_col else ""
        df_d["clean_fee"] = df_d[d_fee_col].astype(str).str.strip() if d_fee_col else ""

        valid_vids = set(df_v["clean_vid"].unique()) - {""}
        valid_cids = set(df_v["clean_cid"].unique()) - {""}

        mask = (df_d["clean_vid"].isin(valid_vids)) | (df_d["clean_cid"].isin(valid_cids))
        df_d = df_d[mask].copy()

    if not df_a.empty:
        poly_col = robust_get_col(df_a, ["Delivery Location Area Polygon", "Polygon", "WKT", "Area Polygon"])
        if poly_col:
            df_a["cleaned_wkt"] = df_a[poly_col].apply(clean_wkt)
            geometries, valid_indices = [], []
            for idx, wkt_str in df_a["cleaned_wkt"].items():
                if pd.notnull(wkt_str):
                    try:
                        geometries.append(wkt.loads(wkt_str))
                        valid_indices.append(idx)
                    except Exception: pass
                        
            gdf_a = gpd.GeoDataFrame(df_a.loc[valid_indices], geometry=geometries, crs="EPSG:4326")
            gdf_a["area_size"] = gdf_a["geometry"].area
            area_name_col = robust_get_col(gdf_a, ["Delivery Location Area Name", "Area Name", "Name"])
            if area_name_col:
                gdf_a["Delivery Location Area Name"] = gdf_a[area_name_col].astype(str).str.strip()
                mask_mcd = gdf_a["Delivery Location Area Name"].str.contains(r"mcd|mcdonald", case=False, na=False)
                gdf_a = gdf_a[(~mask_mcd) & (gdf_a["area_size"] < 0.5)].copy()
                
            gdf_a = gdf_a.sort_values(by="area_size", ascending=False)
            centroids = gdf_a.geometry.centroid
            gdf_a["centroid_lat"] = centroids.y
            gdf_a["centroid_lng"] = centroids.x
            gdf_a["geometry"] = gdf_a["geometry"].simplify(tolerance=0.0012, preserve_topology=True)
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

def init_requests_db():
    if not os.path.exists(REQUESTS_FILE):
        pd.DataFrame(columns=REQUESTS_COLUMNS).to_csv(REQUESTS_FILE, index=False)

def save_detailed_request(vendor_id, vendor_name, edited_df):
    init_requests_db()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    records = []
    for _, r in edited_df.iterrows():
        z_name = str(r.get("Zone", "")).strip()
        classification = str(r.get("Classification", "Vendor Zone Update")).strip()
        action = str(r.get("Action", "Active")).strip()
        
        dist_val = str(r.get("Distance (km)", "-")).strip()
        if dist_val in ["-", "", "nan", "None"]:
            dist_val = calc_vendor_zone_distance(vendor_id, z_name, df_vendors, gdf_areas)
            
        d_time = str(r.get("Delivery Time", "45 mins")).strip()
        fee_val = r.get("Delivery Fees") or r.get("Delivery Fees (EGP)") or r.get("Fees") or 25.0
        try: fee_val = float(fee_val)
        except: fee_val = 25.0
        
        final_status = str(r.get("Final_Status", "Active (Existing)")).strip()
        
        records.append({
            "Date": date_str,
            "Vendor ID": str(vendor_id),
            "Vendor Name": str(vendor_name),
            "Zone": z_name,
            "Classification": classification,
            "Action": action,
            "Distance (km)": dist_val,
            "Delivery Time": d_time,
            "Delivery Fees": fee_val,
            "Final_Status": final_status,
            "Status": "Pending"
        })
        
    save_df = pd.DataFrame(records, columns=REQUESTS_COLUMNS)
    save_df.to_csv(REQUESTS_FILE, mode="a", header=False, index=False)

def build_zone_popup_card(area_name, info_list):
    if not info_list:
        return (
            "<div style='font-family: Arial, sans-serif; font-size: 10.5px; width: 200px; padding: 3px; direction: rtl; text-align: right;'>"
            + "<b style='color: #0d6efd;'>📍 " + str(area_name) + "</b><br>"
            + "<span style='color: #6c757d; font-size: 9.5px;'>منطقة عامة (غير مغطاة حالياً)</span>"
            + "</div>"
        )
    
    branch_count = len(info_list)
    parts = [
        "<div style='font-family: Arial, sans-serif; width: 255px; max-height: 175px; overflow-y: auto; padding: 2px; direction: rtl; text-align: right;'>",
        "<div style='position: sticky; top: 0; background: #ffffff; padding-bottom: 3px; border-bottom: 1.5px solid #0d6efd; margin-bottom: 4px; z-index: 10;'>",
        "<b style='color: #0d6efd; font-size: 11.5px;'>📍 " + str(area_name) + "</b> <span style='color: #198754; font-size: 9.5px; font-weight: bold;'>(" + str(branch_count) + " فروع)</span>",
        "</div>",
        "<div style='display: flex; flex-direction: column; gap: 3px;'>"
    ]
    for b in info_list:
        b_name = b.get("name", "")
        b_hex = b.get("hex", "#28a745")
        b_time = b.get("time", "-")
        b_fee = b.get("fee", "-")
        parts.append(
            "<div style='border-right: 3px solid " + str(b_hex) + "; padding: 2px 5px; background: #f8f9fa; border-radius: 3px; font-size: 10px; line-height: 1.25;'>"
            + "<b style='color: #212529;'>" + str(b_name) + "</b><br>"
            + "<span style='color: #6c757d; font-size: 9px;'>⏱️ " + str(b_time) + " | 💵 " + str(b_fee) + " EGP</span>"
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
<h4 style='margin:0 0 4px 0; color:#0d6efd; font-size: 12.5px;'>💊 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code> | <b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>{T("المدينة", "City")}:</b> {v_city} | <b>AM:</b> <b>{v_am}</b><br>
<b>{T("الحالة", "Status")}:</b> {status_badge}{hidden_badge}<br>
<hr style='margin:5px 0; border:0; border-top:1px solid #ddd;'>"""

    if v_perf:
        html += f"""<div style='background:#f8f9fa; border:1px solid #dee2e6; border-radius:4px; padding:5px; margin-bottom:5px;'>
<b style='color:#0d6efd; font-size: 11px;'>📊 {T("مؤشرات الأداء", "Performance")}:</b>
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

# الدالة الفورية لالتقاط نقرة المضلع بدقة عالية وتفضيل الأصغر مساحة
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
# 5. شاشة تسجيل الدخول
# ==========================================
init_users_db()
init_requests_db()

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["current_user"] = None

if not st.session_state["logged_in"]:
    st.markdown(f"<h2 style='text-align: center;'>🔐 {T('تسجيل الدخول إلى النظام', 'System Login')}</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; color: gray;'>{T('يرجى إدخال البريد الإلكتروني وكلمة المرور للمتابعة', 'Please enter your email and password to continue')}</p>", unsafe_allow_html=True)
    
    _, col_form, _ = st.columns([1, 1.5, 1])
    with col_form:
        with st.form("login_form"):
            email_input = st.text_input(T("البريد الإلكتروني (Email):", "Email:")).strip().lower()
            password_input = st.text_input(T("كلمة المرور (Password):", "Password:"), type="password").strip()
            login_btn = st.form_submit_button(T("تسجيل الدخول", "Login"), type="primary", use_container_width=True)
            
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
    st.stop()

current_user = st.session_state["current_user"]
is_admin = current_user["role"] == "admin"

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
    st.write(f"🛡️ **{T('الصلاحية', 'Role')}:** `{current_user['role'].upper()}`")
    if current_user.get("access_type") != "all":
        st.write(f"📌 **{T('نطاق الربط', 'Scope')}:** `{current_user['access_type']}`")
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

if is_admin:
    tab1, tab2, tab3, tab4 = st.tabs([
        T("🗺️ Overview Map", "🗺️ Overview Map"),
        T("🛒 Vendor Portal", "🛒 Vendor Portal"),
        T("📥 Incoming Requests", "📥 Incoming Requests"),
        T("👥 Users", "👥 Users")
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
                "⏸️ خريطة المراقبة العامة معطلة لتوفير أقصى سرعة لبوابة الفيندورز. فَعِّل المفتاح أعلاه عند الحاجة لاستعراض التغطية العامة.",
                "⏸️ Admin overview map is disabled to maximize Vendor Portal speed. Toggle switch above when you need to view the map."
            ))
        else:
            f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.4, 1.4, 1.2])
            
            with f_col1:
                if not user_vendors.empty and "clean_city" in user_vendors.columns:
                    all_cities = sorted([c for c in user_vendors["clean_city"].dropna().unique() if c and c != "-"])
                else: all_cities = []
                
                if "admin_map_cities" in st.session_state:
                    st.session_state["admin_map_cities"] = [c for c in st.session_state["admin_map_cities"] if c in all_cities]

                selected_cities = st.multiselect(
                    T("1. المدينة / المحافظة:", "1. City:"),
                    options=all_cities,
                    placeholder=T("الكل (أو اختر مدن)", "All (or select cities)"),
                    key="admin_map_cities"
                )

            city_subset = user_vendors[user_vendors["clean_city"].isin(selected_cities)] if selected_cities else user_vendors.copy()

            with f_col2:
                if not city_subset.empty and "clean_am" in city_subset.columns:
                    valid_ams = sorted([a for a in city_subset["clean_am"].dropna().unique() if is_valid_am_name(a)])
                else: valid_ams = []
                
                if "admin_map_ams" in st.session_state:
                    st.session_state["admin_map_ams"] = [a for a in st.session_state["admin_map_ams"] if a in valid_ams]

                selected_ams = st.multiselect(
                    T("2. مسؤول الحساب (AM):", "2. Account Manager (AM):"),
                    options=valid_ams,
                    placeholder=T("الكل (أو اختر AMs)", "All (or select AMs)"),
                    key="admin_map_ams"
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
                    
                if "admin_map_chains" in st.session_state:
                    st.session_state["admin_map_chains"] = [c for c in st.session_state["admin_map_chains"] if c in chain_options]

                selected_chains = st.multiselect(
                    T("3. السلسلة (Chain):", "3. Chain:"),
                    options=chain_options,
                    format_func=lambda x: chain_map.get(x, x),
                    placeholder=T("الكل (أو اختر سلاسل)", "All (or select chains)"),
                    key="admin_map_chains"
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
                    
                if "admin_map_vendors" in st.session_state:
                    st.session_state["admin_map_vendors"] = [v for v in st.session_state["admin_map_vendors"] if v in vendor_options]

                selected_vendors = st.multiselect(
                    T("4. الفرع (Vendor):", "4. Vendor:"),
                    options=vendor_options,
                    format_func=lambda x: vendor_opts.get(x, x),
                    placeholder=T("الكل (أو اختر فروع)", "All (or select vendors)"),
                    key="admin_map_vendors"
                )

            df_disp = chain_subset[chain_subset["clean_vid"].isin(selected_vendors)] if selected_vendors else chain_subset.copy()

            f2_col1, f2_col2, f2_col3 = st.columns([1.5, 1.5, 1.8])
            with f2_col1:
                selected_active = st.selectbox(
                    T("5. حالة التفعيل (Is Active):", "5. Active Status (Is Active):"),
                    options=[T("الكل", "All"), T("نشط فقط (Yes)", "Active Only (Yes)"), T("غير نشط (No)", "Inactive Only (No)")],
                    key="admin_filter_active"
                )
            with f2_col2:
                selected_hidden = st.selectbox(
                    T("6. حالة الظهور (Is Hidden):", "6. Visibility (Is Hidden):"),
                    options=[T("الكل", "All"), T("الظاهر فقط (No)", "Visible Only (No)"), T("المخفي فقط (Yes)", "Hidden Only (Yes)")],
                    key="admin_filter_hidden"
                )
            with f2_col3:
                st.write("")
                st.write("")
                if st.button(T("🔄 إعادة ضبط الفلاتر", "🔄 Reset Filters"), key="admin_reset_filters", use_container_width=True):
                    for k in ["admin_map_cities", "admin_map_ams", "admin_map_chains", "admin_map_vendors", "admin_filter_active", "admin_filter_hidden"]:
                        if k in st.session_state:
                            del st.session_state[k]
                    st.rerun()

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
                            "fee": r.get("clean_fee", "-")
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
                    covered_names = set(zone_to_vendor_info.keys())
                    covered_mask = gdf_areas["Delivery Location Area Name"].astype(str).str.strip().str.lower().isin(covered_names)
                    covered_gdf = gdf_areas[covered_mask].copy()

                    if not plot_vendors.empty:
                        valid_coords = plot_vendors.dropna(subset=["lat", "lng"])
                        if not valid_coords.empty and len(valid_coords) <= 350:
                            minx, miny, maxx, maxy = valid_coords["lng"].min(), valid_coords["lat"].min(), valid_coords["lng"].max(), valid_coords["lat"].max()
                            bbox = box(minx - 0.12, miny - 0.12, maxx + 0.12, maxy + 0.12)
                            nearby_mask = gdf_areas.geometry.intersects(bbox)
                            nearby_gdf = gdf_areas[nearby_mask].copy()
                            gdf_areas_to_render = pd.concat([covered_gdf, nearby_gdf]).drop_duplicates(subset=["Delivery Location Area Name"])
                        else:
                            gdf_areas_to_render = covered_gdf
                    else:
                        gdf_areas_to_render = covered_gdf if not covered_gdf.empty else gdf_areas.head(80).copy()

                if not gdf_areas_to_render.empty:
                    gdf_areas_to_render = gdf_areas_to_render.sort_values(by="area_size", ascending=False)
                    def assign_zone_styling_and_popup(area_name):
                        z_clean = str(area_name).strip().lower()
                        if z_clean in zone_to_vendor_info:
                            info_list = zone_to_vendor_info[z_clean]
                            primary_info = info_list[0]
                            prim_hex = primary_info.get("hex", "#28a745")
                            card_html = build_zone_popup_card(area_name, info_list)
                            return prim_hex, prim_hex, 0.45, 2.0, card_html, True
                        
                        card_html = build_zone_popup_card(area_name, [])
                        return "#3388ff", "#002266", 0.08, 1.0, card_html, False

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
# Tab 2: Vendor Portal (التبديل الذكي للوضع + التحديد من أول كليك)
# ==========================================
with tab2:
    st.header(T("بوابة الفيندور - التغطية والتسعير والأداء", "Vendor Portal - Coverage, Pricing & Performance"))
    
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

            all_known_zones = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist()) if not gdf_areas.empty else []
            zlk = {z.strip().lower(): z for z in all_known_zones}

            if st.session_state.get("portal_session_id") != portal_session_key:
                st.session_state["portal_session_id"] = portal_session_key
                original_alloc = {str(b_vid): {} for b_vid in branch_names.keys()}
                
                vids_in_scope = set(branch_names.keys())
                if not df_delivery.empty and "clean_vid" in df_delivery.columns:
                    m_del = df_delivery[df_delivery["clean_vid"].isin(vids_in_scope)]
                    for _, r in m_del.iterrows():
                        v_id = str(r.get("clean_vid", ""))
                        zn = zlk.get(str(r.get("clean_zone", "")).strip().lower())
                        if zn and v_id in original_alloc:
                            fee_val = 0.0
                            raw_fee = str(r.get("clean_fee", "")).strip()
                            try: fee_val = float(raw_fee)
                            except: fee_val = 0.0
                            raw_t = str(r.get("clean_time", "45 mins")).strip()
                            final_t = raw_t if (raw_t and raw_t.lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                            original_alloc[v_id][zn] = {
                                "time": final_t,
                                "fee": fee_val
                            }
                
                import copy
                st.session_state["portal_orig_alloc"] = copy.deepcopy(original_alloc)
                st.session_state["portal_working_alloc"] = copy.deepcopy(original_alloc)
                st.session_state["portal_active_vid"] = list(branch_names.keys())[0] if branch_names else ""
                st.session_state["portal_show_diff"] = False
                st.session_state["portal_selected_zone"] = ""
                st.session_state["just_clicked_map_zone"] = None

            working_alloc = st.session_state.get("portal_working_alloc", {})
            orig_alloc = st.session_state.get("portal_orig_alloc", {})

            # قراءة الفرع النشط مبكراً لضبط تمركز الخريطة
            active_vid = st.session_state.get("portal_active_branch_select") or st.session_state.get("portal_active_vid") or (list(branch_names.keys())[0] if branch_names else "")
            if active_vid not in branch_names and branch_names:
                active_vid = list(branch_names.keys())[0]
            st.session_state["portal_active_vid"] = active_vid

            active_branch_color = branch_color_map.get(active_vid, {}).get("hex", "#28a745")
            active_branch_name = branch_names.get(active_vid, active_vid)

            # دليل ألوان السلسلة
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
                        badge_tag = "<b style='color:#0d6efd;'>🎯 الفرع المحدد</b><br>" if is_active_card else "<br>"
                        st.markdown(
                            f"<div style='padding:5px 8px; border-radius:5px; margin-bottom:5px; border-left: 6px solid {b_info['hex']}; border: {border_highlight}; background: {bg_highlight}; font-size:11.5px; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>"
                            f"<b>{b_info['name']}</b> ({zone_count} منطقة){badge_tag}"
                            f"<span style='color:gray;'>Vendor ID: {b_vid}</span>"
                            f"</div>",
                            unsafe_allow_html=True
                        )

            rad = st.slider(T("نطاق الخريطة (كم):", "Radius (km):"), 3, 50, 15, key="portal_radius_slider")

            # استخراج مضلعات التغطية
            all_chain_covered_zones = set()
            for v_id, z_dict in working_alloc.items():
                for z in z_dict:
                    all_chain_covered_zones.add(z.strip().lower())

            covered_mask = gdf_areas["Delivery Location Area Name"].astype(str).str.strip().str.lower().isin(all_chain_covered_zones) if not gdf_areas.empty else pd.Series(dtype=bool)
            covered_gdf = gdf_areas[covered_mask].copy() if not gdf_areas.empty else gpd.GeoDataFrame()

            if has_loc and not gdf_areas.empty:
                valid_coords = vd.dropna(subset=["lat", "lng"])
                if not valid_coords.empty:
                    branch_pts = MultiPoint([Point(r['lng'], r['lat']) for _, r in valid_coords.iterrows()])
                    nearby_mask = gdf_areas.geometry.intersects(branch_pts.buffer(rad / 111.0))
                    nearby_gdf = gdf_areas[nearby_mask].copy()
                    pa = pd.concat([covered_gdf, nearby_gdf]).drop_duplicates(subset=["Delivery Location Area Name"])
                else:
                    pa = covered_gdf if not covered_gdf.empty else gdf_areas.head(50).copy()
            else:
                pa = covered_gdf if not covered_gdf.empty else (gdf_areas.head(50).copy() if not gdf_areas.empty else gpd.GeoDataFrame())

            if not pa.empty and "area_size" in pa.columns:
                pa = pa.sort_values(by="area_size", ascending=False)

            zone_to_branch_owner = {}
            for v_id, z_dict in working_alloc.items():
                for z in z_dict:
                    zone_to_branch_owner[z.strip().lower()] = v_id

            cm, cf = st.columns([6, 4])

            # الخريطة والتحريك والتحديد
            with cm:
                st.subheader(f"🗺️ Map ({len(all_chain_covered_zones)} {T('منطقة مغطاة للسلسلة', 'Covered Zones')})")
                st.caption(T("💡 انقر على أي منطقة على الخريطة ليتم اختيارها مباشرة في خانة التعديل أو الإضافة أو الإزالة.", "💡 Click any zone on the map to select it directly in the control panel."))

                # التمركز التلقائي على الفرع المختار
                active_row = vd[vd["clean_vid"] == active_vid]
                if not active_row.empty and pd.notna(active_row.iloc[0]["lat"]) and pd.notna(active_row.iloc[0]["lng"]):
                    mcnt = [float(active_row.iloc[0]["lat"]), float(active_row.iloc[0]["lng"])]
                    zoom_lvl = 14
                elif not valid_coords.empty:
                    mcnt = [float(valid_coords["lat"].mean()), float(valid_coords["lng"].mean())]
                    zoom_lvl = 12
                else:
                    mcnt = [30.0444, 31.2357]
                    zoom_lvl = 11

                vmap = folium.Map(location=mcnt, zoom_start=zoom_lvl)

                if not valid_coords.empty:
                    for _, rv in valid_coords.iterrows():
                        b_id_str = str(rv["clean_vid"])
                        b_info = branch_color_map.get(b_id_str, {"hex": "#28a745", "folium": "green"})
                        is_active_b = (b_id_str == active_vid)
                        
                        target_tag = '<span style="color: red; font-weight: bold;">(🎯 الفرع المحدد حالياً للتعديل)</span>' if is_active_b else ''
                        popup_html = f"""<div style='font-family: Arial, sans-serif; font-size: 11px; width: 210px;'>
                        <b style='color: #0d6efd;'>💊 {rv['clean_name']}</b><br>
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
                        z_name_norm = str(feature["properties"].get("Delivery Location Area Name", "")).strip().lower()
                        is_clicked_target = (z_name_norm == selected_zone_in_state and z_name_norm != "")
                        
                        if z_name_norm in zone_to_branch_owner:
                            owner_vid = zone_to_branch_owner[z_name_norm]
                            b_hex = branch_color_map.get(owner_vid, {}).get("hex", "#28a745")
                            is_active_owner = (owner_vid == active_vid)
                            
                            return {
                                "fillColor": "#ffc107" if is_clicked_target else b_hex,
                                "color": "#000000" if is_clicked_target else b_hex,
                                "weight": 4.5 if is_clicked_target else (3.0 if is_active_owner else 1.2),
                                "fillOpacity": 0.8 if is_clicked_target else (0.6 if is_active_owner else 0.3)
                            }
                        return {
                            "fillColor": "#ffc107" if is_clicked_target else "#3388ff",
                            "color": "#000000" if is_clicked_target else "#002266",
                            "weight": 3.5 if is_clicked_target else 1.0,
                            "fillOpacity": 0.65 if is_clicked_target else 0.08
                        }

                    folium.GeoJson(
                        pa[["Delivery Location Area Name", "geometry"]].to_json(),
                        style_function=get_portal_zone_styling,
                        tooltip=folium.GeoJsonTooltip(
                            fields=["Delivery Location Area Name"],
                            aliases=[T("المنطقة: ", "Zone: ")]
                        )
                    ).add_to(vmap)

                mcd = st_folium(
                    vmap,
                    width="100%",
                    height=540,
                    key=f"vmap_portal_{portal_session_key}_{active_vid}_{rad}",
                    returned_objects=["last_object_clicked"]
                )

                # الالتقاط المباشر من خصائص المضلع من أول كليك
                clicked_zone, click_sig = extract_clicked_zone_direct(mcd, pa, all_known_zones)
                if click_sig and click_sig != st.session_state.get("last_poly_click_sig"):
                    st.session_state["last_poly_click_sig"] = click_sig
                    if clicked_zone:
                        st.session_state["portal_selected_zone"] = clicked_zone
                        st.session_state["just_clicked_map_zone"] = clicked_zone
                        st.session_state["portal_show_diff"] = False
                        st.rerun()

            # لوحة التحكم بجوار الخريطة
            with cf:
                st.subheader(T("🛠️ لوحة تعديل المناطق والتسعير", "🛠️ Zone & Pricing Control Panel"))
                
                # قائمة اختيار الفرع المستهدف للتعديل بجوار الخريطة مباشرة
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
                        f"<div style='border-left: 5px solid {active_branch_color}; background: #fdfdfd; padding: 6px 10px; border-radius: 4px; margin-bottom: 10px;'>"
                        f"<b>🎯 الفرع المسؤول:</b> <span style='color:#0d6efd;'>{active_branch_name}</span> (ID: <code>{active_vid}</code>)"
                        f"</div>",
                        unsafe_allow_html=True
                    )

                opt_edit = T("✏️ تعديل الوقت والرسوم لمناطق حالية", "✏️ Edit Time & Fees")
                opt_add = T("➕ إضافة منطقة لهذا الفرع", "➕ Add Zone to Branch")
                opt_del = T("🗑️ إزالة منطقة من هذا الفرع", "🗑️ Remove Zone from Branch")

                active_branch_zones = working_alloc.get(active_vid, {})
                active_zones_keys = sorted(list(active_branch_zones.keys()))
                available_to_add = sorted([z for z in all_known_zones if z not in active_zones_keys])

                # التبديل الذكي التلقائي للوضع بحسب تبعية المنطقة المنقورة
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
                    T("اختر نوع التعديل:", "Select Action:"),
                    options=[opt_edit, opt_add, opt_del],
                    key="portal_action_mode_radio"
                )

                # 1. وضع تعديل الوقت والرسوم لمناطق حالية
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
                        raw_t = cur_z_info.get("time", "")
                        curr_time = str(raw_t).strip() if (raw_t and str(raw_t).strip().lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                        raw_f = cur_z_info.get("fee", 25.0)
                        try: curr_fee = float(raw_f)
                        except: curr_fee = 25.0

                        c_t1, c_t2 = st.columns(2)
                        with c_t1:
                            edit_time_val = st.text_input(
                                T("وقت التوصيل الجديد:", "New Delivery Time:"),
                                value=curr_time,
                                key=f"edit_time_{selected_edit_zone}"
                            )
                        with c_t2:
                            edit_fee_val = st.number_input(
                                T("رسوم التوصيل الجديدة (EGP):", "New Fee (EGP):"),
                                value=curr_fee,
                                step=1.0,
                                key=f"edit_fee_{selected_edit_zone}"
                            )

                        if st.button(T("💾 حفظ تعديل المنطقة", "💾 Save Zone Update"), type="primary", use_container_width=True):
                            working_alloc[active_vid][selected_edit_zone] = {
                                "time": str(edit_time_val).strip(),
                                "fee": float(edit_fee_val)
                            }
                            st.session_state["portal_working_alloc"] = working_alloc
                            st.session_state["portal_show_diff"] = False
                            st.success(T(f"تم تحديث بيانات منطقة {selected_edit_zone} بنجاح!", f"Updated {selected_edit_zone}!"))
                            st.rerun()

                # 2. وضع إضافة منطقة لهذا الفرع
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

                        other_owner_vid = zone_to_branch_owner.get(selected_add_zone.strip().lower())
                        if other_owner_vid and other_owner_vid != active_vid:
                            other_b_name = branch_names.get(other_owner_vid, other_owner_vid)
                            st.warning(T(
                                f"⚠️ تنبيه: هذه المنطقة مسجلة حالياً لفرع ({other_b_name}). إضافتها هنا ستنقل تغطيتها تلقائياً إلى ({active_branch_name}).",
                                f"⚠️ Note: This zone is currently assigned to ({other_b_name}). Adding it here will transfer it to ({active_branch_name})."
                            ))
                            raw_ot = working_alloc[other_owner_vid].get(selected_add_zone, {}).get("time", "45 mins")
                            raw_of = working_alloc[other_owner_vid].get(selected_add_zone, {}).get("fee", 25.0)
                            default_time = str(raw_ot).strip() if (raw_ot and str(raw_ot).strip().lower() not in ["", "nan", "none", "null", "-"]) else "45 mins"
                            try: default_fee = float(raw_of)
                            except: default_fee = 25.0
                        else:
                            default_time = "45 mins"
                            default_fee = 25.0

                        c_a1, c_a2 = st.columns(2)
                        with c_a1:
                            add_time_val = st.text_input(T("وقت التوصيل المقترح:", "Delivery Time:"), value=default_time, key=f"add_time_{selected_add_zone}")
                        with c_a2:
                            add_fee_val = st.number_input(T("رسوم التوصيل المقترحة (EGP):", "Fees (EGP):"), value=default_fee, step=1.0, key=f"add_fee_{selected_add_zone}")

                        if st.button(T("➕ تأكيد إضافة المنطقة لهذا الفرع", "➕ Add Zone to Branch"), type="primary", use_container_width=True):
                            if other_owner_vid and other_owner_vid in working_alloc and selected_add_zone in working_alloc[other_owner_vid]:
                                del working_alloc[other_owner_vid][selected_add_zone]
                            
                            working_alloc[active_vid][selected_add_zone] = {
                                "time": str(add_time_val).strip(),
                                "fee": float(add_fee_val)
                            }
                            st.session_state["portal_working_alloc"] = working_alloc
                            st.session_state["portal_show_diff"] = False
                            st.session_state["portal_selected_zone"] = selected_add_zone
                            if "portal_add_zone_select" in st.session_state:
                                del st.session_state["portal_add_zone_select"]
                            st.success(T(f"تمت إضافة منطقة {selected_add_zone} لـ {active_branch_name} بنجاح!", f"Added {selected_add_zone}!"))
                            st.rerun()

                # 3. وضع إزالة منطقة من هذا الفرع
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
                            st.session_state["portal_show_diff"] = False
                            st.session_state["portal_selected_zone"] = ""
                            if "portal_remove_zone_select" in st.session_state:
                                del st.session_state["portal_remove_zone_select"]
                            st.success(T(f"تمت إزالة منطقة {selected_remove_zone} من {active_branch_name}!", f"Removed {selected_remove_zone}!"))
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

            # جدول حصر التعديلات فقط مع حساب المسافة ووضع Edit
            if st.session_state.get("portal_show_diff"):
                st.markdown("---")
                st.subheader(T("💰 جدول مراجعة المناطق المعدلة فقط (Modifications Only)", "💰 Review Table - Modified Zones Only"))
                st.caption(T(
                    "يعرض هذا الجدول حصرياً المناطق التي طرأ عليها تعديل مع حساب المسافة ونوع الإجراء:",
                    "This table shows exclusively the modified zones along with calculated distance and action:"
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
                                "Vendor ID": v_id,
                                "Branch Name": branch_names.get(v_id, v_id),
                                "Assigned Branch": b_lbl,
                                "Zone": z,
                                "Distance (km)": dist_calc,
                                "Change Type": T("🗑️ إزالة منطقة", "🗑️ Removal"),
                                "Status": T("مسجلة سابقاً", "Existing"),
                                "Action": T("إلغاء التفعيل", "Deactivate"),
                                "Delivery Time": o_zones[z].get("time", "-"),
                                "Delivery Fees (EGP)": float(o_zones[z].get("fee", 0.0) or 0.0)
                            })

                    for z in w_zones:
                        w_item = w_zones[z]
                        dist_calc = calc_vendor_zone_distance(v_id, z, df_vendors, gdf_areas)
                        if z not in o_zones:
                            diff_rows.append({
                                "Vendor ID": v_id,
                                "Branch Name": branch_names.get(v_id, v_id),
                                "Assigned Branch": b_lbl,
                                "Zone": z,
                                "Distance (km)": dist_calc,
                                "Change Type": T("✨ إضافة جديدة", "✨ New Addition"),
                                "Status": T("منطقة جديدة", "New Zone"),
                                "Action": T("نشط", "Active"),
                                "Delivery Time": str(w_item.get("time", "45 mins")),
                                "Delivery Fees (EGP)": float(w_item.get("fee", 25.0) or 0.0)
                            })
                        else:
                            o_item = o_zones[z]
                            t_chg = str(o_item.get("time", "")).strip() != str(w_item.get("time", "")).strip()
                            f_chg = float(o_item.get("fee", 0.0) or 0.0) != float(w_item.get("fee", 0.0) or 0.0)
                            if t_chg or f_chg:
                                diff_rows.append({
                                    "Vendor ID": v_id,
                                    "Branch Name": branch_names.get(v_id, v_id),
                                    "Assigned Branch": b_lbl,
                                    "Zone": z,
                                    "Distance (km)": dist_calc,
                                    "Change Type": T("✏️ تعديل سعر / وقت", "✏️ Update Time/Fee"),
                                    "Status": T("تعديل بيانات", "Updated"),
                                    "Action": "Edit",
                                    "Delivery Time": str(w_item.get("time", "")),
                                    "Delivery Fees (EGP)": float(w_item.get("fee", 0.0) or 0.0)
                                })

                if not diff_rows:
                    st.info(T("ℹ️ لم يتم العثور على أي تعديلات جديدة مقارنة بالبيانات الأصلية.", "ℹ️ No modifications found compared to original allocations."))
                else:
                    diff_df = pd.DataFrame(diff_rows)

                    column_configs = {
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
                        "Delivery Fees (EGP)": st.column_config.NumberColumn(T("رسوم التوصيل (EGP)", "Fees (EGP)"))
                    }

                    display_diff_df = diff_df.drop(columns=["Vendor ID", "Branch Name"], errors="ignore")

                    edited_diff = st.data_editor(
                        display_diff_df,
                        column_config=column_configs,
                        use_container_width=True,
                        hide_index=True,
                        key="portal_diff_editor"
                    )

                    if st.button(T("✅ اعتماد التعديلات وإرسالها للإدارة", "✅ Finalize & Send Modifications to Admin"), type="primary"):
                        for v_id in diff_df["Vendor ID"].unique():
                            b_vname = diff_df[diff_df["Vendor ID"] == v_id]["Branch Name"].iloc[0]
                            branch_indices = diff_df[diff_df["Vendor ID"] == v_id].index
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

                            save_detailed_request(v_id, b_vname, b_sub_df)

                        st.success(T("🎉 تم إرسال وتوثيق كافة التعديلات بنجاح إلى الإدارة!", "🎉 All modifications submitted successfully to Admin!"))
                        st.session_state["portal_show_diff"] = False
                        import copy
                        st.session_state["portal_orig_alloc"] = copy.deepcopy(st.session_state["portal_working_alloc"])
                        st.rerun()

# ==========================================
# Tab 3: Incoming Requests (صفحة الطلبات المجمعة والتحميل المباشر)
# ==========================================
if is_admin:
    with tab3:
        st.header(T("📥 طلبات التسعير والتغطية الواردة من الفروع", "📥 Vendor Pricing & Coverage Requests"))
        init_requests_db()
        
        has_requests = False
        raw_df = pd.DataFrame()
        if os.path.exists(REQUESTS_FILE):
            try:
                raw_df = pd.read_csv(REQUESTS_FILE, on_bad_lines='skip')
                if not raw_df.empty and "Zone" in raw_df.columns:
                    has_requests = True
                    raw_df["Vendor ID"] = raw_df["Vendor ID"].astype(str)
                    raw_df["Action"] = raw_df.get("Action", "").astype(str)

                    # تحديث السجلات لحظياً لحساب المسافة واستبدال نشط بـ Edit للمناطق المعدلة
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

                    # فلاتر التصفية
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

                    # تجميع الطلبات حسب كل إرسال (Vendor + Date)
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
                        if st.button(T("🗑️ حذف جميع الطلبات", "🗑️ Delete All"), type="secondary", use_container_width=True):
                            if os.path.exists(REQUESTS_FILE):
                                os.remove(REQUESTS_FILE)
                            init_requests_db()
                            st.rerun()

                    if show_details and not selected_rows.empty:
                        st.markdown("---")
                        st.subheader(T("🔍 جدول تفاصيل المناطق للطلبات المحددة", "🔍 Detailed Zones for Selected Requests"))
                        st.dataframe(download_df, hide_index=True, use_container_width=True)
            except Exception as e:
                st.error(f"حدث خطأ أثناء قراءة الطلبات: {e}")
                if st.button(T("🛠️ إصلاح وإعادة تهيئة ملف الطلبات", "🛠️ Reset & Repair Requests File"), type="primary"):
                    if os.path.exists(REQUESTS_FILE):
                        os.remove(REQUESTS_FILE)
                    init_requests_db()
                    st.rerun()

        if not has_requests:
            st.info(T("📭 لا توجد طلبات تعديل واردة حالياً من الفروع.", "📭 No incoming requests found."))
            if os.path.exists(REQUESTS_FILE):
                if st.button(T("🔄 تنظيف وإعادة تهيئة السجل", "🔄 Reset Clean Requests DB")):
                    os.remove(REQUESTS_FILE)
                    init_requests_db()
                    st.rerun()

# ==========================================
# Tab 4: Users Management
# ==========================================
if is_admin:
    with tab4:
        st.header(T("👥 إدارة المستخدمين والصلاحيات", "👥 User Management & Permissions"))
        tab_u1, tab_u2, tab_u3 = st.tabs([
            T("➕ إضافة مستخدم جديد", "➕ Add New User"),
            T("✏️ تعديل صلاحيات وكلمة مرور مستخدم", "✏️ Edit Permissions & Password"),
            T("📋 قائمة المستخدمين", "📋 Users List")
        ])
        
        with tab_u1:
            u_role = st.selectbox(T("نوع الحساب:", "Role:"), ["admin", "vendor"], format_func=lambda x: T("مسؤول نظام (Admin)", "Admin") if x == "admin" else T("مستخدم فيندور (Vendor User)", "Vendor User"))
            with st.form("add_user_form"):
                new_email = st.text_input(T("البريد الإلكتروني:", "Email:")).strip().lower()
                new_password = st.text_input(T("كلمة المرور:", "Password:")).strip()
                access_choice = st.radio(
                    T("نطاق الصلاحيات والفروع التابعة:", "Assigned Scope:"),
                    [T("كل فروع القسم (Master Access)", "All Branches (Master Access)"), T("سلاسل محددة (Chain ID)", "Specific Chains (Chain ID)"), T("فروع محددة (Vendor ID)", "Specific Branches (Vendor ID)")]
                )
                
                access_type, selected_access_ids_str = "all", "all"
                if "Chain" in access_choice or "سلاسل" in access_choice:
                    access_type = "Chain ID"
                    chains_df = df_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                    chains_df = chains_df[chains_df["clean_cid"] != ""]
                    chain_opts = dict(zip(chains_df["clean_cid"], chains_df["clean_chain_name"] + " (" + chains_df["clean_cid"] + ")"))
                    chosen_chains = st.multiselect(T("اختر السلاسل:", "Select Chains:"), options=list(chain_opts.keys()), format_func=lambda x: chain_opts[x])
                    selected_access_ids_str = ", ".join(chosen_chains)
                elif "Vendor" in access_choice or "فروع" in access_choice:
                    access_type = "Vendor ID"
                    vendors_df = df_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                    vendors_df = vendors_df[vendors_df["clean_vid"] != ""]
                    vendor_opts = dict(zip(vendors_df["clean_vid"], vendors_df["clean_name"] + " (" + vendors_df["clean_vid"] + ")"))
                    chosen_vendors = st.multiselect(T("اختر الفروع:", "Select Branches:"), options=list(vendor_opts.keys()), format_func=lambda x: vendor_opts[x])
                    selected_access_ids_str = ", ".join(chosen_vendors)
                
                if st.form_submit_button(T("💾 إنشاء الحساب", "💾 Create User"), type="primary"):
                    if not new_email or not new_password:
                        st.error(T("يرجى ملء جميع الحقول المطلوبة.", "Please fill in all required fields."))
                    elif ("Chain" in access_choice or "Vendor" in access_choice) and not selected_access_ids_str:
                        st.error(T("يرجى اختيار فرع أو سلسلة واحدة على الأقل.", "Please select at least one branch or chain."))
                    else:
                        ok, msg = add_user(new_email, new_password, u_role, access_type, selected_access_ids_str)
                        if ok: st.success(msg); st.rerun()
                        else: st.error(msg)

        with tab_u2:
            st.subheader(T("تعديل صلاحيات ومحفظة فروع وكلمة مرور مستخدم مسجل", "Edit User Permissions, Portfolio & Password"))
            users_list_df = get_users_df()
            selected_edit_user = st.selectbox(T("اختر المستخدم للتعديل:", "Select User to Edit:"), options=users_list_df["email"].tolist())
            user_current_row = users_list_df[users_list_df["email"] == selected_edit_user].iloc[0]
            
            with st.form("edit_user_perm_form"):
                e_role = st.selectbox(
                    T("نوع الحساب:", "Role:"),
                    options=["admin", "vendor"],
                    index=0 if user_current_row["role"] == "admin" else 1,
                    format_func=lambda x: T("مسؤول نظام (Admin)", "Admin") if x == "admin" else T("مستخدم فيندور (Vendor User)", "Vendor User")
                )
                
                edit_password_val = st.text_input(
                    T("🔑 كلمة المرور الجديدة (اتركه فارغاً للإبقاء على الحالية دون تغيير):", "🔑 New Password (leave blank to keep current):"),
                    type="password"
                )

                default_scope_idx = 0 if user_current_row["access_type"] == "all" else (1 if user_current_row["access_type"] == "Chain ID" else 2)
                e_access_choice = st.radio(
                    T("نطاق الصلاحيات والفروع التابعة:", "Assigned Scope:"),
                    [T("كل فروع القسم (Master Access)", "All Branches (Master Access)"), T("سلاسل محددة (Chain ID)", "Specific Chains (Chain ID)"), T("فروع محددة (Vendor ID)", "Specific Branches (Vendor ID)")],
                    index=default_scope_idx
                )
                
                e_access_type, e_selected_access_ids_str = "all", "all"
                if "Chain" in e_access_choice or "سلاسل" in e_access_choice:
                    e_access_type = "Chain ID"
                    if not df_vendors.empty and "clean_cid" in df_vendors.columns:
                        chains_df = df_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                        chains_df = chains_df[chains_df["clean_cid"] != ""]
                        chain_opts = dict(zip(chains_df["clean_cid"], chains_df["clean_chain_name"] + " (" + chains_df["clean_cid"] + ")"))
                        curr_ids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in chain_opts]
                        chosen_chains = st.multiselect(T("اختر السلاسل التابعة له:", "Select Chains:"), options=list(chain_opts.keys()), default=curr_ids, format_func=lambda x: chain_opts[x])
                        e_selected_access_ids_str = ", ".join(chosen_chains)
                    else: e_selected_access_ids_str = ""
                elif "Vendor" in e_access_choice or "فروع" in e_access_choice:
                    e_access_type = "Vendor ID"
                    if not df_vendors.empty and "clean_vid" in df_vendors.columns:
                        vendors_df = df_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                        vendors_df = vendors_df[vendors_df["clean_vid"] != ""]
                        vendor_opts = dict(zip(vendors_df["clean_vid"], vendors_df["clean_name"] + " (" + vendors_df["clean_vid"] + ")"))
                        curr_vids = [x.strip() for x in str(user_current_row["access_ids"]).split(",") if x.strip() in vendor_opts]
                        chosen_vendors = st.multiselect(T("اختر الفروع التابعة له:", "Select Branches:"), options=list(vendor_opts.keys()), default=curr_vids, format_func=lambda x: vendor_opts[x])
                        e_selected_access_ids_str = ", ".join(chosen_vendors)
                    else: e_selected_access_ids_str = ""
                    
                if st.form_submit_button(T("💾 حفظ التعديلات وتحديث كلمة المرور", "💾 Save Changes & Password"), type="primary"):
                    ok, msg, updated_row = update_user_permissions(selected_edit_user, e_role, e_access_type, e_selected_access_ids_str, edit_password_val)
                    if ok:
                        if selected_edit_user.lower() == current_user["email"].lower():
                            st.session_state["current_user"] = updated_row
                        st.success(msg); st.rerun()
                    else: st.error(msg)

        with tab_u3:
            users_list_df = get_users_df()
            display_users_df = users_list_df.copy()
            if "password" in display_users_df.columns:
                display_users_df["password"] = "••••••••"
            st.dataframe(display_users_df, use_container_width=True)
            
            deletable = users_list_df[users_list_df["email"].str.lower() != "mahmoud.alaa.2@talabat.com"]["email"].tolist()
            if deletable:
                to_del = st.selectbox(T("اختر المستخدم للحذف:", "Select User to Delete:"), deletable)
                if st.button(T("حذف الحساب نهائياً", "Delete User"), type="secondary"):
                    ok, msg = delete_user(to_del)
                    if ok: st.success(msg); st.rerun()
                    else: st.error(msg)
