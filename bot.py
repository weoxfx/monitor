import os
import sys
# Force unbuffered output for Render logs
sys.stdout = sys.stdout
os.environ['PYTHONUNBUFFERED'] = '1'
import asyncio
import aiohttp
import aiosqlite
import re
import time
import logging
from decimal import Decimal
from typing import List, Tuple, Optional
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from wallet_groups import setup_wallet_groups


# ===================================================== 
# LOGGING
# ===================================================== 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================================================== 
# CONFIG
# ===================================================== 
TOKEN = os.getenv("CTOKEN")
if not TOKEN:
    raise ValueError("❌ CTOKEN environment variable not set")

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
SOLSCAN_API_KEY = os.getenv("SOLSCAN_API_KEY", "")

if not ETHERSCAN_API_KEY:
    print("⚠️ ETHERSCAN_API_KEY not set - EVM networks will be disabled")
if not SOLSCAN_API_KEY:
    print("⚠️ SOLSCAN_API_KEY not set - Solana will be disabled")

# Use environment variable for DB path (Render persistent disk)
DB = os.getenv("DB_PATH", "/opt/render/project/.data/wallets.db")

# Create directory if it doesn't exist
os.makedirs(os.path.dirname(DB), exist_ok=True)

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "10"))
PRICE_CACHE_DURATION = 60
MAX_RETRIES = 3
REQUEST_TIMEOUT = 15

bot = Bot(TOKEN)
dp = Dispatcher(storage=MemoryStorage())
session: aiohttp.ClientSession | None = None
price_cache = {}
price_cache_lock = asyncio.Lock()

# ===================================================== 
# NETWORK REGISTRY
# ===================================================== 
ETHERSCAN_NETWORKS = {
    # ── Ethereum ──
    "ethereum": ("Ethereum Mainnet", 1, "ETH", False),
    "ethereum_sepolia": ("Ethereum Sepolia Testnet", 11155111,"ETH", True),
    "ethereum_holesky": ("Ethereum Holesky Testnet", 17000, "ETH", True),
    "ethereum_hoodi": ("Ethereum Hoodi Testnet", 560048, "ETH", True),
    # ── Polygon ──
    "polygon": ("Polygon Mainnet", 137, "MATIC", False),
    "polygon_amoy": ("Polygon Amoy Testnet", 80002, "MATIC", True),
    # ── Arbitrum ──
    "arbitrum": ("Arbitrum One Mainnet", 42161, "ETH", False),
    "arbitrum_nova": ("Arbitrum Nova Mainnet", 42170, "ETH", False),
    "arbitrum_sepolia": ("Arbitrum Sepolia Testnet", 421614, "ETH", True),
    # ── Linea ──
    "linea": ("Linea Mainnet", 59144, "ETH", False),
    "linea_sepolia": ("Linea Sepolia Testnet", 59141, "ETH", True),
    # ── Blast ──
    "blast": ("Blast Mainnet", 81457, "ETH", False),
    "blast_sepolia": ("Blast Sepolia Testnet", 168587773,"ETH", True),
    # ── BitTorrent Chain ──
    "bittorrent": ("BitTorrent Chain Mainnet", 199, "BTT", False),
    "bittorrent_testnet": ("BitTorrent Chain Testnet", 1029, "BTT", True),
    # ── Celo ──
    "celo": ("Celo Mainnet", 42220, "CELO", False),
    "celo_sepolia": ("Celo Sepolia Testnet", 11142220,"CELO", True),
    # ── Fraxtal ──
    "fraxtal": ("Fraxtal Mainnet", 252, "ETH", False),
    "fraxtal_hoodi": ("Fraxtal Hoodi Testnet", 2523, "ETH", True),
    # ── Gnosis ──
    "gnosis": ("Gnosis", 100, "XDAI", False),
    # ── Mantle ──
    "mantle": ("Mantle Mainnet", 5000, "MNT", False),
    "mantle_sepolia": ("Mantle Sepolia Testnet", 5003, "MNT", True),
    # ── Memecore ──
    "memecore": ("Memecore Mainnet", 4352, "MEME", False),
    "memecore_testnet": ("Memecore Testnet", 43521, "MEME", True),
    # ── Moonbeam / Moonriver ──
    "moonbeam": ("Moonbeam Mainnet", 1284, "GLMR", False),
    "moonriver": ("Moonriver Mainnet", 1285, "MOVR", False),
    "moonbase_alpha": ("Moonbase Alpha Testnet", 1287, "DEV", True),
    # ── opBNB ──
    "opbnb": ("opBNB Mainnet", 204, "BNB", False),
    "opbnb_testnet": ("opBNB Testnet", 5611, "BNB", True),
    # ── Scroll ──
    "scroll": ("Scroll Mainnet", 534352, "ETH", False),
    "scroll_sepolia": ("Scroll Sepolia Testnet", 534351, "ETH", True),
    # ── Taiko ──
    "taiko": ("Taiko Mainnet", 167000, "ETH", False),
    "taiko_hoodi": ("Taiko Hoodi Testnet", 167013, "ETH", True),
    # ── XDC ──
    "xdc": ("XDC Mainnet", 50, "XDC", False),
    "xdc_apothem": ("XDC Apothem Testnet", 51, "XDC", True),
    # ── ApeChain ──
    "apechain": ("ApeChain Mainnet", 33139, "APE", False),
    "apechain_curtis": ("ApeChain Curtis Testnet", 33111, "APE", True),
    # ── World ──
    "world": ("World Mainnet", 480, "WLD", False),
    "world_sepolia": ("World Sepolia Testnet", 4801, "WLD", True),
    # ── Sonic ──
    "sonic": ("Sonic Mainnet", 146, "S", False),
    "sonic_testnet": ("Sonic Testnet", 14601, "S", True),
    # ── Unichain ──
    "unichain": ("Unichain Mainnet", 130, "ETH", False),
    "unichain_sepolia": ("Unichain Sepolia Testnet", 1301, "ETH", True),
    # ── Abstract ──
    "abstract": ("Abstract Mainnet", 2741, "ETH", False),
    "abstract_sepolia": ("Abstract Sepolia Testnet", 11124, "ETH", True),
    # ── Berachain ──
    "berachain": ("Berachain Mainnet", 80094, "BERA", False),
    "berachain_bepolia": ("Berachain Bepolia Testnet", 80069, "BERA", True),
    # ── Swellchain ──
    "swellchain": ("Swellchain Mainnet", 1923, "ETH", False),
    "swellchain_testnet": ("Swellchain Testnet", 1924, "ETH", True),
    # ── Monad ──
    "monad": ("Monad Mainnet", 143, "MON", False),
    "monad_testnet": ("Monad Testnet", 10143, "MON", True),
    # ── HyperEVM ──
    "hyperevm": ("HyperEVM Mainnet", 999, "HYPE", False),
    # ── Katana ──
    "katana": ("Katana Mainnet", 747474, "ETH", False),
    "katana_bokuto": ("Katana Bokuto Testnet", 737373, "ETH", True),
    # ── Sei ──
    "sei": ("Sei Mainnet", 1329, "SEI", False),
    "sei_testnet": ("Sei Testnet", 1328, "SEI", True),
    # ── Stable ──
    "stable": ("Stable Mainnet", 988, "STABLE","False"),
    "stable_testnet": ("Stable Testnet", 2201, "STABLE",True),
    # ── Plasma ──
    "plasma": ("Plasma Mainnet", 9745, "PLS", False),
    "plasma_testnet": ("Plasma Testnet", 9746, "PLS", True),
}

STANDALONE_NETWORKS = {
    "tron": ("TRON", "TRX", "tronscan"),
    "ton": ("TON", "TON", "tonapi"),
    "solana": ("Solana", "SOL", "solscan"),
}

ALL_NETWORKS = {}
for key, val in ETHERSCAN_NETWORKS.items():
    ALL_NETWORKS[key] = val[0]
for key, val in STANDALONE_NETWORKS.items():
    ALL_NETWORKS[key] = val[0]

def get_native_symbol(net_key: str) -> str:
    if net_key in ETHERSCAN_NETWORKS:
        return ETHERSCAN_NETWORKS[net_key][2]
    if net_key in STANDALONE_NETWORKS:
        return STANDALONE_NETWORKS[net_key][1]
    return "?"

def is_testnet(net_key: str) -> bool:
    if net_key in ETHERSCAN_NETWORKS:
        return ETHERSCAN_NETWORKS[net_key][3] is True
    return False

def search_networks(query: str) -> List[str]:
    """Fuzzy search networks by query string. Returns list of matching keys."""
    q = query.lower().strip()
    if not q:
        return []
    
    results = []
    for key, display in ALL_NETWORKS.items():
        if q in key.replace("_", " ") or q in display.lower():
            results.append(key)
    
    if not results:
        words = q.split()
        for key, display in ALL_NETWORKS.items():
            searchable = (key.replace("_", " ") + " " + display.lower())
            if any(w in searchable for w in words):
                results.append(key)
    
    results.sort(key=lambda k: (is_testnet(k), ALL_NETWORKS[k]))
    return results[:8]

# ===================================================== 
# DATABASE
# ===================================================== 
async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wallets(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                network TEXT NOT NULL,
                address TEXT NOT NULL,
                label TEXT NOT NULL,
                last_tx TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, network, address)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_wallets ON wallets(user_id)
        """)
        await db.commit()
    logger.info("✅ Database initialized")

async def add_wallet(user_id: int, network: str, address: str, label: str, last_tx: str = ""):
    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute(
                "INSERT INTO wallets(user_id,network,address,label,last_tx) VALUES(?,?,?,?,?)",
                (user_id, network, address, label, last_tx)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            logger.warning(f"Duplicate wallet: {address} for user {user_id}")
            return False

async def delete_wallet(wallet_id: int, user_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("DELETE FROM wallets WHERE id=? AND user_id=?", (wallet_id, user_id))
        await db.commit()

async def get_wallets():
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT * FROM wallets")
        return await cur.fetchall()

async def get_user_wallets(user_id: int):
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        return await cur.fetchall()

async def update_last_tx(wallet_id: int, tx: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE wallets SET last_tx=? WHERE id=?", (tx, wallet_id))
        await db.commit()

# ===================================================== 
# FSM
# ===================================================== 
class AddWallet(StatesGroup):
    address = State()
    network_search = State()
    network_confirm = State()
    label = State()

class TxInfo(StatesGroup):
    waiting_input = State()

# ===================================================== 
# UTIL
# ===================================================== 
COINGECKO_IDS = {
    "TRX": "tron",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BUSD": "binance-usd",
    "DAI": "dai",
    "TON": "the-open-network",
    "BNB": "binancecoin",
    "ETH": "ethereum",
    "MATIC": "matic-network",
    "WETH": "weth",
    "WBNB": "wbnb",
    "CAKE": "pancakeswap-token",
    "SHIB": "shiba-inu",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "SOL": "solana",
    "BTT": "bittorrent",
    "CELO": "celo",
    "XDAI": "xdai",
    "MNT": "mantle",
    "GLMR": "moonbeam",
    "MOVR": "moonriver",
    "APE": "apecoin",
    "WLD": "worldcoin",
    "S": "sonic",
    "BERA": "berachain",
    "MON": "monad",
    "HYPE": "hyperliquid",
    "SEI": "sei",
    "XDC": "xdc-network",
    "PLS": "pulse",
}

async def get_price_usd(symbol: str) -> float:
    now = time.time()
    clean_symbol = symbol.replace(" 📥 IN", "").replace(" 📤 OUT", "").strip().upper()
    
    async with price_cache_lock:
        if clean_symbol in price_cache:
            price, timestamp = price_cache[clean_symbol]
            if now - timestamp < PRICE_CACHE_DURATION:
                return price
    
    coin_id = COINGECKO_IDS.get(clean_symbol, clean_symbol.lower())
    
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with session.get(url, timeout=timeout) as r:
            if r.status != 200:
                return 0
            js = await r.json()
            price = js.get(coin_id, {}).get("usd", 0)
            
            async with price_cache_lock:
                price_cache[clean_symbol] = (price, now)
            
            return price
    except Exception as e:
        logger.error(f"Price fetch error [{clean_symbol}]: {e}")
        return 0

def short(addr: str) -> str:
    if len(addr) <= 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"

def validate_address(address: str, net_key: str) -> bool:
    address = address.strip()
    
    if net_key == "tron":
        return address.startswith("T") and len(address) == 34
    elif net_key == "ton":
        return len(address) >= 48
    elif net_key == "solana":
        return 32 <= len(address) <= 44 and all(
            c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            for c in address
        )
    elif net_key in ETHERSCAN_NETWORKS:
        return address.startswith("0x") and len(address) == 42
    
    return False

async def fetch_with_retry(url: str, headers: Optional[dict] = None, max_retries: int = MAX_RETRIES) -> Optional[dict]:
    for attempt in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with session.get(url, timeout=timeout, headers=headers or {}) as r:
                if r.status == 200:
                    return await r.json()
                elif r.status == 429:
                    wait_time = (2 ** attempt) + (attempt * 0.5)
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                elif r.status == 404:
                    return None
                else:
                    logger.warning(f"HTTP {r.status} for {url[:80]}")
                    return None
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
        except Exception as e:
            logger.error(f"Fetch error: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(1)
    
    return None

def extract_tx_hash(text: str) -> Optional[str]:
    """Extract a transaction hash from raw text or a block explorer URL."""
    text = text.strip()
    
    evm_match = re.search(r'(0x[0-9a-fA-F]{64})', text)
    if evm_match:
        return evm_match.group(1)
    
    tron_match = re.search(r'\b([0-9a-fA-F]{64})\b', text)
    if tron_match:
        return tron_match.group(1)
    
    sol_match = re.search(r'\b([1-9A-HJ-NP-Za-km-z]{44,88})\b', text)
    if sol_match:
        candidate = sol_match.group(1)
        if len(candidate) >= 60:
            return candidate
    
    return None

def detect_tx_network(tx_hash: str) -> str:
    """Best-effort detection of which network a tx hash belongs to."""
    if tx_hash.startswith("0x") and len(tx_hash) == 66:
        return "evm"
    if len(tx_hash) == 64 and not tx_hash.startswith("0x"):
        return "tron_or_evm_no_prefix"
    if len(tx_hash) >= 60:
        return "solana"
    return "unknown"

# ===================================================== 
# TX INFO - MULTI-NETWORK LOOKUP
# ===================================================== 
async def lookup_tx_evm(tx_hash: str, net_key: str) -> Optional[dict]:
    """Look up an EVM tx via etherscan unified API."""
    if not ETHERSCAN_API_KEY or net_key not in ETHERSCAN_NETWORKS:
        return None
    
    chain_id = ETHERSCAN_NETWORKS[net_key][1]
    url = (
        f"https://api.etherscan.io/v2/api"
        f"?chainId={chain_id}"
        f"&module=transaction"
        f"&action=gettransactionreceipt"
        f"&txhash={tx_hash}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    
    js = await fetch_with_retry(url)
    if js and js.get("status") == "1" and js.get("result"):
        return js["result"]
    
    return None

async def lookup_tx_tron(tx_hash: str) -> Optional[dict]:
    url = f"https://apilist.tronscanapi.com/api/transaction/{tx_hash}"
    return await fetch_with_retry(url)

async def lookup_tx_ton(tx_hash: str) -> Optional[dict]:
    url = f"https://tonapi.io/v2/blockchain/transactions/{tx_hash}"
    return await fetch_with_retry(url)

async def lookup_tx_solana(tx_hash: str) -> Optional[dict]:
    if not SOLSCAN_API_KEY:
        return None
    
    url = f"https://public-api.solscan.io/transaction/{tx_hash}"
    headers = {"token": SOLSCAN_API_KEY}
    return await fetch_with_retry(url, headers=headers)

def format_evm_receipt(receipt: dict, net_key: str) -> str:
    """Format etherscan transaction receipt into readable text."""
    display = ETHERSCAN_NETWORKS[net_key][0] if net_key in ETHERSCAN_NETWORKS else net_key
    native = get_native_symbol(net_key)
    
    status_val = int(receipt.get("status", "0"), 16)
    status = "✅ Success" if status_val == 1 else "❌ Failed"
    
    block = int(receipt.get("blockNumber", "0"), 16)
    gas_used = int(receipt.get("gasUsed", "0"), 16)
    gas_price_raw = int(receipt.get("effectiveGasPrice", "0"), 16)
    gas_price_gwei = gas_price_raw / 1e9
    fee_wei = gas_used * gas_price_raw
    fee_native = fee_wei / 1e18
    
    from_addr = receipt.get("from", "N/A")
    to_addr = receipt.get("to", "N/A") or "Contract Creation"
    tx_hash = receipt.get("transactionHash", "N/A")
    
    logs = receipt.get("logs", [])
    
    text = (
        f"🔍 Transaction Details\n"
        f"{'─' * 36}\n"
        f"🌐 Network: {display}\n"
        f"📌 Status: {status}\n"
        f"🔗 TX Hash: {short(tx_hash)}\n"
        f"📦 Block: #{block:,}\n"
        f"📤 From: {short(from_addr)}\n"
        f"📥 To: {short(to_addr)}\n"
        f"⛽ Gas Used: {gas_used:,}\n"
        f"💲 Gas Price: {gas_price_gwei:.2f} Gwei\n"
        f"💵 Fee: {fee_native:.8f} {native}\n"
    )
    
    if logs:
        text += f"\n📋 Events ({len(logs)}):\n"
        for i, log in enumerate(logs[:3]):
            topics = log.get("topics", [])
            if topics:
                text += f" • Event topic: {short(topics[0])}\n"
        if len(logs) > 3:
            text += f" ... and {len(logs) - 3} more events\n"
    
    return text

def format_tron_tx(data: dict) -> str:
    tx_hash = data.get("hash", "N/A")
    confirmed = data.get("confirmed", False)
    status = "✅ Confirmed" if confirmed else "⏳ Pending"
    
    block = data.get("blockNumber", "N/A")
    timestamp = data.get("timestamp", 0)
    from_addr = data.get("fromAddress", "N/A")
    to_addr = data.get("toAddress", "N/A")
    amount = Decimal(data.get("amount", 0)) / Decimal(1_000_000)
    token_name = data.get("tokenName", "TRX")
    
    text = (
        f"🔍 TRON Transaction Details\n"
        f"{'─' * 36}\n"
        f"📌 Status: {status}\n"
        f"🔗 TX Hash: {short(tx_hash)}\n"
        f"📦 Block: {block}\n"
        f"📤 From: {short(from_addr)}\n"
        f"📥 To: {short(to_addr)}\n"
        f"💰 Token: {token_name}\n"
        f"📊 Amount: {amount}\n"
    )
    
    return text

def format_solana_tx(data: dict) -> str:
    signature = data.get("txhash", data.get("signature", "N/A"))
    status_val = data.get("status", -1)
    status = "✅ Success" if status_val == 1 else ("❌ Failed" if status_val == 0 else "⏳ Unknown")
    
    slot = data.get("slot", "N/A")
    fee = data.get("fee", 0)
    fee_sol = fee / 1e9
    
    signers = data.get("signers", [])
    signer_str = short(signers[0]) if signers else "N/A"
    
    text = (
        f"🔍 Solana Transaction Details\n"
        f"{'─' * 36}\n"
        f"📌 Status: {status}\n"
        f"🔗 Signature: {short(signature)}\n"
        f"📦 Slot: {slot}\n"
        f"📤 Signer: {signer_str}\n"
        f"⛽ Fee: {fee_sol:.9f} SOL\n"
    )
    
    token_transfers = data.get("tokenTransfers", [])
    if token_transfers:
        text += f"\n🪙 Token Transfers ({len(token_transfers)}):\n"
        for t in token_transfers[:4]:
            amt = t.get("amount", 0)
            sym = t.get("symbol", "?")
            text += f" • {amt} {sym}\n"
    
    return text

async def handle_tx_lookup(tx_hash: str) -> str:
    """Try to find and format a transaction across all supported networks."""
    detected = detect_tx_network(tx_hash)
    
    if detected == "solana" and SOLSCAN_API_KEY:
        data = await lookup_tx_solana(tx_hash)
        if data and data.get("txhash"):
            return format_solana_tx(data)
    
    if detected == "tron_or_evm_no_prefix":
        data = await lookup_tx_tron(tx_hash)
        if data and data.get("hash"):
            return format_tron_tx(data)
        
        tx_hash_0x = "0x" + tx_hash
        detected = "evm"
        tx_hash = tx_hash_0x
    
    if detected == "evm" and ETHERSCAN_API_KEY:
        mainnet_keys = [k for k in ETHERSCAN_NETWORKS if not is_testnet(k)]
        testnet_keys = [k for k in ETHERSCAN_NETWORKS if is_testnet(k)]
        
        priority = [
            "ethereum", "polygon", "arbitrum", "blast", "scroll", 
            "linea", "opbnb", "sonic", "berachain", "base",
        ]
        
        ordered = []
        for p in priority:
            if p in mainnet_keys:
                ordered.append(p)
                mainnet_keys.remove(p)
        
        ordered.extend(mainnet_keys)
        ordered.extend(testnet_keys)
        
        for net_key in ordered:
            receipt = await lookup_tx_evm(tx_hash, net_key)
            if receipt:
                return format_evm_receipt(receipt, net_key)
    
    if len(tx_hash) >= 60:
        data = await lookup_tx_ton(tx_hash)
        if data and data.get("hash"):
            return (
                f"🔍 TON Transaction Found\n"
                f"{'─' * 36}\n"
                f"🔗 Hash: {short(data.get('hash', ''))}\n"
                f"📦 Block: {data.get('block_ref', {}).get('seqno', 'N/A')}\n"
            )
    
    return (
        "❌ Transaction not found\n\n"
        "Could not locate this transaction on any supported network.\n\n"
        "Make sure:\n"
        "• The hash or link is correct\n"
        "• The transaction has been confirmed\n"
        "• The network is supported"
    )

# ===================================================== 
# GET LATEST TX
# ===================================================== 
async def get_latest_tx_etherscan(address: str, net_key: str) -> str:
    """Unified etherscan v2 API for any EVM chain."""
    if not ETHERSCAN_API_KEY or net_key not in ETHERSCAN_NETWORKS:
        return ""
    
    chain_id = ETHERSCAN_NETWORKS[net_key][1]
    url = (
        f"https://api.etherscan.io/v2/api"
        f"?chainId={chain_id}"
        f"&module=account"
        f"&action=txlist"
        f"&address={address}"
        f"&startblock=0"
        f"&endblock=99999999"
        f"&page=1"
        f"&offset=1"
        f"&sort=desc"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    
    js = await fetch_with_retry(url)
    if js and js.get("status") == "1" and js.get("result"):
        return js["result"][0].get("hash", "")
    
    return ""

async def get_latest_tx_tron(address: str) -> str:
    url = f"https://apilist.tronscanapi.com/api/transaction?address={address}&limit=1"
    js = await fetch_with_retry(url)
    
    if js and js.get("data"):
        return js["data"][0].get("hash", "")
    
    return ""

async def get_latest_tx_ton(address: str) -> str:
    url = f"https://tonapi.io/v2/blockchain/accounts/{address}/transactions?limit=1"
    js = await fetch_with_retry(url)
    
    if js and js.get("transactions"):
        return js["transactions"][0].get("hash", "")
    
    return ""

async def get_latest_tx_solana(address: str) -> str:
    if not SOLSCAN_API_KEY:
        return ""
    
    url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=1"
    headers = {"token": SOLSCAN_API_KEY}
    js = await fetch_with_retry(url, headers=headers)
    
    if js and isinstance(js, list) and len(js) > 0:
        return js[0].get("txhash", "")
    
    if js and isinstance(js, dict) and js.get("data"):
        data = js["data"]
        if isinstance(data, list) and data:
            return data[0].get("txhash", "")
    
    return ""

async def get_latest_tx(address: str, net_key: str) -> str:
    try:
        if net_key == "tron":
            return await get_latest_tx_tron(address)
        elif net_key == "ton":
            return await get_latest_tx_ton(address)
        elif net_key == "solana":
            return await get_latest_tx_solana(address)
        elif net_key in ETHERSCAN_NETWORKS:
            return await get_latest_tx_etherscan(address, net_key)
    except Exception as e:
        logger.error(f"Error getting latest tx [{net_key}]: {e}")
    
    return ""

# ===================================================== 
# INLINE MODE - JUST COPY ADDRESS
# ===================================================== 
@dp.inline_query()
async def inline_address_lookup(query: InlineQuery):
    """
    Usage:
    @yourbot myETH → Shows "myETH" wallet, click to paste address
    @yourbot → Shows all wallets
    """
    text = query.query.strip()
    user_id = query.from_user.id
    
    wallets = await get_user_wallets(user_id)
    
    if not wallets:
        results = [
            InlineQueryResultArticle(
                id="no_wallets",
                title="❌ No wallets added",
                description="Add wallets first with /addaddress",
                input_message_content=InputTextMessageContent(
                    message_text="Use /addaddress to add wallets for monitoring"
                )
            )
        ]
        await query.answer(results, cache_time=5, is_personal=True)
        return
    
    # Filter by search query
    if text:
        filtered = [w for w in wallets if text.lower() in w[4].lower()]
    else:
        filtered = wallets[:20]
    
    if not filtered and text:
        results = [
            InlineQueryResultArticle(
                id="not_found",
                title=f"🔍 No wallet found: '{text}'",
                description="Try another label",
                input_message_content=InputTextMessageContent(
                    message_text=f"No wallet with label '{text}'"
                )
            )
        ]
    else:
        results = []
        
        for wallet in filtered:
            wallet_id, _, network, address, label, _, _ = wallet
            display_network = ALL_NETWORKS.get(network, network)
            native = get_native_symbol(network)
            
            # IMPORTANT: input_message_content just has the ADDRESS
            # When user clicks, it replaces their input with ONLY the address
            results.append(
                InlineQueryResultArticle(
                    id=str(wallet_id),
                    title=f"📍 {label}",
                    description=f"{display_network} • {native} • {short(address)}",
                    thumbnail_url=f"https://api.dicebear.com/7.x/identicon/svg?seed={address}",
                    input_message_content=InputTextMessageContent(
                        message_text=address  # JUST THE ADDRESS
                    )
                )
            )
    
    await query.answer(results, cache_time=10, is_personal=True)

# ===================================================== 
# COMMANDS
# ===================================================== 
@dp.message(Command("start"))
async def cmd_start(m: Message):
    await m.answer(
        "👋 Multi-Chain Wallet Monitor\n\n"
        "📡 Supports 60+ networks:\n"
        "• 50+ EVM chains via unified Etherscan API\n"
        "• TRON (TRX + TRC-20 tokens)\n"
        "• TON (native TON)\n"
        "• Solana (SOL + SPL tokens)\n\n"
        "Commands:\n"
        "/addaddress — Monitor a wallet\n"
        "/addresses — View & manage wallets\n"
        "/txinfo — Look up any transaction\n"
        "/stats — Statistics\n"
        "/info — Bot info & links\n\n"
        "⚡ **Inline Mode:**\n"
        "Type @" + (await bot.me()).username + " {label} in ANY chat\n"
        "to quickly paste wallet addresses!"
    )

@dp.message(Command("info"))
async def cmd_info(m: Message):
    total_networks = len(ETHERSCAN_NETWORKS) + len(STANDALONE_NETWORKS)
    mainnet_count = sum(1 for k in ETHERSCAN_NETWORKS if not is_testnet(k)) + len(STANDALONE_NETWORKS)
    testnet_count = sum(1 for k in ETHERSCAN_NETWORKS if is_testnet(k))
    
    bot_username = (await bot.me()).username
    
    await m.answer(
        "ℹ️ CryptoAlert Monitor\n"
        f"{'─' * 34}\n\n"
        f"📡 Networks supported: {total_networks}\n"
        f" • Mainnets: {mainnet_count}\n"
        f" • Testnets: {testnet_count}\n\n"
        f"🔧 Features:\n"
        f" • Real-time wallet monitoring\n"
        f" • Multi-token alerts (native + tokens)\n"
        f" • Transaction lookup (/txinfo)\n"
        f" • USD value via CoinGecko\n"
        f" • Inline mode for quick address sharing\n\n"
        f"⚡ **Inline Mode:**\n"
        f"Type @{bot_username} {{label}} in any chat\n"
        f"Click result to paste address!\n\n"
        f"📢 Channel: @CryptoAlertUpdates\n"
        f"👨‍💻 Developer: @Gamenter\n\n"
        f"💡 How to use:\n"
        f" /addaddress — Add a wallet to monitor\n"
        f" /txinfo — Paste a TX hash or link\n"
        f" /addresses — Manage your wallets\n\n"
        f"🔗 Stay tuned for updates!"
    )

@dp.message(Command("addaddress"))
async def cmd_add_address(m: Message, state: FSMContext):
    await state.set_state(AddWallet.address)
    await m.answer("📝 Send the wallet address:")

@dp.message(AddWallet.address)
async def fsm_get_address(m: Message, state: FSMContext):
    address = m.text.strip()
    
    if len(address) < 20 or len(address) > 100:
        await m.answer("❌ Invalid address format. Please try again:")
        return
    
    await state.update_data(address=address)
    await state.set_state(AddWallet.network_search)
    await m.answer(
        "🌐 Which network? Type the name to search:\n"
        "(e.g. ethereum, polygon, arbitrum, solana, tron, ton, blast…)"
    )

@dp.message(AddWallet.network_search)
async def fsm_search_network(m: Message, state: FSMContext):
    query = m.text.strip()
    matches = search_networks(query)
    
    if not matches:
        await m.answer(
            "🔍 No networks found matching that query.\n\n"
            "Try names like: ethereum, polygon, arbitrum, solana, tron, ton, blast, scroll, linea…"
        )
        return
    
    kb_rows = []
    row = []
    
    for key in matches:
        display = ALL_NETWORKS[key]
        label = display
        
        if is_testnet(key):
            label += " (Testnet)"
        
        row.append(InlineKeyboardButton(text=label, callback_data=f"netsel_{key}"))
        
        if len(row) == 2:
            kb_rows.append(row)
            row = []
    
    if row:
        kb_rows.append(row)
    
    kb_rows.append([InlineKeyboardButton(text="🔄 Search again", callback_data="netsearch_again")])
    
    await m.answer(
        f"🔍 Found {len(matches)} result(s). Pick one:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )

@dp.callback_query(F.data == "netsearch_again")
async def cb_network_search_again(c: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    
    if current in (AddWallet.network_search, AddWallet.network_confirm):
        await state.set_state(AddWallet.network_search)
        await c.message.answer("🌐 Type the network name again:")
        await c.answer()

@dp.callback_query(F.data.startswith("netsel_"))
async def cb_network_selected(c: CallbackQuery, state: FSMContext):
    net_key = c.data.split("_", 1)[1]
    data = await state.get_data()
    address = data.get("address", "")
    
    if not validate_address(address, net_key):
        display = ALL_NETWORKS.get(net_key, net_key)
        await c.message.answer(
            f"❌ Invalid address for {display}.\n\n"
            f"Expected format:\n" +
            (f" • 0x... (42 chars)" if net_key in ETHERSCAN_NETWORKS else
             f" • Starts with T (34 chars)" if net_key == "tron" else
             f" • 48+ chars" if net_key == "ton" else
             f" • Base58 (32-44 chars)") +
            "\n\nPlease start over with /addaddress"
        )
        await state.clear()
        await c.answer()
        return
    
    await state.update_data(network=net_key)
    await state.set_state(AddWallet.label)
    await c.message.answer("🏷 Enter a label for this wallet (max 50 chars):")
    await c.answer()

@dp.message(AddWallet.label)
async def fsm_get_label(m: Message, state: FSMContext):
    data = await state.get_data()
    label = m.text.strip()[:50]
    
    if not label:
        await m.answer("❌ Label cannot be empty.")
        return
    
    net_key = data["network"]
    address = data["address"]
    display = ALL_NETWORKS.get(net_key, net_key)
    
    status_msg = await m.answer(f"⏳ Initializing wallet on {display}…\n🔍 Fetching latest transaction…")
    
    try:
        last_tx = await get_latest_tx(address, net_key)
        
        if not last_tx:
            await status_msg.edit_text(
                "⚠️ No transactions found yet.\n\n"
                "This is fine if the wallet is new.\n"
                "The bot will alert on ALL future transactions.\n\n"
                "Adding wallet now…"
            )
            await asyncio.sleep(1.5)
        
        success = await add_wallet(m.from_user.id, net_key, address, label, last_tx)
        
        if not success:
            await status_msg.edit_text("❌ This wallet is already being monitored.")
            await state.clear()
            return
        
        await state.clear()
        
        status_text = (
            f"✅ Wallet added!\n\n"
            f"🏷 Label: {label}\n"
            f"🌐 Network: {display}\n"
            f"📍 Address: {short(address)}\n"
            f"💎 Native: {get_native_symbol(net_key)}\n\n"
        )
        
        status_text += (
            "✅ Baseline set — monitoring new transactions\n"
            if last_tx else
            "⚠️ No baseline — will alert on ALL transactions\n"
        )
        
        bot_username = (await bot.me()).username
        status_text += (
            f"\n🔔 You'll receive alerts for incoming payments!\n\n"
            f"⚡ **Quick Access:**\n"
            f"Type @{bot_username} {label} in any chat to paste this address!"
        )
        
        await status_msg.edit_text(status_text)
        logger.info(f"✅ User {m.from_user.id} added [{net_key}] wallet: {short(address)}")
    
    except Exception as e:
        logger.error(f"Error adding wallet: {e}", exc_info=True)
        await status_msg.edit_text("❌ Error adding wallet. Please try again with /addaddress")
        await state.clear()

@dp.message(Command("addresses"))
async def cmd_list_wallets(m: Message):
    rows = await get_user_wallets(m.from_user.id)
    
    if not rows:
        await m.answer("📭 No wallets added.\n\nUse /addaddress to add one.")
        return
    
    text = "📋 Your wallets:\n\n"
    kb = []
    
    for r in rows:
        wallet_id, _, net_key, address, label, _, _ = r
        display = ALL_NETWORKS.get(net_key, net_key)
        native = get_native_symbol(net_key)
        
        text += f"🔹 {label}\n {display} | {native} | {short(address)}\n\n"
        
        kb.append([InlineKeyboardButton(
            text=f"❌ Delete {label}",
            callback_data=f"del_{wallet_id}"
        )])
    
    bot_username = (await bot.me()).username
    text += f"\n⚡ Type @{bot_username} {{label}} in any chat to quickly paste addresses!"
    
    await m.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("del_"))
async def cb_delete_wallet(c: CallbackQuery):
    wallet_id = int(c.data.split("_")[1])
    await delete_wallet(wallet_id, c.from_user.id)
    await c.message.edit_text("🗑 Wallet deleted.")
    await c.answer("Deleted")
    logger.info(f"User {c.from_user.id} deleted wallet {wallet_id}")

@dp.message(Command("txinfo"))
async def cmd_txinfo(m: Message, state: FSMContext):
    await state.set_state(TxInfo.waiting_input)
    await m.answer(
        "🔍 Paste a transaction hash or explorer link.\n\n"
        "Supported formats:\n"
        "• EVM hash: 0x…\n"
        "• TRON hash: 64 hex chars\n"
        "• Solana signature: base58 string\n"
        "• Or a full explorer URL (e.g. etherscan, tronscan, solscan)"
    )

@dp.message(TxInfo.waiting_input)
async def fsm_txinfo_input(m: Message, state: FSMContext):
    text = m.text.strip()
    await state.clear()
    
    tx_hash = extract_tx_hash(text)
    
    if not tx_hash:
        await m.answer("❌ Couldn't extract a transaction hash from that input. Try pasting the hash directly.")
        return
    
    loading = await m.answer("⏳ Looking up transaction…")
    result = await handle_tx_lookup(tx_hash)
    await loading.edit_text(result)

@dp.message(Command("stats"))
async def cmd_stats(m: Message):
    all_wallets = await get_wallets()
    user_wallets = await get_user_wallets(m.from_user.id)
    total_nets = len(ETHERSCAN_NETWORKS) + len(STANDALONE_NETWORKS)
    
    await m.answer(
        f"📊 Statistics\n\n"
        f"Your wallets: {len(user_wallets)}\n"
        f"Total monitored: {len(all_wallets)}\n"
        f"Supported networks: {total_nets}\n"
        f"Poll interval: {POLL_SECONDS}s"
    )

# ===================================================== 
# NETWORK CHECKERS
# ===================================================== 
async def check_evm_unified(address: str, last_tx: str, net_key: str) -> List[Tuple[str, str, float]]:
    """Check native + token transfers for ANY EVM chain via etherscan v2 unified API."""
    if not ETHERSCAN_API_KEY or net_key not in ETHERSCAN_NETWORKS:
        return []
    
    chain_id = ETHERSCAN_NETWORKS[net_key][1]
    native_symbol = ETHERSCAN_NETWORKS[net_key][2]
    
    new_txs = []
    
    # Native txs
    native_url = (
        f"https://api.etherscan.io/v2/api"
        f"?chainId={chain_id}"
        f"&module=account"
        f"&action=txlist"
        f"&address={address}"
        f"&startblock=0"
        f"&endblock=99999999"
        f"&page=1"
        f"&offset=20"
        f"&sort=desc"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    
    native_js = await fetch_with_retry(native_url)
    
    if native_js and native_js.get("status") == "1":
        for tx in native_js.get("result", []):
            if tx["hash"] == last_tx:
                break
            
            if tx.get("to", "").lower() == address.lower():
                value = int(tx.get("value", 0)) / 1e18
                if value > 0:
                    new_txs.append((tx["hash"], native_symbol, value))
    
    # Token txs (ERC-20)
    token_url = (
        f"https://api.etherscan.io/v2/api"
        f"?chainId={chain_id}"
        f"&module=account"
        f"&action=tokentx"
        f"&address={address}"
        f"&page=1"
        f"&offset=20"
        f"&sort=desc"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    
    token_js = await fetch_with_retry(token_url)
    
    if token_js and token_js.get("status") == "1":
        for tx in token_js.get("result", []):
            if tx["hash"] == last_tx:
                break
            
            if tx.get("to", "").lower() == address.lower():
                decimals = int(tx.get("tokenDecimal", 18))
                value = int(tx.get("value", 0)) / (10 ** decimals)
                symbol = tx.get("tokenSymbol", "TOKEN")
                
                if value > 0:
                    new_txs.append((tx["hash"], symbol, value))
    
    return new_txs

async def check_tron(address: str, last_tx: str) -> List[Tuple[str, str, float]]:
    url = f"https://apilist.tronscanapi.com/api/transaction?address={address}&limit=20"
    js = await fetch_with_retry(url)
    
    if not js:
        return []
    
    new_txs = []
    
    for tx in js.get("data", []):
        if tx["hash"] == last_tx:
            break
        
        if tx.get("toAddress", "").lower() != address.lower():
            continue
        
        token_name = tx.get("tokenName", "TRX")
        
        if "trigger_info" in tx and "parameter" in tx.get("trigger_info", {}):
            amount_raw = tx.get("amount", 0)
            decimals = tx.get("tokenInfo", {}).get("tokenDecimal", 6)
            amount = Decimal(amount_raw) / Decimal(10 ** decimals)
        else:
            amount = Decimal(tx.get("amount", 0)) / Decimal(1_000_000)
        
        if amount > 0:
            new_txs.append((tx["hash"], token_name, float(amount)))
    
    return new_txs

async def check_ton(address: str, last_tx: str) -> List[Tuple[str, str, float]]:
    url = f"https://tonapi.io/v2/blockchain/accounts/{address}/transactions?limit=20"
    js = await fetch_with_retry(url)
    
    if not js:
        return []
    
    new_txs = []
    
    for tx in js.get("transactions", []):
        if tx["hash"] == last_tx:
            break
        
        in_msg = tx.get("in_msg", {})
        if not in_msg:
            continue
        
        value = int(in_msg.get("value", 0)) / 1e9
        
        if value > 0:
            new_txs.append((tx["hash"], "TON", value))
    
    return new_txs

async def check_solana(address: str, last_tx: str) -> List[Tuple[str, str, float]]:
    if not SOLSCAN_API_KEY:
        return []
    
    url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=20"
    headers = {"token": SOLSCAN_API_KEY}
    js = await fetch_with_retry(url, headers=headers)
    
    if not js:
        return []
    
    txs = js if isinstance(js, list) else js.get("data", [])
    
    if not txs:
        return []
    
    new_txs = []
    
    for tx in txs:
        sig = tx.get("txhash", "")
        
        if sig == last_tx:
            break
        
        token_transfers = tx.get("tokenTransfers", [])
        
        for t in token_transfers:
            if t.get("destination", "").lower() == address.lower():
                amt = t.get("amount", 0)
                sym = t.get("symbol", "SOL")
                
                if amt > 0:
                    new_txs.append((sig, sym, float(amt)))
        
        if not token_transfers:
            status = tx.get("status", -1)
            if status == 1:
                new_txs.append((sig, "SOL", 0.0))
    
    return new_txs

# ===================================================== 
# MONITOR LOOP
# ===================================================== 
async def check_single_wallet(wallet_row):
    wallet_id, user_id, net_key, address, label, last_tx, _ = wallet_row
    
    try:
        if net_key == "tron":
            new_txs = await check_tron(address, last_tx)
        elif net_key == "ton":
            new_txs = await check_ton(address, last_tx)
        elif net_key == "solana":
            new_txs = await check_solana(address, last_tx)
        elif net_key in ETHERSCAN_NETWORKS:
            new_txs = await check_evm_unified(address, last_tx, net_key)
        else:
            logger.warning(f"Unknown network key: {net_key}")
            return
        
        if new_txs:
            display = ALL_NETWORKS.get(net_key, net_key)
            logger.info(f"🔔 Found {len(new_txs)} new tx(s) for wallet {wallet_id} ({label}) on {display}")
            
            for tx_hash, coin, amount in reversed(new_txs):
                try:
                    price = await get_price_usd(coin)
                    usd = round(amount * price, 2) if price else 0
                    
                    if amount > 0:
                        amount_str = f"{amount:,.8f}"
                        usd_str = f"${usd:,.2f}"
                    else:
                        amount_str = "Check TX for details"
                        usd_str = "—"
                    
                    msg = (
                        f"💸 Payment Received!\n\n"
                        f"🏷 Wallet: {label}\n"
                        f"🌐 Network: {display}\n"
                        f"💰 Token: {coin}\n"
                        f"📊 Amount: {amount_str}\n"
                        f"💵 Value: {usd_str}\n\n"
                        f"📍 {short(address)}\n"
                        f"🔗 TX: {short(tx_hash)}"
                    )
                    
                    await bot.send_message(user_id, msg)
                    logger.info(f"✅ Alert sent to user {user_id}: {amount_str} {coin}")
                    
                    await asyncio.sleep(0.5)
                
                except Exception as e:
                    logger.error(f"Error sending notification: {e}")
            
            latest_tx_hash = new_txs[0][0]
            await update_last_tx(wallet_id, latest_tx_hash)
            logger.info(f"💾 Updated last_tx for wallet {wallet_id}")
    
    except Exception as e:
        logger.error(f"Error checking wallet {wallet_id} ({net_key}/{label}): {e}")

async def monitor_loop():
    await asyncio.sleep(10)
    logger.info("🔄 Multi-chain monitor started")
    
    while True:
        try:
            wallets = await get_wallets()
            
            if wallets:
                logger.info(f"🔍 Checking {len(wallets)} wallet(s)…")
                tasks = [check_single_wallet(w) for w in wallets]
                await asyncio.gather(*tasks, return_exceptions=True)
            
            await asyncio.sleep(POLL_SECONDS)
        
        except Exception as e:
            logger.error(f"Monitor loop error: {e}", exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

# ===================================================== 
# MAIN
# ===================================================== 
async def main():
    global session
    
    total_nets = len(ETHERSCAN_NETWORKS) + len(STANDALONE_NETWORKS)
    mainnet_count = sum(1 for k in ETHERSCAN_NETWORKS if not is_testnet(k)) + len(STANDALONE_NETWORKS)
    
    logger.info("🚀 Starting Multi-Chain Wallet Monitor…")
    logger.info("=" * 60)
    logger.info(f"📡 Total networks: {total_nets} ({mainnet_count} mainnets)")
    logger.info(" EVM (unified etherscan): %d chains", len(ETHERSCAN_NETWORKS))
    logger.info(" TRON: TRX + TRC-20")
    logger.info(" TON: Native TON")
    logger.info(" SOL: SOL + SPL tokens")
    logger.info("=" * 60)
    
    await init_db()
    
    connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
    session = aiohttp.ClientSession(connector=connector)
    logger.info("✅ HTTP session created")
    setup_wallet_groups(dp, DB, ETHERSCAN_API_KEY, SOLSCAN_API_KEY, session, ALL_NETWORKS)
    monitor_task = asyncio.create_task(monitor_loop())
    logger.info("✅ Monitor loop started")
    
    try:
        logger.info("✅ Bot polling started\n")
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down…")
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        await session.close()
        await bot.session.close()
        logger.info("✅ Cleanup complete")

if __name__ == "__main__":
    asyncio.run(main())
