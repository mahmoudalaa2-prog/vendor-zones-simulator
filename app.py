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
        
        # حساب المسافة تلقائياً إذا كانت غير محسوبة
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
                st.error(T("❌ الكود غير صحيح
