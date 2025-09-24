# Trailing Exit Bot

**Beginner-friendly Python script** that automates a simple **trailing-profit exit** across your live delivery (CNC) holdings in a Groww account. Runs on a schedule so you don’t have to watch the market.

---

## What it does

* Merges **holdings + today’s positions** to get correct live quantity per symbol.
* **Arms** a stock after it’s up by a threshold (e.g. **+1%** vs your average buy).
* Tracks the **peak** and **sells** if price falls by a trailing amount (e.g. **0.7%**) from that peak.
* Skips symbols **already sold today**; polls LTPs in **batches**; supports **DRY\_RUN**.

---

## Config (edit in script)

```python
DRY_RUN       = True      # True = simulate; False = place real orders
TRIGGER_GAIN  = 1.01      # Arm once LTP >= avg * 1.01  (+1%)
TRAIL_PCT     = 0.007     # 0.7% trail from peak after arming
POLL_SECS     = 2         # Polling interval (seconds)
MAX_LTP_CHUNK = 50        # LTP batch size
```

---

## Setup

```bash
pip install pyotp
# plus your Groww SDK (imported as `growwapi`)
```

**Credentials:** load from environment variables or a `.env` (do not commit secrets).

```
GROWW_API_KEY=your_api_key
GROWW_TOTP_SECRET=otpauth://... or BASE32 secret
```

---

## Run

**Dry run (recommended first):**

```bash
python trailing_bot.py
```

**Live mode:**

* Set `DRY_RUN = False`, re-run. You’ll see order IDs on sells.

---

## (Optional) Schedule on Windows

```cmd
schtasks /create /sc daily /tn "TrailingExitBot" ^
  /tr "\"C:\Python313\python.exe\" \"C:\pyscripts\trailing_bot.py\"" ^
  /st 03:45 /rl HIGHEST
```

* “Run only when user is logged on” → visible console.
* “Run whether user is logged on or not” → background (add log redirection if needed).

---

## Safety & notes

* **Not financial advice.** Use at your own risk; follow broker/exchange T\&Cs.
* Sells are **market orders** on trail hit (expect normal slippage).
* Consider adding a **market-hours guard** (e.g., 09:15–15:30 IST).
* Keep system time synced for **TOTP**.

---

## Roadmap (next steps)

* **Partial profit booking** (sell 30–50% at +1–2%, trail the rest wider).
* **Volatility-aware trailing** (tighter in calm markets, wider in choppy ones).
* **Per-symbol strategies**, daily risk caps, CSV logs + weekly summaries.

---

**Disclaimer:** Please be careful with stock investments and start slow/low
