# 🌊 Flood Monitor & Handbook

Automated hydrological telemetry monitor, alert-by-exception LINE bot, and 1-year flood handbook for the Chao Phraya River Basin and Bangkok.

🌐 **Live Dashboard & Handbook:** [https://pipatpong84.github.io/flood-monitor/](https://pipatpong84.github.io/flood-monitor/)

---

## 📌 Key Capabilities

1. **3-Tier Hydrological Ingestion:**
   - **Primary:** Real-time official telemetry APIs from [ThaiWater](https://api-v3.thaiwater.net) (HII / สสน.).
   - **Secondary:** Fallback to [Royal Irrigation Department (RID SWOC)](https://wmsc.rid.go.th) and [Bangkok Drainage Weather](https://weather.bangkok.go.th/rain).
   - **Tertiary:** Last-Known-Good local cache (`data.json`) with visual warning indicators.
2. **Alert-by-Exception Strategy:**
   - **Silence is Golden:** Normal readings below threshold (`C.13 < 1,800 cms`, `Rain < 30 mm/hr`) trigger zero messages to eliminate alert fatigue.
   - **Proactive Early Warning:** Alerts trigger when:
     - `C.13 >= 1,800 cms` (48-hour prep window before downstream impacts)
     - `C.2 >= 2,200 cms` (upstream flood pulse)
     - `Rain >= 30 mm/hr` (waterlogging risk on BKK roads)
     - **Sunday 08:00 AM Heartbeat:** Weekly pulse check (`🟢 ระบบทำงานปกติ: น้ำยังปลอดภัย`) ensuring the system is alive.
3. **Cross-Platform LINE Flex Message v2:**
   - Dark modern aesthetic (`#0F172A`) matching native mobile and desktop resolutions.
   - Dynamic percentage scale bars with color gradation (🟢 Safe / 🟡 Watch / 🔴 Critical).
   - Direct action buttons to live web dashboard and official ThaiWater river charts.
4. **Zero-Maintenance Serverless Operations:**
   - Runs automatically on GitHub Actions every morning at 07:00 AM ICT (`cron: 0 0 * * *`).
   - Compiles static dashboard and deploys to GitHub Pages for 100% free hosting.

---

## 🛠️ CLI Operations Manual

```bash
# Test real-time API fetch and inspect JSON
python3 monitor.py --test-fetch

# Recompile web/index.html locally
python3 monitor.py --build-html

# Full pipeline dry-run (evaluate thresholds without sending LINE push)
python3 monitor.py --run --dry-run

# Force send live LINE Flex alert to group
python3 monitor.py --force-alert
```

---

## 🔐 Environment Variables

Stored safely in GitHub Repository Secrets (never committed to git):
- `LINE_FLOOD_CHANNEL_ACCESS_TOKEN`: Long-lived LINE Messaging API Bearer token.
- `LINE_FLOOD_GROUP_ID`: Target LINE Group ID (`C...`).

---

## 📄 License & Attribution
Data sourced from National Hydroinformatics Data Center (HII / ThaiWater) and Royal Irrigation Department (RID).
Created and maintained by Pipatpong (myPKA Knowledge Architecture).
