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
# 1. إعدادات الصفحة واللغة
# ==========================================
st.set_page_config(layout="wide", page_title="Pharmacy & Zones Management", page_icon="💊")

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
    {"hex": "#198754", "folium": "darkgreen", "name": "أخضر داكن"},
    {"hex": "#8540f5", "darkpurple": "darkpurple", "name": "أرجواني"},
    {"hex": "#a52a2a", "folium": "darkred", "name": "بني"}
]

# ==========================================
# 2. إدارة المستخدمين وقاعدة البيانات الأمنية
# ==========================================
USERS_FILE = "users.csv"
REQUESTS_FILE = "vendor_pricing_requests.csv"

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

def update_user_permissions(email, role, access_type, access_ids):
    df = get_users_df()
    email_clean = email.strip().lower()
    idx = df[df["email"].str.lower() == email_clean].index
    if not idx.empty:
        df.loc[idx, "role"] = role
        df.loc[idx, "access_type"] = access_type
        df.loc[idx, "access_ids"] = access_ids
        df.to_csv(USERS_FILE, index=False)
        return True, T("تم تحديث الصلاحيات بنجاح!", "Permissions updated successfully!"), df.iloc[idx[0]].to_dict()
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
    if pd.isna(val) or str(val).strip().lower() in ["", "none", "nan", "null"]: return default
    return "Yes" if str(val).strip().lower() in ["yes", "y", "true", "1"] else "No"

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

def get_col(df, possible_names):
    if df.empty: return None
    for name in possible_names:
        for col in df.columns:
            if str(name).strip().lower() == str(col).strip().lower(): return col
    for name in possible_names:
        name_clean = re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()
        for col in df.columns:
            if name_clean == re.sub(r'[^a-zA-Z0-9]', '', str(col)).lower(): return col
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
# 4. جلب وتجهيز البيانات (بما فيها شيت الأداء)
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

    # 1. شيت الفيندورز
    if not df_v.empty:
        vid_col = get_col(df_v, ["Vendor Attributes Vendor Id", "Vendor Id", "Vendor ID", "VendorID", "vendor_id"])
        cid_col = get_col(df_v, ["Chain Attributes Chain ID", "Chain Id", "Chain ID", "ChainID", "chain_id"])
        name_col = get_col(df_v, ["Vendor Attributes Vendor Name (English)", "Vendor Name", "Name", "vendor_name"])
        cname_col = get_col(df_v, ["Chain Attributes Chain Name", "Chain Name", "chain_name"])
        city_col = get_col(df_v, ["Vendor Attributes Vendor City", "City", "Vendor City"])
        am_col = get_col(df_v, ["Vendor Attributes Account Manager", "Account Manager", "AM", "AccountManager", "account_manager"])

        active_col = get_col(df_v, ["Vendor Attributes Is Active", "Is Active", "Active", "IsActive", "is_active"])
        hidden_col = get_col(df_v, ["Vendor Attributes Is Hidden", "Is Hidden", "Hidden", "IsHidden", "is_hidden"])

        df_v["clean_vid"] = df_v[vid_col].apply(normalize_id) if vid_col else ""
        df_v["clean_cid"] = df_v[cid_col].apply(normalize_id) if cid_col else ""
        df_v["clean_name"] = df_v[name_col].astype(str).str.strip() if name_col else ("Vendor " + df_v["clean_vid"])
        df_v["clean_chain_name"] = df_v[cname_col].astype(str).str.strip() if cname_col else ""
        df_v["clean_city"] = df_v[city_col].astype(str).str.strip() if city_col else ""
        df_v["clean_am"] = df_v[am_col].astype(str).str.strip() if am_col else "-"

        df_v["clean_active"] = df_v[active_col].apply(lambda x: parse_yes_no(x, "Yes")) if active_col else "Yes"
        df_v["clean_hidden"] = df_v[hidden_col].apply(lambda x: parse_yes_no(x, "No")) if hidden_col else "No"

        loc_col = get_col(df_v, ["Vendor Attributes Vendor Map Location", "Map Location", "Location", "Coordinates"])
        lat_col = get_col(df_v, ["Latitude", "lat", "Lat"])
        lng_col = get_col(df_v, ["Longitude", "lng", "Lng", "Long", "lon"])

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

    # 2. شيت الأداء
    if not df_p.empty:
        p_vid_col = get_col(df_p, ["Vendor ID", "Vendor Id", "VendorID", "vendor_id"])
        p_cid_col = get_col(df_p, ["Chain ID", "Chain Id", "ChainID", "chain_id"])
        p_am_col = get_col(df_p, ["Account Manager", "AM", "AccountManager", "account_manager"])

        df_p["clean_vid"] = df_p[p_vid_col].apply(normalize_id) if p_vid_col else ""
        df_p["clean_cid"] = df_p[p_cid_col].apply(normalize_id) if p_cid_col else ""
        
        if p_am_col and not df_v.empty:
            df_p["clean_am"] = df_p[p_am_col].astype(str).str.strip()
            if ("clean_am" not in df_v.columns or (df_v["clean_am"] == "-").all()):
                am_dict = dict(zip(df_p["clean_vid"], df_p["clean_am"]))
                df_v["clean_am"] = df_v["clean_vid"].map(am_dict).fillna("-")

        col_qc = get_col(df_p, ["QC Net Orders", "Net Orders", "Orders", "QC_Net_Orders"])
        col_fail_ord = get_col(df_p, ["Vendor Net Failed Orders", "Failed Orders", "Net Failed Orders"])
        col_fail_rate = get_col(df_p, ["Vendor Net Fail Rate", "Fail Rate", "Net Fail Rate", "Fail_Rate"])
        col_cr = get_col(df_p, ["Contact Rate", "CR", "Contact_Rate"])
        col_fault_cr = get_col(df_p, ["Vendor Fault Customer Contact Rate", "Vendor Fault CR", "Fault Contact Rate"])

        df_p["qc_orders"] = df_p[col_qc] if col_qc else "-"
        df_p["fail_orders"] = df_p[col_fail_ord] if col_fail_ord else "-"
        df_p["fail_rate"] = df_p[col_fail_rate] if col_fail_rate else "-"
        df_p["contact_rate"] = df_p[col_cr] if col_cr else "-"
        df_p["fault_cr"] = df_p[col_fault_cr] if col_fault_cr else "-"

    # 3. شيت التوصيل
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

    # 4. شيت المناطق
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
                    except Exception: pass
                        
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

@st.cache_data
def get_nearby_polygons(lat, lng, radius_km):
    if gdf_areas.empty or pd.isna(lat) or pd.isna(lng): return gpd.GeoDataFrame()
    v_point = Point(lng, lat)
    radius_deg = radius_km / 111.0
    nearby_mask = gdf_areas.geometry.intersects(v_point.buffer(radius_deg))
    return gdf_areas[nearby_mask].copy()

def init_requests_db():
    if not os.path.exists(REQUESTS_FILE):
        pd.DataFrame(columns=[
            "Date", "Vendor ID", "Vendor Name", "Zone", "Classification", 
            "Action", "Distance (km)", "Delivery Time", "Delivery Fees", "Final_Status", "Status"
        ]).to_csv(REQUESTS_FILE, index=False)

def save_detailed_request(vendor_id, vendor_name, edited_df):
    init_requests_db()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_df = edited_df.copy()
    save_df.insert(0, "Date", date_str)
    save_df.insert(1, "Vendor ID", str(vendor_id))
    save_df.insert(2, "Vendor Name", vendor_name)
    save_df["Status"] = "Pending"
    save_df.to_csv(REQUESTS_FILE, mode="a", header=False, index=False)

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

    html = f"""<div style='font-family: Arial, sans-serif; width: 290px; font-size: 12px;'>
<h4 style='margin:0 0 5px 0; color:#0d6efd;'>💊 {v_name}</h4>
<b>Vendor ID:</b> <code>{v_id}</code> | <b>Chain:</b> {c_name} (<code>{c_id}</code>)<br>
<b>{T("المدينة", "City")}:</b> {v_city} | <b>AM:</b> <b>{v_am}</b><br>
<b>{T("الحالة", "Status")}:</b> {status_badge}{hidden_badge}<br>
<hr style='margin:6px 0; border:0; border-top:1px solid #ddd;'>"""

    if v_perf:
        html += f"""<div style='background:#f8f9fa; border:1px solid #dee2e6; border-radius:5px; padding:6px; margin-bottom:6px;'>
<b style='color:#0d6efd;'>📊 {T("مؤشرات أداء الفرع (Performance)", "Branch Performance")}:</b>
<table style='width:100%; font-size:11px; margin-top:3px;'>
<tr><td><b>QC Net Orders:</b></td><td style='text-align:right;'><b>{v_perf.get('qc_orders', '-')}</b></td></tr>
<tr><td><b>Failed Orders:</b></td><td style='text-align:right;'>{v_perf.get('fail_orders', '-')} ({v_perf.get('fail_rate', '-')})</td></tr>
<tr><td><b>Contact Rate:</b></td><td style='text-align:right;'>{v_perf.get('contact_rate', '-')}</td></tr>
<tr><td><b>Fault Contact Rate:</b></td><td style='text-align:right;'>{v_perf.get('fault_cr', '-')}</td></tr>
</table></div>"""

    if not match_d.empty and "clean_zone" in match_d.columns:
        zone_count = len(match_d["clean_zone"].dropna().unique())
        html += f"<b style='color:#198754;'>🛵 {T('مناطق توصيل الفرع', 'Delivery Zones')} ({zone_count}):</b>"
        html += "<div style='max-height:120px; overflow-y:auto; margin-top:4px; border:1px solid #dee2e6; border-radius:4px;'>"
        html += "<table style='width:100%; font-size:11px; border-collapse:collapse;'>"
        html += f"<tr style='background:#f8f9fa; text-align:left; position:sticky; top:0;'><th style='padding:3px; border-bottom:1px solid #ddd;'>{T('المنطقة', 'Zone')}</th><th style='padding:3px; border-bottom:1px solid #ddd;'>{T('الوقت', 'Time')}</th><th style='padding:3px; border-bottom:1px solid #ddd;'>{T('السعر', 'Fee')}</th></tr>"
        for _, r in match_d.iterrows():
            z = r.get("clean_zone", "")
            t = r.get("clean_time", "-")
            f = r.get("clean_fee", "-")
            if z:
                html += f"<tr style='border-bottom:1px solid #f1f1f1;'><td style='padding:2px;'>{z}</td><td style='padding:2px;'>{t}</td><td style='padding:2px;'>{f}</td></tr>"
        html += "</table></div>"
    else:
        html += f"<div style='color:#6c757d; font-size:11px; margin-top:4px;'>{T('لا توجد مناطق توصيل مخصصة لهذا الفرع.', 'No dedicated delivery zones.')}</div>"

    html += "</div>"
    return html

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
        value=f"{total_user_branches}",
        delta=f"🟢 {active_user_branches} " + T("نشط", "Active") if total_user_branches > 0 else "0"
    )
    st.caption(T(
        f"📊 تفاصيل: نشط: {active_user_branches} | غير نشط: {inactive_user_branches} | مخفي: {hidden_user_branches}",
        f"📊 Details: Active: {active_user_branches} | Inactive: {inactive_user_branches} | Hidden: {hidden_user_branches}"
    ))
    
    if is_admin:
        st.metric(T("🗺️ إجمالي المناطق الجغرافية", "Total Geographic Zones"), len(gdf_areas))
    
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
# Tab 1: Admin Map (فلتر per AM + مؤشرات الأداء)
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
                    all_cities = [T("كل المدن", "All Cities")] + sorted([c for c in user_vendors["clean_city"].unique() if c])
                else: all_cities = [T("كل المدن", "All Cities")]
                selected_city = st.selectbox(T("1. المدينة / المحافظة:", "1. City:"), options=all_cities, key="admin_map_city")

            if not user_vendors.empty and "clean_city" in user_vendors.columns and selected_city != T("كل المدن", "All Cities"):
                city_df = user_vendors[user_vendors["clean_city"] == selected_city]
            else:
                city_df = user_vendors.copy() if not user_vendors.empty else pd.DataFrame()

            with f_col2:
                if not city_df.empty and "clean_am" in city_df.columns:
                    all_ams = [T("كل الـ AMs", "All AMs")] + sorted([a for a in city_df["clean_am"].unique() if a and a != "-"])
                else: all_ams = [T("كل الـ AMs", "All AMs")]
                selected_am = st.selectbox(T("2. مسؤول الحساب (AM):", "2. Account Manager (AM):"), options=all_ams, key="admin_map_am")

            if not city_df.empty and "clean_am" in city_df.columns and selected_am != T("كل الـ AMs", "All AMs"):
                am_filtered_vendors = city_df[city_df["clean_am"] == selected_am]
            else:
                am_filtered_vendors = city_df.copy()

            with f_col3:
                if not am_filtered_vendors.empty and "clean_cid" in am_filtered_vendors.columns and "clean_chain_name" in am_filtered_vendors.columns:
                    chains_in_city = am_filtered_vendors[["clean_cid", "clean_chain_name"]].drop_duplicates()
                    chains_in_city = chains_in_city[chains_in_city["clean_cid"] != ""]
                    chain_map = dict(zip(chains_in_city["clean_cid"], chains_in_city["clean_chain_name"] + " (" + chains_in_city["clean_cid"] + ")"))
                    chain_options = [T("كل السلاسل", "All Chains")] + list(chain_map.keys())
                else:
                    chain_map = {}
                    chain_options = [T("كل السلاسل", "All Chains")]
                    
                selected_chain = st.selectbox(
                    T("3. السلسلة (Chain):", "3. Chain:"),
                    options=chain_options,
                    format_func=lambda x: T("كل السلاسل", "All Chains") if x == T("كل السلاسل", "All Chains") else chain_map.get(x, x),
                    key="admin_map_chain"
                )

            if not am_filtered_vendors.empty and "clean_cid" in am_filtered_vendors.columns and selected_chain != T("كل السلاسل", "All Chains"):
                chain_filtered_vendors = am_filtered_vendors[am_filtered_vendors["clean_cid"] == selected_chain]
            else:
                chain_filtered_vendors = am_filtered_vendors.copy()

            with f_col4:
                if not chain_filtered_vendors.empty and "clean_vid" in chain_filtered_vendors.columns and "clean_name" in chain_filtered_vendors.columns:
                    vendor_opts = dict(zip(
                        chain_filtered_vendors["clean_vid"],
                        chain_filtered_vendors["clean_name"] + " (ID: " + chain_filtered_vendors["clean_vid"] + ")"
                    ))
                    vendor_options = [T("كل الفروع", "All Vendors")] + list(vendor_opts.keys())
                else:
                    vendor_opts = {}
                    vendor_options = [T("كل الفروع", "All Vendors")]
                    
                selected_vendor = st.selectbox(
                    T("4. الفرع (Vendor):", "4. Vendor:"),
                    options=vendor_options,
                    format_func=lambda x: T("كل الفروع", "All Vendors") if x == T("كل الفروع", "All Vendors") else vendor_opts.get(x, x),
                    key="admin_map_vendor"
                )

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
                    st.rerun()

            df_disp = chain_filtered_vendors.copy() if not chain_filtered_vendors.empty else pd.DataFrame()
            if not df_disp.empty and "clean_vid" in df_disp.columns and selected_vendor != T("كل الفروع", "All Vendors"):
                df_disp = df_disp[df_disp["clean_vid"] == selected_vendor]
                
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

            cnt_total = len(df_disp)
            cnt_active = len(df_disp[df_disp["clean_active"] == "Yes"]) if ("clean_active" in df_disp.columns and not df_disp.empty) else 0
            cnt_inactive = cnt_total - cnt_active
            cnt_hidden = len(df_disp[df_disp["clean_hidden"] == "Yes"]) if ("clean_hidden" in df_disp.columns and not df_disp.empty) else 0

            card_col1, card_col2, card_col3, card_col4 = st.columns(4)
            card_col1.metric(T("الفروع المعروضة", "Displayed Vendors"), cnt_total)
            card_col2.metric(T("🟢 النشطة (Active)", "🟢 Active"), cnt_active)
            card_col3.metric(T("🔴 غير النشطة (Inactive)", "🔴 Inactive"), cnt_inactive)
            card_col4.metric(T("👁️ المخفية (Hidden)", "👁️ Hidden"), cnt_hidden)

            vendor_color_map = {}
            if not chain_filtered_vendors.empty and selected_chain != T("كل السلاسل", "All Chains"):
                chain_branches = chain_filtered_vendors[["clean_vid", "clean_name"]].drop_duplicates()
                for idx, (_, b_row) in enumerate(chain_branches.iterrows()):
                    pal_entry = BRANCH_PALETTE[idx % len(BRANCH_PALETTE)]
                    vendor_color_map[b_row["clean_vid"]] = {
                        "name": b_row["clean_name"],
                        "hex": pal_entry["hex"],
                        "folium": pal_entry["folium"],
                        "color_name": pal_entry["name"]
                    }
            elif not df_disp.empty and selected_vendor != T("كل الفروع", "All Vendors"):
                v_name_sel = df_disp.iloc[0]["clean_name"]
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
                    if not z_norm: continue
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

            if selected_chain != T("كل السلاسل", "All Chains") and vendor_color_map:
                st.write(T("🎨 **دليل تمييز ألوان الفروع ومناطق توصيلها:**", "🎨 **Branch Color Legend & Delivery Areas:**"))
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
                    return "#3388ff", "#002266", 0.12, 1.0, T("منطقة عامة", "General Zone"), False

                props = gdf_areas_plot["Delivery Location Area Name"].apply(assign_zone_styling)
                gdf_areas_plot["fill_color"] = [p[0] for p in props]
                gdf_areas_plot["border_color"] = [p[1] for p in props]
                gdf_areas_plot["fill_opacity"] = [p[2] for p in props]
                gdf_areas_plot["weight"] = [p[3] for p in props]
                gdf_areas_plot["coverage_info"] = [p[4] for p in props]

            if selected_vendor != T("كل الفروع", "All Vendors") and not plot_vendors.empty:
                map_center = [plot_vendors.iloc[0]["lat"], plot_vendors.iloc[0]["lng"]]
                zoom_lvl = 13
            elif not plot_vendors.empty:
                map_center = [plot_vendors["lat"].mean(), plot_vendors["lng"].mean()]
                zoom_lvl = 12 if selected_chain != T("كل السلاسل", "All Chains") else 10 if selected_city != T("كل المدن", "All Cities") else 7
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
                        aliases=[T("المنطقة: ", "Zone: "), T("تغطية الفرع: ", "Branch: ")]
                    ),
                    popup=folium.GeoJsonPopup(
                        fields=["Delivery Location Area Name", "coverage_info"],
                        aliases=[T("اسم المنطقة: ", "Zone: "), T("الفروع المسؤولة: ", "Branches: ")]
                    )
                ).add_to(m_admin)

            if not plot_vendors.empty:
                cluster = MarkerCluster().add_to(m_admin)
                
                for _, row in plot_vendors.iterrows():
                    popup_content = build_vendor_popup_html(row, df_delivery, df_performance)
                    vid_str = row["clean_vid"]
                    b_color_info = vendor_color_map.get(vid_str)
                    pin_color = b_color_info.get("folium", "green") if b_color_info else "blue"
                    is_single_focus = (selected_vendor != T("كل الفروع", "All Vendors") and vid_str == selected_vendor)
                    
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

            st_folium(m_admin, width="100%", height=620, key=f"admin_overview_map_{selected_city}_{selected_am}_{selected_chain}_{selected_vendor}_{selected_active}_{selected_hidden}", returned_objects=[])

# ==========================================
# Tab 2: Vendor Portal (مع الإدارة المجمعة لتقسيم فروع السلسلة)
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
                st.error(T("❌ الكود غير صحيح أو لا تملك صلاحية لإدارته.", "❌ ID not found in database or not in your scope."))
        else:
            st.info(T("ℹ️ يرجى إدخال كود الفرع (Vendor ID) أو السلسلة (Chain ID) أعلاه للبدء.", "ℹ️ Please enter a Vendor ID or Chain ID above to begin."))
    else:
        p_vends = user_vendors.copy() if not user_vendors.empty else pd.DataFrame()
        if p_vends.empty:
            st.warning(T("⚠️ لا توجد فروع مربوطة بحسابك حتى الآن.", "⚠️ No branches linked to your account."))

    if not p_vends.empty:
        is_multi = False
        if len(p_vends) > 1:
            st.markdown("---")
            is_multi = st.toggle(
                T("🔄 تفعيل وضع الإدارة المجمعة لتقسيم المناطق على فروع السلسلة", "🔄 Enable Multi-Branch Allocation Mode"),
                value=False,
                key="multi_branch_toggle"
            )

        if is_multi:
            st.info(T(
                "✨ أنت الآن في وضع الإدارة المجمعة. قم بتحديد جميع مناطق التغطية ثم عين كل منطقة للفرع المسؤول عنها من جدول التسعير.",
                "✨ Multi-branch allocation mode active. Select zones, then assign each to its responsible branch in the table."
            ))
            t_vid = "MULTI_" + str(p_vends.iloc[0].get("clean_cid", "CHAIN"))
            vd = p_vends
        else:
            opt = dict(zip(p_vends["clean_vid"], p_vends["clean_name"] + " (" + p_vends["clean_vid"] + ")"))
            t_vid = st.selectbox(
                T("اختر الفرع:", "Select Branch:"),
                list(opt.keys()),
                format_func=lambda x: opt[x],
                key="single_vendor_select"
            )
            vd = p_vends[p_vends["clean_vid"] == t_vid]

        if not vd.empty:
            if is_multi:
                v_nm = T("مجموعة فروع السلسلة", "Multiple Branches")
                v_cid = vd.iloc[0]["clean_cid"]
                v_cnm = vd.iloc[0].get("clean_chain_name", "")
                v_city = vd.iloc[0].get("clean_city", "")
                has_loc = pd.notna(vd["lat"]).any() and pd.notna(vd["lng"]).any()
            else:
                vr = vd.iloc[0]
                v_nm = vr["clean_name"]
                v_cid = vr["clean_cid"]
                v_cnm = vr.get("clean_chain_name", "")
                v_city = vr.get("clean_city", "")
                v_am = vr.get("clean_am", "-")
                has_loc = pd.notna(vr["lat"]) and pd.notna(vr["lng"])
                
                st.success(f"🏬 **{v_nm}** | {T('المدينة', 'City')}: {v_city} | Vendor ID: `{t_vid}` | Chain: {v_cnm} (`{v_cid}`) | AM: `{v_am}`")

                vp, cp = get_vendor_and_chain_perf(t_vid, v_cid, df_performance)
                if vp or cp:
                    st.subheader(T("📊 مؤشرات الأداء (Performance Metrics)", "📊 Performance Metrics"))
                    t1, t2 = st.tabs([
                        T(f"🏬 أداء الفرع ({v_nm})", f"🏬 Branch ({v_nm})"),
                        T(f"🏢 أداء السلسلة ({v_cnm})", f"🏢 Chain ({v_cnm})")
                    ])
                    with t1:
                        if vp:
                            c1, c2, c3, c4, c5 = st.columns(5)
                            c1.metric(T("الطلبات الصافية (QC Net Orders)", "QC Net Orders"), vp.get("qc_orders", "-"))
                            c2.metric(T("الطلبات الملغاة (Failed Orders)", "Failed Orders"), f"{vp.get('fail_orders', '-')} ({vp.get('fail_rate', '-')})")
                            c3.metric(T("نسبة الإلغاء (Fail Rate)", "Fail Rate"), vp.get("fail_rate", "-"))
                            c4.metric(T("معدل الشكاوى (Contact Rate)", "Contact Rate"), vp.get("contact_rate", "-"))
                            c5.metric(T("شكاوى خطأ الفيندور (Fault CR)", "Vendor Fault CR"), vp.get("fault_cr", "-"))
                        else:
                            st.info(T("لا توجد بيانات أداء مسجلة لهذا الفرع.", "No performance data found."))
                    with t2:
                        if cp:
                            c1, c2, c3, c4, c5 = st.columns(5)
                            c1.metric(T("إجمالي طلبات السلسلة", "Chain Net Orders"), cp.get("qc_orders", "-"))
                            c2.metric(T("إجمالي ملغيات السلسلة", "Chain Failed Orders"), f"{cp.get('fail_orders', '-')} ({cp.get('fail_rate', '-')})")
                            c3.metric(T("متوسط نسبة الإلغاء", "Chain Fail Rate"), cp.get("fail_rate", "-"))
                            c4.metric(T("معدل شكاوى السلسلة", "Chain Contact Rate"), cp.get("contact_rate", "-"))
                            c5.metric(T("شكاوى خطأ فروع السلسلة", "Chain Fault CR"), cp.get("fault_cr", "-"))
                        else:
                            st.info(T("لا توجد بيانات مجمعة لهذه السلسلة.", "No chain performance data available."))
                    st.markdown("---")

            rad = st.slider(T("نطاق الخريطة (كم):", "Radius (km):"), 3, 40, 10, key="portal_radius_slider")
            
            if has_loc:
                if is_multi:
                    pa = gdf_areas[gdf_areas.geometry.intersects(Point(vd["lng"].mean(), vd["lat"].mean()).buffer(rad / 111.0))].copy()
                else:
                    pa = get_nearby_polygons(vr["lat"], vr["lng"], rad)
            else:
                pa = gdf_areas.head(30).copy() if not gdf_areas.empty else gpd.GeoDataFrame()
                
            az = sorted(gdf_areas["Delivery Location Area Name"].dropna().unique().tolist()) if not gdf_areas.empty else []
            zlk = {z.strip().lower(): z for z in az}

            pf_z, pf_d = [], {}
            if not df_delivery.empty and "clean_vid" in df_delivery.columns:
                m_del = df_delivery[df_delivery["clean_vid"].isin(vd["clean_vid"])] if is_multi else df_delivery[df_delivery["clean_vid"] == t_vid]
                for _, r in m_del.iterrows():
                    zn = zlk.get(str(r.get("clean_zone", "")).strip().lower())
                    if zn:
                        if zn not in pf_z: pf_z.append(zn)
                        pf_d[zn] = {
                            "time": str(r.get("clean_time", "")),
                            "fees": float(r.get("clean_fee", 0.0)) if pd.notna(r.get("clean_fee")) and str(r.get("clean_fee")).replace('.','').isdigit() else None,
                            "vid": str(r.get("clean_vid", "")) if is_multi else None
                        }

            if st.session_state.get("vp_id") != t_vid:
                st.session_state.update({
                    "vp_id": t_vid,
                    "ms_z": list(pf_z),
                    "ap_z": list(pf_z),
                    "pf_z": list(pf_z),
                    "pf_d": pf_d,
                    "ms_v": 0,
                    "show_t": False
                })

            valid_z = [z for z in st.session_state.get("ap_z", []) if z in az]

            cm, cf = st.columns([6, 4])
            with cm:
                st.subheader(f"🗺️ Map ({len(valid_z)} {T('منطقة مطبقة', 'Zones Applied')})")
                st.caption(T("💡 انقر على المناطق التي تريد إضافتها/إزالتها، ثم اضغط 'Apply to Map' بالأعلى لترقية الخريطة.", "💡 Click zones to select/deselect, then click 'Apply to Map'."))

                mcnt = [vd["lat"].mean(), vd["lng"].mean()] if (is_multi and has_loc) else ([vr["lat"], vr["lng"]] if has_loc else [30.04, 31.23])
                vmap = folium.Map(location=mcnt, zoom_start=13 if has_real_coords else 11)
                if has_loc:
                    plot_branches = vd.dropna(subset=["lat", "lng"]) if is_multi else vd.iloc[[0]]
                    for _, rv in plot_branches.iterrows():
                        folium.Marker(
                            [rv["lat"], rv["lng"]],
                            tooltip=f"💊 {rv['clean_name']}",
                            popup=f"<b>{rv['clean_name']}</b><br>ID: {rv['clean_vid']}",
                            icon=folium.Icon(color="green", icon="medkit", prefix="fa")
                        ).add_to(vmap)

                vmap.get_root().html.add_child(folium.Element("<style>.leaflet-interactive:focus{outline:none;} path.leaflet-interactive:hover{stroke:#ffc107; stroke-width:3px;}</style>"))
                if not pa.empty:
                    folium.GeoJson(
                        pa[["Delivery Location Area Name", "geometry"]].to_json(),
                        style_function=lambda f: {
                            "fillColor": "#28a745" if f["properties"]["Delivery Location Area Name"] in valid_z else "#3388ff",
                            "color": "#155724" if f["properties"]["Delivery Location Area Name"] in valid_z else "#002266",
                            "weight": 2,
                            "fillOpacity": 0.5 if f["properties"]["Delivery Location Area Name"] in valid_z else 0.15
                        },
                        tooltip=folium.GeoJsonTooltip(["Delivery Location Area Name"])
                    ).add_to(vmap)

                mcd = st_folium(
                    vmap,
                    width="100%",
                    height=500,
                    key=f"vmap_interactive_{t_vid}_{rad}",
                    returned_objects=["last_object_clicked"]
                )
                if mcd and mcd.get("last_object_clicked"):
                    zc = mcd["last_object_clicked"].get("properties", {}).get("Delivery Location Area Name")
                    if zc and zc in az:
                        cs = f"{zc}_{np.random.randint(100)}"
                        if cs != st.session_state.get("lc"):
                            st.session_state["lc"] = cs
                            if zc in st.session_state["ms_z"]: st.session_state["ms_z"].remove(zc)
                            else: st.session_state["ms_z"].append(zc)
                            st.session_state["ap_z"] = list(st.session_state["ms_z"])
                            st.session_state["show_t"] = False
                            st.session_state["ms_v"] = st.session_state.get("ms_v", 0) + 1
                            st.rerun()

            with cf:
                st.subheader(f"📝 {T('المناطق المحددة', 'Selected Zones')}")
                cz = st.multiselect(
                    T("مناطق الخدمة والتوصيل:", "Service Areas:"),
                    az,
                    default=st.session_state["ms_z"],
                    key=f"ms_box_{st.session_state.get('ms_v', 0)}"
                )
                b1, b2 = st.columns(2)
                if b1.button(T("👁️ تحديث الخريطة", "Apply to Map"), use_container_width=True):
                    st.session_state.update({"ap_z": cz.copy(), "ms_z": cz.copy(), "show_t": False})
                    st.rerun()
                if b2.button(T("🚀 تأكيد وتسعير", "Submit Selection"), type="primary", use_container_width=True):
                    st.session_state.update({"ap_z": cz.copy(), "ms_z": cz.copy(), "show_t": True})
                    st.rerun()

            if st.session_state.get("show_t"):
                st.markdown("---")
                st.subheader(T("💰 جدول التسعير وتوزيع الفروع", "Pricing & Allocation Table"))
                st.caption(T(
                    "يوضح الجدول حالة كل منطقة وإمكانية توزيعها وتعيين الفرع المسؤول عنها:",
                    "Table shows zone status and allows assigning each zone to a branch:"
                ))

                all_rz = list(st.session_state["ap_z"]) + [z for z in st.session_state["pf_z"] if z not in st.session_state["ap_z"]]
                th = ",".join(sorted(all_rz)) + str(is_multi)

                if st.session_state.get("ph") != th:
                    rws = []
                    v_opts = [T("غير مخصص", "Unassigned")] + [f"{r['clean_name']} ({r['clean_vid']})" for _, r in vd.iterrows()]
                    for z in all_rz:
                        pdc = st.session_state["pf_d"].get(z, {})
                        isex = z in st.session_state["pf_z"]
                        isap = z in st.session_state["ap_z"]

                        astr = T("غير مخصص", "Unassigned")
                        if is_multi and pdc.get("vid"):
                            mv = vd[vd["clean_vid"] == pdc["vid"]]
                            if not mv.empty:
                                astr = f"{mv.iloc[0]['clean_name']} ({pdc['vid']})"

                        rd = {
                            "Zone": z,
                            "Status": T("📌 مسجلة", "📌 Existing") if isex else T("✨ جديدة", "✨ New"),
                            "Action": T("نشط", "Active") if isap else T("إلغاء التفعيل", "Deactivate"),
                            "Time": pdc.get("time", "") if isap else "",
                            "Fees": pdc.get("fees", None) if isap else 0.0
                        }
                        if is_multi:
                            rd["Assigned Branch"] = astr
                        rws.append(rd)

                    st.session_state["pdf"] = pd.DataFrame(rws)
                    st.session_state["ph"] = th
                    st.session_state["vopts"] = v_opts

                ccf = {
                    "Zone": st.column_config.TextColumn(T("اسم المنطقة", "Zone Name"), disabled=True),
                    "Status": st.column_config.TextColumn(T("نوع المنطقة", "Type"), disabled=True),
                    "Action": st.column_config.SelectboxColumn(
                        T("الحالة / الإجراء", "Action"),
                        options=[T("نشط", "Active"), T("إلغاء التفعيل", "Deactivate")],
                        required=True
                    ),
                    "Time": st.column_config.TextColumn(T("وقت التوصيل المقدر", "Delivery Time")),
                    "Fees": st.column_config.NumberColumn(T("رسوم التوصيل (EGP)", "Fees (EGP)"))
                }
                if is_multi:
                    ccf["Assigned Branch"] = st.column_config.SelectboxColumn(
                        T("الفرع المسؤول (التوزيع)", "Assigned Branch"),
                        options=st.session_state["vopts"],
                        required=True
                    )

                edf = st.data_editor(
                    st.session_state["pdf"],
                    column_config=ccf,
                    use_container_width=True,
                    hide_index=True,
                    key="pricing_editor"
                )

                if st.button(T("✅ إرسال التحديث للإدارة", "✅ Finalize & Send to Admin"), type="primary"):
                    err = False
                    act = edf[edf["Action"].str.contains("Active|نشط", case=False, na=False)]
                    if act["Time"].eq("").any() or act["Fees"].isnull().any():
                        st.error(T("⚠️ يرجى إكمال الوقت ورسوم التوصيل للمناطق النشطة.", "⚠️ Please specify delivery time and fees for active zones."))
                        err = True
                    if is_multi and act["Assigned Branch"].str.contains("Unassigned|غير مخصص", na=False).any():
                        st.error(T("⚠️ يرجى تعيين فرع لكل منطقة في وضع التوزيع المجمع.", "⚠️ Please assign a branch to every active zone."))
                        err = True

                    if not err:
                        if is_multi:
                            for bopt in act["Assigned Branch"].unique():
                                m_match = re.search(r"\((.*?)\)", str(bopt))
                                bvid = m_match.group(1) if m_match else "MULTI"
                                bnm = str(bopt).split("(")[0].strip()
                                bdf = edf[edf["Assigned Branch"] == bopt].copy()
                                bdf["Final_Status"] = bdf.apply(lambda r: "Deactivated" if ("Deactivate" in r["Action"] or "إلغاء" in r["Action"]) else ("Active (New)" if ("جديدة" in r["Status"] or "New" in r["Status"]) else "Active (Existing)"), axis=1)
                                save_detailed_request(bvid, bnm, bdf)
                            st.success(T("🎉 تم إرسال طلبات التوزيع المجمعة بنجاح!", "🎉 Multi-branch allocation requests submitted successfully!"))
                        else:
                            submission_df = edf.copy()
                            submission_df["Final_Status"] = submission_df.apply(lambda r: "Deactivated" if ("Deactivate" in r["Action"] or "إلغاء" in r["Action"]) else ("Active (New)" if ("جديدة" in r["Status"] or "New" in r["Status"]) else "Active (Existing)"), axis=1)
                            save_detailed_request(t_vid, v_nm, submission_df)
                            st.success(T("🎉 تم إرسال الطلب بنجاح!", "🎉 Request submitted successfully!"))

# ==========================================
# Tab 3 & 4: Admin Sections
# ==========================================
if is_admin:
    with tab3:
        st.header(T("📥 طلبات التسعير والتغطية الواردة", "📥 Vendor Pricing & Coverage Requests"))
        init_requests_db()
        if os.path.exists(REQUESTS_FILE):
            rdf = pd.read_csv(REQUESTS_FILE)
            if not rdf.empty and "Zone" in rdf.columns:
                st.dataframe(rdf, use_container_width=True)
                if st.button(T("حذف جميع الطلبات", "Delete All Requests")):
                    os.remove(REQUESTS_FILE)
                    init_requests_db()
                    st.rerun()
            else:
                st.info(T("لا توجد طلبات واردة حالياً.", "No incoming requests found."))

    with tab4:
        st.header(T("👥 إدارة المستخدمين والصلاحيات", "👥 User Management & Permissions"))
        tab_u1, tab_u2, tab_u3 = st.tabs([
            T("➕ إضافة مستخدم جديد", "➕ Add New User"),
            T("✏️ تعديل صلاحيات مستخدم", "✏️ Edit User Permissions"),
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
            st.subheader(T("تعديل صلاحيات ومحفظة فروع مستخدم مسجل", "Edit User Permissions & Portfolio"))
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
                    
                if st.form_submit_button(T("💾 حفظ التعديلات", "💾 Save Changes"), type="primary"):
                    ok, msg, updated_row = update_user_permissions(selected_edit_user, e_role, e_access_type, e_selected_access_ids_str)
                    if ok:
                        if selected_edit_user.lower() == current_user["email"].lower():
                            st.session_state["current_user"] = updated_row
                        st.success(msg); st.rerun()
                    else: st.error(msg)

        with tab_u3:
            users_list_df = get_users_df()
            st.dataframe(users_list_df, use_container_width=True)
            deletable = users_list_df[users_list_df["email"].str.lower() != "mahmoud.alaa.2@talabat.com"]["email"].tolist()
            if deletable:
                to_del = st.selectbox(T("اختر المستخدم للحذف:", "Select User to Delete:"), deletable)
                if st.button(T("حذف الحساب نهائياً", "Delete User"), type="secondary"):
                    ok, msg = delete_user(to_del)
                    if ok: st.success(msg); st.rerun()
                    else: st.error(msg)
