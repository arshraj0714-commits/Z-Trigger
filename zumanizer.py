#!/usr/bin/env python3
"""
███████╗██╗   ██╗███╗   ███╗ █████╗ ███╗   ██╗██╗███████╗██████╗ ███████╗██████╗ 
╚══███╔╝██║   ██║████╗ ████║██╔══██╗████╗  ██║██║╚══███╔╝██╔══██╗██╔════╝██╔══██╗
  ███╔╝ ██║   ██║██╔████╔██║███████║██╔██╗ ██║██║  ███╔╝ ██████╔╝█████╗  ██████╔╝
 ███╔╝  ██║   ██║██║╚██╔╝██║██╔══██║██║╚██╗██║██║ ███╔╝  ██╔══██╗██╔══╝  ██╔══██╗
███████╗╚██████╔╝██║ ╚═╝ ██║██║  ██║██║ ╚████║██║███████╗██║  ██║███████╗██║  ██║
╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝

                         Z U M A N I Z E R
                         Built By Arsh

Exact implementation of madsnod/Discord-Token-Humanizer with advanced features:
- WebSocket live session for avatar & profile updates
- Proxy rotation with bad proxy detection
- Multi‑threading with dynamic thread count
- Automatic rate‑limit handling
- Unique names/avatars per token
"""

import time
import base64
import hashlib
import inspect
import re
import os
import json
import uuid
import random
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from typing import Optional, Dict, Any, List
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, quote

import primp
from colorama import Fore, Style, init
from PIL import Image
import asyncio
import websockets
from python_socks.async_.asyncio import Proxy

init()

_async_loop = asyncio.new_event_loop()
_async_loop_thread = threading.Thread(target=_async_loop.run_forever, daemon=True)
_async_loop_thread.start()

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
INPUT_DIR = SCRIPT_DIR / "input"
AVATARS_DIR = SCRIPT_DIR / "avatar"
BANNERS_DIR = SCRIPT_DIR / "banners"

TOKENS_FILE = INPUT_DIR / "tokens.txt"
PROXIES_FILE = INPUT_DIR / "proxies.txt"
BIOS_FILE = DATA_DIR / "bios.txt"
NAMES_FILE = DATA_DIR / "names.txt"
PRONOUNS_FILE = DATA_DIR / "pronouns.txt"
SUCCESS_FILE = INPUT_DIR / "success.txt"
FAILED_FILE = INPUT_DIR / "failed.txt"

def load_config():
    default_config = {
        "max_threads": 3,
        "avatar_dimension": 256,
        "max_avatar_cache": 100,
        "update_display_name": True,
        "update_bio": True,
        "update_pronouns": True,
        "update_avatar": True,
        "update_hypesquad": True,
        "RetryLimit": 1
    }
    
    config_path = SCRIPT_DIR / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
                for key, val in data.items():
                    default_config[key] = val
        except Exception as e:
            print(f"{Fore.YELLOW}[WARN] Could not load config.json ({e}). Using defaults.{Style.RESET_ALL}")
    
    return default_config

config = load_config()

MAX_THREADS = config.get("max_threads", 3)
AVATAR_DIMENSION = config.get("avatar_dimension", 256)
MAX_AVATAR_CACHE = config.get("max_avatar_cache", 100)
UPDATE_DISPLAY_NAME = config.get("update_display_name", True)
UPDATE_BIO = config.get("update_bio", True)
UPDATE_PRONOUNS = config.get("update_pronouns", True)
UPDATE_AVATAR = config.get("update_avatar", True)
UPDATE_HYPESQUAD = config.get("update_hypesquad", True)
RETRY_LIMIT = config.get("RetryLimit", 1)

HYPESQUAD_HOUSES = {
    1: "Bravery",
    2: "Brilliance",
    3: "Balance"
}

DISCORD_API = "https://discord.com/api/v9"
DISCORD_GATEWAY = "wss://gateway.discord.gg/?v=9&encoding=json"
FALLBACK_BUILD_NUMBER = 519006
DISCORD_CLIENT_VERSION = "1.0.9171"
ELECTRON_VERSION = "34.5.1"
CHROME_VERSION_ELECTRON = "132"
DEFAULT_USER_AGENT = (
    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) discord/{DISCORD_CLIENT_VERSION} "
    f"Chrome/{CHROME_VERSION_ELECTRON}.0.0.0 Electron/{ELECTRON_VERSION} Safari/537.36"
)

def fetch_build_number() -> int:
    try:
        resp = primp.Client(verify=False).get("https://discord.com/login", timeout=10)
        if resp.status_code != 200:
            return FALLBACK_BUILD_NUMBER
        
        asset_urls = re.findall(r'/assets/([a-zA-Z0-9_-]+)\.js', resp.text)
        if not asset_urls:
            return FALLBACK_BUILD_NUMBER
        
        for asset_hash in reversed(asset_urls):
            try:
                js_resp = primp.Client(verify=False).get(
                    f"https://discord.com/assets/{asset_hash}.js",
                    timeout=10
                )
                if js_resp.status_code != 200:
                    continue
                
                match = re.search(r'buildNumber["\s:,]+(\d{4,7})', js_resp.text)
                if match:
                    return int(match.group(1))
            except Exception:
                continue
        
        return FALLBACK_BUILD_NUMBER
    except Exception:
        return FALLBACK_BUILD_NUMBER

BUILD_NUMBER = fetch_build_number()

def _random_uuid() -> str:
    return f"{random.randint(10000000, 99999999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(100000000000, 999999999999)}"

def generate_super_properties(
    launch_id: str, signature: str, heartbeat_id: str, native_build: int
) -> str:
    return base64.b64encode(json.dumps({
        "os": "Windows",
        "browser": "Discord Client",
        "release_channel": "stable",
        "client_version": DISCORD_CLIENT_VERSION,
        "os_version": "10.0.26100",
        "os_arch": "x64",
        "app_arch": "x64",
        "system_locale": "en-US",
        "has_client_mods": False,
        "browser_user_agent": DEFAULT_USER_AGENT,
        "browser_version": ELECTRON_VERSION,
        "client_build_number": BUILD_NUMBER,
        "native_build_number": native_build,
        "client_event_source": None,
        "client_launch_id": launch_id,
        "launch_signature": signature,
        "client_heartbeat_session_id": heartbeat_id,
    }, separators=(",", ":")).encode()).decode()

stats = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "start_time": time.time()
}
stats_lock = threading.Lock()
file_lock = threading.Lock()
print_lock = threading.Lock()

class ProxyManager:
    
    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self.lock = threading.Lock()
        self.index = 0
        self.bad_proxies = set()
        self.in_use = set()
    
    def get_proxy(self) -> Optional[str]:
        with self.lock:
            if not self.proxies:
                return None

            attempts = 0
            while attempts < len(self.proxies):
                proxy = self.proxies[self.index]
                self.index = (self.index + 1) % len(self.proxies)
                
                if proxy in self.bad_proxies:
                    attempts += 1
                    continue
                
                if proxy in self.in_use:
                    attempts += 1
                    continue
                
                self.in_use.add(proxy)
                return proxy

            for _ in range(len(self.proxies)):
                proxy = self.proxies[self.index]
                self.index = (self.index + 1) % len(self.proxies)
                if proxy not in self.bad_proxies:
                    return proxy 
            
            return None
    
    def release_proxy(self, proxy: str):
        with self.lock:
            if proxy:
                self.in_use.discard(proxy)
    
    def mark_bad(self, proxy: str):
        with self.lock:
            if proxy:
                self.bad_proxies.add(proxy)
    
    def get_stats(self) -> Dict[str, int]:
        with self.lock:
            return {
                "total": len(self.proxies),
                "bad": len(self.bad_proxies),
                "active": len(self.proxies) - len(self.bad_proxies)
            }

proxy_manager: Optional[ProxyManager] = None

def get_timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")

def log(log_type: str, token: str, message: str):
    timestamp = get_timestamp()
    masked = mask_token(token)
    
    with print_lock:
        if log_type == "SUCCESS":
            tag = f"{Fore.GREEN}COP{Style.RESET_ALL}"
        elif log_type == "FAILED":
            tag = f"{Fore.RED}DBG{Style.RESET_ALL}"
        elif log_type == "WARN":
            tag = f"{Fore.YELLOW}WAR{Style.RESET_ALL}"
        elif log_type == "INFO":
            tag = f"{Fore.BLUE}INF{Style.RESET_ALL}"
        else:
            tag = f"{Fore.WHITE}{log_type}{Style.RESET_ALL}"
        
        # Parse message: strip brackets and reformat
        msg = message.strip()
        if msg.startswith("[") and msg.endswith("]"):
            msg = msg[1:-1]
        msg = msg.replace(" : ", " | ")
        
        print(f"{Fore.WHITE}{timestamp}{Style.RESET_ALL}  {tag}  {Fore.WHITE}{msg}{Style.RESET_ALL} | {Fore.WHITE}{masked}{Style.RESET_ALL}")

def log_simple(log_type: str, message: str):
    timestamp = get_timestamp()
    
    with print_lock:
        if log_type == "FAILED":
            tag = f"{Fore.RED}DBG{Style.RESET_ALL}"
        elif log_type == "INFO":
            tag = f"{Fore.BLUE}INF{Style.RESET_ALL}"
        elif log_type == "WARN":
            tag = f"{Fore.YELLOW}WAR{Style.RESET_ALL}"
        else:
            tag = f"{Fore.WHITE}{log_type}{Style.RESET_ALL}"
        
        print(f"{Fore.WHITE}{timestamp}{Style.RESET_ALL}  {tag}  {Fore.WHITE}{message}{Style.RESET_ALL}")

def display_banner():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ███████╗██╗   ██╗███╗   ███╗ █████╗ ███╗   ██╗██╗███████╗ ██████╗ ██████║ ║
║   ╚══███╔╝██║   ██║████╗ ████║██╔══██╗████╗  ██║██║╚══███╔╝██╔═══██╗██╔══██╗║
║     ███╔╝ ██║   ██║██╔████╔██║███████║██╔██╗ ██║██║  ███╔╝ ██║   ██║██████╔╝║
║    ███╔╝  ██║   ██║██║╚██╔╝██║██╔══██║██║╚██╗██║██║ ███╔╝  ██║   ██║██╔══██╗║
║   ███████╗╚██████╔╝██║ ╚═╝ ██║██║  ██║██║ ╚████║██║███████╗╚██████╔╝██║  ██║║
║   ╚══════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝║
║                                                              ║
║                   Discord Token Humanizer                    ║
║                      Built By Arsh                          ║
╚══════════════════════════════════════════════════════════════╝
""")

def mask_token(token: str) -> str:
    if len(token) <= 20:
        return token[:10] + "****"
    return token[:10] + "****" + token[-10:]

def load_file_lines(file_path: Path) -> List[str]:
    if not file_path.exists():
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]

def append_to_file(file_path: Path, content: str):
    with file_lock:
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(content + '\n')

def remove_token_from_file(file_path: Path, token: str):
    with file_lock:
        try:
            lines = file_path.read_text(encoding='utf-8').splitlines()
            new_lines = [l for l in lines if extract_token(l) != token.strip()]
            file_path.write_text('\n'.join(new_lines) + ('\n' if new_lines else ''), encoding='utf-8')
        except Exception:
            pass 

def format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    hours = minutes // 60
    if hours > 0:
        return f"{hours}h {minutes % 60}m"
    if minutes > 0:
        secs = seconds % 60
        return f"{minutes}m {secs:.2f}s"
    return f"{seconds:.2f}s"

def is_valid_token(s: str) -> bool:
    if not s or len(s) < 50:
        return False
    parts = s.split('.')
    if len(parts) != 3:
        return False
    return all(re.match(r'^[A-Za-z0-9_-]+$', part) and len(part) > 0 for part in parts)

def extract_token(line: str) -> Optional[str]:
    line = line.strip()
    if not line:
        return None
    
    if is_valid_token(line):
        return line
    
    for delimiter in [':', '|', '\t', ' ']:
        if delimiter in line:
            parts = line.split(delimiter)
            for part in reversed(parts):
                part = part.strip()
                if is_valid_token(part):
                    return part
    
    return None

def load_tokens(file_path: Path) -> List[str]:
    lines = load_file_lines(file_path)
    tokens = []
    
    for line in lines:
        token = extract_token(line)
        if token:
            tokens.append(token)
    
    seen = set()
    deduped = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped

def load_avatar_files() -> List[Path]:
    if not AVATARS_DIR.exists():
        return []
    valid_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    return [f for f in AVATARS_DIR.iterdir() if f.suffix.lower() in valid_extensions]

DISCORD_AVATAR_MAX_BYTES = 1_000_000  

def load_avatar_as_base64(image_path: Path) -> Optional[str]:
    try:
        with Image.open(image_path) as img:
            is_png = image_path.suffix.lower() == '.png'
            
            if is_png:
                if img.mode == 'P':
                    img = img.convert('RGBA')
            else:
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
            
            img = img.resize((AVATAR_DIMENSION, AVATAR_DIMENSION), Image.Resampling.LANCZOS)
            img_copy = img.copy()  

            def _encode(pil_img, fmt, quality=80) -> str:
                buf = BytesIO()
                kw = {"format": fmt}
                if fmt == "JPEG":
                    kw["quality"] = quality
                    kw["optimize"] = True
                pil_img.save(buf, **kw)
                buf.seek(0)
                return base64.b64encode(buf.read()).decode()

            img_format = 'PNG' if is_png else 'JPEG'
            b64 = _encode(img_copy, img_format)
            mime = 'image/png' if img_format == 'PNG' else 'image/jpeg'

            if len(b64) > DISCORD_AVATAR_MAX_BYTES:
                work_img = img_copy.convert('RGB') if img_copy.mode in ('RGBA', 'P', 'LA') else img_copy
                mime = 'image/jpeg'
                for quality in (80, 60, 40, 20):
                    b64 = _encode(work_img, 'JPEG', quality)
                    if len(b64) <= DISCORD_AVATAR_MAX_BYTES:
                        break
                else:
                    half = max(64, AVATAR_DIMENSION // 2)
                    work_img = work_img.resize((half, half), Image.Resampling.LANCZOS)
                    for quality in (80, 60, 40):
                        b64 = _encode(work_img, 'JPEG', quality)
                        if len(b64) <= DISCORD_AVATAR_MAX_BYTES:
                            break
                    else:
                        return None  

            return f"data:{mime};base64,{b64}"
    except Exception:
        return None

def parse_proxy(proxy_string: str) -> Optional[str]:
    proxy = proxy_string.strip()
    if proxy.startswith('#'):
        return None
    
    if '://' in proxy:
        parsed = urlparse(proxy)
        if parsed.hostname and parsed.port:
            return proxy
        return None
    
    if '@' in proxy:
        at_idx = proxy.rfind('@')
        auth = proxy[:at_idx]
        hostport = proxy[at_idx + 1:]
        
        colon_idx = auth.find(':')
        if colon_idx == -1:
            return None
        user = auth[:colon_idx]
        password = auth[colon_idx + 1:]
        
        host_parts = hostport.rsplit(':', 1)
        if len(host_parts) != 2:
            return None
        host, port = host_parts
        
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    
    parts = proxy.split(':')
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    elif len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    
    return None

class Humanizer:
    def __init__(self, token: str, proxy: Optional[str] = None):
        self.token = token
        self.proxy = proxy
        self.client = primp.Client(
            verify=False,
            proxy=proxy if proxy else None
        )
        self.user_agent = DEFAULT_USER_AGENT
        self.session_id = None
        self.proxy_failed = False
        self.is_locked = False
        self.installation_id = f"{random.randint(10**18, 10**19 - 1)}.{''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_', k=22))}"
        self._launch_id = str(uuid.uuid4())
        self._signature = str(uuid.uuid4())
        self._heartbeat_id = str(uuid.uuid4())
        self._native_build = random.randint(65600, 65800)
        self._super_props = generate_super_properties(
            self._launch_id, self._signature, self._heartbeat_id, self._native_build
        )
    
    def get_fingerprint(self):
        try:
            r = self.client.get("https://discord.com/api/v9/experiments", timeout=30)
            if r.status_code == 200:
                return r.json().get("fingerprint")
        except:
            pass
        return None
    
    async def _send_identify(self, ws) -> bool:
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if hello.get("op") != 10:
                return False
            
            identify_payload = {
                "op": 2,
                "d": {
                    "token": self.token,
                    "capabilities": 16381,
                    "properties": {
                        "os": "Windows",
                        "browser": "Discord Client",
                        "release_channel": "stable",
                        "client_version": DISCORD_CLIENT_VERSION,
                        "os_version": "10.0.26100",
                        "os_arch": "x64",
                        "app_arch": "x64",
                        "system_locale": "en-US",
                        "browser_user_agent": self.user_agent,
                        "browser_version": ELECTRON_VERSION,
                        "os_sdk_version": "26100",
                        "client_build_number": BUILD_NUMBER,
                        "native_build_number": self._native_build,
                        "client_event_source": None,
                        "design_id": 0
                    },
                    "presence": {
                        "status": "online",
                        "since": 0,
                        "activities": [],
                        "afk": False
                    },
                    "compress": False,
                    "client_state": {
                        "guild_versions": {},
                        "highest_last_message_id": "0",
                        "read_state_version": 0,
                        "user_guild_settings_version": -1,
                        "user_settings_version": -1,
                        "private_channels_version": "0",
                        "api_code_version": 0
                    }
                }
            }
            
            await ws.send(json.dumps(identify_payload))
            return True
            
        except Exception:
            return False
    
    async def _wait_for_ready(self, ws) -> bool:
        for _ in range(12):     
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                op = msg.get("op")
                t = msg.get("t")
                if op == 11 or (op == 0 and t != "READY"):
                    continue
                if t == "READY":
                    self.session_id = msg["d"].get("session_id")
                    return True
                if op == 9:
                    return False
            except asyncio.TimeoutError:
                break
        return False

    async def update_account_with_live_session(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if getattr(self, "is_locked", False):
            return {"success": False, "error": "Token Locked"}

        headers = self.get_headers()
        loop = asyncio.get_event_loop()

        if "avatar" not in payload:
            direct = await loop.run_in_executor(None, lambda: self.update_user_profile(payload, headers))
            if direct.get("success") or direct.get("captcha") or direct.get("rate_limited"):
                return direct
            if not direct.get("unknown_session"):
                return direct

        async def _ws_patch(ws) -> Dict[str, Any]:
            if not await self._send_identify(ws):
                return {"success": False, "error": "Gateway IDENTIFY failed"}

            if not await self._wait_for_ready(ws):
                return {"success": False, "error": "Gateway READY timeout"}

            return await loop.run_in_executor(None, lambda: self.update_user_profile(payload, headers))

        try:
            extra_headers = {"User-Agent": self.user_agent}
            connect_kwargs = {"open_timeout": 60, "close_timeout": 10, "max_size": None}

            try:
                connect_params = inspect.signature(websockets.connect).parameters
                header_kwarg = "additional_headers" if "additional_headers" in connect_params else "extra_headers"
            except (TypeError, ValueError):
                header_kwarg = "extra_headers"

            connect_kwargs[header_kwarg] = extra_headers

            if self.proxy:
                proxy = Proxy.from_url(self.proxy)
                sock = await proxy.connect(dest_host="gateway.discord.gg", dest_port=443)
                connect_kwargs["sock"] = sock
                connect_kwargs["server_hostname"] = "gateway.discord.gg"

                async with websockets.connect(DISCORD_GATEWAY, **connect_kwargs) as ws:
                    return await _ws_patch(ws)
            else:
                async with websockets.connect(DISCORD_GATEWAY, **connect_kwargs) as ws:
                    return await _ws_patch(ws)

        except Exception as e:
            err_str = str(e)

            if not err_str:
                err_str = type(e).__name__
            if self.proxy and ("proxy" in err_str.lower() or "connect" in err_str.lower()):
                self.proxy_failed = True
            return {"success": False, "error": err_str}
    
    def update_account_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.update_account_with_live_session(payload), _async_loop
                )
                result = future.result()

                if result["success"]:
                    return result

                error = str(result.get("error", ""))
                if self._is_transient_error(error):
                    last_error = self._clean_error(error)
                    if proxy_manager and attempt < max_retries - 1:
                        new_proxy = proxy_manager.get_proxy()
                        if new_proxy:
                            self.proxy = new_proxy
                            self.client = primp.Client(verify=False, proxy=new_proxy)
                        continue

                return result

            except Exception as e:
                last_error = self._clean_error(str(e))
                if attempt < max_retries - 1 and proxy_manager:
                    new_proxy = proxy_manager.get_proxy()
                    if new_proxy:
                        self.proxy = new_proxy
                        self.client = primp.Client(verify=False, proxy=new_proxy)
                    continue

        return {"success": False, "error": last_error or "Max retries reached"}
    
    def _clean_error(self, error) -> str:
        error = str(error)
        
        if "RATE_LIMIT" in error or "rate limit" in error.lower() or "too often" in error.lower():
            return "Rate Limited"
        
        if "curl:" in error:
            if "(56)" in error:
                return "Proxy closed"
            elif "(28)" in error:
                return "Timeout"
            elif "(7)" in error:
                return "Proxy failed"
            else:
                match = re.search(r'curl: \((\d+)\)', error)
                if match:
                    return f"Curl {match.group(1)}"
        
        if "Unknown Session" in error:
            return "Bad session"
        if "received 4000" in error or "4000 (private" in error:
            return "Token locked / flagged (WS 4000)"
        if "received 4001" in error:
            return "Invalid token (WS 4001)"
        if "received 4004" in error:
            return "Auth failed (WS 4004)"
        if "received 4006" in error:
            return "Session invalid (WS 4006)"
        if "Unauthorized" in error or "401" in error:
            return "Unauthorized"
        if "captcha" in error.lower():
            return "Captcha"
        if "Invalid Form Body" in error:
            return "Invalid request"
        if "message" in error and "code" in error:
            match = re.search(r"'message': '([^']+)'", error)
            if match:
                msg = match.group(1)
                if len(msg) > 25:
                    return msg[:22] + "..."
                return msg
        
        if len(error) > 80:
            return error[:77] + "..."
        
        return error
    
    def get_headers(self) -> Dict[str, str]:
        headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "en-US",
            "authorization": self.token,
            "content-type": "application/json",
            "user-agent": self.user_agent,
            "x-debug-options": "bugReporterEnabled",
            "x-discord-locale": "en-US",
            "x-discord-timezone": "Asia/Calcutta",
            "x-installation-id": self.installation_id,
            "x-super-properties": self._super_props
        }

        fp = self.get_fingerprint()
        if fp:
            headers["x-fingerprint"] = fp

        return headers
    
    def _is_transient_error(self, error_str: str) -> bool:
        lower = error_str.lower()
        return any(kw in lower for kw in (
            "connection", "proxy", "timeout", "reset", "connect",
            "sending", "refused", "unreachable", "eof", "read error",
            "gateway ready", "gateway identify", "gateway",
            "no close frame", "connection closed", "websocket"
        ))
    
    def _api_call_with_retry(self, method: str, url: str, data: Dict[str, Any],
                              headers: Dict[str, str], max_retries: int = 5) -> Dict[str, Any]:
        if getattr(self, "is_locked", False):
            return {"success": False, "error": "Token Locked"}
            
        last_result = None
        
        for attempt in range(max_retries):
            if getattr(self, "is_locked", False):
                return {"success": False, "error": "Token Locked"}
                
            try:
                if method.upper() == "POST":
                    resp = self.client.post(url, headers=headers, json=data, timeout=60)
                else:
                    resp = self.client.patch(url, headers=headers, json=data, timeout=60)
                
                if resp.status_code in (200, 204):
                    try:
                        data = resp.json() if resp.text and resp.status_code == 200 else {}
                    except Exception:
                        data = {}
                    return {"success": True, "data": data}
                
                try:
                    error_data = resp.json() if resp.text and resp.text.strip() else {}
                except Exception:
                    error_data = {}

                if error_data.get("captcha_key"):
                    return {"success": False, "captcha": True, "error": error_data}

                if resp.status_code == 400 and isinstance(error_data, dict):
                    code = error_data.get("code")
                    if code == 10020:
                        return {"success": False, "unknown_session": True, "error": "Unknown Session"}
                    errors = error_data.get("errors", {})
                    for field_errors in errors.values():
                        for err in field_errors.get("_errors", []):
                            if err.get("code") == "AVATAR_RATE_LIMIT":
                                return {"success": False, "rate_limited": True, "retry_after": 0, "error": "Avatar Rate Limited"}
                
                if resp.status_code == 429:
                    try:
                        ra_header = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
                        ra_body = error_data.get("retry_after", 0) if isinstance(error_data, dict) else 0
                        retry_after = float(ra_header) if ra_header else float(ra_body or 0)
                    except (TypeError, ValueError):
                        retry_after = 0
                    wait_time = max(retry_after, 1.0)
                    time.sleep(wait_time)
                    continue  
                
                last_result = {"success": False, "error": error_data}
                
                if resp.status_code in (401, 403):
                    self.is_locked = True
                    return last_result
                
            except Exception as e:
                error_str = str(e)
                last_result = {"success": False, "error": error_str}
                
                if self.proxy and self._is_transient_error(error_str):
                    self.proxy_failed = True
                
                if self._is_transient_error(error_str) and proxy_manager and attempt < max_retries - 1:
                    new_proxy = proxy_manager.get_proxy()
                    if new_proxy:
                        self.proxy = new_proxy
                        self.client = primp.Client(verify=False, proxy=new_proxy)
                    continue
                
                if attempt >= max_retries - 1:
                    return last_result
        
        return last_result or {"success": False, "error": "Max retries reached"}
    
    def update_user_profile(self, data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        return self._api_call_with_retry("patch", f"{DISCORD_API}/users/@me", data, headers)
    
    def update_profile_fields(self, data: Dict[str, Any], headers: Dict[str, str]) -> Dict[str, Any]:
        return self._api_call_with_retry("patch", f"{DISCORD_API}/users/@me/profile", data, headers)
    
    def set_hypesquad(self, house_id: int, headers: Dict[str, str], retry_count: int = 0) -> Dict[str, Any]:
        time.sleep(random.uniform(2, 5))
        
        house_name = HYPESQUAD_HOUSES.get(house_id, "Unknown")
        
        # First check if user already has a HypeSquad badge
        try:
            check = self.client.get(
                f"{DISCORD_API}/users/@me",
                headers=headers,
                timeout=30
            )
            
            if check.status_code == 200:
                data = check.json()
                flags = data.get("flags", 0)
                # Check if any HypeSquad flag is already set (bits 1,2,3 = 2,4,8 = 0xE)
                if flags & 0xE:
                    existing_house = None
                    for hid, hname in HYPESQUAD_HOUSES.items():
                        if flags & (1 << hid):
                            existing_house = hname
                            break
                    if existing_house:
                        log("INFO", self.token, f"[HypeSquad Already Set : {existing_house}]")
                        return {"success": True, "house_name": existing_house, "already_set": True}
        except Exception:
            pass
        
        # Try to assign new HypeSquad badge
        res = self._api_call_with_retry(
            "post",
            f"{DISCORD_API}/hypesquad/online",
            {"house_id": house_id},
            headers,
            max_retries=2
        )
        
        # 204 means success for HypeSquad endpoint
        if res.get("success"):
            return {"success": True, "house_name": house_name}
        
        # If not successful, check if we should retry
        if retry_count < RETRY_LIMIT:
            log("WARN", self.token, f"[HypeSquad Retry : {retry_count + 1}/{RETRY_LIMIT} for {house_name}]")
            time.sleep(random.uniform(2.0, 4.0))
            return self.set_hypesquad(house_id, headers, retry_count + 1)
        
        return {"success": False, "error": f"HypeSquad {house_name} not applied - Account may already have a badge or is rate limited", "house_name": house_name}

    def process(self, names: List[str], bios: List[str], pronouns_list: List[str],
                avatar_files: List[Path], avatar_loader, get_unique_name_fn=None, get_unique_avatar_fn=None) -> bool:

        headers = self.get_headers()
        success = True

        parallel_tasks = []

        account_payload = {}
        avatar_name = None

        if UPDATE_AVATAR and avatar_files:
            avatar_path = get_unique_avatar_fn() if get_unique_avatar_fn else random.choice(avatar_files)
            if avatar_path:
                avatar_b64 = avatar_loader(avatar_path)
                if avatar_b64:
                    account_payload["avatar"] = avatar_b64
                    av_hash = hashlib.md5(avatar_b64[:100].encode()).hexdigest()
                    now = datetime.now()
                    now_str = now.strftime("%B {d}, %Y at {t}").format(
                        d=now.day,
                        t=now.strftime("%I:%M %p").lstrip("0")
                    )
                    account_payload["avatar_description"] = f"{av_hash}, added {now_str}"
                    avatar_name = avatar_path.name

        display_name = None
        if UPDATE_DISPLAY_NAME and names:
            display_name = get_unique_name_fn() if get_unique_name_fn else random.choice(names)
            if display_name:
                account_payload["global_name"] = display_name

        if account_payload:
            parallel_tasks.append(("account", (account_payload, avatar_name, display_name)))

        profile_payload = {}
        bio = None
        if UPDATE_BIO and bios:
            bio = random.choice(bios)
            profile_payload["bio"] = bio

        pronouns = None
        if UPDATE_PRONOUNS and pronouns_list:
            pronouns = random.choice(pronouns_list)
            profile_payload["pronouns"] = pronouns

        if profile_payload:
            parallel_tasks.append(("profile", (profile_payload, bio, pronouns)))

        house_id = None
        house_name = None
        if UPDATE_HYPESQUAD:
            time.sleep(random.uniform(0, 3))
            house_id = random.choice([1, 2, 3])
            house_name = HYPESQUAD_HOUSES[house_id]
            parallel_tasks.append(("hypesquad", (house_id, house_name)))
        
        if parallel_tasks:
            def _run_field(task_type, value):
                if getattr(self, "is_locked", False):
                    return (task_type, {"success": False, "error": "Token Locked"}, value)
                h = headers.copy()
                if task_type == "account":
                    payload, _, _ = value
                    if "avatar" in payload:
                        return ("account", self.update_account_sync(payload), value)
                    else:
                        return ("account", self.update_user_profile(payload, h), value)
                elif task_type == "profile":
                    payload, _, _ = value
                    return ("profile", self.update_profile_fields(payload, h), value)
                elif task_type == "hypesquad":
                    hid, _ = value
                    return ("hypesquad", self.set_hypesquad(hid, h), value)
                return ("unknown", {"success": False, "error": "Unknown field type"}, value)
            
            with ThreadPoolExecutor(max_workers=len(parallel_tasks)) as field_executor:
                futures = [field_executor.submit(_run_field, tt, val) for tt, val in parallel_tasks]
                
                for future in as_completed(futures):
                    try:
                        task_type, result, values = future.result()
                    except Exception as e:
                        log("FAILED", self.token, f"[Field Error : {str(e)[:30]}]")
                        success = False
                        continue
                    
                    if task_type == "account":
                        _, aname, dname = values
                        if result["success"]:
                            if aname: log("SUCCESS", self.token, f"[Avatar Updated : {aname}]")
                            if dname: log("SUCCESS", self.token, f"[Name Updated : {dname}]")
                        elif result.get("captcha"):
                            if aname: log("WARN", self.token, "[Avatar Failed : Captcha]")
                            if dname: log("WARN", self.token, "[Name Failed : Captcha]")
                            success = False
                        elif result.get("rate_limited"):
                            ra = result.get("retry_after", 0)
                            ra_str = f"{int(ra)}s" if ra else "unknown"
                            if aname: log("WARN", self.token, f"[Avatar Failed : Rate Limited ({ra_str})]")
                            if dname: log("WARN", self.token, f"[Name Failed : Rate Limited ({ra_str})]")
                            success = False
                        else:
                            error_msg = self._clean_error(result.get("error", "Unknown"))
                            if aname: log("FAILED", self.token, f"[Avatar Failed : {error_msg}]")
                            if dname: log("FAILED", self.token, f"[Name Failed : {error_msg}]")
                            success = False
                            
                    elif task_type == "profile":
                        _, bname, pname = values
                        if result["success"]:
                            if bname: log("SUCCESS", self.token, f"[Bio Updated : {bname[:40]}{'...' if len(bname) > 40 else ''}]")
                            if pname: log("SUCCESS", self.token, f"[Pronouns Updated : {pname}]")
                        elif result.get("captcha"):
                            if bname: log("WARN", self.token, "[Bio Failed : Captcha]")
                            if pname: log("WARN", self.token, "[Pronouns Failed : Captcha]")
                            success = False
                        else:
                            error_msg = self._clean_error(result.get("error", "Unknown"))
                            if bname: log("FAILED", self.token, f"[Bio Failed : {error_msg}]")
                            if pname: log("FAILED", self.token, f"[Pronouns Failed : {error_msg}]")
                            success = False
                            
                    elif task_type == "hypesquad":
                        _, hsname = values
                        if result.get("success"):
                            applied_house = result.get("house_name", hsname)
                            if result.get("already_set"):
                                log("INFO", self.token, f"[HypeSquad Already Set : {applied_house}]")
                            else:
                                log("SUCCESS", self.token, f"[HypeSquad Updated : {applied_house}]")
                        else:
                            error_msg = self._clean_error(result.get("error", "Unknown"))
                            log("FAILED", self.token, f"[HypeSquad Failed : {hsname} - {error_msg}]")
                            success = False
        
        if self.proxy_failed and proxy_manager:
            proxy_manager.mark_bad(self.proxy)
        
        with stats_lock:
            if success:
                append_to_file(SUCCESS_FILE, self.token)
                remove_token_from_file(TOKENS_FILE, self.token)
                stats["success"] += 1
            else:
                append_to_file(FAILED_FILE, self.token)
                stats["failed"] += 1
        
        return success

def process_token(token: str, names: List[str], bios: List[str], pronouns_list: List[str],
                  avatar_files: List[Path], avatar_loader, get_unique_name_fn, get_unique_avatar_fn) -> bool:
    proxy = proxy_manager.get_proxy() if proxy_manager else None
    humanizer = Humanizer(token, proxy)
    try:
        return humanizer.process(names, bios, pronouns_list, avatar_files, avatar_loader, get_unique_name_fn, get_unique_avatar_fn)
    finally:
        if proxy_manager and proxy:
            proxy_manager.release_proxy(proxy)

def main():
    global proxy_manager, MAX_THREADS
    
    display_banner()
    
    try:
        threads_input = input(f"{Fore.LIGHTBLACK_EX}[{Fore.WHITE}?{Fore.LIGHTBLACK_EX}]{Style.RESET_ALL} Threads (Default: {MAX_THREADS}): ").strip()
        if threads_input:
            MAX_THREADS = int(threads_input)
    except ValueError:
        log_simple("WARN", f"Invalid thread count. Using default: {MAX_THREADS}")
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    BANNERS_DIR.mkdir(parents=True, exist_ok=True)
    
    tokens = load_tokens(TOKENS_FILE)
    if not tokens:
        log_simple("FAILED", f"No valid tokens found in {TOKENS_FILE}")
        return
    
    with stats_lock:
        stats["total"] = len(tokens)
    
    proxy_lines = load_file_lines(PROXIES_FILE)
    proxies = [p for p in (parse_proxy(line) for line in proxy_lines) if p]
    
    if proxies:
        proxy_manager = ProxyManager(proxies)
    
    names = load_file_lines(NAMES_FILE)
    bios = load_file_lines(BIOS_FILE)
    pronouns_list = load_file_lines(PRONOUNS_FILE)
    avatar_files = load_avatar_files()
    
    # Shuffle names and avatars so each token gets a unique one
    random.shuffle(names)
    random.shuffle(avatar_files)
    
    # Create per-token assignment lists (no duplicates)
    names_queue = list(names)
    avatars_queue = list(avatar_files)
    names_lock = threading.Lock()
    avatars_lock = threading.Lock()
    
    def get_unique_name() -> Optional[str]:
        with names_lock:
            if names_queue:
                return names_queue.pop()
            # If we run out, reshuffle original list
            refill = list(names)
            random.shuffle(refill)
            names_queue.extend(refill)
            return names_queue.pop() if names_queue else None
    
    def get_unique_avatar() -> Optional[Path]:
        with avatars_lock:
            if avatars_queue:
                return avatars_queue.pop()
            # If we run out, reshuffle original list
            refill = list(avatar_files)
            random.shuffle(refill)
            avatars_queue.extend(refill)
            return avatars_queue.pop() if avatars_queue else None

    _avatar_lock = threading.Lock()
    _avatar_cache: Dict[Path, str] = {}

    def lazy_get_avatar(path: Path) -> Optional[str]:
        with _avatar_lock:
            if path in _avatar_cache:
                return _avatar_cache[path]
        b64 = load_avatar_as_base64(path)
        if b64:
            with _avatar_lock:
                _avatar_cache[path] = b64
        return b64

    if avatar_files:
        log_simple("INFO", f"{len(avatar_files)} avatar(s) loaded")
    
    print("")
    
    SUCCESS_FILE.write_text('')
    FAILED_FILE.write_text('')
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        token_iter = iter(tokens)
        active_futures = set()
        
        while True:
            while len(active_futures) < MAX_THREADS:
                try:
                    token = next(token_iter)
                    future = executor.submit(process_token, token, names, bios, pronouns_list, avatar_files, lazy_get_avatar, get_unique_name, get_unique_avatar)
                    future._token = token
                    active_futures.add(future)
                except StopIteration:
                    break
            
            if not active_futures:
                break
                
            done, _ = wait(
                active_futures, 
                return_when=FIRST_COMPLETED
            )
            
            for future in done:
                active_futures.remove(future)
                try:
                    future.result()
                except Exception as e:
                    token = getattr(future, '_token', 'Unknown')
                    log("FAILED", token, f"Unexpected error: {str(e)[:50]}")
    
    elapsed = time.time() - stats["start_time"]
    success_rate = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
    
    print("")
    ts = get_timestamp()
    print(f"{Fore.WHITE}{ts}{Style.RESET_ALL}  {Fore.GREEN}COP{Style.RESET_ALL}  {Fore.WHITE}Done {stats['total']}/{stats['total']} | {format_time(elapsed)}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{ts}{Style.RESET_ALL}  {Fore.GREEN}COP{Style.RESET_ALL}  {Fore.WHITE}Success | {stats['success']}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{ts}{Style.RESET_ALL}  {Fore.RED}DBG{Style.RESET_ALL}  {Fore.WHITE}Failed | {stats['failed']}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{ts}{Style.RESET_ALL}  {Fore.BLUE}INF{Style.RESET_ALL}  {Fore.WHITE}Rate | {success_rate:.1f}%{Style.RESET_ALL}")
    if proxy_manager:
        ps = proxy_manager.get_stats()
        print(f"{Fore.WHITE}{ts}{Style.RESET_ALL}  {Fore.BLUE}INF{Style.RESET_ALL}  {Fore.WHITE}Proxies | {ps['active']} good / {ps['bad']} bad{Style.RESET_ALL}")

    if proxy_manager and proxy_manager.bad_proxies:
        proxy_lines = load_file_lines(PROXIES_FILE)
        cleaned = [p for p in proxy_lines if parse_proxy(p) not in proxy_manager.bad_proxies]
        PROXIES_FILE.write_text("\n".join(cleaned) + "\n")
        log_simple("INFO", f"Removed {len(proxy_lines) - len(cleaned)} bad proxies from proxies.txt")


if __name__ == "__main__":
    main()
