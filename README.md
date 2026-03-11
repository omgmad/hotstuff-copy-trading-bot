# 🤖 Hotstuff Copy Trading Bot

> Automated copy trading bot for [Hotstuff.trade](https://app.hotstuff.trade/join/hot) — mirrors top trader positions in real time with risk management, Telegram alerts, and a live terminal dashboard.

```
╔══════════════════════════════════════════════════════════════╗
║  Status: ● RUNNING   API: OK   Ratio: 100%   Sync: 5s       ║
║  Leader: 0x01234567890...   Copies today: 26         ║
║  HYPE-PERP   Mine: -0.86   Leader: -0.86   SHORT ▼          ║
╚══════════════════════════════════════════════════════════════╝
```

---

## How It Works

```
  Leader opens HYPE-PERP SHORT $500
          │
          ▼
  Bot detects position change (every 5s)
          │
          ▼
  Bot opens HYPE-PERP SHORT (scaled to your max size)
          │
          ▼
  Leader closes → Bot closes automatically ✅

```
![Demo](copy_bot_demo.gif)
---

## Features

| Feature | Description |
|---|---|
| ✅ Real-time copy | Polls leader wallet every 5s for position changes |
| ✅ Position scaling | Mirrors trades proportionally using COPY_RATIO |
| ✅ Multi-symbol | BTC, ETH, SOL, HYPE, and more |
| ✅ Risk limits | Daily loss limit, max exposure, unrealized stop-loss |
| ✅ Telegram alerts | Trade notifications and remote control commands |
| ✅ Live dashboard | Real-time terminal UI with positions, PnL, risk bars |
| ✅ Auto-restart | systemd service for 24/7 VPS operation |
| ✅ Setup wizard | Interactive first-time configuration (`--setup`) |

---

## Requirements

- Python 3.10+
- A [Hotstuff.trade](https://app.hotstuff.trade/join/hot) account with funds deposited
- An **API Wallet (Agent)** created in Hotstuff settings
- Ubuntu / Debian Linux (or any OS with Python 3.10+)

---

## Installation

### Step 1 — Clone the repo

```bash
git clone https://github.com/omgmad/hotstuff-copy-trading-bot
cd hotstuff-copy-trading-bot
```

### Step 2 — Create a Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install dependencies

```bash
pip install requests msgpack eth-account eth-utils python-dotenv colorama
```

### Step 4 — Create an API Wallet on Hotstuff

1. Go to [app.hotstuff.trade/api](https://app.hotstuff.trade/api)
2. Click **"Create API Wallet"**
3. Give it a name (e.g. `copybot`)
4. **Copy the Private Key — it is shown only once!**
5. Copy the Agent Wallet Address
6. Click **"Authorize API Wallet"** and sign with MetaMask

> ⚠️ The private key is shown **only once**. Save it somewhere safe before authorizing.

### Step 5 — Run the setup wizard

```bash
python hotstuff_copy_bot.py --setup
```

The wizard will ask for:

- Agent wallet private key
- Leader wallet address (the trader you want to copy)
- Copy ratio (1.0 = mirror exact size, 0.5 = half size)
- Symbols to trade (e.g. `HYPE-PERP,SOL-PERP`)
- Max position sizes and risk limits
- Telegram bot token and chat ID (optional)

Configuration is saved to `.env` automatically.

### Step 6 — Start the bot

```bash
set -a && source .env && set +a
python hotstuff_copy_bot.py
```

---

## Configuration

The `.env` file contains all settings:

```env
# Agent wallet (created on Hotstuff → API page)
PRIVATE_KEY=0x_your_agent_private_key
WALLET_ADDRESS=0x_your_agent_wallet_address

# Trader to copy
LEADER_ADDRESS=0x_leader_wallet_address

# Trading settings
COPY_RATIO=1.0          # 1.0 = mirror exact %, 0.5 = half size
SYMBOLS=HYPE-PERP,SOL-PERP,BTC-PERP

# Per-symbol max position (USD)
MAX_HYPE=30
MAX_SOL=50
MAX_BTC=100
MAX_ETH=100
MAX_TOTAL=100           # Total across all symbols

# Risk limits
DAILY_LOSS_LIMIT=5      # Halt bot if daily loss exceeds this (USD)
UNREALIZED_LOSS_LIMIT=10  # Force-close if unrealized loss exceeds this (USD)

# Sync interval
SYNC_INTERVAL=5         # Poll interval in seconds

# Telegram (optional)
TELEGRAM_TOKEN=1234567890:ABCdef...
TELEGRAM_CHAT_ID=123456789
```

---

## Telegram Commands

Once the bot is running, control it via Telegram:

| Command | Action |
|---|---|
| `/status` | Show current positions, PnL, and risk |
| `/pnl` | Show today's PnL summary |
| `/pause` | Stop copying new trades |
| `/resume` | Resume copying |
| `/close` | Close all open positions (market order) |
| `/restart` | Restart the bot |
| `/stop` | Stop bot completely |
| `/help` | Show all commands |

---

## Platform Setup

### 🍎 macOS

```bash
# 1. Install Python (if not already installed)
brew install python3
# Or download from https://www.python.org/downloads/

# 2. Clone repo
git clone https://github.com/omgmad/hotstuff-copy-trading-bot
cd hotstuff-copy-trading-bot

# 3. Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install requests msgpack eth-account eth-utils python-dotenv colorama

# 4. Run setup wizard
python hotstuff_copy_bot.py --setup

# 5. Start bot
set -a && source .env && set +a
python hotstuff_copy_bot.py
```

To run 24/7 on Mac, use **screen** (same as Linux):
```bash
screen -S copybot
source venv/bin/activate
set -a && source .env && set +a
python hotstuff_copy_bot.py
# Ctrl+A, D to detach
```

---

### 🪟 Windows

```powershell
# 1. Install Python from https://www.python.org/downloads/
#    ✅ Check "Add Python to PATH" during installation

# 2. Open Command Prompt or PowerShell and clone repo
git clone https://github.com/omgmad/hotstuff-copy-trading-bot
cd hotstuff-copy-trading-bot

# 3. Create venv and install
python -m venv venv
venv\Scripts\activate
pip install requests msgpack eth-account eth-utils python-dotenv colorama

# 4. Run setup wizard
python hotstuff_copy_bot.py --setup

# 5. Start bot
python hotstuff_copy_bot.py
```

> ⚠️ On Windows, `.env` is loaded automatically — no `set -a` needed.

To run 24/7 on Windows, install as a **Task Scheduler** service:
```powershell
python hotstuff_copy_bot.py --install
```
This creates a Windows Task that starts the bot automatically on login.

---

## Run 24/7 with Auto-Restart (Linux systemd)

To install the bot as a systemd service that starts automatically on boot:

```bash
set -a && source .env && set +a
python hotstuff_copy_bot.py --install
```

Then manage it with:

```bash
sudo systemctl start  hotstuff-copy-bot
sudo systemctl stop   hotstuff-copy-bot
sudo systemctl status hotstuff-copy-bot
sudo journalctl -u hotstuff-copy-bot -f   # live logs
```

---

## Run 24/7 with screen (simple alternative)

```bash
screen -S copybot
source venv/bin/activate
set -a && source .env && set +a
python hotstuff_copy_bot.py

# Detach — bot keeps running in background
# Press Ctrl+A, then D

# Reattach later
screen -r copybot
```

---

## Shortcut alias (optional)

Add this to `~/.bashrc` to start the bot with a single command:

```bash
echo 'alias hotbot="cd ~/hotstuff-copy-trading-bot && source venv/bin/activate && set -a && source .env && set +a && python hotstuff_copy_bot.py"' >> ~/.bashrc
source ~/.bashrc
```

Then just run:

```bash
hotbot
```

---

## VPS Setup (Ubuntu from scratch)

```bash
# 1. Update system
sudo apt update && sudo apt upgrade -y

# 2. Install Python and screen
sudo apt install python3 python3-pip python3-venv screen -y

# 3. Clone repo
git clone https://github.com/omgmad/hotstuff-copy-trading-bot
cd hotstuff-copy-trading-bot

# 4. Create venv and install
python3 -m venv venv
source venv/bin/activate
pip install requests msgpack eth-account eth-utils python-dotenv colorama

# 5. Run setup wizard
python hotstuff_copy_bot.py --setup

# 6. Start bot
set -a && source .env && set +a
python hotstuff_copy_bot.py
```

---

## File Structure

```
hotstuff-copy-trading-bot/
├── hotstuff_copy_bot.py   # Main bot
├── .env                   # Your config (auto-created by --setup)
├── copy_bot.log           # Log file
├── pnl_history.json       # PnL history (auto-created)
└── venv/                  # Python virtual environment
```

---

## Risk Management

```
Daily loss limit hit  ──────────►  HALT + close all positions + Telegram alert
Unrealized loss > limit  ────────►  Force-close all positions
Total exposure > MAX_TOTAL  ─────►  Block new trades
Per-symbol > MAX_SYMBOL  ────────►  Block that symbol
```

---

## ⚠️ Choosing a Leader Wallet

Not all wallets are suitable to copy. Avoid the following:

| Wallet Type | Why to Avoid |
|---|---|
| HFT (High-Frequency Trading) bots | Open/close hundreds of trades per minute — fees will destroy your account |
| Maker bots | Place and cancel limit orders constantly — not real directional trades |
| Taker bots | Scalp tiny price movements — impossible to copy profitably at retail speed |

**✅ Good leader wallets to follow:**
- Traders who open **fewer trades** but with **consistent profit**
- Positions held for **minutes to hours**, not milliseconds
- Clear directional trades (LONG / SHORT) with reasonable size

> 💡 Tip: Before following a wallet, check their trade history on Hotstuff. Look for traders with a low trade count but high win rate — these are the most copyable.

---

## ⚠️ Disclaimer

This bot trades real money on mainnet. Copy trading carries significant financial risk — past performance of copied traders does not guarantee future results. Start with small amounts, monitor closely, and never risk more than you can afford to lose. The authors are not responsible for any trading losses.

---

## Links

🔴 **Trade on Hotstuff** → [Hotstuff.trade](https://app.hotstuff.trade/join/hot)

🐦 **Twitter/X** → [@0mgm4d](https://x.com/0mgm4d)

💻 **GitHub** → [github.com/omgmad/hotstuff-copy-trading-bot](https://github.com/omgmad/hotstuff-copy-trading-bot)

---

*⭐ Star the repo if this helps you!*
