"""
Wallet Grouping Feature - Render Compatible Version
Groups wallets by their labels (e.g., "Trust Wallet BNB", "Trust Wallet ETH" → "Trust Wallet")
"""

import asyncio
import aiosqlite
import aiohttp
from typing import List, Dict, Tuple, Optional
from decimal import Decimal
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import io
from PIL import Image, ImageDraw, ImageFont
import logging

logger = logging.getLogger(__name__)

# ===================================================== 
# WALLET NAME DATABASE
# ===================================================== 
KNOWN_WALLET_NAMES = [
    # Popular wallets
    "Trust Wallet", "MetaMask", "Coinbase Wallet", "Ledger", "Trezor",
    "Exodus", "Phantom", "Rainbow", "SafePal", "Argent", "Zerion", "Rabby",
    
    # Exchange wallets
    "Binance", "Coinbase", "Kraken", "Kucoin", "Bybit", "OKX",
    "Huobi", "Gate.io", "Bitfinex", "Gemini",
    
    # Hardware wallets
    "Ledger Nano", "Trezor One", "Trezor Model T", "KeepKey",
    "BitBox", "CoolWallet",
    
    # Other categories
    "Main", "Trading", "Savings", "Cold Storage", "Hot Wallet",
    "DeFi", "NFT", "Gaming", "Staking", "Airdrop",
    "Personal", "Business", "Family", "Friends",
]

KNOWN_WALLET_NAMES.sort(key=len, reverse=True)

# ===================================================== 
# HELPER FUNCTIONS
# ===================================================== 

def extract_wallet_group(label: str) -> Optional[str]:
    """Extract wallet group name from label"""
    label_lower = label.lower()
    
    for wallet_name in KNOWN_WALLET_NAMES:
        if wallet_name.lower() in label_lower:
            return wallet_name
    
    patterns = [
        r'^([A-Za-z0-9]+)\s+Wallet',
        r'^([A-Za-z0-9]+)\s+Exchange',
        r'^([A-Za-z0-9]+)\s+\w+$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, label)
        if match:
            return match.group(1)
    
    return None

def group_wallets_by_name(wallets: List[Tuple]) -> Dict[str, List[Tuple]]:
    """Group wallets by extracted wallet name"""
    groups = {}
    ungrouped = []
    
    for wallet in wallets:
        label = wallet[4]
        group_name = extract_wallet_group(label)
        
        if group_name:
            if group_name not in groups:
                groups[group_name] = []
            groups[group_name].append(wallet)
        else:
            ungrouped.append(wallet)
    
    if ungrouped:
        groups["_ungrouped"] = ungrouped
    
    return groups

async def get_wallet_balance(address: str, network: str, 
                            etherscan_key: str, solscan_key: str,
                            session: aiohttp.ClientSession,
                            etherscan_networks: Dict,
                            get_native_symbol: callable) -> Dict:
    """Get balance for a wallet"""
    
    try:
        if network in etherscan_networks:
            if not etherscan_key:
                return {"native_amount": 0, "usd_value": 0, "token_symbol": get_native_symbol(network)}
            
            chain_id = etherscan_networks[network][1]
            native_symbol = etherscan_networks[network][2]
            
            url = f"https://api.etherscan.io/v2/api?chainId={chain_id}&module=account&action=balance&address={address}&apikey={etherscan_key}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    if js.get("status") == "1":
                        balance = int(js["result"]) / 1e18
                        price = await get_simple_price(native_symbol, session)
                        
                        return {
                            "native_amount": balance,
                            "usd_value": balance * price,
                            "token_symbol": native_symbol
                        }
        
        elif network == "tron":
            url = f"https://apilist.tronscanapi.com/api/account?address={address}"
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    balance = js.get("balance", 0) / 1_000_000
                    price = await get_simple_price("TRX", session)
                    
                    return {
                        "native_amount": balance,
                        "usd_value": balance * price,
                        "token_symbol": "TRX"
                    }
        
        elif network == "solana":
            if not solscan_key:
                return {"native_amount": 0, "usd_value": 0, "token_symbol": "SOL"}
            
            url = f"https://public-api.solscan.io/account/{address}"
            headers = {"token": solscan_key}
            
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    js = await r.json()
                    balance = js.get("lamports", 0) / 1e9
                    price = await get_simple_price("SOL", session)
                    
                    return {
                        "native_amount": balance,
                        "usd_value": balance * price,
                        "token_symbol": "SOL"
                    }
    
    except Exception as e:
        logger.error(f"Error fetching balance for {network}/{address}: {e}")
    
    return {"native_amount": 0, "usd_value": 0, "token_symbol": get_native_symbol(network)}

async def get_simple_price(symbol: str, session: aiohttp.ClientSession) -> float:
    """Get simple USD price from CoinGecko"""
    coin_ids = {
        "ETH": "ethereum", "TRX": "tron", "SOL": "solana",
        "BNB": "binancecoin", "MATIC": "matic-network",
        "TON": "the-open-network", "CELO": "celo",
        "XDAI": "xdai", "MNT": "mantle", "GLMR": "moonbeam",
        "MOVR": "moonriver", "APE": "apecoin", "WLD": "worldcoin",
        "S": "sonic", "BERA": "berachain", "MON": "monad",
        "HYPE": "hyperliquid", "SEI": "sei", "XDC": "xdc-network",
        "PLS": "pulse", "BTT": "bittorrent",
    }
    
    coin_id = coin_ids.get(symbol.upper(), symbol.lower())
    
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status == 200:
                js = await r.json()
                return js.get(coin_id, {}).get("usd", 0)
    except:
        pass
    
    return 0

def short(addr: str) -> str:
    if len(addr) <= 10:
        return addr
    return f"{addr[:6]}...{addr[-4:]}"

# ===================================================== 
# IMAGE GENERATION
# ===================================================== 

async def generate_wallet_image(wallet_name: str, total_usd: float, holdings: List[Dict]) -> io.BytesIO:
    """Generate a visual card for the wallet group"""
    
    width = 800
    base_height = 400
    item_height = 60
    height = base_height + (len(holdings) * item_height)
    
    img = Image.new('RGB', (width, height), color='#1a1a2e')
    draw = ImageDraw.Draw(img)
    
    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
        item_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except:
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        item_font = ImageFont.load_default()
        small_font = ImageFont.load_default()
    
    # Gradient background
    for i in range(height):
        r = int(26 + (i / height) * 20)
        g = int(26 + (i / height) * 30)
        b = int(46 + (i / height) * 40)
        draw.rectangle([(0, i), (width, i + 1)], fill=(r, g, b))
    
    # Header
    draw.rectangle([(20, 20), (width - 20, 180)], fill='#16213e', outline='#0f3460', width=3)
    draw.text((40, 40), wallet_name, fill='#ffffff', font=title_font)
    draw.text((40, 100), "Total Value", fill='#94a3b8', font=small_font)
    draw.text((40, 125), f"${total_usd:,.2f}", fill='#4ade80', font=subtitle_font)
    
    # Holdings
    y_offset = 220
    
    if holdings:
        draw.text((40, y_offset), "Holdings", fill='#94a3b8', font=small_font)
        y_offset += 40
        
        for holding in holdings:
            draw.rectangle([(40, y_offset), (width - 40, y_offset + 50)], fill='#16213e', outline='#0f3460', width=2)
            draw.text((60, y_offset + 5), holding['network'], fill='#e2e8f0', font=item_font)
            draw.text((60, y_offset + 30), f"{holding['amount']:.6f} {holding['symbol']}", fill='#94a3b8', font=small_font)
            
            usd_text = f"${holding['usd']:,.2f}"
            bbox = draw.textbbox((0, 0), usd_text, font=item_font)
            text_width = bbox[2] - bbox[0]
            draw.text((width - 60 - text_width, y_offset + 15), usd_text, fill='#4ade80', font=item_font)
            
            y_offset += 60
    
    draw.text((40, height - 40), "CryptoAlert Monitor", fill='#64748b', font=small_font)
    
    bio = io.BytesIO()
    bio.name = f'{wallet_name.replace(" ", "_")}.png'
    img.save(bio, 'PNG')
    bio.seek(0)
    
    return bio

# ===================================================== 
# ROUTER & HANDLERS
# ===================================================== 

router = Router()

# Global storage for dependencies
_config = {}

def setup_wallet_groups(dp, db_path: str, etherscan_key: str, 
                       solscan_key: str, session: aiohttp.ClientSession,
                       all_networks: Dict, etherscan_networks: Dict,
                       get_native_symbol_func: callable):
    """Setup wallet groups feature"""
    
    _config['db_path'] = db_path
    _config['etherscan_key'] = etherscan_key
    _config['solscan_key'] = solscan_key
    _config['session'] = session
    _config['all_networks'] = all_networks
    _config['etherscan_networks'] = etherscan_networks
    _config['get_native_symbol'] = get_native_symbol_func
    
    dp.include_router(router)
    logger.info("✅ Wallet Groups feature enabled")

@router.message(Command("wallet"))
async def cmd_wallet_groups(m: Message):
    """Show wallet groups"""
    user_id = m.from_user.id
    
    async with aiosqlite.connect(_config['db_path']) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    if not wallets:
        await m.answer(
            "📭 No wallets added yet.\n\n"
            "Use /addaddress to add wallets for monitoring.\n\n"
            "💡 **Tip:** Name your wallets like:\n"
            "• Trust Wallet BNB\n"
            "• Trust Wallet ETH\n"
            "• MetaMask Polygon\n\n"
            "The bot will automatically group them!"
        )
        return
    
    groups = group_wallets_by_name(wallets)
    keyboard = []
    
    sorted_groups = sorted(
        [(k, v) for k, v in groups.items() if k != "_ungrouped"],
        key=lambda x: x[0]
    )
    
    if "_ungrouped" in groups:
        sorted_groups.append(("_ungrouped", groups["_ungrouped"]))
    
    for group_name, group_wallets in sorted_groups:
        if group_name == "_ungrouped":
            display_name = "🔹 Other Wallets"
        else:
            display_name = f"💼 {group_name}"
        
        keyboard.append([InlineKeyboardButton(
            text=f"{display_name} ({len(group_wallets)})",
            callback_data=f"wgroup_{group_name}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="📊 View All Wallets", callback_data="wgroup_all")])
    
    text = (
        "💼 **Your Wallet Groups**\n\n"
        f"Total wallets: {len(wallets)}\n"
        f"Groups: {len(groups)}\n\n"
        "Select a group to view details:"
    )
    
    await m.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode="Markdown")

@router.callback_query(F.data.startswith("wgroup_"))
async def cb_wallet_group_details(c: CallbackQuery):
    """Show detailed view of a wallet group"""
    group_name = c.data.replace("wgroup_", "")
    user_id = c.from_user.id
    
    async with aiosqlite.connect(_config['db_path']) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    if group_name == "all":
        selected_wallets = wallets
        display_name = "All Wallets"
    else:
        groups = group_wallets_by_name(wallets)
        selected_wallets = groups.get(group_name, [])
        display_name = group_name if group_name != "_ungrouped" else "Other Wallets"
    
    if not selected_wallets:
        await c.answer("No wallets in this group", show_alert=True)
        return
    
    loading_msg = await c.message.edit_text(
        f"⏳ Loading {display_name}...\n"
        f"Fetching balances for {len(selected_wallets)} wallet(s)..."
    )
    
    total_usd = 0
    holdings_list = []
    wallet_details = []
    
    for wallet in selected_wallets:
        wallet_id, _, network, address, label, _, _ = wallet
        
        balance = await get_wallet_balance(
            address, network,
            _config['etherscan_key'],
            _config['solscan_key'],
            _config['session'],
            _config['etherscan_networks'],
            _config['get_native_symbol']
        )
        
        native_amount = balance['native_amount']
        usd_value = balance['usd_value']
        token_symbol = balance['token_symbol']
        
        total_usd += usd_value
        
        network_display = _config['all_networks'].get(network, network.title())
        
        holdings_list.append({
            'network': network_display,
            'amount': native_amount,
            'symbol': token_symbol,
            'usd': usd_value
        })
        
        wallet_details.append({
            'label': label,
            'network': network_display,
            'address': address,
            'amount': native_amount,
            'symbol': token_symbol,
            'usd': usd_value
        })
    
    # Generate and send image
    try:
        image_bio = await generate_wallet_image(display_name, total_usd, holdings_list)
        await c.message.answer_photo(
            photo=image_bio,
            caption=f"💼 **{display_name}**\n\n💰 Total Value: **${total_usd:,.2f}**\n📊 Networks: {len(holdings_list)}"
        )
    except Exception as e:
        logger.error(f"Error generating image: {e}")
    
    # Build detailed text
    text = f"💼 **{display_name}**\n{'━' * 36}\n\n"
    text += f"💰 **Total Value:** ${total_usd:,.2f}\n"
    text += f"📊 **Networks:** {len(holdings_list)}\n\n**Holdings:**\n\n"
    
    for detail in wallet_details:
        text += f"🔹 **{detail['label']}**\n"
        text += f"   🌐 {detail['network']}\n"
        text += f"   📍 `{short(detail['address'])}`\n"
        text += f"   💎 {detail['amount']:.6f} {detail['symbol']}\n"
        text += f"   💵 ${detail['usd']:,.2f}\n\n"
    
    keyboard = [
        [InlineKeyboardButton(text="🔙 Back to Groups", callback_data="wgroup_back")],
        [InlineKeyboardButton(text="🔄 Refresh", callback_data=f"wgroup_{group_name}")],
    ]
    
    await loading_msg.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    await c.answer()

@router.callback_query(F.data == "wgroup_back")
async def cb_back_to_groups(c: CallbackQuery):
    """Go back to wallet groups list"""
    user_id = c.from_user.id
    
    async with aiosqlite.connect(_config['db_path']) as db:
        cur = await db.execute("SELECT * FROM wallets WHERE user_id=?", (user_id,))
        wallets = await cur.fetchall()
    
    groups = group_wallets_by_name(wallets)
    keyboard = []
    
    sorted_groups = sorted(
        [(k, v) for k, v in groups.items() if k != "_ungrouped"],
        key=lambda x: x[0]
    )
    
    if "_ungrouped" in groups:
        sorted_groups.append(("_ungrouped", groups["_ungrouped"]))
    
    for group_name, group_wallets in sorted_groups:
        if group_name == "_ungrouped":
            display_name = "🔹 Other Wallets"
        else:
            display_name = f"💼 {group_name}"
        
        keyboard.append([InlineKeyboardButton(
            text=f"{display_name} ({len(group_wallets)})",
            callback_data=f"wgroup_{group_name}"
        )])
    
    keyboard.append([InlineKeyboardButton(text="📊 View All Wallets", callback_data="wgroup_all")])
    
    text = (
        "💼 **Your Wallet Groups**\n\n"
        f"Total wallets: {len(wallets)}\n"
        f"Groups: {len(groups)}\n\n"
        "Select a group to view details:"
    )
    
    await c.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="Markdown"
    )
    await c.answer()
