#!/usr/bin/env python3
"""
Flood Monitor Engine & Dashboard Compiler
Zero-dependency, standalone automation for Chao Phraya River & Bangkok Flood Monitoring.
Author: Mack (Automation Specialist) & Pony (YAGNI Auditor)
"""

import argparse
import datetime
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# Directory Layout
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_FILE = os.path.join(BASE_DIR, "data.json")
INDEX_FILE = os.path.join(WEB_DIR, "index.html")

# Default Environment Variables
def load_dotenv():
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k and k not in os.environ:
                    os.environ[k] = v

load_dotenv()

LINE_ACCESS_TOKEN = os.environ.get("LINE_FLOOD_CHANNEL_ACCESS_TOKEN", "")
LINE_GROUP_ID = os.environ.get("LINE_FLOOD_GROUP_ID", "")
DASHBOARD_URL = "https://pipatpong84.github.io/flood-monitor/"

# SSL Context for permissive government endpoints
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ==============================================================================
# 1. 3-TIER DATA INGESTION ENGINE
# ==============================================================================

def fetch_json(url: str, timeout: int = 10) -> dict:
    """Fetch and parse JSON from a given URL with timeout and custom headers."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_thaiwater_data() -> dict:
    """Tier 1: Fetch primary real-time hydrological data from api-v3.thaiwater.net."""
    print("[1/3] Fetching primary data from ThaiWater API...")
    wl_url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/waterlevel_load"
    rain_url = "https://api-v3.thaiwater.net/api/v1/thaiwater30/public/rain_24h"

    wl_data = fetch_json(wl_url, timeout=12)
    rain_data = fetch_json(rain_url, timeout=12)

    items = wl_data.get("waterlevel_data", {}).get("data", [])
    
    c2_flow = 0.0
    c13_flow = 0.0
    s26_flow = 0.0
    c35_flow = 0.0
    data_time = ""

    for it in items:
        code = str(it.get("station", {}).get("tele_station_oldcode", ""))
        discharge_val = it.get("discharge")
        if discharge_val is not None:
            try:
                flow = float(discharge_val)
            except (ValueError, TypeError):
                flow = 0.0

            if code == "C.2":
                c2_flow = flow
                data_time = it.get("waterlevel_datetime", "")
            elif code == "C.13":
                c13_flow = flow
                if not data_time:
                    data_time = it.get("waterlevel_datetime", "")
            elif code == "S.26":
                s26_flow = flow
            elif code == "C.35":
                c35_flow = flow

    # Estimate C.29B (Pathum Thani / Bang Sai) flow:
    # Hydrological convergence: Chao Phraya Ayutthaya (C.35) + Pasak (S.26) + intermediate sideflow (~50 cms)
    # If C.35 is missing, fallback to (C.13 * 0.60) + S.26 + 50.0
    if c35_flow > 0:
        c29b_flow = c35_flow + s26_flow + 50.0
    else:
        c29b_flow = (c13_flow * 0.60) + s26_flow + 50.0

    # Process Bangkok rainfall (14 official stations)
    rain_items = rain_data.get("data", [])
    bkk_rain_vals = []
    for r in rain_items:
        prov = str(r.get("geocode", {}).get("province_name", {}).get("th", ""))
        if "กรุงเทพ" in prov:
            try:
                v = float(r.get("rain_24h") or 0.0)
                bkk_rain_vals.append(v)
            except (ValueError, TypeError):
                pass

    max_rain = max(bkk_rain_vals) if bkk_rain_vals else 0.0

    return {
        "status": "success",
        "tier": "Tier 1: ThaiWater API (api-v3.thaiwater.net)",
        "timestamp": data_time or datetime.datetime.now().strftime("%Y-%m-%d %H:00"),
        "c2": {
            "name": "C.2 นครสวรรค์",
            "desc": "รับน้ำเหนือ (ค่ายจิรประวัติ)",
            "flow": round(c2_flow, 1),
            "max": 3500.0,
            "unit": "cms"
        },
        "c13": {
            "name": "C.13 เขื่อนเจ้าพระยา",
            "desc": "จุดระบายน้ำท้ายเขื่อน จ.ชัยนาท",
            "flow": round(c13_flow, 1),
            "max": 3000.0,
            "unit": "cms"
        },
        "c29b": {
            "name": "C.29B ปทุมธานี [ประเมิน C.35+S.26]",
            "desc": "ด่านหน้าก่อนเข้า กทม. (ประเมินจาก C.35 อยุธยา + S.26 ป่าสัก)",
            "flow": round(c29b_flow, 1),
            "max": 3500.0,
            "unit": "cms"
        },
        "rain": {
            "name": "เรดาร์ฝน กทม. (สะสม 24 ชม.)",
            "desc": "ปริมาณฝนสะสม 24 ชม. สูงสุด (ขีดระบาย กทม. 60 มม. | สถิติน้ำท่วมใหญ่ 300 มม.)",
            "rate": round(max_rain, 1),
            "max": 300.0,
            "unit": "มม."
        }
    }


def fetch_fallback_rid_data() -> dict:
    """Tier 2: Fallback directly to RID SWOC & BKK Weather endpoints."""
    print("[2/3] ThaiWater unavailable. Attempting Tier 2 Fallback (RID SWOC)...")
    # In Tier 2, if primary API times out, scrape or query SWOC report
    # For now, return standard RID approximation or raise to trigger Tier 3
    raise RuntimeError("Tier 2 Fallback parsing not yet required; proceeding to Tier 3 Cache.")


def get_live_hydrological_data() -> dict:
    """Retrieve data with automatic 3-Tier fallback."""
    # Tier 1
    try:
        data = fetch_thaiwater_data()
        # Persist as Last-Known-Good cache
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception as e:
        print(f"[WARN] Tier 1 fetch error: {e}", file=sys.stderr)

    # Tier 2
    try:
        data = fetch_fallback_rid_data()
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    except Exception as e:
        print(f"[WARN] Tier 2 fetch error: {e}", file=sys.stderr)

    # Tier 3: Last-Known-Good Cache
    print("[3/3] Falling back to Tier 3 (Last-Known-Good local cache)...")
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["tier"] = "Tier 3: Offline Cache (Last-Known-Good)"
                data["is_cached"] = True
                return data
        except Exception as e:
            print(f"[ERROR] Failed reading cache: {e}", file=sys.stderr)

    # Hard emergency fallback defaults if fresh repo with zero cache
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:00")
    return {
        "status": "fallback",
        "tier": "Tier 3: Emergency Fallback Defaults",
        "timestamp": now_str,
        "is_cached": True,
        "c2": {"name": "C.2 นครสวรรค์", "desc": "รับน้ำเหนือ", "flow": 2023.0, "max": 3500.0, "unit": "cms"},
        "c13": {"name": "C.13 เขื่อนเจ้าพระยา", "desc": "ท้ายเขื่อนชัยนาท", "flow": 2500.0, "max": 3000.0, "unit": "cms"},
        "c29b": {"name": "C.29B ปทุมธานี [ประเมิน C.35+S.26]", "desc": "ด่านหน้าก่อนเข้า กทม. (ประเมินจาก C.35 อยุธยา + S.26 ป่าสัก)", "flow": 2220.0, "max": 3500.0, "unit": "cms"},
        "rain": {"name": "เรดาร์ฝน กทม. (สะสม 24 ชม.)", "desc": "ปริมาณฝนสะสม 24 ชม. สูงสุด (ขีดระบาย กทม. 60 มม. | สถิติน้ำท่วมใหญ่ 300 มม.)", "rate": 0.0, "max": 300.0, "unit": "มม."}
    }


# ==============================================================================
# 2. STATUS & COLOR EVALUATION LOGIC
# ==============================================================================

def get_station_status(flow_val: float, station_id: str) -> tuple:
    """Return (color_hex, badge_tag, badge_bg, subtext) based on hydrological thresholds."""
    if station_id == "c29b":
        if flow_val < 2500:
            return "#10B981", "🟢 ปกติ", "#ECFDF5", "ต่ำกว่าคันกั้นน้ำ กทม. >1,000 cms • กทม. ชั้นในปลอดภัย"
        elif flow_val < 3000:
            return "#F59E0B", "🟡 เฝ้าระวัง", "#FEF3C7", "เริ่มกระทบชุมชนนอกคัน • คันกั้นน้ำ กทม. ชั้นในยังรับมือได้"
        else:
            return "#EF4444", "🔴 วิกฤต", "#FEE2E2", "ใกล้แตะขีดจำกัดคันกั้นน้ำ (3,500 cms) • กทม. เสี่ยงน้ำท่วมใหญ่"

    if flow_val < 1800:
        color = "#10B981"  # Emerald Green
        tag = "🟢 ปกติ"
        tag_bg = "#ECFDF5"
        subtext = "อัตราไหลปกติ ไม่มีความเสี่ยงน้ำเอ่อล้น"
    elif flow_val < 2500:
        color = "#F59E0B"  # Amber
        tag = "🟡 เฝ้าระวัง"
        tag_bg = "#FEF3C7"
        if station_id == "c2":
            subtext = "รับน้ำเหนือ • มีแนวโน้มระบายลงเขื่อนเจ้าพระยาใน 48 ชม."
        elif station_id == "c13":
            subtext = "ท้ายเขื่อน • ชุมชนลุ่มต่ำนอกคันเริ่มได้รับผลกระทบ"
        else:
            subtext = "ด่านหน้า กทม. • ในคันกั้นน้ำชั้นในยังปลอดภัย"
    elif flow_val < 3000:
        color = "#EA580C"  # Dark Orange
        tag = "🟠 เตือนภัย"
        tag_bg = "#FFEDD5"
        subtext = "ระดับน้ำสูงมาก • เสริมแนวกระสอบทรายและยกของขึ้นที่สูง"
    else:
        color = "#EF4444"  # Red
        tag = "🔴 วิกฤต"
        tag_bg = "#FEE2E2"
        subtext = "สัญญาณวิกฤตล้นคันกั้นน้ำ • กทม. เสี่ยงน้ำท่วมใหญ่"
    return color, tag, tag_bg, subtext


def get_rain_status(rain_val: float) -> tuple:
    """Return (color_hex, badge_tag, badge_bg, subtext) based on rainfall thresholds."""
    if rain_val < 60.0:
        color = "#10B981"
        tag = "🟢 ปกติ"
        tag_bg = "#ECFDF5"
        subtext = "ต่ำกว่าขีดระบาย กทม. (60 มม.) • สถิติน้ำท่วมใหญ่ปลาย ก.ย. 300 มม."
    elif rain_val < 150.0:
        color = "#F59E0B"
        tag = "🟡 เฝ้าระวัง"
        tag_bg = "#FEF3C7"
        subtext = "เกินขีดระบาย กทม. (60 มม.) เริ่มมีน้ำขังบนถนน • สถิติน้ำท่วมใหญ่ 300 มม."
    else:
        color = "#EF4444"
        tag = "🔴 วิกฤต"
        tag_bg = "#FEE2E2"
        subtext = "ฝนตกหนักสะสมรุนแรง • ระดับวิกฤตใกล้เคียงน้ำท่วมใหญ่ปลาย ก.ย. (300 มม.)"
    return color, tag, tag_bg, subtext


# ==============================================================================
# 3. ALERT-BY-EXCEPTION EVALUATION
# ==============================================================================

def evaluate_alert_decision(data: dict, force: bool = False) -> tuple:
    """
    Decide whether to dispatch a LINE notification.
    Rules:
    - Force flag (--force-alert) -> Alert
    - C.29B >= 2,800 cms -> Alert
    - Rain >= 60.0 mm -> Alert
    - C.13 >= 1,800 cms -> Alert
    - C.2 >= 2,200 cms -> Alert
    - Sunday morning heartbeat (08:00 AM) -> Alert
    - Otherwise -> Silent (exit 0)
    """
    now = datetime.datetime.now()
    is_sunday = (now.weekday() == 6) # 6 = Sunday
    month = now.month
    is_peak_season = (month in [8, 9, 10])

    c13_val = data["c13"]["flow"]
    c2_val = data["c2"]["flow"]
    c29b_val = data["c29b"]["flow"]
    rain_val = data["rain"]["rate"]

    if force:
        return True, "⚡ Manual Dispatch: สั่งส่งแจ้งเตือนด้วยคำสั่งตรง (--force-alert)"

    if c29b_val >= 2800:
        return True, f"⚠️ ด่านหน้า กทม. (C.29B) แตะเกณฑ์เฝ้าระวัง: {c29b_val:,.0f} cms (>= 2,800)"

    if rain_val >= 60.0:
        return True, f"🌧️ ฝนสะสม 24 ชม. กทม. เกินขีดระบายน้ำ: {rain_val:.1f} มม. (>= 60 มม. เสี่ยงน้ำท่วมขัง)"

    if c13_val >= 1800:
        return True, f"⚠️ เขื่อนเจ้าพระยาระบายน้ำแตะเกณฑ์เฝ้าระวัง: {c13_val:,.0f} cms (>= 1,800)"

    if c2_val >= 2200:
        return True, f"⚠️ น้ำเหนือนครสวรรค์สะสมสูง: {c2_val:,.0f} cms (มีผลต่อเขื่อนเจ้าพระยาใน 48 ชม.)"

    if is_sunday:
        return True, "🟢 รายงานประจำสัปดาห์ (Sunday Heartbeat): ระบบตรวจวัดทำงานปกติ สถานการณ์น้ำยังปลอดภัย"

    return False, "สภาวะน้ำปกติ อยู่ต่ำกว่าเกณฑ์เฝ้าระวัง (Alert by Exception: ไม่รบกวนกลุ่มไลน์)"


# ==============================================================================
# 4. LINE FLEX MESSAGE BUILDER (CROSS-PLATFORM DESKTOP & MOBILE)
# ==============================================================================

def build_scale_bar_flex(pct: float, color: str) -> dict:
    pct_clamped = min(max(pct, 3.0), 100.0)
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": "#E2E8F0",
        "height": "8px",
        "cornerRadius": "sm",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": color,
                "height": "8px",
                "width": f"{pct_clamped:.1f}%",
                "cornerRadius": "sm",
                "contents": []
            }
        ]
    }


def make_card_item_flex(name: str, val_str: str, max_val: float, unit: str, color: str, subtext: str, pct: float, benchmark_row: dict = None) -> dict:
    contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": name,
                    "size": "sm",
                    "weight": "bold",
                    "color": "#0F172A",
                    "flex": 5
                },
                {
                    "type": "text",
                    "text": f"{val_str} / {max_val:,.0f} {unit}",
                    "size": "sm",
                    "weight": "bold",
                    "color": color,
                    "align": "end",
                    "flex": 5
                }
            ]
        },
        build_scale_bar_flex(pct, color)
    ]
    if benchmark_row:
        contents.append(benchmark_row)
    contents.append({
        "type": "text",
        "text": subtext,
        "size": "xxs",
        "color": "#64748B",
        "wrap": True
    })
    return {
        "type": "box",
        "layout": "vertical",
        "margin": "md",
        "spacing": "xs",
        "contents": contents
    }


def build_line_flex_payload(data: dict, trigger_reason: str) -> dict:
    """Build cross-platform LINE Flex Message v2 (size: mega, normalized text)."""
    c2_col, c2_tag, _, c2_sub = get_station_status(data["c2"]["flow"], "c2")
    c13_col, c13_tag, _, c13_sub = get_station_status(data["c13"]["flow"], "c13")
    c29b_col, c29b_tag, _, c29b_sub = get_station_status(data["c29b"]["flow"], "c29b")
    r_col, r_tag, _, r_sub = get_rain_status(data["rain"]["rate"])

    c2_pct = (data["c2"]["flow"] / data["c2"]["max"]) * 100.0
    c13_pct = (data["c13"]["flow"] / data["c13"]["max"]) * 100.0
    c29b_pct = (data["c29b"]["flow"] / data["c29b"]["max"]) * 100.0
    r_pct = (data["rain"]["rate"] / data["rain"]["max"]) * 100.0

    rain_benchmark_row = {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": "0",
                "size": "xxs",
                "color": "#94A3B8",
                "flex": 1
            },
            {
                "type": "text",
                "text": "▲ รับได้ 60 มม.",
                "size": "xxs",
                "color": "#0284C7",
                "align": "center",
                "flex": 2
            },
            {
                "type": "text",
                "text": "300 มม. (วิกฤต)",
                "size": "xxs",
                "color": "#EF4444",
                "align": "end",
                "flex": 2
            }
        ]
    }

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#0F172A",
            "paddingAll": "16px",
            "spacing": "xs",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "FLOOD MONITOR",
                            "color": "#38BDF8",
                            "size": "xxs",
                            "weight": "bold",
                            "flex": 1
                        },
                        {
                            "type": "text",
                            "text": f"อัปเดต: {data['timestamp']}",
                            "color": "#94A3B8",
                            "size": "xxs",
                            "align": "end",
                            "flex": 1
                        }
                    ]
                },
                {
                    "type": "text",
                    "text": "สถานการณ์น้ำ & ฝน กทม.",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#FFFFFF"
                },
                {
                    "type": "text",
                    "text": trigger_reason,
                    "size": "xs",
                    "color": "#FCD34D",
                    "wrap": True
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "16px",
            "contents": [
                {
                    "type": "text",
                    "text": "🌊 อัตราการไหลของน้ำ (3 สถานีหลัก)",
                    "weight": "bold",
                    "size": "xs",
                    "color": "#475569"
                },
                make_card_item_flex(data["c2"]["name"], f"{data['c2']['flow']:,.0f}", data["c2"]["max"], "cms", c2_col, f"{c2_tag}: {c2_sub}", c2_pct),
                make_card_item_flex(data["c13"]["name"], f"{data['c13']['flow']:,.0f}", data["c13"]["max"], "cms", c13_col, f"{c13_tag}: {c13_sub}", c13_pct),
                make_card_item_flex(data["c29b"]["name"], f"{data['c29b']['flow']:,.0f}", data["c29b"]["max"], "cms", c29b_col, f"{c29b_tag}: {c29b_sub}", c29b_pct),
                {"type": "separator", "margin": "lg", "color": "#E2E8F0"},
                {
                    "type": "text",
                    "text": "🌧️ ปริมาณฝนเฉพาะหน้า (กทม.)",
                    "weight": "bold",
                    "size": "xs",
                    "color": "#475569",
                    "margin": "md"
                },
                make_card_item_flex(data["rain"]["name"], f"{data['rain']['rate']:.1f}", data["rain"]["max"], data["rain"]["unit"], r_col, f"{r_tag}: {r_sub}", r_pct, benchmark_row=rain_benchmark_row)
            ]
        },
        "footer": {
            "type": "box",
            "layout": "horizontal",
            "spacing": "sm",
            "paddingAll": "12px",
            "paddingTop": "0px",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": "#0F172A",
                    "height": "sm",
                    "flex": 1,
                    "action": {
                        "type": "uri",
                        "label": "📊 ดูแดชบอร์ด",
                        "uri": DASHBOARD_URL
                    }
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "height": "sm",
                    "flex": 1,
                    "action": {
                        "type": "uri",
                        "label": "ผังน้ำ Real-time",
                        "uri": "https://waterchart.thaiwater.net/basin/chaophraya"
                    }
                }
            ]
        }
    }

    return {
        "to": LINE_GROUP_ID,
        "messages": [
            {
                "type": "flex",
                "altText": f"🌊 สถานการณ์น้ำ & ฝน กทม. ({data['timestamp']})",
                "contents": bubble
            }
        ]
    }


def send_line_message(payload: dict) -> bool:
    """Transmit Flex Message payload via LINE Messaging API."""
    if not LINE_ACCESS_TOKEN or not LINE_GROUP_ID:
        print("[ERROR] LINE_FLOOD_CHANNEL_ACCESS_TOKEN or LINE_FLOOD_GROUP_ID missing.", file=sys.stderr)
        return False

    url = "https://api.line.me/v2/bot/message/push"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[SUCCESS] Delivered LINE Flex alert to {LINE_GROUP_ID} (HTTP {resp.status}).")
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"[ERROR] LINE delivery failed HTTP {e.code}: {err}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[ERROR] LINE connection error: {e}", file=sys.stderr)
        return False


# ==============================================================================
# 5. DASHBOARD & 1-YEAR HANDBOOK STATIC COMPILER (web/index.html)
# ==============================================================================

def compile_dashboard_html(data: dict) -> str:
    """Generate pixel-perfect, responsive HTML dashboard combining Live Data & 1-Year Handbook."""
    c2_col, c2_tag, c2_bg, c2_sub = get_station_status(data["c2"]["flow"], "c2")
    c13_col, c13_tag, c13_bg, c13_sub = get_station_status(data["c13"]["flow"], "c13")
    c29b_col, c29b_tag, c29b_bg, c29b_sub = get_station_status(data["c29b"]["flow"], "c29b")
    r_col, r_tag, r_bg, r_sub = get_rain_status(data["rain"]["rate"])

    c2_pct = min(max((data["c2"]["flow"] / data["c2"]["max"]) * 100.0, 3.0), 100.0)
    c13_pct = min(max((data["c13"]["flow"] / data["c13"]["max"]) * 100.0, 3.0), 100.0)
    c29b_pct = min(max((data["c29b"]["flow"] / data["c29b"]["max"]) * 100.0, 3.0), 100.0)
    r_pct = min(max((data["rain"]["rate"] / data["rain"]["max"]) * 100.0, 3.0), 100.0)

    cached_badge = ""
    if data.get("is_cached"):
        cached_badge = '<div class="bg-amber-500/10 border border-amber-500/30 text-amber-300 px-3 py-2 rounded-lg text-xs mb-4">⚠️ ข้อมูลชั่วคราว: เซิร์ฟเวอร์ต้นทางไม่ตอบสนอง กำลังแสดงข้อมูลล่าสุดที่มีในแคช</div>'

    html = f"""<!DOCTYPE html>
<html lang="th" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Flood Monitor & Handbook — สถานการณ์น้ำ & ฝน กทม.</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&family=Sarabun:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          fontFamily: {{
            sans: ['Sarabun', 'sans-serif'],
            display: ['Plus Jakarta Sans', 'Sarabun', 'sans-serif']
          }},
          colors: {{
            slate: {{
              850: '#0F172A',
              900: '#0B1120',
              950: '#020617'
            }}
          }}
        }}
      }}
    }}
  </script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen font-sans antialiased selection:bg-cyan-500 selection:text-white">

  <!-- Main Container -->
  <div class="max-w-3xl mx-auto px-4 py-8">
    
    <!-- Top Header -->
    <header class="mb-6">
      <div class="flex items-center justify-between gap-2 mb-2">
        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 uppercase tracking-wider font-display">
          <span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
          Live Monitoring
        </span>
        <span class="text-xs text-slate-400">อัปเดต: {data["timestamp"]}</span>
      </div>
      <h1 class="text-2xl sm:text-3xl font-bold font-display tracking-tight text-white mb-1">
        สถานการณ์น้ำ & เฝ้าระวังน้ำท่วม
      </h1>
      <p class="text-sm text-slate-400">
        ลุ่มน้ำเจ้าพระยา & กรุงเทพมหานคร • แดชบอร์ด & คู่มือประเมินความเสี่ยงกันลืม
      </p>
    </header>

    {cached_badge}

    <!-- SECTION 1: LIVE DATA METRICS -->
    <section class="bg-slate-900 border border-slate-800 rounded-2xl p-5 mb-8 shadow-xl">
      <div class="flex items-center justify-between pb-3 mb-4 border-b border-slate-800">
        <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider font-display flex items-center gap-2">
          <span>🌊</span> อัตราการไหลของน้ำ (3 สถานีหลัก)
        </h2>
        <span class="text-[11px] text-slate-500">หน่วย: ลบ.ม./วินาที (cms)</span>
      </div>

      <!-- Station 1: C.2 -->
      <div class="mb-5">
        <div class="flex justify-between items-baseline mb-1">
          <div>
            <span class="font-bold text-white text-sm sm:text-base">{data["c2"]["name"]}</span>
            <span class="text-xs text-slate-400 ml-1">({data["c2"]["desc"]})</span>
          </div>
          <div class="text-right">
            <span class="font-bold text-base sm:text-lg font-display" style="color: {c2_col};">{data["c2"]["flow"]:,.0f}</span>
            <span class="text-xs text-slate-500">/ {data["c2"]["max"]:,.0f} cms</span>
          </div>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
          <div class="h-full rounded-full transition-all duration-500" style="width: {c2_pct:.1f}%; background-color: {c2_col};"></div>
        </div>
        <div class="flex justify-between items-center text-[11px] mt-1.5">
          <span class="text-slate-400">{c2_sub}</span>
          <span class="font-semibold" style="color: {c2_col};">{c2_tag}</span>
        </div>
      </div>

      <!-- Station 2: C.13 -->
      <div class="mb-5">
        <div class="flex justify-between items-baseline mb-1">
          <div>
            <span class="font-bold text-white text-sm sm:text-base">{data["c13"]["name"]}</span>
            <span class="text-xs text-slate-400 ml-1">({data["c13"]["desc"]})</span>
          </div>
          <div class="text-right">
            <span class="font-bold text-base sm:text-lg font-display" style="color: {c13_col};">{data["c13"]["flow"]:,.0f}</span>
            <span class="text-xs text-slate-500">/ {data["c13"]["max"]:,.0f} cms</span>
          </div>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
          <div class="h-full rounded-full transition-all duration-500" style="width: {c13_pct:.1f}%; background-color: {c13_col};"></div>
        </div>
        <div class="flex justify-between items-center text-[11px] mt-1.5">
          <span class="text-slate-400">{c13_sub}</span>
          <span class="font-semibold" style="color: {c13_col};">{c13_tag}</span>
        </div>
      </div>

      <!-- Station 3: C.29B -->
      <div class="mb-6">
        <div class="flex justify-between items-baseline mb-1">
          <div>
            <span class="font-bold text-white text-sm sm:text-base">{data["c29b"]["name"]}</span>
            <span class="text-xs text-slate-400 ml-1">({data["c29b"]["desc"]})</span>
          </div>
          <div class="text-right">
            <span class="font-bold text-base sm:text-lg font-display" style="color: {c29b_col};">{data["c29b"]["flow"]:,.0f}</span>
            <span class="text-xs text-slate-500">/ {data["c29b"]["max"]:,.0f} cms</span>
          </div>
        </div>
        <div class="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
          <div class="h-full rounded-full transition-all duration-500" style="width: {c29b_pct:.1f}%; background-color: {c29b_col};"></div>
        </div>
        <div class="flex justify-between items-center text-[11px] mt-1.5">
          <span class="text-slate-400">{c29b_sub}</span>
          <span class="font-semibold" style="color: {c29b_col};">{c29b_tag}</span>
        </div>
      </div>

      <!-- Rainfall Section -->
      <div class="pt-4 border-t border-slate-800">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider font-display flex items-center gap-2">
            <span>🌧️</span> ปริมาณฝนเฉพาะหน้า (กทม.)
          </h2>
          <span class="text-[11px] text-slate-500">ขีดระบาย กทม. 60 มม. | สถิติน้ำท่วมใหญ่ 300 มม.</span>
        </div>
        <div class="flex justify-between items-baseline mb-1">
          <div>
            <span class="font-bold text-white text-sm sm:text-base">{data["rain"]["name"]}</span>
            <span class="text-xs text-slate-400 ml-1">({data["rain"]["desc"]})</span>
          </div>
          <div class="text-right">
            <span class="font-bold text-base sm:text-lg font-display" style="color: {r_col};">{data["rain"]["rate"]:.1f}</span>
            <span class="text-xs text-slate-500">/ {data["rain"]["max"]:,.0f} {data["rain"]["unit"]}</span>
          </div>
        </div>
        <div class="relative w-full bg-slate-800 rounded-full h-2.5 my-1">
          <div class="h-full rounded-full transition-all duration-500" style="width: {r_pct:.1f}%; background-color: {r_col};"></div>
          <!-- Visual threshold pin at 20% (60mm) -->
          <div class="absolute -top-1 -bottom-1 left-[20%] w-0.5 bg-amber-400 rounded-full shadow-[0_0_6px_rgba(251,191,36,0.8)] z-10"></div>
        </div>
        <!-- Benchmark marker labels row -->
        <div class="relative w-full text-[10px] text-slate-400 h-4 mb-1">
          <span class="absolute left-0 text-slate-500">0</span>
          <span class="absolute left-[20%] -translate-x-2 text-amber-400 font-semibold">▲ ขีดรับน้ำ กทม. (60 มม.)</span>
          <span class="absolute right-0 text-slate-400">300 มม. (สถิติน้ำท่วมใหญ่)</span>
        </div>
        <div class="flex justify-between items-center text-[11px] mt-1.5">
          <span class="text-slate-400">{r_sub}</span>
          <span class="font-semibold" style="color: {r_col};">{r_tag}</span>
        </div>
      </div>
    </section>

    <!-- SECTION 2: 72H VISUAL RIVER FLOW -->
    <section class="bg-slate-900 border border-slate-800 rounded-2xl p-5 mb-8">
      <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider font-display mb-4 flex items-center gap-2">
        <span>🗺️</span> แผนผังเส้นทางน้ำ & เวลาเดินทาง (72-Hour Horizon)
      </h2>
      <div class="grid grid-cols-1 sm:grid-cols-4 gap-3 text-center text-xs">
        <div class="bg-slate-800/60 p-3 rounded-xl border border-slate-700/50">
          <div class="text-cyan-400 font-bold mb-1">C.2 นครสวรรค์</div>
          <div class="text-[11px] text-slate-400">รับน้ำ ปิง วัง ยม น่าน</div>
          <div class="mt-2 text-[10px] text-amber-400 font-mono">เดินทาง ~48 ชม. ↓</div>
        </div>
        <div class="bg-slate-800/60 p-3 rounded-xl border border-slate-700/50">
          <div class="text-cyan-400 font-bold mb-1">C.13 เขื่อนเจ้าพระยา</div>
          <div class="text-[11px] text-slate-400">จุดชี้ชะตาระบายน้ำ</div>
          <div class="mt-2 text-[10px] text-amber-400 font-mono">เดินทาง ~24 ชม. ↓</div>
        </div>
        <div class="bg-slate-800/60 p-3 rounded-xl border border-slate-700/50">
          <div class="text-cyan-400 font-bold mb-1">C.29B ปทุมธานี</div>
          <div class="text-[11px] text-slate-400">ด่านหน้าก่อนเข้า กทม.</div>
          <div class="mt-2 text-[10px] text-emerald-400 font-mono">แนวป้องกันชั้นใน ↓</div>
        </div>
        <div class="bg-slate-800/60 p-3 rounded-xl border border-slate-700/50">
          <div class="text-cyan-400 font-bold mb-1">กทม. & อ่าวไทย</div>
          <div class="text-[11px] text-slate-400">รับน้ำเหนือ + ทะเลหนุน</div>
          <div class="mt-2 text-[10px] text-slate-400 font-mono">ออกสู่ทะเล</div>
        </div>
      </div>
    </section>

    <!-- SECTION 3: 1-YEAR CHEATSHEET & MAGIC NUMBERS -->
    <section class="bg-slate-900 border border-slate-800 rounded-2xl p-5 mb-8">
      <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider font-display mb-4 flex items-center gap-2">
        <span>📖</span> คู่มือจำเกณฑ์ตัดสินใจ (Magic Numbers กันลืม 1 ปี)
      </h2>
      <div class="space-y-3 text-xs sm:text-sm">
        <div class="flex gap-3 items-start bg-slate-800/40 p-3 rounded-xl border border-slate-800">
          <span class="px-2 py-0.5 rounded font-mono font-bold text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 whitespace-nowrap">&lt; 1,800 cms</span>
          <div>
            <strong class="text-white">ปลอดภัย 100%</strong>
            <p class="text-slate-400 text-xs mt-0.5">การระบายน้ำอยู่ในเกณฑ์ปกติ คันกั้นน้ำ กทม. รับน้ำได้สบาย ไร้ความกังวล</p>
          </div>
        </div>
        <div class="flex gap-3 items-start bg-slate-800/40 p-3 rounded-xl border border-slate-800">
          <span class="px-2 py-0.5 rounded font-mono font-bold text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 whitespace-nowrap">1,800 – 2,500</span>
          <div>
            <strong class="text-amber-300">เริ่มเฝ้าระวัง & เตรียมตัวล่วงหน้า 48 ชม.</strong>
            <p class="text-slate-400 text-xs mt-0.5">ชุมชนนอกแนวคันกั้นน้ำริมเจ้าพระยา (ทั้งปริมณฑลและ กทม. 16 ชุมชน) น้ำเริ่มปริ่มตลิ่ง ต้องเตรียมยกของขึ้นที่สูง</p>
          </div>
        </div>
        <div class="flex gap-3 items-start bg-slate-800/40 p-3 rounded-xl border border-slate-800">
          <span class="px-2 py-0.5 rounded font-mono font-bold text-xs bg-rose-500/10 text-rose-400 border border-rose-500/20 whitespace-nowrap">&gt; 3,000 cms</span>
          <div>
            <strong class="text-rose-400">สัญญาณวิกฤตสูงสุด (ความเสี่ยงปี 2554)</strong>
            <p class="text-slate-400 text-xs mt-0.5">ปริมาณน้ำเกินขีดรับน้ำของคันกั้นน้ำ กทม. ชั้นใน เสี่ยงเกิดน้ำล้นตลิ่งและท่วมขังเป็นวงกว้าง</p>
          </div>
        </div>
      </div>

      <!-- 3-Factor Formula Card -->
      <div class="mt-4 p-3.5 bg-slate-950/80 rounded-xl border border-slate-800 text-xs">
        <div class="font-bold text-cyan-300 mb-1">⚡ สูตรน้ำท่วม กทม. "3 ประสาน" (The 3-Factor Formula):</div>
        <p class="text-slate-300">น้ำท่วม กทม. มักเกิดจาก 3 ตัวแปรมาชนกันในเดือน <strong>ตุลาคม</strong>: <br>
        (1) น้ำเหนือระบายเกิน 2,000 cms + (2) ฝนตกสะสมในพื้นที่ &gt; 60 มม. + (3) น้ำทะเลหนุนสูงในอ่าวไทย (> 1.7 ม.รทก.) ทำให้น้ำไหลลงทะเลไม่ได้</p>
      </div>
    </section>

    <!-- SECTION 4: ACTION CHECKLIST -->
    <section class="bg-slate-900 border border-slate-800 rounded-2xl p-5 mb-8">
      <h2 class="text-xs font-bold text-slate-400 uppercase tracking-wider font-display mb-3 flex items-center gap-2">
        <span>✅</span> สิ่งที่ต้องทำเมื่อตัวเลขแตะสีเหลือง/ส้ม (Action Checklist)
      </h2>
      <ul class="space-y-2 text-xs text-slate-300">
        <li class="flex items-center gap-2">
          <input type="checkbox" class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0">
          <span>ตรวจสอบปลั๊กไฟและสวิตช์เครื่องใช้ไฟฟ้าชั้นล่าง</span>
        </li>
        <li class="flex items-center gap-2">
          <input type="checkbox" class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0">
          <span>วางแผนจุดจอดรถยนต์สำรองบนที่สูง (หากพักอาศัยในจุดเสี่ยงริมน้ำ)</span>
        </li>
        <li class="flex items-center gap-2">
          <input type="checkbox" class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0">
          <span>ตรวจสอบปั๊มน้ำไดโว่และท่อระบายน้ำรอบบ้านว่าไม่อุดตัน</span>
        </li>
        <li class="flex items-center gap-2">
          <input type="checkbox" class="rounded bg-slate-800 border-slate-700 text-cyan-500 focus:ring-0">
          <span>สำรองน้ำดื่มและยาประจำตัวสำหรับ 3–5 วัน</span>
        </li>
      </ul>
    </section>

    <!-- Footer Links -->
    <footer class="text-center text-xs text-slate-500 pt-4 border-t border-slate-900">
      <div class="flex justify-center gap-4 mb-2">
        <a href="https://waterchart.thaiwater.net/basin/chaophraya" target="_blank" class="hover:text-cyan-400 transition">ผังน้ำ ThaiWater</a>
        <a href="https://wmsc.rid.go.th" target="_blank" class="hover:text-cyan-400 transition">กรมชลประทาน SWOC</a>
        <a href="https://weather.bangkok.go.th/Radar/" target="_blank" class="hover:text-cyan-400 transition">เรดาร์ กทม.</a>
      </div>
      <p>จัดทำโดย myPKA Automation • แหล่งข้อมูล: สถาบันสารสนเทศทรัพยากรน้ำ (สสน.) & กรมชลประทาน</p>
    </footer>

  </div>
</body>
</html>
"""
    return html


# ==============================================================================
# 6. MAIN ORCHESTRATION PIPELINE
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Flood Monitor & Alert Engine (Zero Dependency)")
    parser.add_argument("--run", action="store_true", help="Execute full daily cron pipeline (Fetch -> Alert -> Compile HTML)")
    parser.add_argument("--test-fetch", action="store_true", help="Test live API data retrieval and print JSON")
    parser.add_argument("--force-alert", action="store_true", help="Force send LINE Flex alert message regardless of thresholds")
    parser.add_argument("--dry-run", action="store_true", help="Run pipeline and print status without dispatching LINE message")
    parser.add_argument("--build-html", action="store_true", help="Compile and save web/index.html only")
    args = parser.parse_args()

    if not any([args.run, args.test_fetch, args.force_alert, args.dry_run, args.build_html]):
        parser.print_help()
        sys.exit(0)

    # Mode: Test Fetch
    if args.test_fetch:
        data = get_live_hydrological_data()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        sys.exit(0)

    # Core Flow
    print("=== Flood Monitor Pipeline Initialized ===")
    data = get_live_hydrological_data()

    # Always compile & save HTML dashboard
    os.makedirs(WEB_DIR, exist_ok=True)
    html_content = compile_dashboard_html(data)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"[SUCCESS] Compiled live dashboard to {INDEX_FILE} ({len(html_content):,} bytes).")

    if args.build_html and not (args.run or args.force_alert):
        sys.exit(0)

    # Evaluate Alert
    should_alert, reason = evaluate_alert_decision(data, force=args.force_alert)
    print(f"Alert Decision: {'TRIGGER ALERT' if should_alert else 'SILENT'}")
    print(f"Reason: {reason}")

    if should_alert:
        payload = build_line_flex_payload(data, reason)
        if args.dry_run:
            print("[DRY-RUN] Alert triggered, skipping API call. Payload target:", payload["to"])
        else:
            success = send_line_message(payload)
            if not success:
                sys.exit(1)
    else:
        print("[INFO] Under thresholds. No LINE notification dispatched (Alert-by-Exception).")

    print("=== Pipeline Complete ===")


if __name__ == "__main__":
    main()
