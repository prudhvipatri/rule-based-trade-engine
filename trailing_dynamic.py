
from growwapi import GrowwAPI
import pyotp
import time
import datetime
 
# =====================
# STEP 1: Setup
# =====================

API_KEY = ""
API_SECRET_TOTP = ""
 
totp = pyotp.TOTP(API_SECRET_TOTP).now()
access_token = GrowwAPI.get_access_token(api_key=API_KEY, totp=totp)
groww = GrowwAPI(access_token)
print(" Ready to Groww (TOTP)")


# -------- Config --------
DRY_RUN         = True              # set False to actually place orders
TRIGGER_GAIN    = 1.01                 # arm trailing once LTP >= avg * 1.01  (i.e., +1%)
TRAIL_PCT       = 0.007                # 0.7% trailing distance
POLL_SECS       = 2                    # seconds between polls
MAX_LTP_CHUNK   = 50                   # API limit safety

# -------- Helpers (your merge logic, lightly wrapped) --------
def to_int(x):
    try: return int(float(x or 0))
    except: return 0

def norm_symbol(s):
    s = (s or "").upper().strip()
    if s.endswith("-EQ"): s = s[:-3]
    return s

def pick_avg(row):
    for k in ("net_price","average_price","credit_price","carry_forward_credit_price"):
        v = row.get(k)
        try:
            f = float(v)
            if f > 0: return f
        except:
            pass
    return 0.0

def fetch_live_rows(groww):
    h_resp = groww.get_holdings_for_user() or {}
    p_resp = groww.get_positions_for_user() or {}
    holdings  = h_resp.get("holdings", []) or []
    positions = p_resp.get("positions", []) or []
    print(f" Holdings (raw): {len(holdings)} |  Positions (raw): {len(positions)}")

    # Seed from holdings (yesterday’s CNC snapshot)
    live = {}  # key: (exch, sym) -> row
    for h in holdings:
        sym  = norm_symbol(h.get("trading_symbol"))
        exch = (h.get("exchange") or "NSE").upper()
        qty  = to_int(h.get("quantity"))
        avg  = pick_avg(h)
        if not sym or qty <= 0:
            continue
        live[(exch, sym)] = {"symbol": sym, "exchange": exch, "qty": qty, "avg": avg}

    # Adjust with positions: ONLY add today's delta; if no holding exists, seed from CF once
    for p in positions:
        sym   = norm_symbol(p.get("trading_symbol"))
        exch  = (p.get("exchange") or "NSE").upper()
        if not sym:
            continue

        cf_cr  = to_int(p.get("carry_forward_credit_quantity"))
        cf_db  = to_int(p.get("carry_forward_debit_quantity"))
        day_cr = to_int(p.get("credit_quantity"))
        day_db = to_int(p.get("debit_quantity"))
        day_delta = day_cr - day_db

        key = (exch, sym)
        if key in live:
            base_qty = live[key]["qty"]
        else:
            base_qty = cf_cr - cf_db
            live[key] = {"symbol": sym, "exchange": exch, "qty": 0, "avg": 0.0}

        new_qty = base_qty + day_delta
        live[key]["qty"] = new_qty
        if live[key]["avg"] <= 0:
            live[key]["avg"] = pick_avg(p)

    # Finalize rows (qty > 0) and build LTP key
    live_rows = []
    for (exch, sym), r in live.items():
        if r["qty"] > 0:
            r["key"] = f"{exch}_{sym}"
            live_rows.append(r)

    print(f" Live CNC rows (corrected): {len(live_rows)}")
    for r in live_rows:
        print(f"   • {r['symbol']} ({r['exchange']}) qty={r['qty']} avg={r['avg']:.2f}")

    # Detect anything sold today to avoid re-selling
    sold_today = set()
    for p in positions:
        if to_int(p.get("debit_quantity")) > 0:
            sold_today.add(f"{(p.get('exchange') or 'NSE').upper()}_{norm_symbol(p.get('trading_symbol'))}")

    return live_rows, sold_today

def chunked(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]

# -------- Trailing-stop runner for ALL live rows --------
def run_trailing_all():
    # Build the symbol list dynamically from your account
    live_rows, sold_today = fetch_live_rows(groww)

    # Build per-symbol state: armed & peak
    state = {}  # key -> {"armed": bool, "peak": float}
    for r in live_rows:
        key = r["key"]
        state[key] = {"armed": False, "peak": 0.0}

    # Precompute the arm thresholds
    arm_threshold = {r["key"]: (r["avg"] * TRIGGER_GAIN if r["avg"] > 0 else float("inf")) for r in live_rows}
    qty_map       = {r["key"]: r["qty"] for r in live_rows}
    avg_map       = {r["key"]: r["avg"] for r in live_rows}
    exch_map      = {r["key"]: r["exchange"] for r in live_rows}
    sym_map       = {r["key"]: r["symbol"] for r in live_rows}

    keys = [r["key"] for r in live_rows]
    if not keys:
        print("ℹ No live holdings to monitor. Exiting.")
        return

    print(f"\n Trailing config: arm at +{(TRIGGER_GAIN-1)*100:.2f}% | trail {TRAIL_PCT*100:.2f}% | poll {POLL_SECS}s")
    print("  Monitoring:", ", ".join(sym_map[k] for k in keys))

    try:
        while True:
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            # Batch LTP by chunks (API limit)
            ltp_results = {}
            for batch in chunked(keys, MAX_LTP_CHUNK):
                ltp_resp = groww.get_ltp(
                    segment=groww.SEGMENT_CASH,
                    exchange_trading_symbols=tuple(batch)
                ) or {}
                ltp_results.update(ltp_resp)

            any_action = False
            for key in keys[:]:  # iterate over a snapshot since we may remove keys that sell
                symbol = sym_map[key]
                exch   = exch_map[key]
                qty    = qty_map[key]
                avg    = avg_map[key]

                # Skip symbols sold today (extra safety)
                if key in sold_today:
                    # You can choose to continue watching for re-entry; for now, stop tracking.
                    continue

                # Parse LTP
                try:
                    ltp = float(ltp_results.get(key, 0) or 0)
                except:
                    ltp = 0.0

                if ltp <= 0:
                    continue

                s = state[key]
                if not s["armed"]:
                    print(f" {symbol}: Avg {avg:.2f} | LTP {ltp:.2f} | Arm @ ≥ {arm_threshold[key]:.2f}")
                    if avg > 0 and ltp >= arm_threshold[key]:
                        s["armed"] = True
                        s["peak"]  = ltp
                        print(f" {symbol} armed at {ltp:.2f} (+{(TRIGGER_GAIN-1)*100:.2f}%)")
                else:
                    # Update peak, compute trailing stop
                    if ltp > s["peak"]:
                        s["peak"] = ltp
                    trail_stop = s["peak"] * (1.0 - TRAIL_PCT)
                    print(f"  {symbol}: Peak {s['peak']:.2f} | Trail {trail_stop:.2f} | LTP {ltp:.2f}")
                    if ltp <= trail_stop:
                        # SELL ALL for this symbol
                        if DRY_RUN:
                            print(f" DRY-RUN: Would SELL {qty} {symbol} @ MARKET (trail hit)")
                        else:
                            try:
                                print(f" SELL {symbol} Qty {qty} on {exch} @ MARKET (trail hit)")
                                order = groww.place_order(
                                    trading_symbol=symbol,
                                    quantity=max(1, int(qty)),
                                    validity=groww.VALIDITY_DAY,
                                    exchange=(groww.EXCHANGE_NSE if exch == "NSE" else groww.EXCHANGE_BSE),
                                    segment=groww.SEGMENT_CASH,
                                    product=groww.PRODUCT_CNC,
                                    order_type=groww.ORDER_TYPE_MARKET,
                                    transaction_type=groww.TRANSACTION_TYPE_SELL
                                )
                                print(f" SOLD {symbol} | Order ID: {order.get('groww_order_id')}")
                                sold_today.add(key)
                            except Exception as e:
                                print(f" SELL failed {symbol}: {e}")
                        # After sell (or dry-run), stop tracking this key
                        keys.remove(key)
                        any_action = True

            if not keys:
                print("🏁 All tracked symbols finished.")
                return

            if not any_action:
                time.sleep(POLL_SECS)

    except KeyboardInterrupt:
        print("\n Stopped by user.")

# -------- Run it --------
if __name__ == "__main__":
    run_trailing_all()
