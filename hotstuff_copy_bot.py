"""
Hotstuff.trade Copy Trading Bot v1.3
======================================
Designed for non-technical users. No manual .env editing required.

NEW in v1.3:
  [NEW 1] Interactive setup wizard — guides user through all settings
           on first run. No need to manually edit .env files.
  [NEW 2] Live terminal dashboard — real-time status, positions, PnL
           refreshed every 5 seconds directly in the terminal.
  [NEW 3] PnL tracking — every copy trade is recorded to pnl_history.json.
           Dashboard shows today's PnL, best/worst trade, total fees paid.
  [NEW 4] Auto-restart installer built in:
           - Windows: creates a Task Scheduler XML file
           - Mac/Linux: creates a systemd service file
           Run: python hotstuff_copy_bot.py --install-autostart
  [NEW 5] --reset flag to re-run setup wizard and overwrite .env

All v1.2 fixes retained:
  daily_loss tracking, API failure guard, error_count reset,
  global exposure cap, /restart command, log rotation, key safety.

Install:
  pip install requests msgpack eth-account eth-utils python-dotenv colorama

Usage:
  python hotstuff_copy_bot.py                  # normal start
  python hotstuff_copy_bot.py --setup          # re-run setup wizard
  python hotstuff_copy_bot.py --install        # install auto-restart service
  python hotstuff_copy_bot.py --dashboard      # show dashboard only (no trading)
"""

import os, sys, time, uuid, json, logging, requests, msgpack, threading, platform
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass, field
from datetime import datetime, date
from logging.handlers import RotatingFileHandler
from eth_account import Account
from eth_utils import keccak

try:
    from dotenv import load_dotenv, set_key
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False

try:
    from colorama import init as colorama_init, Fore, Back, Style
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False
    class Fore:
        GREEN = YELLOW = RED = CYAN = WHITE = MAGENTA = BLUE = RESET = ""
    class Style:
        BRIGHT = RESET_ALL = DIM = ""
    class Back:
        BLACK = RESET = ""

# ──────────────────────────────────────────────────────
#  PATHS
# ──────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
ENV_FILE     = os.path.join(BASE_DIR, ".env")
PNL_FILE     = os.path.join(BASE_DIR, "pnl_history.json")
LOG_FILE     = os.path.join(BASE_DIR, "copy_bot.log")

# ──────────────────────────────────────────────────────
#  SYMBOL DEFINITIONS
# ──────────────────────────────────────────────────────
ALL_SYMBOLS = ["BTC-PERP", "ETH-PERP", "SOL-PERP", "HYPE-PERP"]

# ──────────────────────────────────────────────────────
#  LOGGING  — rotating, 10 MB max
# ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=3),
        logging.StreamHandler(open(os.devnull, "w"))  # suppress to stdout (dashboard handles that)
    ]
)
log = logging.getLogger(__name__)

TX_PLACE_ORDER = 1301
TX_CANCEL_ALL  = 1311


# ══════════════════════════════════════════════════════
#  [NEW 1]  SETUP WIZARD
# ══════════════════════════════════════════════════════
def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    """Ask user a question with an optional default value."""
    display_default = "****" if secret and default else (f"[{default}]" if default else "")
    full_prompt = f"  {prompt} {display_default}: "
    while True:
        if secret:
            import getpass
            val = getpass.getpass(full_prompt).strip()
        else:
            val = input(full_prompt).strip()
        if val == "" and default:
            return default
        if val:
            return val
        print("  ⚠️  This field is required.")

def _ask_float(prompt: str, default: float, min_val: float, max_val: float) -> float:
    while True:
        raw = _ask(prompt, str(default))
        try:
            v = float(raw)
            if min_val <= v <= max_val:
                return v
            print(f"  ⚠️  Enter a number between {min_val} and {max_val}.")
        except ValueError:
            print("  ⚠️  Please enter a valid number.")

def run_setup_wizard() -> dict:
    """
    Interactive setup wizard. Saves settings to .env and returns CONFIG dict.
    """
    print()
    print(f"{Style.BRIGHT}{Fore.CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║   🚀  Hotstuff Copy Bot — First Time Setup       ║")
    print(f"║   Answer the questions below to get started.     ║")
    print(f"╚══════════════════════════════════════════════════╝{Style.RESET_ALL}")
    print()

    cfg = {}

    # ── Wallet ──────────────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 1: Your Agent Wallet ───────────────────────{Fore.RESET}")
    print("  Use your Hotstuff AGENT wallet (not your main wallet).")
    print("  Hotstuff dashboard → Settings → Agents → create agent.")
    print("  Your agent private key is only stored locally in .env")
    print("  and is never sent anywhere except directly to Hotstuff.")
    print()
    cfg["PRIVATE_KEY"]    = _ask("Agent private key (starts with 0x)", secret=True)

    # Wallet address — must be MAIN wallet, not agent wallet
    try:
        from eth_account import Account as _Acc
        agent_addr = _Acc.from_key(cfg["PRIVATE_KEY"]).address
        print(f"  {Fore.CYAN}ℹ️  Agent address (derived from key): {agent_addr}{Fore.RESET}")
    except Exception:
        agent_addr = ""
    print(f"  {Fore.YELLOW}⚠️  MAIN wallet address оруулна уу (agent хаяг биш!){Fore.RESET}")
    print("  Hotstuff dashboard → дээд баруун булан дахь үндсэн хаяг.")
    cfg["WALLET_ADDRESS"] = _ask("Main wallet address (0x...)")
    print()

    # ── Leader ──────────────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 2: Leader to Follow ────────────────────────{Fore.RESET}")
    cfg["LEADER_ADDRESS"] = _ask("Leader wallet address to copy (0x...)")
    print()

    # ── Copy ratio ──────────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 3: Copy Ratio ──────────────────────────────{Fore.RESET}")
    print("  How much of the leader's position to copy.")
    print("  Example: 0.5 = copy 50% of their size")
    print("           1.0 = copy 100% (same size as leader)")
    print("           0.1 = copy 10%  (safest for beginners)")
    print()
    ratio = _ask_float("Copy ratio (0.05 – 1.0)", 0.5, 0.05, 1.0)
    cfg["COPY_RATIO"] = str(ratio)
    print()

    # ── Symbols ──────────────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 4: Which Symbols to Follow ─────────────────{Fore.RESET}")
    print("  Available: BTC-PERP, ETH-PERP, SOL-PERP, HYPE-PERP")
    print("  You can type short names: btc, eth, sol, hype")
    print("  Leave blank to follow all 4 symbols.")
    print()
    syms_raw = _ask("Symbols (comma separated, or press Enter for all)", "")

    # Normalize: "hype" → "HYPE-PERP", "BTC" → "BTC-PERP", etc.
    _sym_map = {
        "BTC": "BTC-PERP", "ETH": "ETH-PERP",
        "SOL": "SOL-PERP", "HYPE": "HYPE-PERP",
    }
    def _normalize_sym(s: str) -> str:
        u = s.strip().upper().replace("-PERP", "")
        return _sym_map.get(u, u + "-PERP")

    if syms_raw.strip():
        active = [_normalize_sym(s) for s in syms_raw.split(",") if s.strip()]
        # Filter to only known symbols
        active = [s for s in active if s in ALL_SYMBOLS]
        if not active:
            print(f"  {Fore.YELLOW}No valid symbols found — using all 4.{Fore.RESET}")
            active = ALL_SYMBOLS
        cfg["SYMBOLS"] = ",".join(active)
    else:
        active = ALL_SYMBOLS
        cfg["SYMBOLS"] = ""

    print(f"  Following: {Fore.CYAN}{', '.join(active)}{Fore.RESET}")

    # ── Per-symbol max position ───────────────────────────────────────────
    print()
    print(f"{Fore.YELLOW}── Step 5: Max Position Size (USD) ─────────────────{Fore.RESET}")
    print("  Maximum USD value to hold per symbol.")
    print("  This limits your risk. Hotstuff minimum is $15.")
    print()
    for sym in ALL_SYMBOLS:
        key = f"MAX_{sym.split('-')[0]}"
        if sym in active:
            val = _ask_float(f"Max position for {sym} (USD)", 100.0, 15.0, 100000.0)
            cfg[key] = str(val)
        else:
            cfg[key] = "100"

    total_default = sum(float(cfg[f"MAX_{s.split('-')[0]}"]) for s in active)
    cfg["MAX_TOTAL"] = str(total_default)
    print()

    # ── Risk limits ───────────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 6: Risk Limits ─────────────────────────────{Fore.RESET}")
    print("  The bot will automatically stop trading if losses exceed these limits.")
    print()
    daily = _ask_float("Daily loss limit (USD) — bot pauses if exceeded", 30.0, 1.0, 100000.0)
    unreal = _ask_float("Unrealized loss limit (USD) — closes all positions if exceeded", 50.0, 1.0, 100000.0)
    cfg["DAILY_LOSS_LIMIT"]      = str(daily)
    cfg["UNREALIZED_LOSS_LIMIT"] = str(unreal)
    print()

    # ── Telegram (optional) ────────────────────────────────────────────────
    print(f"{Fore.YELLOW}── Step 7: Telegram Notifications (optional) ────────{Fore.RESET}")
    print("  Receive trade alerts and status reports on Telegram.")
    print("  Press Enter to skip.")
    print()
    tg_token   = input("  Telegram bot token (press Enter to skip): ").strip()
    tg_chat_id = input("  Telegram chat ID   (press Enter to skip): ").strip() if tg_token else ""
    cfg["TELEGRAM_TOKEN"]   = tg_token
    cfg["TELEGRAM_CHAT_ID"] = tg_chat_id
    cfg["SYNC_INTERVAL"]    = "5"

    # ── Save to .env ────────────────────────────────────────────────────────
    print()
    print(f"{Fore.GREEN}Saving settings to {ENV_FILE} ...{Fore.RESET}")
    with open(ENV_FILE, "w") as f:
        for k, v in cfg.items():
            # Wrap values with spaces or special chars in quotes
            safe_v = f'"{v}"' if " " in v or "#" in v else v
            f.write(f"{k}={safe_v}\n")

    print(f"{Fore.GREEN}✅ Setup complete!{Fore.RESET}")
    print()
    return cfg


# ══════════════════════════════════════════════════════
#  CONFIG LOADER
# ══════════════════════════════════════════════════════
def load_config() -> dict:
    """Load config from environment (after .env is loaded)."""
    _env_symbols = os.getenv("SYMBOLS", "").strip()
    active_symbols = (
        [s.strip() for s in _env_symbols.split(",") if s.strip()]
        if _env_symbols else ALL_SYMBOLS
    )
    _default_max = float(os.getenv("MAX_POSITION_DEFAULT", "100"))
    symbol_max_usd = {
        "BTC-PERP":  float(os.getenv("MAX_BTC",  str(_default_max))),
        "ETH-PERP":  float(os.getenv("MAX_ETH",  str(_default_max))),
        "SOL-PERP":  float(os.getenv("MAX_SOL",  str(_default_max))),
        "HYPE-PERP": float(os.getenv("MAX_HYPE", str(_default_max))),
    }
    return {
        "private_key":    os.getenv("PRIVATE_KEY",    ""),
        "wallet_address": os.getenv("WALLET_ADDRESS", ""),
        "leader_address": os.getenv("LEADER_ADDRESS", ""),
        "base_url":       "https://api.hotstuff.trade",
        "copy_ratio":     float(os.getenv("COPY_RATIO", "0.5")),
        "min_order_usd":  15.0,
        "symbols":        active_symbols,
        "instrument_ids": {s: None for s in ALL_SYMBOLS},
        "tick_size": {
            "BTC-PERP": "0.1", "ETH-PERP": "0.1",
            "SOL-PERP": "0.01", "HYPE-PERP": "0.001",
        },
        "lot_size": {
            "BTC-PERP": "0.0001", "ETH-PERP": "0.0001",
            "SOL-PERP": "0.01",   "HYPE-PERP": "0.001",
        },
        "symbol_max_usd":            symbol_max_usd,
        "_default_max":              _default_max,
        "max_total_exposure_usd":    float(os.getenv("MAX_TOTAL",             "400")),
        "daily_loss_limit_usd":      float(os.getenv("DAILY_LOSS_LIMIT",      "30")),
        "unrealized_loss_limit_usd": float(os.getenv("UNREALIZED_LOSS_LIMIT", "50")),
        "sync_interval":             int(os.getenv("SYNC_INTERVAL", "5")),
        "http_timeout":  10,
        "max_retries":    3,
        "retry_delay":    2.0,
        "telegram_token":   os.getenv("TELEGRAM_TOKEN",   ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
    }


# ══════════════════════════════════════════════════════
#  [NEW 3]  PNL TRACKER
# ══════════════════════════════════════════════════════
class PnlTracker:
    """
    Persists every copy trade to pnl_history.json.
    Provides daily/total summaries for the dashboard.
    """
    def __init__(self):
        self._lock   = threading.Lock()
        self._trades = self._load()

    def _load(self) -> list:
        try:
            with open(PNL_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self):
        try:
            with open(PNL_FILE, "w") as f:
                json.dump(self._trades, f, indent=2)
        except Exception as e:
            log.warning(f"PnL save failed: {e}")

    def record(self, symbol: str, side: str, size_usd: float,
               fee_usd: float, is_reduce: bool):
        """Record a copy trade."""
        with self._lock:
            self._trades.append({
                "ts":        time.time(),
                "date":      date.today().isoformat(),
                "symbol":    symbol,
                "side":      side,
                "size_usd":  round(size_usd, 2),
                "fee_usd":   round(fee_usd, 4),
                "is_reduce": is_reduce,
            })
            self._save()

    def today_summary(self) -> dict:
        today = date.today().isoformat()
        with self._lock:
            today_trades = [t for t in self._trades if t.get("date") == today]
        if not today_trades:
            return {
                "count": 0, "volume": 0.0, "fees": 0.0,
                "best_sym": "-", "worst_sym": "-",
            }
        by_sym: dict = {}
        for t in today_trades:
            sym = t["symbol"]
            by_sym.setdefault(sym, {"volume": 0.0, "fees": 0.0, "count": 0})
            by_sym[sym]["volume"] += t["size_usd"]
            by_sym[sym]["fees"]   += t["fee_usd"]
            by_sym[sym]["count"]  += 1
        best  = max(by_sym, key=lambda s: by_sym[s]["volume"])
        worst = min(by_sym, key=lambda s: by_sym[s]["fees"])
        return {
            "count":      len(today_trades),
            "volume":     sum(t["size_usd"] for t in today_trades),
            "fees":       sum(t["fee_usd"]  for t in today_trades),
            "best_sym":   best,
            "worst_sym":  worst,
            "by_sym":     by_sym,
        }

    def all_time_summary(self) -> dict:
        with self._lock:
            trades = list(self._trades)
        return {
            "count":  len(trades),
            "volume": sum(t["size_usd"] for t in trades),
            "fees":   sum(t["fee_usd"]  for t in trades),
        }

    def recent_trades(self, n: int = 5) -> list:
        with self._lock:
            return list(reversed(self._trades[-n:]))


# ══════════════════════════════════════════════════════
#  [NEW 2]  LIVE TERMINAL DASHBOARD
# ══════════════════════════════════════════════════════
class Dashboard:
    """
    Draws a live-updating terminal dashboard using ANSI escape codes.
    Runs in a background thread and refreshes every sync_interval seconds.
    """
    def __init__(self, bot: "CopyTradingBot"):
        self.bot   = bot
        self._lock = threading.Lock()
        self._last_render = ""

    def _bar(self, val: float, max_val: float, width: int = 10) -> str:
        if max_val <= 0:
            return "░" * width
        pct   = min(abs(val) / max_val, 1.0)
        filled = int(pct * width)
        empty  = width - filled
        color  = Fore.RED if pct > 0.8 else (Fore.YELLOW if pct > 0.5 else Fore.GREEN)
        return color + "█" * filled + Fore.WHITE + Style.DIM + "░" * empty + Style.RESET_ALL

    def _side_label(self, size: float) -> str:
        if size > 0:
            return f"{Fore.GREEN}LONG ▲{Style.RESET_ALL}"
        if size < 0:
            return f"{Fore.RED}SHORT ▼{Style.RESET_ALL}"
        return f"{Style.DIM}FLAT  -{Style.RESET_ALL}"

    def render(self, mids: dict, my_pos: dict, leader_pos: dict,
               unreal: float, api_ok: bool) -> str:
        cfg   = self.bot.CONFIG
        risk  = self.bot.risk
        pnl   = self.bot.pnl
        today = pnl.today_summary()
        alltime = pnl.all_time_summary()
        recent = pnl.recent_trades(4)
        now   = datetime.now().strftime("%H:%M:%S")
        status_str = (
            f"{Fore.GREEN}● RUNNING{Style.RESET_ALL}"  if not risk.halted and not self.bot._pause_flag.is_set()
            else f"{Fore.YELLOW}⏸ PAUSED{Style.RESET_ALL}"  if self.bot._pause_flag.is_set()
            else f"{Fore.RED}✖ HALTED{Style.RESET_ALL}"
        )
        api_str = f"{Fore.GREEN}OK{Style.RESET_ALL}" if api_ok else f"{Fore.RED}FAILED{Style.RESET_ALL}"
        total_exp = sum(abs(my_pos.get(s, 0)) * mids.get(s, 0) for s in cfg["symbols"])

        lines = []
        W = 62
        def sep(char="─"):
            return Fore.WHITE + Style.DIM + char * W + Style.RESET_ALL

        lines.append(sep("═"))
        lines.append(
            f"{Style.BRIGHT}{Fore.CYAN}  🤖 Hotstuff Copy Bot v1.3"
            f"{Style.RESET_ALL}"
            f"{'':>10}{Style.DIM}updated {now}{Style.RESET_ALL}"
        )
        lines.append(sep("═"))

        # ── Status row ──────────────────────────────────────────────────
        lines.append(
            f"  Status: {status_str}   "
            f"API: {api_str}   "
            f"Ratio: {Fore.CYAN}{cfg['copy_ratio']*100:.0f}%{Style.RESET_ALL}   "
            f"Sync: {cfg['sync_interval']}s"
        )
        lines.append(
            f"  Leader: {Fore.CYAN}{cfg['leader_address'][:20]}...{Style.RESET_ALL}   "
            f"Copies today: {Fore.CYAN}{today['count']}{Style.RESET_ALL}"
        )
        lines.append(sep())

        # ── Positions ────────────────────────────────────────────────────
        lines.append(f"  {Style.BRIGHT}POSITIONS{Style.RESET_ALL}")
        lines.append(
            f"  {'Symbol':<12} {'Mine':>10} {'Leader':>10} "
            f"{'Side':<13} {'Exposure':>9} {'Max':>6}"
        )
        lines.append(sep())
        for sym in cfg["symbols"]:
            m   = my_pos.get(sym, 0.0)
            l   = leader_pos.get(sym, 0.0)
            mid = mids.get(sym, 0)
            mx  = cfg["symbol_max_usd"].get(sym, 100)
            exp = abs(m) * mid
            bar = self._bar(exp, mx, 8)
            lines.append(
                f"  {sym:<12} "
                f"{m:>+10.4f} "
                f"{l:>+10.4f} "
                f"{self._side_label(m):<13} "
                f"${exp:>7.1f} "
                f"${mx:>5.0f}"
            )
            lines.append(f"  {'':12} [{bar}] {abs(exp)/mx*100:.0f}%")
        lines.append(sep())

        # ── Exposure & Risk ───────────────────────────────────────────────
        exp_bar   = self._bar(total_exp,       cfg["max_total_exposure_usd"])
        loss_bar  = self._bar(risk.daily_loss_usd, cfg["daily_loss_limit_usd"])
        unr_color = Fore.RED if unreal < -cfg["unrealized_loss_limit_usd"] * 0.5 else (
                    Fore.YELLOW if unreal < 0 else Fore.GREEN)
        lines.append(f"  {Style.BRIGHT}RISK{Style.RESET_ALL}")
        lines.append(
            f"  Exposure   [{exp_bar}] "
            f"${total_exp:.1f} / ${cfg['max_total_exposure_usd']:.0f}"
        )
        lines.append(
            f"  Daily loss [{loss_bar}] "
            f"${risk.daily_loss_usd:.2f} / ${cfg['daily_loss_limit_usd']:.0f}"
        )
        lines.append(
            f"  Unrealized  {unr_color}${unreal:+.2f}{Style.RESET_ALL}  "
            f"(limit: -${cfg['unrealized_loss_limit_usd']:.0f})"
        )
        lines.append(sep())

        # ── PnL Summary ───────────────────────────────────────────────────
        lines.append(f"  {Style.BRIGHT}PNL TODAY{Style.RESET_ALL}")
        lines.append(
            f"  Volume: ${today['volume']:,.1f}   "
            f"Fees paid: ${today['fees']:.3f}   "
            f"Trades: {today['count']}"
        )
        if today.get("by_sym"):
            sym_summary = "  " + "  ".join(
                f"{sym.split('-')[0]}: {d['count']}× ${d['volume']:.0f}"
                for sym, d in today["by_sym"].items()
            )
            lines.append(sym_summary)
        lines.append(
            f"  All time — Volume: ${alltime['volume']:,.0f}  "
            f"Fees: ${alltime['fees']:.2f}  "
            f"Trades: {alltime['count']}"
        )
        lines.append(sep())

        # ── Recent trades ─────────────────────────────────────────────────
        lines.append(f"  {Style.BRIGHT}RECENT TRADES{Style.RESET_ALL}")
        if recent:
            for t in recent:
                ts   = datetime.fromtimestamp(t["ts"]).strftime("%H:%M:%S")
                side = f"{Fore.GREEN}BUY{Style.RESET_ALL}" if t["side"] == "b" \
                       else f"{Fore.RED}SELL{Style.RESET_ALL}"
                tag  = f"{Style.DIM}[close]{Style.RESET_ALL}" if t["is_reduce"] else ""
                lines.append(
                    f"  {ts}  {t['symbol']:<12} {side}  "
                    f"${t['size_usd']:>7.1f}  fee ${t['fee_usd']:.3f}  {tag}"
                )
        else:
            lines.append(f"  {Style.DIM}No trades yet today.{Style.RESET_ALL}")
        lines.append(sep())

        # ── Controls ─────────────────────────────────────────────────────
        lines.append(
            f"  {Style.DIM}Telegram: /pause  /resume  /restart  "
            f"/close  /status  /stop{Style.RESET_ALL}"
        )
        lines.append(
            f"  {Style.DIM}Terminal: Ctrl+C to stop bot{Style.RESET_ALL}"
        )
        lines.append(sep("═"))
        return "\n".join(lines)

    def refresh(self, mids: dict, my_pos: dict, leader_pos: dict,
                unreal: float, api_ok: bool):
        """Clear screen and redraw dashboard."""
        rendered = self.render(mids, my_pos, leader_pos, unreal, api_ok)
        with self._lock:
            # Move cursor to top-left and overwrite
            sys.stdout.write("\033[H\033[J")   # clear screen
            sys.stdout.write(rendered + "\n")
            sys.stdout.flush()


# ══════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════
def tg_send(msg: str, cfg: dict):
    token   = cfg.get("telegram_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not token or not chat_id:
        return
    chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
    for chunk in chunks:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                timeout=5
            )
        except Exception as e:
            log.debug(f"Telegram error: {e}")


# ══════════════════════════════════════════════════════
#  EIP-712 SIGNING
# ══════════════════════════════════════════════════════
def sign_action(wallet: Account, action: dict, tx_type: int) -> str:
    action_bytes     = msgpack.packb(action["data"], use_bin_type=True)
    payload_hash     = keccak(action_bytes)
    payload_hash_hex = "0x" + payload_hash.hex()
    signable = Account.sign_typed_data(
        wallet.key,
        full_message={
            "types": {
                "EIP712Domain": [
                    {"name": "name",              "type": "string"},
                    {"name": "version",           "type": "string"},
                    {"name": "chainId",           "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Action": [
                    {"name": "source",  "type": "string"},
                    {"name": "hash",    "type": "bytes32"},
                    {"name": "txType",  "type": "uint16"},
                ],
            },
            "primaryType": "Action",
            "domain": {
                "name": "HotstuffCore", "version": "1",
                "chainId": 1,
                "verifyingContract": "0x1234567890123456789012345678901234567890",
            },
            "message": {
                "source": "Mainnet",
                "hash":   payload_hash_hex,
                "txType": tx_type,
            },
        }
    )
    return "0x" + signable.signature.hex()


# ══════════════════════════════════════════════════════
#  INFO CLIENT
# ══════════════════════════════════════════════════════
class InfoClient:
    def __init__(self, cfg: dict):
        self.url = f"{cfg['base_url']}/info"
        self.cfg = cfg

    def _post(self, method: str, params: dict):
        for i in range(self.cfg["max_retries"]):
            try:
                r = requests.post(
                    self.url,
                    json={"method": method, "params": params},
                    timeout=self.cfg["http_timeout"]
                )
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i < self.cfg["max_retries"] - 1:
                    time.sleep(self.cfg["retry_delay"])
                else:
                    log.error(f"Info/{method} failed: {e}")
                    return None

    def get_instruments(self) -> list:
        res = self._post("instruments", {"type": "perps"})
        if not res:
            return []
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            return res.get("perps", res.get("instruments", res.get("data", [])))
        return []

    def get_mids(self) -> dict:
        res = self._post("mids", {"symbol": "all"})
        if not res:
            return {}
        if isinstance(res, dict):
            return {k: float(v) for k, v in res.items() if v}
        if isinstance(res, list):
            return {item["symbol"]: float(item["mid_price"])
                    for item in res if "symbol" in item}
        return {}

    def get_fills(self, address: str, limit: int = 100) -> list:
        """Fetch recent fills for position calculation fallback."""
        res = self._post("fills", {"user": address, "limit": limit})
        if isinstance(res, dict):
            return res.get("data", [])
        if isinstance(res, list):
            return res
        return []

    def get_positions(self, address: str) -> tuple:
        """
        Returns (positions_list, api_ok).
        Tries checksum and lowercase address variants.
        Hotstuff requires EIP-55 checksum address (mixed case).
        """
        try:
            from eth_utils import to_checksum_address
            addrs = list(dict.fromkeys([
                to_checksum_address(address), address.lower(), address
            ]))
        except Exception:
            addrs = [address, address.lower()]

        for addr in addrs:
            for params in [{"user": addr}, {"address": addr}, {"agent": addr}]:
                res = self._post("positions", params)
                if res is None:
                    continue
                if isinstance(res, list):
                    if len(res) > 0:
                        log.info(f"positions OK addr={addr[:12]}.. param={list(params.keys())[0]} n={len(res)}")
                    return res, True
                if isinstance(res, dict):
                    if "error" in res:
                        continue
                    for key in ("data", "positions", "result"):
                        val = res.get(key)
                        if val is not None:
                            return val, True
                    return [], True
        return [], False


# ══════════════════════════════════════════════════════
#  EXCHANGE CLIENT
# ══════════════════════════════════════════════════════
class ExchangeClient:
    def __init__(self, cfg: dict, wallet: Account):
        self.url    = f"{cfg['base_url']}/exchange"
        self.wallet = wallet
        self.cfg    = cfg

    def _nonce(self) -> int:
        return int(time.time() * 1000)

    def _post(self, payload: dict) -> dict:
        for i in range(self.cfg["max_retries"]):
            try:
                r = requests.post(self.url, json=payload,
                                  timeout=self.cfg["http_timeout"])
                if not r.ok:
                    log.error(f"Exchange error {r.status_code}: {r.text[:500]}")
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if i < self.cfg["max_retries"] - 1:
                    time.sleep(self.cfg["retry_delay"])
                else:
                    return {"error": str(e)}

    def _fmt_price(self, price: float, sym: str) -> str:
        """Tick-size aware price rounding — identical to MM bot fmt_price."""
        tick = self.cfg["tick_size"].get(sym, "0.1")
        from decimal import Decimal, ROUND_DOWN
        return str(Decimal(str(price)).quantize(Decimal(tick), rounding=ROUND_DOWN))

    def place_open_order(self, instrument_id: int, side: str,
                          size: str, mid_price: float, sym: str = "") -> dict:
        """
        Open a new position using limit order (GTC, post-only=True).
        Price must be tick_size rounded — same as MM bot fmt_price().
        """
        try:
            nonce = self._nonce()
            slippage  = 1.002 if side == "b" else 0.998
            raw_price = mid_price * slippage
            price_str = self._fmt_price(raw_price, sym) if sym else str(round(raw_price, 1))
            action_data = {
                "orders": [{
                    "instrumentId": instrument_id,
                    "side":         side,
                    "positionSide": "BOTH",
                    "price":        price_str,
                    "size":         str(size),
                    "tif":          "GTC",
                    "ro":           False,
                    "po":           False,
                    "cloid":        str(uuid.uuid4()),
                    "triggerPx":    "",
                    "isMarket":     False,
                    "tpsl":         "",
                    "grouping":     "",
                }],
                "expiresAfter": nonce + 3_600_000,
                "nonce":        nonce,
            }
            action = {"data": action_data, "type": str(TX_PLACE_ORDER)}
            sig    = sign_action(self.wallet, action, TX_PLACE_ORDER)
            return self._post({"action": action, "signature": sig, "nonce": nonce})
        except Exception as e:
            log.warning(f"place_open_order error: {e}")
            return {"error": str(e)}

    def place_market_order(self, instrument_id: int, side: str,
                           size: str, reduce_only: bool = False,
                           mid_price: float = 0.0) -> dict:
        """
        Close/reduce a position using market order (IOC, reduce-only).
        Same as MM bot's place_market_order.
        price="0" works for reduce-only orders on Hotstuff.
        """
        try:
            nonce = self._nonce()
            # Hotstuff requires positive price even for IOC/market orders.
            # Use mid price with 1% slippage to guarantee fill.
            # BUY to close short → price above mid; SELL to close long → price below mid
            if mid_price and mid_price > 0:
                slippage  = 1.01 if side == "b" else 0.99
                raw_price = mid_price * slippage
                # Round to 1 decimal (safe default for all symbols)
                from decimal import Decimal, ROUND_DOWN
                price_str = str(Decimal(str(raw_price)).quantize(Decimal("0.1"), rounding=ROUND_DOWN))
            else:
                price_str = "1"   # fallback — should not happen
            action_data = {
                "orders": [{
                    "instrumentId": instrument_id,
                    "side":         side,
                    "positionSide": "BOTH",
                    "price":        price_str,
                    "size":         str(size),
                    "tif":          "IOC",
                    "ro":           True,
                    "po":           False,
                    "cloid":        str(uuid.uuid4()),
                    "triggerPx":    "",
                    "isMarket":     True,
                    "tpsl":         "",
                    "grouping":     "",
                }],
                "expiresAfter": nonce + 3_600_000,
                "nonce":        nonce,
            }
            action = {"data": action_data, "type": str(TX_PLACE_ORDER)}
            sig    = sign_action(self.wallet, action, TX_PLACE_ORDER)
            return self._post({"action": action, "signature": sig, "nonce": nonce})
        except Exception as e:
            log.warning(f"place_market_order error: {e}")
            return {"error": str(e)}

    def cancel_all(self) -> dict:
        nonce = self._nonce()
        action_data = {"expiresAfter": nonce + 3_600_000, "nonce": nonce}
        action = {"data": action_data, "type": str(TX_CANCEL_ALL)}
        sig    = sign_action(self.wallet, action, TX_CANCEL_ALL)
        return self._post({"action": action, "signature": sig, "nonce": nonce})


# ══════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════
def fmt_size(s: float, sym: str, cfg: dict) -> str:
    lot = cfg["lot_size"].get(sym, "0.0001")
    v = Decimal(str(abs(s))).quantize(Decimal(lot), rounding=ROUND_DOWN)
    return str(max(v, Decimal("0")))

def parse_positions(raw_list: list) -> dict:
    """
    Convert raw API position list to {symbol: size}.
    Hotstuff format: {"instrument": "SOL-PERP", "size": "-1.57", ...}
    Positive size = LONG, negative = SHORT.
    """
    result = {}
    for p in raw_list:
        sym  = p.get("instrument") or p.get("symbol") or p.get("name") or ""
        # Hotstuff uses "size" field (string), may be negative for SHORT
        raw_size = p.get("size") or p.get("qty") or p.get("positionAmt") or 0
        try:
            size = float(raw_size)
        except (ValueError, TypeError):
            size = 0.0
        if sym and size != 0.0:
            result[sym] = size
    return result


# ══════════════════════════════════════════════════════
#  RISK TRACKER
# ══════════════════════════════════════════════════════
@dataclass
class RiskTracker:
    daily_loss_usd:    float = 0.0
    total_copies:      int   = 0
    successful_cycles: int   = 0
    error_count:       int   = 0
    halted:            bool  = False
    halt_reason:       str   = ""
    _day_start:        float = field(default_factory=time.time)

    def reset_daily(self):
        if time.time() - self._day_start > 86400:
            self.daily_loss_usd = 0.0
            self._day_start     = time.time()
            log.info("Daily loss counter reset")

    def record_loss(self, usd: float):
        if usd > 0:
            self.daily_loss_usd += usd

    def check_limits(self, cfg: dict) -> tuple:
        self.reset_daily()
        if self.daily_loss_usd >= cfg["daily_loss_limit_usd"]:
            return False, f"Daily loss limit ${cfg['daily_loss_limit_usd']} reached"
        return True, ""

    def halt(self, reason: str, cfg: dict):
        self.halted      = True
        self.halt_reason = reason
        log.critical(f"HALTED: {reason}")
        tg_send(f"🚨 <b>Copy Bot HALTED</b>\nReason: {reason}", cfg)


# ══════════════════════════════════════════════════════
#  COPY TRADING BOT
# ══════════════════════════════════════════════════════
class CopyTradingBot:

    def __init__(self, cfg: dict):
        self.CONFIG = cfg

        if not cfg["private_key"]:
            raise ValueError("PRIVATE_KEY not set. Run setup first.")
        if not cfg["leader_address"] or cfg["leader_address"] == "0xLEADER_WALLET":
            raise ValueError("LEADER_ADDRESS not set. Run setup first.")

        self.wallet   = Account.from_key(cfg["private_key"])
        self.info     = InfoClient(cfg)
        self.exchange = ExchangeClient(cfg, self.wallet)
        self.risk     = RiskTracker()
        self.pnl      = PnlTracker()
        self.dash     = Dashboard(self)

        self._stop_flag    = threading.Event()
        self._pause_flag   = threading.Event()
        self._restart_flag = threading.Event()

        # Shared state for dashboard (updated each cycle)
        self._last_mids:       dict  = {}
        self._last_my_pos:     dict  = {}
        self._last_leader_pos: dict  = {}
        self._last_unreal:     float = 0.0
        self._last_api_ok:     bool  = True

        # [FIX] In-memory position tracker for when API returns []
        # Tracks net position in contracts: {symbol: size}
        self._my_pos_tracker: dict = {}
        self._tracker_initialized = False

        log.info("Bot initialized — wallet %s", cfg["wallet_address"])
        self._resolve_instruments()
        self._init_my_positions()

    def _resolve_instruments(self):
        instruments = self.info.get_instruments()
        if not instruments:
            log.warning("Could not fetch instruments — using defaults")
            return
        for inst in instruments:
            name = inst.get("name", "")
            iid  = inst.get("id")
            tick = inst.get("tick_size")
            lot  = inst.get("lot_size")
            if name in ALL_SYMBOLS:
                if self.CONFIG["instrument_ids"].get(name) is None and iid:
                    self.CONFIG["instrument_ids"][name] = iid
                if tick:
                    self.CONFIG["tick_size"][name] = str(tick)
                if lot:
                    self.CONFIG["lot_size"][name] = str(lot)

    def _init_my_positions(self):
        """
        Initialize position tracker from fills history.
        Called once on startup. Computes net position from all historical fills.
        """
        cfg = self.CONFIG
        log.info("Initializing position tracker from fills history...")
        fills = self.info.get_fills(cfg["wallet_address"], limit=500)
        net = {}
        for f in reversed(fills):  # oldest first
            sym  = f.get("instrument", "")
            side = f.get("side", "")
            size = float(f.get("size", 0))
            if sym not in cfg["symbols"]:
                continue
            cur = net.get(sym, 0.0)
            if side == "b":
                net[sym] = cur + size
            elif side == "s":
                net[sym] = cur - size

        # Cross-check with API positions if available
        api_raw, api_ok = self.info.get_positions(cfg["wallet_address"])
        if api_ok and api_raw:
            api_pos = parse_positions(api_raw)
            for sym, size in api_pos.items():
                if sym in cfg["symbols"]:
                    net[sym] = size
                    log.info(f"  Position from API: {sym} {size:+.5f}")
        else:
            for sym, size in net.items():
                # Round to lot size precision
                lot = float(cfg["lot_size"].get(sym, "0.0001"))
                rounded = round(size / lot) * lot
                net[sym] = rounded
                if abs(rounded) > lot:
                    log.info(f"  Position from fills: {sym} {rounded:+.5f}")

        self._my_pos_tracker = net
        self._tracker_initialized = True
        log.info(f"Position tracker ready: {net}")

    def _get_my_positions(self) -> dict:
        """
        Get my current positions.
        Prefers API response; falls back to in-memory tracker.
        """
        cfg = self.CONFIG
        api_raw, api_ok = self.info.get_positions(cfg["wallet_address"])
        if api_ok and api_raw:
            pos = parse_positions(api_raw)
            log.info(f"My positions from API: {pos}")
            # API returned data — trust it completely, reset all symbols first
            for sym in cfg["symbols"]:
                self._my_pos_tracker[sym] = pos.get(sym, 0.0)
            return pos, api_raw
        if api_ok and not api_raw:
            # API returned empty list = no open positions — reset tracker
            log.info("API returned empty positions — resetting all to 0")
            for sym in cfg["symbols"]:
                self._my_pos_tracker[sym] = 0.0
            return {}, []
        # API returned [] — use tracker
        log.debug("Position API empty — using in-memory tracker")
        fake_raw = [
            {"instrument": sym, "size": str(size)}
            for sym, size in self._my_pos_tracker.items()
            if size != 0.0
        ]
        return self._my_pos_tracker.copy(), fake_raw

    def _update_tracker(self, sym: str, side: str, size: float):
        """Update in-memory position tracker after a fill."""
        cur = self._my_pos_tracker.get(sym, 0.0)
        if side == "b":
            self._my_pos_tracker[sym] = cur + size
        else:
            self._my_pos_tracker[sym] = cur - size
        log.debug(f"Tracker updated: {sym} {cur:+.5f} → {self._my_pos_tracker[sym]:+.5f}")

    def _unrealized_pnl(self, positions_raw: list, mids: dict) -> float:
        total = 0.0
        for p in positions_raw:
            sym   = p.get("instrument", p.get("symbol", ""))
            size  = float(p.get("size", p.get("qty", 0)))
            api_v = p.get("unrealizedPnl") or p.get("unrealized_pnl") or p.get("pnl")
            if api_v is not None:
                total += float(api_v)
                continue
            entry = float(p.get("entryPrice") or p.get("entry_price") or
                          p.get("avgPrice") or p.get("avg_price") or 0)
            mark  = mids.get(sym, 0)
            if entry and mark and size:
                total += (mark - entry) * size
        return total

    def _total_exposure(self, my_pos: dict, mids: dict) -> float:
        return sum(abs(my_pos.get(s, 0)) * mids.get(s, 0)
                   for s in self.CONFIG["symbols"])

    def _calc_target(self, leader_size: float, mid: float, sym: str,
                     cur_exp: float, my_size: float) -> float:
        if mid <= 0:
            return 0.0
        cfg    = self.CONFIG
        target = leader_size * cfg["copy_ratio"]

        # Per-symbol cap
        max_size = cfg["symbol_max_usd"].get(sym, cfg["_default_max"]) / mid
        if abs(target) > max_size:
            target = (1 if target > 0 else -1) * max_size

        # Global exposure cap
        if abs(target) * mid > abs(my_size) * mid:
            other = cur_exp - abs(my_size) * mid
            allowed = cfg["max_total_exposure_usd"] - other
            if allowed <= 0:
                return my_size
            if abs(target) * mid > allowed:
                target = (1 if target > 0 else -1) * (allowed / mid)
        return target

    def sync_once(self) -> bool:
        cfg  = self.CONFIG
        mids = self.info.get_mids()
        if not mids:
            log.warning("Mid price fetch failed — skipping cycle")
            self._last_api_ok = False
            return False

        cfg["_current_mids"] = mids  # share mids for order pricing
        leader_raw, leader_ok = self.info.get_positions(cfg["leader_address"])

        if not leader_ok:
            log.warning("Leader position fetch failed — skipping cycle")
            self._last_api_ok = False
            return False

        leader_pos           = parse_positions(leader_raw)
        my_pos, my_raw       = self._get_my_positions()
        unreal               = self._unrealized_pnl(my_raw, mids)

        # Update dashboard state
        self._last_mids       = mids
        self._last_my_pos     = my_pos
        self._last_leader_pos = leader_pos
        self._last_unreal     = unreal
        self._last_api_ok     = True

        # Unrealized loss check
        limit = cfg["unrealized_loss_limit_usd"]
        if unreal <= -limit:
            log.critical(f"Unrealized loss ${unreal:.2f} — closing all")
            tg_send(f"🚨 Unrealized loss limit hit: ${unreal:.2f}\nClosing all...", cfg)
            self._close_all(my_raw, mids)
            self.risk.record_loss(abs(unreal))
            self.risk.halt(f"Unrealized loss ${unreal:.2f}", cfg)
            return False

        cur_exp = self._total_exposure(my_pos, mids)

        for sym in set(cfg["symbols"]) | set(leader_pos) | set(my_pos):
            if sym not in cfg["symbols"]:
                continue
            mid = mids.get(sym, 0)
            if not mid:
                continue
            iid = cfg["instrument_ids"].get(sym)
            if not iid:
                log.warning(f"instrument_id not found for {sym} — skipping")
                continue

            leader_size = leader_pos.get(sym, 0.0)
            my_size     = my_pos.get(sym, 0.0)

            # Leader flat + API confirmed OK → close ours
            if leader_size == 0.0 and my_size != 0.0:
                sz   = fmt_size(abs(my_size), sym, cfg)
                side = "b" if my_size < 0 else "s"
                fee  = self._place_order(sym, iid, side, sz, True,
                                         abs(my_size) * mid, 0.0)
                self.risk.record_loss(fee)
                time.sleep(0.3)
                continue

            target    = self._calc_target(leader_size, mid, sym, cur_exp, my_size)
            delta     = target - my_size
            delta_usd = abs(delta) * mid

            if delta_usd < cfg["min_order_usd"]:
                continue
            lot = float(cfg["lot_size"].get(sym, "0.0001"))
            if abs(delta) < lot:
                continue

            side      = "b" if delta > 0 else "s"
            sz        = fmt_size(abs(delta), sym, cfg)
            is_reduce = (my_size > 0 and delta < 0) or (my_size < 0 and delta > 0)
            fee = self._place_order(sym, iid, side, sz, is_reduce, delta_usd, target)
            if is_reduce:
                self.risk.record_loss(fee)
            cur_exp = cur_exp - abs(my_size)*mid + abs(target)*mid
            time.sleep(0.3)

        return True

    def _place_order(self, sym: str, iid: int, side: str, sz: str,
                     is_reduce: bool, delta_usd: float, target: float) -> float:
        cfg = self.CONFIG
        if float(sz) <= 0:
            return 0.0
        direction = "BUY" if side == "b" else "SELL"
        emoji     = "📈" if side == "b" else "📉"
        log.info(f"{sym} {'CLOSE' if is_reduce else 'OPEN'}: {direction} {sz} ~${delta_usd:.1f}")

        mid = self.CONFIG.get("_current_mids", {}).get(sym, 0.0)
        if is_reduce:
            # Closing position: market order (IOC, reduce-only), price=0
            res = self.exchange.place_market_order(iid, side, sz, reduce_only=True, mid_price=mid)
        else:
            # Opening position: limit order (GTC, post-only) with mid price
            res = self.exchange.place_open_order(iid, side, sz, mid_price=mid, sym=sym)

        # ── Log full API response to diagnose silent rejections ──────────
        log.info(f"{sym} API response: {res}")

        if res.get("error"):
            log.error(f"{sym} order FAILED (network/exception): {res['error']}")
            self.risk.error_count += 1
            tg_send(f"❌ <b>{sym} copy failed</b>\n{res['error']}", cfg)
            return 0.0

        # Check for server-side rejection (status/code field)
        status = str(res.get("status", res.get("code", res.get("returnCode", "")))).upper()
        if status and status not in ("OK", "SUCCESS", "0", ""):
            log.error(f"{sym} order REJECTED by server — status={status} full={res}")
            tg_send(f"❌ <b>{sym} server rejected</b>\nStatus: {status}\n{res}", cfg)
            return 0.0

        self.risk.total_copies += 1
        fee = delta_usd * 0.0007   # estimated taker fee 0.07%

        # [NEW 3] Record to PnL history
        self.pnl.record(sym, side, delta_usd, fee, is_reduce)

        # Update in-memory position tracker
        try:
            size_f = float(sz)
            self._update_tracker(sym, side, size_f)
        except Exception:
            pass

        tg_send(
            f"{emoji} <b>Copy Trade</b>\n"
            f"Symbol: {sym}\n"
            f"Action: {direction} {sz}\n"
            f"Value:  ~${delta_usd:.1f}\n"
            f"Ratio:  {cfg['copy_ratio']*100:.0f}%",
            cfg
        )
        return fee

    def _close_all(self, positions_raw: list = None, mids: dict = None):
        cfg = self.CONFIG
        self.exchange.cancel_all()
        time.sleep(0.5)
        if mids is None:
            mids = self.info.get_mids() or {}
        if positions_raw is None:
            positions_raw, ok = self.info.get_positions(cfg["wallet_address"])
            if not ok:
                tg_send("⚠️ Could not fetch positions. Please close manually.", cfg)
                return

        closed = []
        for p in positions_raw:
            sym  = p.get("instrument", p.get("symbol", ""))
            size = float(p.get("size", 0))
            iid  = cfg["instrument_ids"].get(sym)
            mid  = mids.get(sym, 0)
            if not iid or size == 0 or not mid:
                continue
            side = "b" if size < 0 else "s"
            sz   = fmt_size(abs(size), sym, cfg)
            if float(sz) <= 0:
                continue
            res = self.exchange.place_market_order(iid, side, sz, reduce_only=True, mid_price=mid)
            if res.get("error"):
                tg_send(f"⚠️ Failed to close {sym}: {res['error']}\nClose manually!", cfg)
            else:
                closed.append(f"{sym}: {side.upper()} {sz} (~${abs(size)*mid:.1f})")
            time.sleep(0.3)

        msg = ("✅ <b>All closed:</b>\n" + "\n".join(f"• {c}" for c in closed)
               if closed else "ℹ️ No open positions.")
        tg_send(msg, cfg)

    # ── Telegram ──────────────────────────────────────────────────────────

    def _tg_poll(self):
        cfg     = self.CONFIG
        token   = cfg.get("telegram_token", "")
        chat_id = str(cfg.get("telegram_chat_id", ""))
        if not token or not chat_id:
            return
        offset = 0
        log.info("Telegram listener started")
        while not self._stop_flag.is_set():
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": 20},
                    timeout=25
                )
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    msg    = upd.get("message", {})
                    if str(msg.get("chat", {}).get("id", "")) != chat_id:
                        continue
                    self._tg_command(msg.get("text", "").strip().lower())
            except Exception as e:
                log.debug(f"TG poll: {e}")
                time.sleep(5)

    def _tg_command(self, text: str):
        cfg = self.CONFIG
        log.info(f"TG command: {text}")

        if text == "/stop":
            tg_send("🛑 Stopping bot...", cfg)
            self.exchange.cancel_all()
            self._stop_flag.set()

        elif text == "/pause":
            if self._pause_flag.is_set():
                tg_send("⚠️ Already paused. Send /resume.", cfg); return
            self._pause_flag.set()
            self.exchange.cancel_all()
            tg_send("⏸ <b>PAUSED</b> — send /resume to restart.", cfg)

        elif text == "/resume":
            if not self._pause_flag.is_set():
                tg_send("✅ Already running.", cfg); return
            self._pause_flag.clear()
            tg_send("▶️ <b>RESUMED</b>", cfg)

        elif text == "/restart":
            self._pause_flag.clear()
            self.risk.error_count = 0
            self._restart_flag.set()
            tg_send("🔄 Restarting...", cfg)

        elif text == "/close":
            tg_send("📉 Closing all positions...", cfg)
            self._close_all()

        elif text == "/status":
            mids       = self._last_mids or {}
            my_pos     = self._last_my_pos
            leader_pos = self._last_leader_pos
            unreal     = self._last_unreal
            today      = self.pnl.today_summary()
            total_exp  = self._total_exposure(my_pos, mids)
            lines = [
                "📊 <b>Copy Bot v1.3</b>",
                f"Status: {'⏸ PAUSED' if self._pause_flag.is_set() else ('✖ HALTED' if self.risk.halted else '● RUNNING')}",
                f"Leader: <code>{cfg['leader_address'][:16]}...</code>",
                f"Ratio: {cfg['copy_ratio']*100:.0f}%  |  Min: ${cfg['min_order_usd']}",
                f"Exposure: ${total_exp:.1f} / ${cfg['max_total_exposure_usd']}",
                f"Daily loss: ${self.risk.daily_loss_usd:.2f} / ${cfg['daily_loss_limit_usd']}",
                f"Unrealized: ${unreal:+.2f}",
                f"Today — {today['count']} trades, vol ${today['volume']:.1f}, fees ${today['fees']:.3f}",
                "",
                "📍 <b>Positions</b>",
            ]
            for sym in cfg["symbols"]:
                m   = my_pos.get(sym, 0.0)
                l   = leader_pos.get(sym, 0.0)
                mid = mids.get(sym, 0)
                side = "LONG" if m > 0 else ("SHORT" if m < 0 else "FLAT")
                lines.append(f"  {sym}: {side} ${abs(m)*mid:.1f}  |  leader: {l:+.4f}")
            tg_send("\n".join(lines), cfg)

        elif text == "/pnl":
            today   = self.pnl.today_summary()
            alltime = self.pnl.all_time_summary()
            recent  = self.pnl.recent_trades(5)
            lines = [
                "💰 <b>PnL Report</b>",
                f"<b>Today</b>",
                f"  Trades:  {today['count']}",
                f"  Volume:  ${today['volume']:,.1f}",
                f"  Fees:    ${today['fees']:.4f}",
            ]
            if today.get("by_sym"):
                for sym, d in today["by_sym"].items():
                    lines.append(f"  {sym}: {d['count']}× ${d['volume']:.1f}")
            lines += [
                "",
                f"<b>All Time</b>",
                f"  Trades:  {alltime['count']}",
                f"  Volume:  ${alltime['volume']:,.0f}",
                f"  Fees:    ${alltime['fees']:.3f}",
                "",
                f"<b>Recent Trades</b>",
            ]
            for t in recent:
                ts   = datetime.fromtimestamp(t["ts"]).strftime("%m/%d %H:%M")
                side = "BUY" if t["side"] == "b" else "SELL"
                lines.append(f"  {ts} {t['symbol']} {side} ${t['size_usd']:.1f}")
            tg_send("\n".join(lines), cfg)

        elif text == "/config":
            lines = [
                "⚙️ <b>Configuration</b>",
                f"Copy ratio:      {cfg['copy_ratio']*100:.0f}%",
                f"Min order:       ${cfg['min_order_usd']}",
                f"Sync interval:   {cfg['sync_interval']}s",
                f"Max total:       ${cfg['max_total_exposure_usd']}",
                f"Daily loss lim:  ${cfg['daily_loss_limit_usd']}",
                f"Unreal lim:      ${cfg['unrealized_loss_limit_usd']}",
                "",
                "Per-symbol max:",
            ] + [f"  {s}: ${cfg['symbol_max_usd'].get(s, cfg['_default_max'])}"
                 for s in cfg["symbols"]]
            tg_send("\n".join(lines), cfg)

        elif text == "/help":
            tg_send(
                "📋 <b>Commands</b>\n\n"
                "/status   — Positions & risk overview\n"
                "/pnl      — PnL report & trade history\n"
                "/config   — Current settings\n"
                "/pause    — Stop copying new trades\n"
                "/resume   — Resume copying\n"
                "/restart  — Reset errors, resume (no server needed)\n"
                "/close    — Close all positions\n"
                "/stop     — Stop the bot\n"
                "/help     — This message",
                cfg
            )

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self):
        cfg = self.CONFIG
        log.info("Copy Bot v1.3 started")

        my_raw, _ = self.info.get_positions(cfg["wallet_address"])
        my_pos    = parse_positions(my_raw)
        pos_lines = "\n".join(f"  {s}: {my_pos.get(s, 0):+.5f}" for s in cfg["symbols"])
        sym_lines = "\n".join(f"  {s}: ${cfg['symbol_max_usd'].get(s, cfg['_default_max'])}"
                              for s in cfg["symbols"])
        tg_send(
            f"📋 <b>Copy Bot Started v1.3</b>\n\n"
            f"Leader: <code>{cfg['leader_address']}</code>\n"
            f"Ratio: {cfg['copy_ratio']*100:.0f}%  |  Min: ${cfg['min_order_usd']}\n\n"
            f"Max per symbol:\n{sym_lines}\n"
            f"Max total: ${cfg['max_total_exposure_usd']}\n\n"
            f"Positions now:\n{pos_lines}\n\n"
            f"/status /pnl /config /pause /resume /restart /close /stop /help",
            cfg
        )

        threading.Thread(target=self._tg_poll, daemon=True).start()

        # Initial dashboard draw
        sys.stdout.write("\033[2J")   # clear screen once
        last_hourly = time.time()

        while not self._stop_flag.is_set():
            try:
                if self._restart_flag.is_set():
                    self._restart_flag.clear()
                    self.risk.halted      = False
                    self.risk.halt_reason = ""
                    self.risk.error_count = 0
                    tg_send("✅ Restarted successfully.", cfg)

                if self.risk.halted:
                    self.dash.refresh(
                        self._last_mids, self._last_my_pos,
                        self._last_leader_pos, self._last_unreal, False
                    )
                    time.sleep(cfg["sync_interval"])
                    continue

                ok, reason = self.risk.check_limits(cfg)
                if not ok:
                    self.risk.halt(reason, cfg)
                    continue

                if self._pause_flag.is_set():
                    self.dash.refresh(
                        self._last_mids, self._last_my_pos,
                        self._last_leader_pos, self._last_unreal,
                        self._last_api_ok
                    )
                    time.sleep(cfg["sync_interval"])
                    continue

                if self.risk.error_count >= 10:
                    self.risk.halt("10+ errors. Use /restart.", cfg)
                    continue

                success = self.sync_once()
                if success:
                    self.risk.error_count = 0
                    self.risk.successful_cycles += 1

                # Refresh dashboard after each cycle
                self.dash.refresh(
                    self._last_mids, self._last_my_pos,
                    self._last_leader_pos, self._last_unreal,
                    self._last_api_ok
                )

                if time.time() - last_hourly > 3600:
                    last_hourly = time.time()
                    self._tg_command("/status")

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Loop error: {e}", exc_info=True)
                self.risk.error_count += 1
                tg_send(f"⚠️ Error: {e}", cfg)

            time.sleep(cfg["sync_interval"])

        self.exchange.cancel_all()
        tg_send(
            f"🛑 <b>Bot stopped</b>\n"
            f"Copies: {self.risk.total_copies}\n"
            f"Daily loss: ${self.risk.daily_loss_usd:.2f}",
            cfg
        )
        log.info("Bot stopped.")


# ══════════════════════════════════════════════════════
#  [NEW 4]  AUTO-RESTART INSTALLER
# ══════════════════════════════════════════════════════
def install_autostart():
    """Create platform-appropriate auto-start service."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    system = platform.system()

    print()
    print(f"{Style.BRIGHT}── Auto-Restart Installer ──────────────────────────{Style.RESET_ALL}")

    if system == "Windows":
        # Task Scheduler XML
        xml_path = os.path.join(BASE_DIR, "copy_bot_task.xml")
        xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{python_path}</Command>
      <Arguments>"{script_path}"</Arguments>
      <WorkingDirectory>{BASE_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <RestartInterval>PT30S</RestartInterval>
    <RestartCount>999</RestartCount>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
</Task>"""
        with open(xml_path, "w", encoding="utf-16") as f:
            f.write(xml)
        print(f"\n✅ Task file created: {xml_path}")
        print("\nTo install, open Command Prompt as Administrator and run:")
        print(f'{Fore.CYAN}  schtasks /create /xml "{xml_path}" /tn "HotstuffCopyBot"{Fore.RESET}')
        print("\nTo remove:")
        print(f'{Fore.CYAN}  schtasks /delete /tn "HotstuffCopyBot" /f{Fore.RESET}')

    elif system in ("Linux", "Darwin"):
        service_name = "hotstuff-copy-bot"
        service_path = f"/etc/systemd/system/{service_name}.service" \
                       if system == "Linux" \
                       else os.path.expanduser(f"~/Library/LaunchAgents/com.{service_name}.plist")

        if system == "Linux":
            content = f"""[Unit]
Description=Hotstuff Copy Trading Bot
After=network.target

[Service]
Type=simple
ExecStart={python_path} {script_path}
WorkingDirectory={BASE_DIR}
Restart=always
RestartSec=10
StandardOutput=append:{LOG_FILE}
StandardError=append:{LOG_FILE}

[Install]
WantedBy=multi-user.target
"""
            tmp = os.path.join(BASE_DIR, f"{service_name}.service")
            with open(tmp, "w") as f:
                f.write(content)
            print(f"\n✅ Service file created: {tmp}")
            print("\nTo install (requires sudo):")
            print(f"{Fore.CYAN}  sudo cp {tmp} /etc/systemd/system/")
            print(f"  sudo systemctl daemon-reload")
            print(f"  sudo systemctl enable {service_name}")
            print(f"  sudo systemctl start {service_name}{Fore.RESET}")
            print("\nTo check status:")
            print(f"{Fore.CYAN}  sudo systemctl status {service_name}{Fore.RESET}")
            print("\nTo stop:")
            print(f"{Fore.CYAN}  sudo systemctl stop {service_name}{Fore.RESET}")

        else:  # macOS
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>         <string>com.{service_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
    </array>
    <key>WorkingDirectory</key> <string>{BASE_DIR}</string>
    <key>RunAtLoad</key>        <true/>
    <key>KeepAlive</key>        <true/>
    <key>StandardOutPath</key>  <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key><string>{LOG_FILE}</string>
</dict>
</plist>"""
            tmp = os.path.join(BASE_DIR, f"com.{service_name}.plist")
            with open(tmp, "w") as f:
                f.write(plist)
            print(f"\n✅ LaunchAgent created: {tmp}")
            print("\nTo install:")
            print(f"{Fore.CYAN}  cp {tmp} ~/Library/LaunchAgents/")
            print(f"  launchctl load ~/Library/LaunchAgents/com.{service_name}.plist{Fore.RESET}")
    else:
        print(f"⚠️  Unsupported platform: {system}")
    print()


# ══════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]

    # ── --install flag ───────────────────────────────────────────────────
    if "--install" in args:
        install_autostart()
        return

    # ── --setup flag or no .env yet → run wizard ─────────────────────────
    # Always load .env first (with correct path)
    if HAS_DOTENV and os.path.exists(ENV_FILE):
        load_dotenv(ENV_FILE, override=True)

    needs_setup = "--setup" in args or not os.path.exists(ENV_FILE)
    if needs_setup:
        run_setup_wizard()
        load_dotenv(ENV_FILE, override=True)

    # ── Load config ───────────────────────────────────────────────────────
    cfg = load_config()

    if not cfg["private_key"]:
        print(f"{Fore.RED}❌ PRIVATE_KEY not set. Run with --setup to configure.{Fore.RESET}")
        sys.exit(1)

    # ── Dashboard-only mode ───────────────────────────────────────────────
    if "--dashboard" in args:
        print("Dashboard-only mode — no trading.")
        bot = CopyTradingBot(cfg)
        while True:
            mids             = bot.info.get_mids()
            my_raw, my_ok    = bot.info.get_positions(cfg["wallet_address"])
            lead_raw, lead_ok = bot.info.get_positions(cfg["leader_address"])
            my_pos           = parse_positions(my_raw if my_ok else [])
            lead_pos         = parse_positions(lead_raw if lead_ok else [])
            unreal           = bot._unrealized_pnl(my_raw if my_ok else [], mids)
            bot.dash.refresh(mids, my_pos, lead_pos, unreal, my_ok and lead_ok)
            time.sleep(cfg["sync_interval"])
        return

    # ── Normal start ──────────────────────────────────────────────────────
    print(f"\n{Style.BRIGHT}{Fore.CYAN}")
    print("╔══════════════════════════════════════════════════════╗")
    print("║   🤖  Hotstuff Copy Trading Bot v1.3                 ║")
    print("║   Press Ctrl+C at any time to stop.                  ║")
    print("╚══════════════════════════════════════════════════════╝")
    print(Style.RESET_ALL)
    print(f"  Leader:  {cfg['leader_address']}")
    print(f"  Wallet:  {cfg['wallet_address']}")
    print(f"  Ratio:   {cfg['copy_ratio']*100:.0f}%")
    print(f"  Symbols: {', '.join(cfg['symbols'])}")
    print()

    confirm = input("  Start bot? [yes/no]: ").strip().lower()
    if confirm != "yes":
        print("  Cancelled.")
        return

    try:
        CopyTradingBot(cfg).run()
    except ValueError as e:
        print(f"\n{Fore.RED}❌ {e}{Fore.RESET}")
        print("  Run with --setup to reconfigure.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Bot stopped by user.{Fore.RESET}")


if __name__ == "__main__":
    main()
