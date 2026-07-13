"""
Z Trigger — Discord Nitro Trial Trigger Tool
============================================

New Nitro Trial Method (works after recent patch).

Pipeline per token:
  1. Validate token            (HTTP API — proper check, no wasted browser launches)
  2. Humanize account          (HTTP API — change avatar, bio, username, pronouns)
     - Falls back to browser-based humanize if HTTP returns "Unknown Session"
  3. Complete a quest          (browser — accept + watch video quest)
  4. Claim the reward          (browser — click Claim Reward / Claim Orbs)
  5. Buy Orbs badge            (browser — redeem Orbs Apprentice Badge in /shop)
  6. Add payment method        (browser — open /settings/#billing, manual card entry)

Then wait 12–48 hours and the trial will appear in the account.
Reported success rate: 80–90%.

Author: Z Trigger
License: For educational use only. Use of automation against Discord may violate
         their Terms of Service — you accept all responsibility by running this tool.
"""

# ── Version marker ────────────────────────────────────────────────────────────
# Used to verify you are running the latest version. Bump on every fix.
Z_TRIGGER_VERSION = "1.27.0"  # debug quest JS result — log type and value to diagnose JS error: None


import asyncio
import base64
import io
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

try:
    import httpx
except ImportError:
    print("Missing dependency: httpx.  Run:  pip install httpx")
    sys.exit(1)

try:
    import nodriver as uc
except ImportError:
    print("Missing dependency: nodriver.  Run:  pip install nodriver")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Missing dependency: pyyaml.  Run:  pip install pyyaml")
    sys.exit(1)

try:
    from colorama import Fore, init
    init(autoreset=True)
except ImportError:
    print("Missing dependency: colorama.  Run:  pip install colorama")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # optional

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ─────────────────────────────────────────────────────────────────────────────
# Visual palette
# ─────────────────────────────────────────────────────────────────────────────
LC  = "\033[96m"   # cyan
W   = "\033[97m"   # bright white
RS  = "\033[0m"    # reset
DIM = "\033[2m"    # dim
GRN = Fore.LIGHTGREEN_EX
YEL = Fore.YELLOW
RED = Fore.RED
CYN = Fore.CYAN


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def log_info(msg: str) -> None:
    print(f"{DIM}[{_ts()}]{RS} {LC}[$]{RS} {W}{msg}{RS}", flush=True)

def log_ok(msg: str) -> None:
    print(f"{DIM}[{_ts()}]{RS} {Fore.GREEN}[$]{RS} {GRN}{msg}{RS}", flush=True)

def log_warn(msg: str) -> None:
    print(f"{DIM}[{_ts()}]{RS} {YEL}[$]{RS} {YEL}{msg}{RS}", flush=True)

def log_err(msg: str) -> None:
    print(f"{DIM}[{_ts()}]{RS} {RED}[$]{RS} {RED}{msg}{RS}", flush=True)

def log_stage(stage: str, label: str) -> None:
    print(f"{DIM}[{_ts()}]{RS} {Fore.MAGENTA}[#]{RS} {W}{stage} for {CYN}{label}{RS}", flush=True)


ASCII_ART = f"""
{LC}
 ███████╗████████╗ █████╗ ██╗  ██╗
 ╚══███╔╝██╔════╝██╔══██╗██║ ██╔╝
   ███╔╝ █████╗  ███████║█████╔╝
  ███╔╝  ██╔══╝  ██╔══██║██╔═██╗
 ███████╗███████╗██║  ██║██║  ██╗
 ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝
{W}        Z TRIGGER  -  Discord Nitro Trial Trigger
{DIM}        New method  -  80-90% success rate after 12-48h
{Fore.YELLOW}        v{Z_TRIGGER_VERSION}
{RS}"""


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_FILE = Path("config.yaml")

DEFAULTS: dict[str, Any] = {
    "headless": False,
    "max_retries": 3,
    "retry_base_delay": 4,
    "screenshot_on_error": True,
    "log_dir": "logs",
    "tokens_file": "tokens.txt",
    "proxies_file": "",
    "api_timeout": 20,
    "quest_video_buffer_secs": 5,
    "payment_method_required": True,
    "humanize_required": True,
    "browser_profile_persist": False,
    "nopecha_extension_path": "",  # path to NopeCHA extension folder (for auto-solving captchas)
    "nopecha_api_key": "",  # NopeCHA API key from https://nopecha.com (auto-injected into extension)
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}
        cfg.update(overrides)
    cfg["headless"] = os.getenv("HEADLESS", str(cfg["headless"])).lower() == "true"
    cfg["payment_method_required"] = str(cfg.get("payment_method_required", True)).lower() in ("true", "1", "yes")
    cfg["humanize_required"] = str(cfg.get("humanize_required", True)).lower() in ("true", "1", "yes")
    return cfg


CFG = load_config()
LOG_DIR = Path(CFG["log_dir"])
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "main.log", encoding="utf-8")],
)


def get_logger(label: str) -> logging.Logger:
    logger = logging.getLogger(f"acct_{label}")
    if not logger.handlers:
        fh = logging.FileHandler(LOG_DIR / f"acct_{label}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    return logger


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Account:
    email: Optional[str]
    password: Optional[str]
    token: Optional[str]
    proxy: Optional[str] = None
    raw_line: str = ""
    # Cached Discord user info from /users/@me
    user_id: Optional[str] = None
    username: Optional[str] = None
    discriminator: Optional[str] = None
    premium_type: int = 0   # 0=none, 1=classic, 2=nitro, 3=basic
    verified: bool = False
    flags: int = 0

    @property
    def label(self) -> str:
        if self.token:
            return self.token[-6:]
        if self.email:
            return self.email.split("@")[0][-8:]
        return "unknown"

    @property
    def has_token(self) -> bool:
        return bool(self.token)

    @property
    def has_credentials(self) -> bool:
        return bool(self.email and self.password)


@dataclass
class AccountResult:
    account: Account
    success: bool
    message: str = ""
    attempts: int = 0
    elapsed: float = 0.0
    stage_reached: str = "init"   # validate / humanize / quest / claim / orbs / billing / done
    extracted_token: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Discord API client (HTTP)
# ─────────────────────────────────────────────────────────────────────────────
DISCORD_API = "https://discord.com/api/v9"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _super_properties_b64() -> str:
    """
    Build a base64-encoded X-Super-Properties header value that mimics the
    Discord web client. This is required for write operations on /users/@me
    (PATCH) — without it Discord returns 400 'Unknown Session'.
    """
    import json as _json
    props = {
        "os": "Windows",
        "browser": "Chrome",
        "device": "",
        "system_locale": "en-US",
        "browser_version": "126.0.0.0",
        "os_version": "10",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": 298682,
        "client_event_source": None,
    }
    raw = _json.dumps(props, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


_SUPER_PROPS = _super_properties_b64()


def api_headers(token: str, is_write: bool = False) -> dict:
    """
    Build Discord API request headers.

    For write operations (PATCH/POST/DELETE), include Discord's internal
    client headers (X-Super-Properties, X-Discord-Locale, Origin, Referer)
    — without these Discord returns 400 'Unknown Session' for any account
    modification.
    """
    h = {
        "Authorization": token,
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
    }
    if is_write:
        h["X-Super-Properties"] = _SUPER_PROPS
        h["X-Discord-Locale"] = "en-US"
        h["Origin"] = "https://discord.com"
        h["Referer"] = "https://discord.com/channels/@me"
        h["X-Discord-Timezone"] = "America/Los_Angeles"
    return h



async def validate_token(token: str, logger: logging.Logger) -> tuple[bool, str, Optional[dict]]:
    """
    Validate the token against Discord's /users/@me endpoint.

    Returns:
        (valid, message, user_dict_or_None)
    """
    if not token or len(token) < 30:
        return False, "Token is empty or too short — Please check your token properly.", None

    # Basic format sanity check: tokens are typically <base64>.<base64>.<hex>
    if token.count(".") < 2:
        return False, "Token format looks wrong (expected 3 dot-separated parts) — Please check your token properly.", None

    try:
        async with httpx.AsyncClient(timeout=CFG["api_timeout"], follow_redirects=True) as client:
            r = await client.get(f"{DISCORD_API}/users/@me", headers=api_headers(token))
    except httpx.RequestError as e:
        return False, f"Network error while validating token: {e}", None

    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            return False, "Got 200 but response was not JSON.", None
        # Check for known bad signals
        if data.get("verified") is False:
            return False, "Token is valid but email is not verified.", data
        return True, "Token is valid.", data

    if r.status_code == 401:
        return False, "Token is invalid or expired (401) — Please check your token properly.", None
    if r.status_code == 403:
        # Try to surface the reason
        try:
            body = r.json()
            msg = body.get("message", "Forbidden")
        except Exception:
            msg = "Forbidden (403) — account may be locked, flagged, or phone-verification required."
        return False, msg, None
    if r.status_code == 429:
        return False, "Rate limited while validating token (429) — slow down and retry.", None
    if r.status_code >= 500:
        return False, f"Discord server error {r.status_code} — try again later.", None

    return False, f"Unexpected response {r.status_code}.", None


async def refresh_token_via_login(
    email: str,
    password: str,
    logger: logging.Logger,
) -> tuple[bool, str, Optional[str]]:
    """
    Log in via Discord's /auth/login endpoint to get a fresh token.

    Useful when a token has been invalidated by Discord's anti-automation
    rotation (common after a failed profile edit). Requires email + password.

    Returns:
        (success, message, new_token_or_None)
    """
    if not email or not password:
        return False, "No email/password on file — cannot refresh token.", None

    payload = {
        "login": email,
        "password": password,
        "undelete": False,
        "login_source": "/auth/login",
        "gift_code_sku_id": None,
    }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://discord.com",
        "Referer": "https://discord.com/login",
    }

    try:
        async with httpx.AsyncClient(timeout=CFG["api_timeout"], follow_redirects=True) as client:
            r = await client.post(f"{DISCORD_API}/auth/login", headers=headers, json=payload)
    except httpx.RequestError as e:
        return False, f"Network error during login refresh: {e}", None

    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            return False, "Login returned 200 but body was not JSON.", None
        new_token = data.get("token")
        if new_token:
            return True, "Fresh token acquired via email/password login.", new_token
        return False, "Login returned 200 but no token in response.", None

    # Try to surface the reason
    try:
        body = r.json()
    except Exception:
        body = {}

    # Captcha required
    if body.get("captcha_key"):
        return False, (
            "Discord requires a captcha for fresh login. Open Discord in your "
            "browser, log in manually with email/password, solve the captcha, "
            "then re-extract your token from DevTools (Network tab -> any "
            "discord.com request -> Authorization header)."
        ), None

    # MFA required
    if body.get("mfa") or body.get("code") == 50006:
        return False, (
            "MFA (2FA) is enabled on this account. Login refresh cannot bypass "
            "MFA. Please log in manually in the browser, then re-extract your "
            "token from DevTools."
        ), None

    # Wrong password
    if body.get("code") == 50005 or "password" in str(body.get("errors", "")).lower():
        return False, (
            "Password does not match. The password in your tokens.txt is wrong. "
            "Please verify it (special characters are case-sensitive)."
        ), None

    msg = body.get("message", f"HTTP {r.status_code}")
    return False, f"Login refresh failed: {msg}", None


# ─────────────────────────────────────────────────────────────────────────────
# Humanize helpers — reads from bios.txt, names.txt, pronouns.txt, avatar/ folder
# ─────────────────────────────────────────────────────────────────────────────
AVATAR_DIR = Path("avatar")
BIOS_FILE = Path("bios.txt")
NAMES_FILE = Path("names.txt")
PRONOUNS_FILE = Path("pronouns.txt")


def _load_lines_from_file(path: Path) -> list:
    """Load non-empty lines from a text file. Returns empty list if file missing."""
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        # Strip whitespace, skip empty lines and comments
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    except Exception:
        return []


# Load names, bios, pronouns at startup (cached for the session)
_NAMES_CACHE = _load_lines_from_file(NAMES_FILE)
_BIOS_CACHE = _load_lines_from_file(BIOS_FILE)
_PRONOUNS_CACHE = _load_lines_from_file(PRONOUNS_FILE)

# Fallbacks if the files are missing
_NAMES_FALLBACK = [
    "lunar_fox", "cyber_drift", "neon_panda", "quantum_owl", "violet_lynx",
    "frost_byte", "ember_wolf", "pixel_raven", "mystic_river", "cosmic_jay",
]
_BIOS_FALLBACK = [
    "Just here for the vibes.",
    "Gaming | Coding | Music",
    "Late night explorer. Coffee powered.",
    "Building things on the internet.",
    "Probably afk right now.",
]
_PRONOUNS_FALLBACK = ["he/him", "she/her", "they/them", "ask me"]


def get_random_name() -> str:
    """Pick a random display name from names.txt (or fallback)."""
    pool = _NAMES_CACHE if _NAMES_CACHE else _NAMES_FALLBACK
    return random.choice(pool)


def get_random_bio() -> str:
    """Pick a random bio from bios.txt (or fallback)."""
    pool = _BIOS_CACHE if _BIOS_CACHE else _BIOS_FALLBACK
    return random.choice(pool)


def get_random_pronouns() -> str:
    """Pick random pronouns from pronouns.txt (or fallback)."""
    pool = _PRONOUNS_CACHE if _PRONOUNS_CACHE else _PRONOUNS_FALLBACK
    return random.choice(pool)


def _load_avatar_from_folder() -> Optional[str]:
    """
    Pick a random .png/.jpg image from the avatar/ folder and return as a data URL.
    Returns None if the folder is empty or doesn't exist.
    """
    if not AVATAR_DIR.exists():
        return None

    extensions = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG")
    images: list = []
    for ext in extensions:
        images.extend(AVATAR_DIR.glob(ext))

    if not images:
        return None

    picked = random.choice(images)
    try:
        raw = picked.read_bytes()
    except Exception:
        return None

    ext_lower = picked.suffix.lower()
    if ext_lower == ".png":
        mime = "image/png"
    elif ext_lower in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    else:
        mime = "image/png"

    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def random_avatar_data_url() -> str:
    """
    Return a data URL for an avatar.

    Priority:
      1. Random image from avatar/ folder (if it exists and has images)
      2. Fallback: generated 256x256 random-color PNG via Pillow
    """
    # Try the avatar/ folder first
    avatar = _load_avatar_from_folder()
    if avatar:
        return avatar

    # Fallback: generate a random colored PNG
    if not _HAS_PIL:
        return (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )

    img = Image.new("RGB", (256, 256))
    draw = ImageDraw.Draw(img)
    for x in range(256):
        r = int(random.randint(40, 220))
        g = int(random.randint(40, 220))
        b = int(random.randint(40, 220))
        draw.line([(x, 0), (x, 256)], fill=(r, g, b))
    cx, cy = 128, 110
    draw.ellipse([cx-45, cy-45, cx+45, cy+45], fill=(255, 255, 255, 230))
    draw.ellipse([cx-12, cy-12, cx+12, cy+12], fill=(40, 40, 40))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"



async def _humanize_patch(
    token: str,
    payload: dict,
    logger: logging.Logger,
    label: str,
) -> tuple[bool, str, Optional[dict]]:
    """Send a single PATCH /users/@me with retry-once on rate limit. Returns (ok, msg, json)."""
    try:
        async with httpx.AsyncClient(timeout=CFG["api_timeout"], follow_redirects=True) as client:
            r = await client.patch(
                f"{DISCORD_API}/users/@me",
                headers=api_headers(token, is_write=True),
                json=payload,
            )
    except httpx.RequestError as e:
        return False, f"Network error during {label}: {e}", None

    if r.status_code == 200:
        try:
            data = r.json()
        except Exception:
            data = None
        return True, f"{label} OK.", data

    if r.status_code == 429:
        try:
            body = r.json()
            retry = float(body.get("retry_after", 5))
        except Exception:
            retry = 5.0
        logger.warning(f"{label} rate-limited, sleeping {retry}s")
        await asyncio.sleep(retry + 0.5)
        try:
            async with httpx.AsyncClient(timeout=CFG["api_timeout"], follow_redirects=True) as client:
                r = await client.patch(
                    f"{DISCORD_API}/users/@me",
                    headers=api_headers(token, is_write=True),
                    json=payload,
                )
            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = None
                return True, f"{label} OK (after rate-limit retry).", data
        except Exception as e:
            return False, f"{label} retry error: {e}", None

    # Failed — surface the FULL raw response for debugging
    raw_text = r.text[:500] if r.text else "(empty body)"
    try:
        body = r.json()
        msg = body.get("message", "") or "(no message field)"
        errors = body.get("errors")
        if errors:
            msg += f" | details: {json.dumps(errors)[:300]}"
        code = body.get("code", "")
        if code:
            msg += f" | code: {code}"
    except Exception:
        msg = f"non-JSON response: {raw_text}"
    return False, f"{label} failed: HTTP {r.status_code} — {msg} | raw: {raw_text[:200]}", None


# Path to Humanizer.exe — use absolute path based on script location
_SCRIPT_DIR = Path(__file__).parent.resolve() if "__file__" in dir() else Path.cwd()
HUMANIZER_EXE = _SCRIPT_DIR / "Humanizer.exe"


async def humanize_account(account: Account, logger: logging.Logger) -> tuple[bool, str]:
    """
    Humanize the account using Humanizer.exe.

    The exe is called with the token as a command-line argument:
        Humanizer.exe <token>

    The exe reads from bios.txt, names.txt, pronouns.txt, and the avatar/ folder
    and handles the Discord API calls (avatar, bio, display name, pronouns).

    If Humanizer.exe is not found or fails, returns False (non-fatal — bot continues).
    """
    token = account.token
    if not token:
        return False, "No token available for humanize step."

    # ── Check if Humanizer.exe exists (check multiple locations) ──────────────
    exe_path = None
    candidates = [
        HUMANIZER_EXE,                              # script dir
        Path("Humanizer.exe"),                      # cwd
        Path.cwd() / "Humanizer.exe",               # cwd absolute
        _SCRIPT_DIR / "Humanizer.exe",              # script dir absolute
    ]
    for cand in candidates:
        if cand.exists():
            exe_path = cand.resolve()
            break

    if not exe_path:
        log_warn("Humanizer.exe not found — skipping humanize (non-fatal).")
        log_info("Place Humanizer.exe in the same folder as z_trigger.py.")
        return False, "Humanizer.exe not found (non-fatal)"

    # ── Run Humanizer.exe with the token ─────────────────────────────────────
    log_info(f"Running Humanizer.exe for token ...{account.label}")
    log_info(f"Exe path: {exe_path}")

    # Also write the token to a temp file in case the exe reads from stdin/file
    token_file = _SCRIPT_DIR / "token.txt"
    try:
        token_file.write_text(token, encoding="utf-8")
    except Exception:
        pass

    # Detect platform — on macOS/Linux, Windows .exe files need Wine
    import platform
    is_windows = platform.system() == "Windows"
    wine_path = os.getenv("WINE_PATH", "wine")

    try:
        if is_windows:
            # Windows: run the exe directly
            log_info("Platform: Windows — running exe directly")
            proc = await asyncio.create_subprocess_exec(
                str(exe_path),
                token,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_SCRIPT_DIR),
            )
        else:
            # macOS/Linux: run via Wine
            log_info(f"Platform: {platform.system()} — running exe via Wine ({wine_path})")
            log_info(f"Working directory: {_SCRIPT_DIR}")
            # Set PYTHONIOENCODING=utf-8 to fix UnicodeEncodeError when the exe
            # tries to print Unicode characters (banner, emoji, etc.) under Wine.
            # Wine defaults to cp1252 which can't encode many Unicode chars.
            import subprocess as _sp
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            env["LANG"] = "en_US.UTF-8"
            env["LC_ALL"] = "en_US.UTF-8"
            # Use create_subprocess_shell to combine stdout+stderr for Wine
            cmd = f'"{wine_path}" "{exe_path}" "{token}" 2>&1'
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(_SCRIPT_DIR),
                env=env,
            )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            log_warn("Humanizer.exe timed out after 120s — continuing anyway.")
            return False, "Humanizer.exe timed out (non-fatal)"

        stdout_text = stdout_data.decode("utf-8", errors="ignore") if stdout_data else ""
        # stderr might be None if we merged it into stdout (Wine shell mode)
        stderr_text = ""
        if stderr_data:
            stderr_text = stderr_data.decode("utf-8", errors="ignore")
        return_code = proc.returncode

        logger.info(f"Humanizer.exe returned code {return_code}")
        logger.info(f"Humanizer.exe full output ({len(stdout_text)} chars): {stdout_text[:2000]}")

        # Print ALL output from the exe (not just first 5 lines)
        if stdout_text:
            log_info("=== Humanizer.exe output ===")
            for line in stdout_text.strip().split("\n"):
                if line.strip():
                    log_info(f"[Humanizer] {line.strip()}")
            log_info("=== End Humanizer.exe output ===")

        if stderr_text and not is_windows:
            # On Windows we keep stderr separate; on Wine it's merged into stdout
            log_info("=== Humanizer.exe stderr ===")
            for line in stderr_text.strip().split("\n"):
                if line.strip():
                    log_warn(f"[Humanizer stderr] {line.strip()}")

        if return_code == 0:
            log_ok("Humanizer.exe completed successfully.")
            return True, "Humanized via Humanizer.exe"
        else:
            log_warn(f"Humanizer.exe exited with code {return_code}")
            return False, f"Humanizer.exe exit code {return_code} (non-fatal)"

    except FileNotFoundError:
        if not is_windows:
            log_warn(f"Wine not found ({wine_path}) — install Wine to run Humanizer.exe on macOS/Linux.")
            log_info("Install with: brew install wine   (macOS)   or   sudo apt install wine   (Linux)")
        else:
            log_warn(f"Humanizer.exe not found at {exe_path} — skipping humanize.")
        return False, "Humanizer.exe/Wine not found (non-fatal)"
    except Exception as e:
        log_err(f"Error running Humanizer.exe: {e}")
        return False, f"Humanizer.exe error: {e} (non-fatal)"


async def _humanize_via_python(account: Account, logger: logging.Logger) -> tuple[bool, str]:
    """
    Built-in Python humanizer — used as fallback when Humanizer.exe is not available.
    Tries each field separately: bio, global_name, pronouns, avatar.
    """
    token = account.token
    if not token:
        return False, "No token available for humanize step."

    new_display_name = get_random_name()
    new_bio = get_random_bio()
    new_pronouns = get_random_pronouns()
    new_avatar = random_avatar_data_url()

    log_info(
        f"Humanizing (Python): avatar=NEW bio={CYN}{new_bio[:30]}{RS} "
        f"display_name={CYN}{new_display_name}{RS} pronouns={CYN}{new_pronouns}{RS}"
    )

    successes = []
    failures = []

    # Step 1: bio only
    ok1, msg1, _ = await _humanize_patch(token, {"bio": new_bio}, logger, "bio")
    if ok1:
        successes.append("bio")
    else:
        failures.append(f"bio: {msg1[:100]}")

    # Step 2: global_name (display name) only
    ok2, msg2, data2 = await _humanize_patch(token, {"global_name": new_display_name}, logger, "display_name")
    if ok2:
        successes.append("display_name")
        if data2:
            account.username = data2.get("global_name") or account.username
    else:
        failures.append(f"display_name: {msg2[:100]}")

    # Step 3: pronouns only
    ok3, msg3, _ = await _humanize_patch(token, {"pronouns": new_pronouns}, logger, "pronouns")
    if ok3:
        successes.append("pronouns")
    else:
        failures.append(f"pronouns: {msg3[:100]}")

    # Step 4: avatar only
    ok4, msg4, _ = await _humanize_patch(token, {"avatar": new_avatar}, logger, "avatar")
    if ok4:
        successes.append("avatar")
    else:
        failures.append(f"avatar: {msg4[:100]}")

    if successes:
        log_ok(f"Humanized: {CYN}{', '.join(successes)}{RS}" + (f" (failed: {len(failures)})" if failures else ""))
        return True, f"Humanized ({', '.join(successes)})"
    else:
        return False, f"All humanize fields failed: {'; '.join(failures[:2])}"


# ─────────────────────────────────────────────────────────────────────────────
# Browser automation helpers (nodriver)
# ─────────────────────────────────────────────────────────────────────────────
def get_brave_path() -> str:
    env_path = os.getenv("BRAVE_PATH", "")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/usr/bin/brave-browser",
        "/usr/bin/brave",
        "/snap/bin/brave",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p

    # Fall back to Chrome if Brave not found (nodriver supports Chrome too)
    chrome_candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for p in chrome_candidates:
        if os.path.exists(p):
            return p

    import shutil
    found = shutil.which("brave") or shutil.which("brave-browser") or shutil.which("chrome") or shutil.which("chromium")
    if found:
        return found

    raise FileNotFoundError(
        "Brave/Chrome browser not found. Install Brave from https://brave.com/download/ "
        "or set BRAVE_PATH in your .env file."
    )


def build_browser_args() -> list:
    """
    Build browser args for nodriver, including NopeCHA extension if configured.

    Set `nopecha_extension_path` in config.yaml or the NOPECHA_PATH env var
    to the folder containing the NopeCHA extension (unpacked).
    """
    args = [
        "--disable-blink-features=AutomationControlled",
    ]

    nopecha_path = (
        os.getenv("NOPECHA_PATH", "")
        or CFG.get("nopecha_extension_path", "")
        or ""
    )
    if nopecha_path and Path(nopecha_path).exists():
        args.append(f"--load-extension={nopecha_path}")
        args.append(f"--disable-extensions-except={nopecha_path}")
        log_ok(f"NopeCHA extension loaded from: {nopecha_path}")
    elif nopecha_path:
        log_warn(f"NopeCHA path configured but not found: {nopecha_path}")

    return args


# NopeCHA extension ID (fixed — same for all installs from nopecha.com)
NOPECHA_EXTENSION_ID = "dknlfmiahfcgjclgjepdohbbmdchhiaf"


async def inject_nopecha_api_key(tab: uc.Tab, api_key: str, logger: logging.Logger) -> bool:
    """
    Inject the NopeCHA API key into the extension's storage.

    NopeCHA stores its API key in chrome.storage.local. We navigate to the
    extension's options page (which has access to chrome.storage) and set it
    programmatically.

    The key persists in the browser profile, so this only needs to run once
    per profile. With nodriver's temp profiles, it runs every time.
    """
    if not api_key:
        return False

    log_info(f"Injecting NopeCHA API key into extension...")

    # NopeCHA's popup/options page — this is where chrome.storage is accessible
    options_url = f"chrome-extension://{NOPECHA_EXTENSION_ID}/popup.html"

    try:
        await tab.get(options_url)
        await asyncio.sleep(2)
    except Exception as e:
        log_warn(f"Could not open NopeCHA options page: {e}")
        log_info("Make sure the NopeCHA extension is properly loaded.")
        return False

    # Try to set the API key via chrome.storage.local
    # NopeCHA uses the key 'key' in chrome.storage.local
    key_escaped = api_key.replace("\\", "\\\\").replace("'", "\\'")
    script = (
        "(function(apiKey){"
        "return new Promise(function(resolve){"
        "try{"
        "if(typeof chrome==='undefined'||!chrome.storage||!chrome.storage.local){"
        "resolve(JSON.stringify({ok:false,error:'chrome.storage not available'}));return;"
        "}"
        "chrome.storage.local.set({key: apiKey, balance: 0}, function(){"
        # Verify it was set
        "chrome.storage.local.get(['key'], function(result){"
        "if(result && result.key === apiKey){"
        "resolve(JSON.stringify({ok:true}));"
        "}else{"
        "resolve(JSON.stringify({ok:false,error:'key mismatch after set'}));"
        "}"
        "});"
        "});"
        "}catch(e){resolve(JSON.stringify({ok:false,error:String(e)}));}"
        "});"
        "})('" + key_escaped + "')"
    )

    try:
        raw = await tab.evaluate(script, await_promise=True)
    except Exception as e:
        log_warn(f"NopeCHA key injection failed: {e}")
        return False

    if not raw:
        log_warn("NopeCHA key injection returned empty.")
        return False

    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        log_warn(f"NopeCHA key injection returned unparseable: {str(raw)[:200]}")
        return False

    if result.get("ok"):
        log_ok("NopeCHA API key injected successfully.")
        # Navigate back to discord.com
        await tab.get("https://discord.com/channels/@me")
        await asyncio.sleep(2)
        return True
    else:
        error = result.get("error", "unknown")
        log_warn(f"NopeCHA key injection failed: {error}")

        # Fallback: try setting via the options page UI (find input field)
        log_info("Trying UI-based key injection...")
        try:
            # Look for an input field on the options page
            ui_ok = await tab.evaluate(
                "(function(apiKey){"
                "try{"
                "var inputs=document.querySelectorAll('input[type=\"text\"],input[type=\"password\"],input:not([type])');"
                "for(var i=0;i<inputs.length;i++){"
                "var ph=inputs[i].placeholder||'';"
                "var name=inputs[i].name||'';"
                "var id=inputs[i].id||'';"
                "if(ph.toLowerCase().indexOf('key')!==-1||name.toLowerCase().indexOf('key')!==-1||id.toLowerCase().indexOf('key')!==-1){"
                "inputs[i].value=apiKey;"
                "inputs[i].dispatchEvent(new Event('input',{bubbles:true}));"
                "inputs[i].dispatchEvent(new Event('change',{bubbles:true}));"
                "return true;"
                "}"
                "}"
                # If no key-specific input found, try the first text input
                "if(inputs.length>0){"
                "inputs[0].value=apiKey;"
                "inputs[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "inputs[0].dispatchEvent(new Event('change',{bubbles:true}));"
                "return true;"
                "}"
                "return false;"
                "}catch(e){return false;}"
                "})('" + key_escaped + "')"
            )
            if ui_ok:
                # Try to click a save button
                await asyncio.sleep(1)
                save_clicked = await tab.evaluate(
                    "(function(){"
                    "var btns=document.querySelectorAll('button');"
                    "for(var i=0;i<btns.length;i++){"
                    "var t=(btns[i].innerText||'').trim().toLowerCase();"
                    "if(t.indexOf('save')!==-1||t.indexOf('apply')!==-1||t.indexOf('set')!==-1||t.indexOf('confirm')!==-1){"
                    "btns[i].click();return true;"
                    "}"
                    "}"
                    "return false;"
                    "})()"
                )
                if save_clicked:
                    log_ok("NopeCHA API key set via UI.")
                    await asyncio.sleep(1)
                    await tab.get("https://discord.com/channels/@me")
                    await asyncio.sleep(2)
                    return True
            log_warn("UI-based key injection also failed.")
        except Exception as e:
            log_warn(f"UI key injection error: {e}")

        # Navigate back to discord.com
        await tab.get("https://discord.com/channels/@me")
        await asyncio.sleep(2)
        return False


async def js(tab: uc.Tab, script: str):
    try:
        return await tab.evaluate(script)
    except Exception:
        return None


def safe_int(val, default: int = 0) -> int:
    try:
        return int(val)
    except Exception:
        return default


async def human_delay(min_ms: int = 500, max_ms: int = 1500) -> None:
    await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)


async def take_screenshot(tab: uc.Tab, label: str, tag: str) -> None:
    if not CFG["screenshot_on_error"]:
        return
    path = LOG_DIR / f"acct_{label}_{tag}_{int(time.time())}.png"
    try:
        await tab.save_screenshot(str(path))
    except Exception:
        pass


async def wait_for_url(tab: uc.Tab, text: str, timeout: float = 20) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            if text in (tab.url or ""):
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def js_click(tab: uc.Tab, text: str) -> bool:
    """Click first button/[role=button] whose innerText contains text."""
    script = (
        "(function(t){"
        "var els=Array.from(document.querySelectorAll('button,[role=\"button\"]'));"
        "for(var i=0;i<els.length;i++){"
        "if((els[i].innerText||'').indexOf(t)!==-1){els[i].click();return true;}"
        "}return false;"
        "})('" + text.replace("'", "\\'") + "')"
    )
    return bool(await js(tab, script))


async def js_click_any(tab: uc.Tab, text: str) -> bool:
    """Click any leaf element containing text (for card clicks)."""
    script = (
        "(function(t){"
        "var els=Array.from(document.querySelectorAll('*'));"
        "for(var i=0;i<els.length;i++){"
        "var el=els[i];"
        "if(el.childElementCount===0&&(el.innerText||'').indexOf(t)!==-1){el.click();return true;}"
        "}return false;"
        "})('" + text.replace("'", "\\'") + "')"
    )
    return bool(await js(tab, script))


async def wait_and_click(tab: uc.Tab, text: str, timeout: int = 15) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if await js_click(tab, text):
            return True
        await asyncio.sleep(1)
    return False


# ── Captcha detection ────────────────────────────────────────────────────────
_CAPTCHA_JS = (
    "(function(){"
    "var frames=document.querySelectorAll('iframe');"
    "for(var i=0;i<frames.length;i++){"
    "var src=frames[i].src||'';"
    "if(src.indexOf('hcaptcha')===-1 && src.indexOf('recaptcha')===-1 && src.indexOf('turnstile')===-1)continue;"
    "var el=frames[i];"
    "while(el){"
    "var s=window.getComputedStyle(el);"
    "if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;"
    "el=el.parentElement;"
    "}"
    "return true;"
    "}"
    "return false;"
    "})()"
)


async def check_captcha(tab: uc.Tab, logger: logging.Logger, timeout: int = 300) -> bool:
    """Block until visible captcha is solved or timeout. Returns True if solved/absent."""
    try:
        found = False
        for _ in range(5):
            if await js(tab, _CAPTCHA_JS):
                found = True
                break
            await asyncio.sleep(1)
        if not found:
            return True  # no captcha

        logger.warning("Captcha detected — waiting for manual solve.")
        log_warn("Captcha detected! Please solve it in the browser window.")
        log_info("The bot will continue automatically once solved.")

        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1
            if not await js(tab, _CAPTCHA_JS):
                log_ok("Captcha solved! Continuing...")
                logger.info(f"Captcha solved after {elapsed}s.")
                await asyncio.sleep(2)
                return True
            if elapsed % 20 == 0:
                log_info(f"Still waiting for captcha... ({elapsed}s)")
        logger.warning(f"Captcha timed out after {timeout}s.")
        log_warn("Captcha timeout — continuing anyway.")
        return False
    except Exception as e:
        logger.debug(f"Captcha check error: {e}")
        return True


# ── Token login (browser) ────────────────────────────────────────────────────
async def _wait_for_page_load(tab: uc.Tab, timeout: int = 30) -> bool:
    """Wait until document.readyState === 'complete' or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            state = await tab.evaluate("document.readyState")
            if state == "complete":
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def _check_logged_in(tab: uc.Tab) -> bool:
    """
    Check if the browser is logged into Discord.
    Returns True if the Discord app has loaded (not on login page).

    Uses window.location.href via JS (not tab.url) because tab.url can return
    empty string after a reload/navigation in nodriver.
    """
    try:
        # Get URL via JS evaluation — more reliable than tab.url after navigation
        href = await tab.evaluate("window.location.href")
        if not isinstance(href, str):
            href = str(href) if href else ""
        url = href or ""

        # URL-based check — if we're on /channels, /app, or quest-home, we're in
        if "channels/@me" in url or "/app" in url or "quest-home" in url:
            return True
        # If URL still has /login, we're NOT logged in
        if "/login" in url:
            return False
        # If URL is empty or still loading, can't tell yet
        if not url or "about:blank" in url:
            return False

        # JS-based check: is there a token in localStorage AND is the Discord
        # app shell loaded (look for the app container div)?
        result = await tab.evaluate(
            "(function(){"
            "try{"
            "var t=window.localStorage.getItem('token');"
            "if(!t || t==='null' || t==='\"\"') return false;"
            "var app=document.querySelector('[class*=\"app_\"]')||document.querySelector('[class*=\"base_\"]')||document.querySelector('#app-mount');"
            "return !!app;"
            "}catch(e){return false;}"
            "})()"
        )
        return bool(result)
    except Exception:
        return False


async def login_via_token(tab: uc.Tab, token: str, logger: logging.Logger) -> bool:
    """
    Inject the Discord token into the browser and log in.

    Uses the setInterval approach: continuously re-sets the token in localStorage
    every 10ms for 5 seconds, then reloads. The interval wins the race against
    Discord's JS which may clear localStorage on page load.

    After reload, waits up to 30 seconds for Discord to redirect to the app.
    Uses window.location.href (via JS) instead of tab.url because tab.url can
    return empty string after navigation in nodriver.
    """
    logger.debug("Injecting token into browser...")

    # Step 1: Navigate to discord.com login page (clean state)
    log_info("Opening Discord login page...")
    await tab.get("https://discord.com/login")
    await _wait_for_page_load(tab, timeout=20)
    await asyncio.sleep(3)

    for attempt in range(1, 4):
        logger.debug(f"Token injection attempt {attempt}/3...")
        log_info(f"Injecting token (attempt {attempt}/3)...")

        # Set up a setInterval that continuously re-sets the token every 10ms.
        # This races against Discord's JS which may clear localStorage on load.
        # The interval is cleared after 5 seconds.
        await js(tab, (
            "(function(t){"
            "try{"
            "window.localStorage.setItem('token', JSON.stringify(t));"
            "}catch(e){}"
            "if(window.__token_interval){clearInterval(window.__token_interval);}"
            "window.__token_interval=setInterval(function(){"
            "try{window.localStorage.setItem('token', JSON.stringify(t));}catch(e){}"
            "},10);"
            "setTimeout(function(){"
            "if(window.__token_interval){clearInterval(window.__token_interval);window.__token_interval=null;}"
            "},5000);"
            "})('" + token + "')"
        ))

        # Also immediately set via iframe (belt and suspenders)
        await js(tab, (
            "(function(t){"
            "try{"
            "var f=document.createElement('iframe');"
            "document.body.appendChild(f);"
            "f.contentWindow.localStorage.setItem('token', JSON.stringify(t));"
            "document.body.removeChild(f);"
            "}catch(e){}"
            "})('" + token + "')"
        ))

        # Give the setInterval a moment to run
        await asyncio.sleep(1)

        # Reload to apply the token. The setInterval will keep re-setting it
        # during the reload, winning the race against Discord's clear.
        log_info("Reloading page to log in...")
        try:
            await js(tab, "window.location.reload()")
        except Exception:
            # If JS eval fails (page mid-navigation), try tab.reload
            try:
                await tab.reload()
            except Exception:
                pass

        # Wait for Discord to load and redirect. Discord needs several seconds
        # to process the token and redirect from /login to /channels/@me.
        # Poll every 1 second for up to 30 seconds.
        log_info("Waiting for Discord to load (up to 30s)...")
        logged_in = False
        for wait_sec in range(30):
            await asyncio.sleep(1)
            try:
                if await _check_logged_in(tab):
                    logged_in = True
                    logger.debug(f"Login detected after {wait_sec+1}s")
                    break
            except Exception as e:
                logger.debug(f"Wait {wait_sec+1}s: check error: {e}")

        if logged_in:
            logger.info(f"Browser token login OK on attempt {attempt}.")
            log_ok("Logged into Discord successfully.")
            # Clear any remaining interval
            await js(tab, "if(window.__token_interval){clearInterval(window.__token_interval);window.__token_interval=null;}")
            # Navigate to quest-home
            log_info("Navigating to quest-home...")
            await tab.get("https://discord.com/quest-home")
            await _wait_for_page_load(tab, timeout=20)
            await asyncio.sleep(3)
            return True

        # Get current URL for logging (via JS, not tab.url)
        cur_url = ""
        try:
            cur_url = await tab.evaluate("window.location.href") or ""
        except Exception:
            pass
        log_warn(f"Login not detected after reload (attempt {attempt}). URL: {cur_url}")
        if attempt < 3:
            # Navigate back to login page for next attempt
            try:
                await tab.get("https://discord.com/login")
                await _wait_for_page_load(tab, timeout=15)
                await asyncio.sleep(2)
            except Exception:
                pass

    return False


# ── Browser-based humanize (fallback for HTTP "Unknown Session") ─────────────
async def _wait_for_discord_ready(tab: uc.Tab, timeout: int = 30) -> bool:
    """
    Wait until the Discord page is fully ready: localStorage is available,
    document is complete, and we're on a real discord.com page (not about:blank
    or a redirect page).

    This prevents 'Cannot read properties of undefined (reading getItem)' errors
    that happen when scripts run during page navigation.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            ready = await tab.evaluate(
                "(function(){"
                "try{"
                "if(document.readyState!=='complete')return false;"
                "if(typeof window.localStorage==='undefined'||!window.localStorage)return false;"
                "var href=window.location.href||'';"
                "if(!href||href.indexOf('about:')===0)return false;"
                "if(href.indexOf('discord.com')===-1)return false;"
                "return true;"
                "}catch(e){return false;}"
                "})()"
            )
            if ready:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def humanize_via_browser(
    tab: uc.Tab,
    account: Account,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """
    Humanize the account by running fetch() from inside the Discord browser
    session. The browser has real cookies + a real session context, so Discord
    accepts the PATCH.

    Used as a fallback when the HTTP API returns 400 'Unknown Session'.

    Changes: avatar (from pfp folder) + bio + global_name (display name).
    No password required — display name can be changed freely.

    Tries each field separately so that if one fails, the others still succeed.
    """
    # Navigate to /channels/@me (the main app) — this page has the most stable
    # localStorage context. quest-home sometimes has issues.
    log_info("Navigating to Discord app for humanize...")
    try:
        await tab.get("https://discord.com/channels/@me")
    except Exception:
        pass
    await asyncio.sleep(5)

    new_display_name = get_random_name()
    new_bio = get_random_bio()
    new_avatar = random_avatar_data_url()

    log_info(
        f"Humanizing via browser: avatar=NEW bio={CYN}{new_bio[:30]}{RS} "
        f"display_name={CYN}{new_display_name}{RS}"
    )
    logger.info(
        f"Browser humanize -> bio={new_bio!r} display_name={new_display_name!r}"
    )

    successes = []
    failures = []

    # Try each field separately — pass the token directly (no localStorage)
    # Step 1: bio only
    ok1, msg1 = await _browser_patch_user(tab, {"bio": new_bio}, logger, "bio", token=account.token)
    if ok1:
        successes.append("bio")
    else:
        failures.append(f"bio: {msg1[:80]}")

    # Step 2: global_name (display name) only
    ok2, msg2 = await _browser_patch_user(tab, {"global_name": new_display_name}, logger, "display_name", token=account.token)
    if ok2:
        successes.append("display_name")
        account.username = new_display_name
    else:
        failures.append(f"display_name: {msg2[:80]}")

    # Step 3: avatar only
    ok3, msg3 = await _browser_patch_user(tab, {"avatar": new_avatar}, logger, "avatar", token=account.token)
    if ok3:
        successes.append("avatar")
    else:
        failures.append(f"avatar: {msg3[:80]}")

    if successes:
        log_ok(f"Humanized via browser: {CYN}{', '.join(successes)}{RS}" + (f" (failed: {len(failures)})" if failures else ""))
        if failures:
            log_warn(f"Failed fields: {'; '.join(failures[:2])}")
        return True, f"Humanized via browser ({', '.join(successes)})"
    else:
        return False, f"All browser humanize fields failed: {'; '.join(failures[:2])}"


# ── UI-based humanize (clicks through Discord's settings like a real user) ────

async def _ui_wait_and_click_by_text(tab: uc.Tab, texts: list, timeout: int = 15) -> bool:
    """Wait for any of the given button texts to appear, then click it."""
    start = time.time()
    while time.time() - start < timeout:
        for text in texts:
            if await js_click(tab, text):
                return True
        # Also try clicking elements by aria-label
        for text in texts:
            clicked = await js(tab, (
                "(function(t){"
                "var els=Array.from(document.querySelectorAll('button,[role=\"button\"],div[aria-label]'));"
                "for(var i=0;i<els.length;i++){"
                "var aria=els[i].getAttribute('aria-label')||'';"
                "var txt=(els[i].innerText||'').trim();"
                "if(aria.indexOf(t)!==-1||txt.indexOf(t)!==-1){els[i].click();return true;}"
                "}"
                "return false;"
                "})('" + text.replace("'", "\\'") + "')"
            ))
            if clicked:
                return True
        await asyncio.sleep(1)
    return False


async def _ui_wait_for_captcha_solve(tab: uc.Tab, timeout: int = 120) -> bool:
    """
    Wait for NopeCHA to solve any captcha that appears.
    Returns True if captcha was solved or no captcha appeared.
    """
    captcha_detected = False
    for wait in range(timeout):
        await asyncio.sleep(1)
        has_captcha = await js(tab, (
            "(function(){"
            "var frames=document.querySelectorAll('iframe');"
            "for(var i=0;i<frames.length;i++){"
            "var src=frames[i].src||'';"
            "if(src.indexOf('hcaptcha')!==-1||src.indexOf('recaptcha')!==-1||src.indexOf('turnstile')!==-1){"
            "var el=frames[i];"
            "while(el){"
            "var s=window.getComputedStyle(el);"
            "if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;"
            "el=el.parentElement;"
            "}"
            "return true;"
            "}"
            "}"
            "return false;"
            "})()"
        ))
        if has_captcha and not captcha_detected:
            captcha_detected = True
            log_info("hCaptcha detected — waiting for NopeCHA to solve it...")
        if not has_captcha and captcha_detected:
            log_ok("Captcha solved by NopeCHA!")
            await asyncio.sleep(2)
            return True
        if wait % 15 == 14 and captcha_detected:
            log_info(f"Still waiting for NopeCHA to solve captcha... ({wait+1}s)")
    if captcha_detected:
        log_warn("Captcha was detected but NopeCHA didn't solve it in time.")
        return False
    return True  # no captcha appeared


async def humanize_via_ui(
    tab: uc.Tab,
    account: Account,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """
    Humanize the account by clicking through Discord's Edit Profile UI.

    Exact flow (matching how a real user does it):
      1. Click own avatar at bottom-left → opens profile popup
      2. Click "Edit Profiles" text (with pencil icon) → opens profile editor
      3. Click the center of the avatar in the editor → shows dropdown
      4. Click "Change Avatar" / "Add Avatar" → opens file picker
      5. Upload PFP file from pfp/ folder
      6. Set bio in the bio textarea
      7. Set display name in the display name input
      8. Click "Save Changes"
      9. Wait for NopeCHA to solve any captcha
    """
    new_display_name = get_random_name()
    new_bio = get_random_bio()

    # Pick a PFP file path from the pfp/ folder for upload
    pfp_file_path = None
    if AVATAR_DIR.exists():
        extensions = ("*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG")
        images: list = []
        for ext in extensions:
            images.extend(AVATAR_DIR.glob(ext))
        if images:
            pfp_file_path = random.choice(images)

    log_info(
        f"Humanizing via UI: avatar={'FILE' if pfp_file_path else 'NONE'} "
        f"bio={CYN}{new_bio[:30]}{RS} display_name={CYN}{new_display_name}{RS}"
    )
    logger.info(f"UI humanize -> bio={new_bio!r} display_name={new_display_name!r} pfp={pfp_file_path}")

    # Make sure we're on the Discord app (not settings page)
    try:
        href = await tab.evaluate("window.location.href")
    except Exception:
        href = ""
    if not href or "discord.com/channels" not in str(href):
        log_info("Navigating to Discord app...")
        await tab.get("https://discord.com/channels/@me")
        await asyncio.sleep(5)

    # ── Step 1: Click own avatar at bottom-left to open profile popup ────────
    log_info("Clicking own avatar at bottom-left...")
    avatar_panel_opened = False
    for attempt in range(15):
        clicked = await js(tab, (
            "(function(){"
            # The user's own avatar is at the bottom-left, near the settings gear.
            # It's usually a clickable button/div with an avatar image.
            "var btns=document.querySelectorAll('button,div[role=\"button\"]');"
            "for(var i=btns.length-1;i>=0;i--){"
            "var aria=btns[i].getAttribute('aria-label')||'';"
            "var rect=btns[i].getBoundingClientRect();"
            # Bottom-left area: left < 100, bottom of screen (top > window.innerHeight-150)
            "if(rect.left<120&&rect.bottom>window.innerHeight-100&&rect.bottom<window.innerHeight-10){"
            # Check if it contains an avatar image or has avatar-related attributes
            "var img=btns[i].querySelector('img');"
            "if(img||aria.toLowerCase().indexOf('profile')!==-1||btns[i].className.indexOf('avatar')!==-1){"
            "btns[i].click();return true;"
            "}"
            "}"
            "}"
            "return false;"
            "})()"
        ))
        if clicked:
            avatar_panel_opened = True
            log_ok("Clicked own avatar — profile popup should be open.")
            break
        await asyncio.sleep(1)

    if not avatar_panel_opened:
        log_warn("Could not click own avatar — trying direct profile navigation...")
        await tab.get("https://discord.com/channels/@me")
        await asyncio.sleep(3)
        # Try again after navigation
        for attempt in range(5):
            clicked = await js(tab, (
                "(function(){"
                "var btns=document.querySelectorAll('button,div[role=\"button\"]');"
                "for(var i=btns.length-1;i>=0;i--){"
                "var rect=btns[i].getBoundingClientRect();"
                "if(rect.left<120&&rect.bottom>window.innerHeight-100&&rect.bottom<window.innerHeight-10){"
                "var img=btns[i].querySelector('img');"
                "if(img){btns[i].click();return true;}"
                "}"
                "}"
                "return false;"
                "})()"
            ))
            if clicked:
                avatar_panel_opened = True
                log_ok("Clicked own avatar (retry).")
                break
            await asyncio.sleep(1)

    await asyncio.sleep(3)

    # ── Step 2: Click "Edit Profiles" text (with pencil icon) ────────────────
    log_info("Looking for 'Edit Profiles' text...")
    edit_clicked = False
    for attempt in range(10):
        # Click on text containing "Edit Profile" or "Edit Profiles"
        edit_clicked = await js(tab, (
            "(function(){"
            # Find elements with "Edit Profile" or "Edit Profiles" text
            "var els=document.querySelectorAll('*');"
            "for(var i=0;i<els.length;i++){"
            "var el=els[i];"
            "if(el.childElementCount>2)continue;"  # Only leaf-ish elements
            "var t=(el.innerText||'').trim();"
            "var lc=t.toLowerCase();"
            "if(lc==='edit profiles'||lc==='edit profile'||(lc.indexOf('edit profile')!==-1&&t.length<30)){"
            "el.click();return true;"
            "}"
            "}"
            # Also try clicking by aria-label
            "var ariaEls=document.querySelectorAll('[aria-label]');"
            "for(var i=0;i<ariaEls.length;i++){"
            "var a=(ariaEls[i].getAttribute('aria-label')||'').toLowerCase();"
            "if(a.indexOf('edit profile')!==-1){ariaEls[i].click();return true;}"
            "}"
            "return false;"
            "})()"
        ))
        if edit_clicked:
            log_ok("Clicked 'Edit Profiles'.")
            break
        await asyncio.sleep(1)

    if not edit_clicked:
        log_warn("Could not click 'Edit Profiles' — trying settings/profile navigation...")
        await tab.get("https://discord.com/settings/profile")
        await asyncio.sleep(4)

    await asyncio.sleep(4)  # Wait for the profile editor to load

    # ── Step 3: Click the center of the avatar to show "Change/Add Avatar" ───
    if pfp_file_path:
        log_info("Clicking avatar in profile editor to show options...")
        await asyncio.sleep(2)

        avatar_clicked = False
        for attempt in range(10):
            avatar_clicked = await js(tab, (
                "(function(){"
                # The avatar in the profile editor is the large circular image
                # at the top-center of the edit panel.
                # Find the largest avatar image and click it.
                "var imgs=document.querySelectorAll('img');"
                "var best=null;var bestSize=0;"
                "for(var i=0;i<imgs.length;i++){"
                "var src=imgs[i].src||'';"
                "var rect=imgs[i].getBoundingClientRect();"
                # Avatar images: width 80-200px, in the center area
                "if(rect.width>60&&rect.width<250&&rect.left>100&&rect.left<600&&rect.top>50&&rect.top<300){"
                "var size=rect.width*rect.height;"
                "if(size>bestSize){bestSize=size;best=imgs[i];}"
                "}"
                "}"
                "if(best){"
                # Click the parent container (the clickable avatar wrapper)
                "var parent=best.closest('div[role=\"button\"],button,div[class*=\"avatar\"],div[class*=\"wrapper\"]');"
                "if(parent){parent.click();return true;}"
                "best.click();return true;"
                "}"
                # Fallback: click divs with avatar class
                "var avEls=document.querySelectorAll('div[class*=\"avatar\"],div[class*=\"Avatar\"]');"
                "for(var i=0;i<avEls.length;i++){"
                "var rect=avEls[i].getBoundingClientRect();"
                "if(rect.width>60&&rect.width<250&&rect.left>100&&rect.left<600&&rect.top>50&&rect.top<300){"
                "avEls[i].click();return true;"
                "}"
                "}"
                "return false;"
                "})()"
            ))
            if avatar_clicked:
                log_ok("Clicked avatar in editor.")
                break
            await asyncio.sleep(1)

        if avatar_clicked:
            await asyncio.sleep(2)
            # ── Step 4: Click "Change Avatar" or "Add Avatar" ──────────────────
            log_info("Looking for 'Change Avatar' / 'Add Avatar' option...")
            change_clicked = False
            for attempt in range(8):
                change_clicked = await js(tab, (
                    "(function(){"
                    "var els=document.querySelectorAll('button,div[role=\"button\"],div,span');"
                    "for(var i=0;i<els.length;i++){"
                    "var t=(els[i].innerText||'').trim().toLowerCase();"
                    "if(t==='change avatar'||t==='add avatar'||t==='change avatar.'||t.indexOf('change avatar')!==-1||t.indexOf('add avatar')!==-1){"
                    "els[i].click();return true;"
                    "}"
                    "}"
                    "return false;"
                    "})()"
                ))
                if change_clicked:
                    log_ok("Clicked 'Change Avatar' / 'Add Avatar'.")
                    break
                await asyncio.sleep(1)

            if not change_clicked:
                log_warn("Change Avatar option not found — trying file input directly...")

            # ── Step 5: Upload PFP file ────────────────────────────────────────
            await asyncio.sleep(2)
            log_info(f"Uploading PFP: {pfp_file_path.name}")
            try:
                file_input = await tab.find('input[type="file"]', timeout=10)
                if file_input:
                    await file_input.send_file(str(pfp_file_path))
                    log_ok("PFP uploaded.")
                    await asyncio.sleep(3)
                else:
                    log_warn("No file input found for avatar upload.")
            except Exception as e:
                log_warn(f"Avatar upload failed: {e}")

    # ── Step 6: Set bio ──────────────────────────────────────────────────────
    log_info(f"Setting bio: {CYN}{new_bio[:40]}{RS}")
    await asyncio.sleep(1)
    bio_set = await js(tab, (
        "(function(bio){"
        "var textareas=document.querySelectorAll('textarea');"
        "for(var i=0;i<textareas.length;i++){"
        "var ph=(textareas[i].placeholder||'').toLowerCase();"
        "var aria=(textareas[i].getAttribute('aria-label')||'').toLowerCase();"
        "if(ph.indexOf('vibe')!==-1||ph.indexOf('haiku')!==-1||ph.indexOf('bio')!==-1||ph.indexOf('about')!==-1||ph.indexOf('describe')!==-1){"
        "var ns=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;"
        "ns.call(textareas[i],bio);"
        "textareas[i].dispatchEvent(new Event('input',{bubbles:true}));"
        "textareas[i].dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;"
        "}"
        "}"
        # Fallback: first textarea in center area
        "for(var i=0;i<textareas.length;i++){"
        "var rect=textareas[i].getBoundingClientRect();"
        "if(rect.left>200&&rect.top>100&&rect.top<600){"
        "var ns=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;"
        "ns.call(textareas[i],bio);"
        "textareas[i].dispatchEvent(new Event('input',{bubbles:true}));"
        "textareas[i].dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;"
        "}"
        "}"
        "return false;"
        "})('" + new_bio.replace("'", "\\'") + "')"
    ))
    if bio_set:
        log_ok("Bio set.")
    else:
        log_warn("Could not find bio textarea.")

    # ── Step 7: Set display name ─────────────────────────────────────────────
    log_info(f"Setting display name: {CYN}{new_display_name}{RS}")
    await asyncio.sleep(1)
    name_set = await js(tab, (
        "(function(name){"
        "var inputs=document.querySelectorAll('input[type=\"text\"]');"
        "for(var i=0;i<inputs.length;i++){"
        "var ph=(inputs[i].placeholder||'').toLowerCase();"
        "var aria=(inputs[i].getAttribute('aria-label')||'').toLowerCase();"
        "if(ph.indexOf('display')!==-1||aria.indexOf('display')!==-1||ph.indexOf('name')!==-1){"
        "var ns=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "ns.call(inputs[i],name);"
        "inputs[i].dispatchEvent(new Event('input',{bubbles:true}));"
        "inputs[i].dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;"
        "}"
        "}"
        # Fallback: first text input in center area
        "for(var i=0;i<inputs.length;i++){"
        "var rect=inputs[i].getBoundingClientRect();"
        "if(rect.left>200&&rect.top>100&&rect.top<400){"
        "var ns=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;"
        "ns.call(inputs[i],name);"
        "inputs[i].dispatchEvent(new Event('input',{bubbles:true}));"
        "inputs[i].dispatchEvent(new Event('change',{bubbles:true}));"
        "return true;"
        "}"
        "}"
        "return false;"
        "})('" + new_display_name.replace("'", "\\'") + "')"
    ))
    if name_set:
        log_ok("Display name set.")
    else:
        log_warn("Could not find display name input.")

    # ── Step 8: Click "Save Changes" ─────────────────────────────────────────
    log_info("Looking for Save Changes button...")
    await asyncio.sleep(1)
    save_clicked = await _ui_wait_and_click_by_text(tab, ["Save Changes", "Save"], timeout=10)
    if save_clicked:
        log_ok("Clicked Save Changes.")
    else:
        save_clicked = await js(tab, (
            "(function(){"
            "var btns=document.querySelectorAll('button');"
            "for(var i=0;i<btns.length;i++){"
            "var t=(btns[i].innerText||'').trim().toLowerCase();"
            "var rect=btns[i].getBoundingClientRect();"
            "if(t.indexOf('save')!==-1&&rect.top>200){"
            "btns[i].click();return true;"
            "}"
            "}"
            "return false;"
            "})()"
        ))
        if save_clicked:
            log_ok("Clicked Save button.")
        else:
            log_warn("Save Changes button not found — changes may auto-save.")

    # No captcha wait here — humanize doesn't trigger captcha.
    # Captcha appears later when claiming quest rewards, and NopeCHA handles it there.
    await asyncio.sleep(2)
    log_ok("Humanize via UI complete.")
    account.username = new_display_name
    return True, "Humanized via UI"


async def _browser_patch_user(
    tab: uc.Tab,
    payload: dict,
    logger: logging.Logger,
    label: str,
    token: str = "",
) -> tuple[bool, str]:
    """
    Run fetch() inside the browser to PATCH /users/@me.

    The token is injected directly into the JS — no localStorage needed.
    This avoids the 'localStorage not available' error that happens during
    page navigation.
    """
    # Serialize the payload safely as JSON inside JS
    payload_json = json.dumps(payload)
    payload_js = payload_json.replace("\\", "\\\\").replace("'", "\\'")

    # Escape the token for JS string
    token_js = token.replace("\\", "\\\\").replace("'", "\\'") if token else ""

    # Build the JS — token is passed directly, no localStorage reading
    script = (
        "(function(payload_str, token_str){"
        "return new Promise(function(resolve){"
        "try{"
        "var body=JSON.parse(payload_str);"
        "var token=token_str;"
        "if(!token){resolve(JSON.stringify({status:401,body:'no token provided'}));return;}"
        "var sp={os:'Windows',browser:'Chrome',device:'',system_locale:'en-US',browser_version:'126.0.0.0',os_version:'10',referrer:'',referring_domain:'',referrer_current:'',referring_domain_current:'',release_channel:'stable',client_build_number:298682,client_event_source:null};"
        "var spB64=btoa(JSON.stringify(sp));"
        "fetch('/api/v9/users/@me',{"
        "method:'PATCH',"
        "headers:{"
        "'Content-Type':'application/json',"
        "'Authorization':token,"
        "'X-Super-Properties':spB64,"
        "'X-Discord-Locale':'en-US',"
        "'Origin':'https://discord.com',"
        "'Referer':'https://discord.com/channels/@me'"
        "},"
        "credentials:'include',"
        "body:JSON.stringify(body)"
        "}).then(function(r){"
        "return r.text().then(function(t){"
        "resolve(JSON.stringify({status:r.status,body:t}));"
        "});"
        "}).catch(function(e){"
        "resolve(JSON.stringify({status:0,body:String(e)}));"
        "});"
        "}catch(e){resolve(JSON.stringify({status:-1,body:String(e)}));}"
        "});"
        "})('" + payload_js + "','" + token_js + "')"
    )

    try:
        raw = await tab.evaluate(script, await_promise=True)
    except Exception as e:
        return False, f"{label} browser fetch error: {e}"

    if not raw:
        return False, f"{label} browser fetch returned empty."

    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return False, f"{label} browser fetch returned unparseable: {str(raw)[:200]}"

    status = int(result.get("status", 0))
    body_text = result.get("body", "")

    if status == 200:
        try:
            data = json.loads(body_text)
            logger.info(f"{label} OK via browser.")
            return True, f"{label} OK."
        except Exception:
            logger.info(f"{label} OK via browser (non-JSON body).")
            return True, f"{label} OK."

    # Failed — surface the full error
    try:
        body_json = json.loads(body_text)
        msg = body_json.get("message", "") or "(no message)"
        errors = body_json.get("errors")
        if errors:
            msg += f" | details: {json.dumps(errors)[:200]}"
        code = body_json.get("code", "")
        if code:
            msg += f" | code: {code}"
        captcha = body_json.get("captcha_key")
        if captcha:
            msg += f" | captcha required"
    except Exception:
        msg = body_text[:200]
    return False, f"{label} failed in browser: HTTP {status} — {msg}"


# ─────────────────────────────────────────────────────────────────────────────
# Quest completion via Discord API (no DOM clicking)
#
# Based on the approach from github.com/nyxxbit/discord-quest-completer:
#   1. GET /users/@me/quests           -> fetch the user's available quests
#   2. POST /quests/{id}/enroll        -> accept the quest (if not enrolled)
#   3. POST /quests/{id}/video-progress -> send fake timestamps until target reached
#   4. POST /quests/{id}/claim-reward   -> claim the Orbs reward
#
# All requests are run via fetch() from inside the browser tab, so Discord
# sees real cookies + real X-Super-Properties. No UI clicking = resilient
# to Discord layout changes.
# ─────────────────────────────────────────────────────────────────────────────

# Quest IDs known to break enrollment (from Orion's blacklist)
_BLACKLISTED_QUEST_ID = "1412491570820812933"


# ─────────────────────────────────────────────────────────────────────────────
# Console-injection quest completion
#
# Injects JavaScript directly into Discord's web client (like pasting into
# DevTools console). Uses Discord's internal webpack modules (QuestStore + API)
# to access the quest API with real session context.
#
# Based on github.com/nyxxbit/discord-quest-completer — condensed to:
#   1. Find first WATCH_VIDEO quest (only ONE quest, as requested)
#   2. Enroll if needed
#   3. Send fake video-progress timestamps until complete
#   4. Claim the reward
# ─────────────────────────────────────────────────────────────────────────────

# The full JS script as a single string. Injected via tab.evaluate().
# It uses Discord's own API module (found via webpack module extraction) so
# all requests have proper Authorization + X-Super-Properties headers.
_QUEST_CONSOLE_JS = r"""
(async () => {
    "use strict";

    function result(ok, data) {
        try { return JSON.stringify({ ok: ok, ...data }); }
        catch(e) { return JSON.stringify({ ok: false, error: "result() failed: " + String(e) }); }
    }

    function errStr(e) {
        try {
            if (e && e.body && typeof e.body === 'object') return JSON.stringify(e.body).slice(0, 300);
            if (e && e.status) return 'HTTP ' + e.status;
            if (e && e.message) return e.message;
            return String(e);
        } catch(_) { return String(e); }
    }

    function notExpired(q) {
        try {
            const e = new Date(q.config?.expiresAt ?? 0).getTime();
            return Number.isNaN(e) || e > Date.now();
        } catch(_) { return true; }
    }

    try {
        if (typeof webpackChunkdiscord_app === 'undefined') {
            return result(false, { error: 'webpackChunkdiscord_app not found' });
        }

        let req;
        try {
            webpackChunkdiscord_app.push([[Symbol()], {}, (r) => {
                const cur = Object.keys(req?.c || {}).length;
                const incoming = Object.keys(r?.c || {}).length;
                if (incoming > cur) req = r;
            }]);
            webpackChunkdiscord_app.pop();
        } catch(e) {
            return result(false, { error: 'webpack extraction failed: ' + String(e) });
        }

        if (!req || !req.c) return result(false, { error: 'Module registry not available' });

        const modules = Object.values(req.c);

        function findStore(storeName) {
            try {
                for (const m of modules) {
                    try {
                        const exp = m?.exports;
                        if (!exp || typeof exp !== 'object') continue;
                        for (const key of Object.keys(exp)) {
                            const prop = exp[key];
                            if (prop && typeof prop === 'object') {
                                try {
                                    if (prop.__proto__?.constructor?.displayName === storeName) return prop;
                                } catch(_) {}
                            }
                        }
                    } catch (e) {}
                }
            } catch(e) {}
            return undefined;
        }

        function findAPI() {
            try {
                for (const m of modules) {
                    try {
                        const exp = m?.exports;
                        if (!exp || typeof exp !== 'object') continue;
                        for (const key of Object.keys(exp)) {
                            const prop = exp[key];
                            if (prop && typeof prop.get === 'function'
                                && typeof prop.post === 'function'
                                && typeof prop.del === 'function'
                                && !prop._dispatcher) return prop;
                        }
                    } catch (e) {}
                }
            } catch(e) {}
            return undefined;
        }

        const QuestStore = findStore('QuestStore');
        const API = findAPI();

        if (!QuestStore) return result(false, { error: 'QuestStore not found', moduleCount: modules.length });
        if (!API) return result(false, { error: 'API module not found', moduleCount: modules.length });

        const BLACKLISTED = '1412491570820812933';

        function getQuests() {
            try {
                const q = QuestStore.quests;
                if (!q) return [];
                return q instanceof Map ? [...q.values()] : Object.values(q);
            } catch(e) { return []; }
        }

        function detectType(cfg, applicationId) {
            try {
                const taskKeys = Object.keys(cfg.tasks);
                const typeMap = [
                    { key: 'PLAY', type: 'GAME' },
                    { key: 'STREAM', type: 'STREAM' },
                    { key: 'VIDEO', type: 'WATCH_VIDEO' },
                    { key: 'ACHIEVEMENT_IN_ACTIVITY', type: 'ACHIEVEMENT' },
                    { key: 'ACTIVITY', type: 'ACTIVITY' }
                ];
                for (const { key, type } of typeMap) {
                    const keyName = taskKeys.find(k => k.includes(key));
                    if (keyName) return { type, keyName, target: cfg.tasks[keyName]?.target ?? 0 };
                }
                if (applicationId) return { type: 'GAME', keyName: 'PLAY_ON_DESKTOP', target: cfg.tasks[taskKeys[0]]?.target ?? 0 };
                return null;
            } catch(e) { return null; }
        }

        function findAllQuests(quests) {
            const found = [];
            for (const quest of quests) {
                try {
                    if (!quest || !quest.id || quest.id === BLACKLISTED) continue;
                    if (quest.userStatus?.completedAt) continue;
                    if (!notExpired(quest)) continue;
                    const cfg = quest.config?.taskConfig ?? quest.config?.taskConfigV2;
                    if (!cfg?.tasks) continue;
                    const app = quest.config?.application?.id;
                    const typeData = detectType(cfg, app);
                    if (typeData) found.push({ quest, type: typeData.type, keyName: typeData.keyName, target: typeData.target });
                } catch(e) {}
            }
            const priority = { 'WATCH_VIDEO': 0, 'ACTIVITY': 1, 'ACHIEVEMENT': 2, 'GAME': 3, 'STREAM': 4 };
            found.sort((a, b) => (priority[a.type] ?? 9) - (priority[b.type] ?? 9));
            return found;
        }

        function findChannel() {
            try {
                const ChanStore = findStore('ChannelStore');
                if (ChanStore) {
                    const dms = ChanStore.getSortedPrivateChannels?.();
                    if (dms && dms[0]) return dms[0].id;
                }
                const GuildChanStore = findStore('GuildChannelStore');
                if (GuildChanStore) {
                    const guilds = GuildChanStore.getAllGuilds?.() ?? {};
                    for (const g of Object.values(guilds)) {
                        const vc = g?.VOCAL?.[0]?.channel?.id;
                        if (vc) return vc;
                    }
                }
            } catch (e) {}
            return null;
        }

        let quests = getQuests();
        let allQuests = findAllQuests(quests);

        for (let wait = 0; wait < 30 && allQuests.length === 0; wait++) {
            await new Promise(r => setTimeout(r, 1000));
            quests = getQuests();
            allQuests = findAllQuests(quests);
        }

        if (allQuests.length === 0) {
            return result(false, {
                error: 'No quests found after waiting 30s',
                totalQuests: quests.length,
                questNames: quests.map(q => q.config?.messages?.questName ?? q.id).slice(0, 10)
            });
        }

        // FIRST: Check for already-completed quests that haven't been claimed
        for (const quest of quests) {
            try {
                if (!quest || !quest.id || quest.id === BLACKLISTED) continue;
                if (quest.userStatus?.completedAt && !quest.userStatus?.claimedAt) {
                    const questName = quest.config?.messages?.questName ?? 'Unknown Quest';
                    const questId = quest.id;
                    try {
                        const claimRes = await API.post({
                            url: '/quests/' + questId + '/claim-reward',
                            body: { platform: 0, location: 11, is_targeted: false, metadata_raw: null, metadata_sealed: null, traffic_metadata_raw: null, traffic_metadata_sealed: null }
                        });
                        if (claimRes?.body?.claimed_at || claimRes?.status === 200) {
                            return result(true, { questName: questName + ' (already completed)', questId, calls: 0, target: 0, triedQuests: [questName + ' (claimed)'], claimed: true });
                        }
                    } catch (e) {
                        const needsCaptcha = e?.body?.captcha_key || e?.body?.captcha_sitekey;
                        if (needsCaptcha) {
                            return result(true, { questName: questName + ' (already completed)', questId, calls: 0, target: 0, triedQuests: [questName + ' (captcha)'], claimed: false, captchaRequired: true });
                        }
                    }
                }
            } catch(e) {}
        }

        // SECOND: Try to complete ONE quest, then claim it
        const triedQuests = [];
        const q = allQuests[0];
        const targetQuest = q.quest;
        const questType = q.type;
        const keyName = q.keyName;
        const target = q.target;
        const questName = targetQuest.config?.messages?.questName ?? 'Unknown Quest';
        const questId = targetQuest.id;

        triedQuests.push(questName + ' (' + questType + ')');

        // Enroll if needed
        if (!targetQuest.userStatus?.enrolledAt) {
            try {
                await API.post({ url: '/quests/' + questId + '/enroll', body: { location: 11, is_targeted: false } });
                await new Promise(r => setTimeout(r, 1000 + Math.random() * 500));
            } catch (e) {}
        }

        let completed = false;
        let calls = 0;

        if (questType === 'WATCH_VIDEO') {
            let cur = 0.2 + Math.random() * 0.05;
            let initOk = true;
            try {
                await API.post({ url: '/quests/' + questId + '/video-progress', body: { timestamp: Number(cur.toFixed(6)) } });
            } catch (e) { initOk = false; }

            if (initOk) {
                const startTime = Date.now();
                const MAX_TIME = 5 * 60 * 1000;
                while (cur < target && (Date.now() - startTime) < MAX_TIME) {
                    const delayMs = 3500 + Math.floor(Math.random() * 1250);
                    await new Promise(r => setTimeout(r, delayMs));
                    cur += (delayMs / 1000) + (Math.random() * 0.02 - 0.01);
                    const payloadTs = Number(Math.min(target, cur).toFixed(6));
                    try {
                        const r = await API.post({ url: '/quests/' + questId + '/video-progress', body: { timestamp: payloadTs } });
                        calls++;
                        const sv = r?.body?.progress?.[keyName]?.value ?? r?.body?.progress?.WATCH_VIDEO?.value;
                        if (sv && sv > cur) cur = Math.min(target, sv);
                        if (r?.body?.completed_at) { cur = target; break; }
                    } catch (e) {}
                }
                completed = cur >= target;
            }
        } else {
            // ACTIVITY / ACHIEVEMENT / GAME / STREAM — heartbeat approach
            const chan = findChannel();
            if (chan) {
                const key = 'call:' + chan + ':' + Math.floor(Math.random() * 9000 + 1000);
                let cur = 0;
                const startTime = Date.now();
                const MAX_TIME = 5 * 60 * 1000;
                while (cur < target && (Date.now() - startTime) < MAX_TIME) {
                    try {
                        const r = await API.post({ url: '/quests/' + questId + '/heartbeat', body: { stream_key: key, terminal: false } });
                        calls++;
                        cur = r?.body?.progress?.[keyName]?.value
                            ?? r?.body?.progress?.PLAY_ACTIVITY?.value
                            ?? r?.body?.progress?.PLAY_ON_DESKTOP?.value
                            ?? r?.body?.progress?.STREAM_ON_DESKTOP?.value
                            ?? cur + 20;
                        if (cur >= target) {
                            try { await API.post({ url: '/quests/' + questId + '/heartbeat', body: { stream_key: key, terminal: true } }); } catch (e) {}
                            break;
                        }
                    } catch (e) { break; }
                    await new Promise(r => setTimeout(r, 19000 + Math.random() * 3000));
                }
                completed = cur >= target;
            }
        }

        if (!completed) {
            return result(false, { error: 'Quest did not complete (type=' + questType + ', target=' + target + ')', triedQuests, totalQuests: allQuests.length });
        }

        // Claim reward
        try {
            const claimRes = await API.post({
                url: '/quests/' + questId + '/claim-reward',
                body: { platform: 0, location: 11, is_targeted: false, metadata_raw: null, metadata_sealed: null, traffic_metadata_raw: null, traffic_metadata_sealed: null }
            });
            if (claimRes?.body?.claimed_at || claimRes?.status === 200) {
                return result(true, { questName, questId, calls, target, triedQuests, claimed: true });
            }
            return result(false, { error: 'Claim failed: ' + JSON.stringify(claimRes?.body ?? {}).slice(0, 200), triedQuests });
        } catch (e) {
            const needsCaptcha = e?.body?.captcha_key || e?.body?.captcha_sitekey;
            if (needsCaptcha) {
                return result(true, { questName, questId, calls, target, triedQuests, claimed: false, captchaRequired: true });
            }
            return result(false, { error: 'Claim error: ' + errStr(e), triedQuests });
        }
    } catch (e) {
        return result(false, { error: 'Unexpected: ' + (e?.message ?? String(e)) });
    }
})()
"""


async def complete_one_quest_via_console(
    tab: uc.Tab,
    account: Account,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """
    Inject JS into Discord's web client to complete ONE video quest + claim reward.
    Uses Discord's internal API module (webpack extraction) — same approach as
    pasting the script into DevTools console.

    Returns (success, message).
    """
    log_info("Injecting quest-completion script into Discord console...")

    # Make sure we're on discord.com
    if "discord.com" not in (tab.url or ""):
        await tab.get("https://discord.com/channels/@me")
        await _wait_for_page_load(tab, timeout=20)
        await asyncio.sleep(3)

    # Inject the script
    try:
        raw = await tab.evaluate(_QUEST_CONSOLE_JS, await_promise=True)
    except Exception as e:
        return False, f"Console injection failed: {e}"

    if not raw:
        return False, "Console injection returned empty result"

    # Debug: log the type and value of raw
    raw_type = type(raw).__name__
    logger.info(f"Quest JS returned type: {raw_type}")
    if isinstance(raw, str):
        logger.info(f"Quest JS returned string (len {len(raw)}): {raw[:300]}")
    else:
        logger.info(f"Quest JS returned {raw_type}: {str(raw)[:300]}")

    # raw might be a string (JSON), a dict, or an ExceptionDetails object
    # Handle all cases
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return False, f"Console injection returned unparseable string: {raw[:200]}"
    elif isinstance(raw, dict):
        data = raw
    elif hasattr(raw, 'exception') or hasattr(raw, 'text') or hasattr(raw, 'columnNumber'):
        # nodriver ExceptionDetails object — JS threw an error
        # Try to extract the error message from various possible attributes
        exc_text = ""
        try:
            exc = getattr(raw, 'exception', None)
            if exc is not None:
                if hasattr(exc, 'value'):
                    exc_text = str(exc.value)
                elif hasattr(exc, 'description'):
                    exc_text = str(exc.description)
                elif isinstance(exc, dict):
                    exc_text = exc.get('value', '') or exc.get('description', '')
                else:
                    exc_text = str(exc)
            if not exc_text:
                exc_text = getattr(raw, 'text', '') or str(raw)
        except Exception:
            exc_text = str(raw)
        return False, f"JS error: {exc_text[:200]}"
    else:
        # Try to convert to dict
        try:
            data = dict(raw) if not isinstance(raw, str) else json.loads(raw)
        except Exception:
            return False, f"Console returned unexpected type {raw_type}: {str(raw)[:200]}"

    if data.get("ok"):
        quest_name = data.get("questName", "Unknown")
        calls = data.get("calls", 0)
        target = data.get("target", 0)
        tried = data.get("triedQuests", [])
        claimed = data.get("claimed", False)
        captcha_required = data.get("captchaRequired", False)
        quest_id = data.get("questId", "")

        log_ok(f"Quest completed via console: {CYN}{quest_name}{RS} ({calls} API calls, {target}s target)")
        if tried and len(tried) > 1:
            log_info(f"Quests tried: {', '.join(tried)}")

        if claimed:
            log_ok(f"Reward claimed automatically for: {CYN}{quest_name}{RS}")
            return True, f"Completed + claimed: {quest_name}"

        if captcha_required:
            log_warn(f"Captcha required for claim — falling back to UI-based claim...")
            log_info(f"NopeCHA extension will solve the hCaptcha automatically.")
            # Do a UI-based claim: click the "Claim Reward" button on the quest page
            ui_ok = await _ui_claim_reward(tab, quest_name, logger)
            if ui_ok:
                log_ok(f"Reward claimed via UI (NopeCHA solved captcha): {CYN}{quest_name}{RS}")
                return True, f"Completed + claimed (UI): {quest_name}"
            else:
                log_warn(f"UI claim failed — quest is complete but reward not claimed.")
                log_info(f"You can claim it manually on the quest page.")
                return True, f"Completed (claim failed): {quest_name}"

        # Quest completed but claim status unknown
        return True, f"Completed quest: {quest_name}"
    else:
        error = data.get("error", "Unknown error")
        quest_name = data.get("questName", "")
        tried = data.get("triedQuests", [])
        total_vq = data.get("totalVideoQuests", 0)
        if quest_name:
            log_err(f"Quest failed: {CYN}{quest_name}{RS} — {error}")
        else:
            log_err(f"Quest failed: {error}")
        if tried:
            log_info(f"Quests tried ({len(tried)}): {', '.join(tried)}")
        if total_vq:
            log_info(f"Total video quests found: {total_vq}")
        return False, error


async def _ui_claim_reward(
    tab: uc.Tab,
    quest_name: str,
    logger: logging.Logger,
) -> bool:
    """
    UI-based claim fallback: click the 'Claim Reward' button on the quest page.
    This triggers a visible hCaptcha that NopeCHA extension can auto-solve.

    Returns True if claim appears to have succeeded.
    """
    log_info("Looking for Claim Reward button on quest page...")

    # Navigate to quest-home first — the Claim button only exists there
    log_info("Navigating to https://discord.com/quest-home ...")
    try:
        await tab.get("https://discord.com/quest-home")
        await asyncio.sleep(8)
    except Exception:
        pass

    # Scroll through the ENTIRE page to find all claim buttons
    # Quests are listed vertically, so we need to scroll down gradually
    log_info("Scrolling through quests to find Claim button...")

    clicked = False
    for scroll_attempt in range(10):  # Scroll up to 10 times
        # Try clicking "Claim Reward" / "Claim" / "Claim Orbs" button
        clicked = (
            await js_click(tab, "Claim Reward") or
            await js_click(tab, "Claim Orbs") or
            await js_click(tab, "Claim")
        )

        if not clicked:
            # Try a broader search — any button with "claim" text
            clicked = await js(tab, (
                "(function(){"
                "var btns=Array.from(document.querySelectorAll('button,[role=\"button\"]'));"
                "for(var i=0;i<btns.length;i++){"
                "var t=(btns[i].innerText||'').trim().toLowerCase();"
                "if(t.indexOf('claim')!==-1){btns[i].click();return true;}"
                "}"
                "return false;"
                "})()"
            ))

        if clicked:
            break

        # Scroll down to see more quests
        await js(tab, "window.scrollBy(0,400)")
        await asyncio.sleep(1)

    if not clicked:
        log_warn("No Claim button found on quest page after scrolling.")
        return False

    log_ok("Clicked Claim button — waiting for NopeCHA to solve captcha...")

    # Wait for hCaptcha to appear and NopeCHA to solve it.
    # NopeCHA auto-solves hCaptcha iframes — we just need to wait.
    # Poll for up to 120 seconds (NopeCHA can take 10-60s to solve).
    captcha_detected = False
    for wait in range(120):
        await asyncio.sleep(1)

        # Check if a captcha iframe is visible
        has_captcha = await js(tab, (
            "(function(){"
            "var frames=document.querySelectorAll('iframe');"
            "for(var i=0;i<frames.length;i++){"
            "var src=frames[i].src||'';"
            "if(src.indexOf('hcaptcha')!==-1||src.indexOf('recaptcha')!==-1||src.indexOf('turnstile')!==-1){"
            "var el=frames[i];"
            "while(el){"
            "var s=window.getComputedStyle(el);"
            "if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;"
            "el=el.parentElement;"
            "}"
            "return true;"
            "}"
            "}"
            "return false;"
            "})()"
        ))

        if has_captcha and not captcha_detected:
            captcha_detected = True
            log_info("hCaptcha detected — NopeCHA is solving it...")

        if not has_captcha and captcha_detected:
            # Captcha was visible and now it's gone — NopeCHA solved it!
            log_ok("Captcha solved! Claim should be processing...")
            await asyncio.sleep(3)
            return True

        # Also check if a success message appeared
        has_success = await js(tab, (
            "(function(){"
            "var txt=document.body.innerText||'';"
            "return txt.indexOf('Claimed')!==-1||txt.indexOf('Reward claimed')!==-1||txt.indexOf('Success')!==-1;"
            "})()"
        ))
        if has_success:
            log_ok("Claim success detected!")
            return True

        if wait % 15 == 14 and captcha_detected:
            log_info(f"Still waiting for NopeCHA to solve captcha... ({wait+1}s)")

    if captcha_detected:
        log_warn("Captcha was detected but NopeCHA didn't solve it in 120s.")
        log_info("You may need to solve it manually in the browser.")
    else:
        log_warn("No captcha appeared after clicking Claim — claim may have succeeded without captcha.")
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# HTTP-based quest completion (no browser needed)
#
# These functions call Discord's quest API directly via httpx with the
# X-Super-Properties header. This is faster and doesn't require browser login.
# Used as the PRIMARY quest completion method.
# ─────────────────────────────────────────────────────────────────────────────

async def _http_api_call(
    token: str,
    method: str,
    path: str,
    body: Optional[dict],
    logger: logging.Logger,
    label: str,
) -> tuple[int, Optional[dict], str]:
    """Call Discord API via httpx with write headers. Returns (status, json, raw)."""
    method = method.upper()
    headers = api_headers(token, is_write=True)
    url = f"{DISCORD_API}{path}"

    try:
        async with httpx.AsyncClient(timeout=CFG["api_timeout"], follow_redirects=True) as client:
            if method == "GET":
                r = await client.get(url, headers=headers)
            elif method == "POST":
                r = await client.post(url, headers=headers, json=body)
            elif method == "PATCH":
                r = await client.patch(url, headers=headers, json=body)
            elif method == "DELETE":
                r = await client.delete(url, headers=headers)
            else:
                return -1, None, f"Unsupported method: {method}"
    except httpx.RequestError as e:
        logger.debug(f"{label} network error: {e}")
        return -1, None, str(e)

    try:
        data = r.json()
    except Exception:
        data = None

    return r.status_code, data, r.text


async def fetch_quests_http(token: str, logger: logging.Logger) -> list:
    """GET /users/@me/quests via HTTP. Returns list of quest objects."""
    status, data, raw = await _http_api_call(
        token, "GET", "/users/@me/quests", None, logger, "fetch-quests-http"
    )
    if status != 200:
        log_warn(f"HTTP fetch quests failed: HTTP {status} — {raw[:200]}")
        return []
    if not isinstance(data, list):
        return []
    return data


async def enroll_quest_http(token: str, quest_id: str, logger: logging.Logger) -> tuple[bool, str]:
    """POST /quests/{id}/enroll via HTTP."""
    status, data, raw = await _http_api_call(
        token, "POST", f"/quests/{quest_id}/enroll",
        {"location": 11, "is_targeted": False}, logger, f"enroll-http-{quest_id}"
    )
    if status == 200:
        return True, "Enrolled."
    if status == 429:
        try:
            retry = float((data or {}).get("retry_after", 3))
        except Exception:
            retry = 3.0
        await asyncio.sleep(retry + 0.5)
        return False, f"Rate-limited (retry after {retry}s)"
    return False, f"Enroll failed: HTTP {status} — {raw[:150]}"


async def complete_video_quest_http(
    token: str,
    quest: dict,
    task_info: dict,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """Send fake video-progress timestamps via HTTP until target reached."""
    quest_id = quest["id"]
    target = task_info["target"]
    key_name = task_info["keyName"]

    if target <= 0:
        return False, "Invalid target"

    log_info(f"Video quest (HTTP): target={CYN}{target}s{RS} key={CYN}{key_name}{RS}")

    user_status = quest.get("userStatus") or {}
    progress = user_status.get("progress") or {}
    cur = 0.0
    try:
        cur = float(progress.get(key_name, {}).get("value", 0))
    except Exception:
        pass
    if not cur:
        try:
            cur = float(progress.get("WATCH_VIDEO", {}).get("value", 0))
        except Exception:
            pass

    log_info(f"Starting progress: {CYN}{cur:.1f}s / {target}s{RS}")

    # Initial buffer ping
    if cur == 0:
        await asyncio.sleep(random.uniform(0.2, 0.35))
        cur = 0.2 + random.uniform(0, 0.05)
        status, data, raw = await _http_api_call(
            token, "POST", f"/quests/{quest_id}/video-progress",
            {"timestamp": round(cur, 6)}, logger, "video-init-http"
        )
        if status == 200 and data:
            server_val = (
                (data.get("progress") or {}).get(key_name, {}).get("value")
                or (data.get("progress") or {}).get("WATCH_VIDEO", {}).get("value")
                or 0
            )
            if server_val and server_val > cur:
                cur = min(target, float(server_val))

    fail_count = 0
    max_fails = 5
    start_time = time.time()
    max_time = 25 * 60
    calls = 0

    while cur < target and (time.time() - start_time) < max_time:
        delay_ms = random.randint(3500, 4750)
        await asyncio.sleep(delay_ms / 1000)

        elapsed = (delay_ms / 1000) + random.uniform(-0.01, 0.01)
        cur += elapsed
        payload_ts = round(min(target, cur), 6)

        status, data, raw = await _http_api_call(
            token, "POST", f"/quests/{quest_id}/video-progress",
            {"timestamp": payload_ts}, logger, "video-progress-http"
        )
        calls += 1

        if status == 200 and data:
            server_val = (
                (data.get("progress") or {}).get(key_name, {}).get("value")
                or (data.get("progress") or {}).get("WATCH_VIDEO", {}).get("value")
                or 0
            )
            if server_val and server_val > cur:
                cur = min(target, float(server_val))
            if data.get("completed_at"):
                cur = target
                break
            fail_count = 0
            if calls % 5 == 0:
                log_info(f"Video progress: {CYN}{cur:.1f}s / {target}s{RS} ({calls} calls)")
        elif status == 429:
            try:
                retry = float((data or {}).get("retry_after", 3))
            except Exception:
                retry = 3.0
            await asyncio.sleep(retry + 0.5)
            fail_count += 1
        elif status in (400, 403, 404, 409, 410):
            return False, f"Quest unavailable (HTTP {status})"
        else:
            fail_count += 1

        if fail_count >= max_fails:
            return False, f"Too many network failures ({fail_count})"

    if cur >= target:
        log_ok(f"Video quest complete! {CYN}{cur:.1f}s / {target}s{RS} in {calls} API calls")
        return True, f"Completed in {calls} API calls"
    return False, "Timed out before reaching target"


async def claim_quest_reward_http(token: str, quest_id: str, logger: logging.Logger) -> tuple[bool, str]:
    """POST /quests/{id}/claim-reward via HTTP."""
    body = {
        "platform": 0, "location": 11, "is_targeted": False,
        "metadata_raw": None, "metadata_sealed": None,
        "traffic_metadata_raw": None, "traffic_metadata_sealed": None,
    }
    for attempt in range(3):
        status, data, raw = await _http_api_call(
            token, "POST", f"/quests/{quest_id}/claim-reward", body, logger, f"claim-http-{quest_id}"
        )
        if status == 200:
            return True, "Reward claimed."
        if status == 429:
            try:
                retry = float((data or {}).get("retry_after", 3))
            except Exception:
                retry = 3.0
            await asyncio.sleep(retry + 0.5)
            continue
        if status in (400, 403, 404, 409, 410):
            return False, f"Claim failed: HTTP {status} — {raw[:150]}"
        await asyncio.sleep(2)
    return False, f"Claim failed after 3 attempts (last: HTTP {status})"


async def complete_quests_http(
    token: str,
    account: Account,
    logger: logging.Logger,
) -> tuple[bool, int]:
    """
    Complete quests entirely via HTTP API — no browser needed.
    Returns (success, num_completed).
    """
    log_info("Fetching available quests via HTTP API...")
    quests = await fetch_quests_http(token, logger)
    if not quests:
        log_warn("No quests returned by Discord API.")
        log_info("This account may not have any quests available (region/age restricted).")
        return False, 0

    log_ok(f"Found {CYN}{len(quests)}{RS} quest(s).")

    completed = 0
    skipped = 0
    failed = 0

    for quest in quests:
        quest_id = quest.get("id")
        if not quest_id:
            continue
        if quest_id == _BLACKLISTED_QUEST_ID:
            skipped += 1
            continue

        quest_name = (quest.get("config") or {}).get("messages", {}).get("questName", "Unknown Quest")
        user_status = quest.get("userStatus") or {}

        if user_status.get("completedAt"):
            log_info(f"Quest already completed: {CYN}{quest_name}{RS}")
            ok, _ = await claim_quest_reward_http(token, quest_id, logger)
            if ok:
                log_ok(f"Claimed reward: {CYN}{quest_name}{RS}")
                completed += 1
            continue

        task_info = detect_quest_task_type(quest)
        if not task_info:
            skipped += 1
            continue

        task_type = task_info["type"]
        target = task_info["target"]
        log_info(f"Quest: {CYN}{quest_name}{RS}  type={CYN}{task_type}{RS}  target={CYN}{target}{RS}")

        # Enroll
        if not user_status.get("enrolledAt"):
            log_info(f"Enrolling: {CYN}{quest_name}{RS}")
            enrolled = False
            for _ in range(3):
                ok, emsg = await enroll_quest_http(token, quest_id, logger)
                if ok:
                    enrolled = True
                    break
                if "Rate-limited" in emsg:
                    continue
                break
            if not enrolled:
                log_err(f"Enroll failed: {quest_name} — {emsg}")
                failed += 1
                continue
            log_ok(f"Enrolled: {CYN}{quest_name}{RS}")
            await asyncio.sleep(random.uniform(0.8, 1.5))

        # Execute
        if task_type == "WATCH_VIDEO":
            ok, vmsg = await complete_video_quest_http(token, quest, task_info, logger)
            if not ok:
                log_err(f"Video failed: {CYN}{quest_name}{RS} — {vmsg}")
                failed += 1
                continue
        else:
            log_warn(f"{task_type} quests not supported via HTTP — skipping {quest_name}")
            skipped += 1
            continue

        # Claim reward
        log_info(f"Claiming reward: {CYN}{quest_name}{RS}")
        ok, cmsg = await claim_quest_reward_http(token, quest_id, logger)
        if ok:
            log_ok(f"Reward claimed: {CYN}{quest_name}{RS}")
            completed += 1
        else:
            log_err(f"Claim failed: {CYN}{quest_name}{RS} — {cmsg}")
            failed += 1

        await asyncio.sleep(random.uniform(1.0, 2.0))

    log_info(f"Quest summary: {GRN}completed={completed}{RS}  {YEL}skipped={skipped}{RS}  {RED}failed={failed}{RS}")
    return completed > 0, completed


async def _browser_api_call(
    tab: uc.Tab,
    method: str,
    path: str,
    body: Optional[dict],
    logger: logging.Logger,
    label: str,
) -> tuple[int, Optional[dict], str]:
    """
    Run fetch() inside the browser to call the Discord API.
    Returns (status_code, parsed_json_or_None, raw_body_text).

    Uses credentials:'include' so cookies are sent, and Discord's own
    X-Super-Properties header is auto-attached by the Discord web client.
    """
    method = method.upper()
    body_str = json.dumps(body) if body else "null"

    # Escape for embedding inside a JS string
    body_js = body_str.replace("\\", "\\\\").replace("'", "\\'")
    path_js = path.replace("\\", "\\\\").replace("'", "\\'")

    script = (
        "(function(m,p,b){"
        "return new Promise(function(resolve){"
        "try{"
        "var opts={method:m,headers:{'Content-Type':'application/json'},credentials:'include'};"
        "if(b!==null)opts.body=b;"
        "fetch('/api/v9'+p,opts).then(function(r){"
        "return r.text().then(function(t){"
        "var j=null;try{j=JSON.parse(t);}catch(e){}"
        "resolve(JSON.stringify({status:r.status,body:t,json:j}));"
        "});"
        "}).catch(function(e){resolve(JSON.stringify({status:0,body:String(e),json:null}));});"
        "}catch(e){resolve(JSON.stringify({status:-1,body:String(e),json:null}));}"
        "});"
        "})('" + method + "','" + path_js + "'," + ("'" + body_js + "'" if body else "null") + ")"
    )

    try:
        raw = await tab.evaluate(script, await_promise=True)
    except Exception as e:
        logger.debug(f"{label} fetch error: {e}")
        return -1, None, str(e)

    if not raw:
        return -1, None, "empty response"

    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return -1, None, str(raw)[:200]

    return (
        int(result.get("status", 0)),
        result.get("json"),
        result.get("body", ""),
    )


async def fetch_quests_via_browser(
    tab: uc.Tab,
    logger: logging.Logger,
) -> list:
    """GET /users/@me/quests and return the list of quest objects."""
    status, data, body = await _browser_api_call(
        tab, "GET", "/users/@me/quests", None, logger, "fetch-quests"
    )
    if status != 200:
        log_warn(f"Fetch quests failed: HTTP {status} — {body[:200]}")
        return []
    if not isinstance(data, list):
        log_warn(f"Fetch quests returned non-list: {str(data)[:200]}")
        return []
    return data


def detect_quest_task_type(quest: dict) -> Optional[dict]:
    """
    Detect the task type from a quest's config.
    Returns {type, keyName, target} or None if unknown.

    Mirrors Orion's Tasks.detectType:
      - PLAY* -> GAME
      - STREAM* -> STREAM
      - VIDEO* -> WATCH_VIDEO
      - ACHIEVEMENT_IN_ACTIVITY* -> ACHIEVEMENT
      - ACTIVITY* -> ACTIVITY
    """
    cfg = quest.get("config") or {}
    task_cfg = cfg.get("taskConfig") or cfg.get("taskConfigV2") or {}
    tasks = task_cfg.get("tasks") or {}
    if not tasks:
        return None

    task_keys = list(tasks.keys())
    type_map = [
        ("PLAY", "GAME"),
        ("STREAM", "STREAM"),
        ("VIDEO", "WATCH_VIDEO"),
        ("ACHIEVEMENT_IN_ACTIVITY", "ACHIEVEMENT"),
        ("ACTIVITY", "ACTIVITY"),
    ]
    for key_frag, type_name in type_map:
        for k in task_keys:
            if key_frag in k:
                return {"type": type_name, "keyName": k, "target": int(tasks[k].get("target", 0) or 0)}

    # Fallback: if there's an application id, treat as GAME
    app_id = cfg.get("application", {}).get("id")
    if app_id:
        first_key = task_keys[0]
        return {"type": "GAME", "keyName": "PLAY_ON_DESKTOP", "target": int(tasks[first_key].get("target", 0) or 0)}
    return None


async def enroll_quest_via_browser(
    tab: uc.Tab,
    quest_id: str,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """POST /quests/{id}/enroll to accept the quest."""
    body = {"location": 11, "is_targeted": False}
    status, data, raw = await _browser_api_call(
        tab, "POST", f"/quests/{quest_id}/enroll", body, logger, f"enroll-{quest_id}"
    )
    if status == 200:
        return True, "Enrolled."
    if status == 429:
        try:
            retry = float((data or {}).get("retry_after", 3))
        except Exception:
            retry = 3.0
        logger.warning(f"Enroll rate-limited, sleeping {retry}s")
        await asyncio.sleep(retry + 0.5)
        return False, f"Rate-limited (retry after {retry}s)"
    return False, f"Enroll failed: HTTP {status} — {raw[:150]}"


async def complete_video_quest_via_browser(
    tab: uc.Tab,
    quest: dict,
    task_info: dict,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """
    Send fake /quests/{id}/video-progress timestamps until target reached.
    ~2x faster than real-time (4s delay, 4s increment).
    """
    quest_id = quest["id"]
    target = task_info["target"]
    key_name = task_info["keyName"]

    if target <= 0:
        return False, "Invalid target"

    log_info(f"Video quest: target={CYN}{target}s{RS} key={CYN}{key_name}{RS}")
    logger.info(f"Video quest {quest_id}: target={target}s key={key_name}")

    user_status = quest.get("userStatus") or {}
    progress = user_status.get("progress") or {}
    cur = 0.0
    try:
        cur = float(progress.get(key_name, {}).get("value", 0))
    except Exception:
        pass
    if not cur:
        try:
            cur = float(progress.get("WATCH_VIDEO", {}).get("value", 0))
        except Exception:
            pass

    log_info(f"Starting progress: {CYN}{cur:.1f}s / {target}s{RS}")

    # Initial buffer ping (simulates player load)
    if cur == 0:
        await asyncio.sleep(random.uniform(0.2, 0.35))
        cur = 0.2 + random.uniform(0, 0.05)
        try:
            status, data, raw = await _browser_api_call(
                tab, "POST", f"/quests/{quest_id}/video-progress",
                {"timestamp": round(cur, 6)}, logger, "video-init"
            )
            if status == 200 and data:
                server_val = (
                    (data.get("progress") or {}).get(key_name, {}).get("value")
                    or (data.get("progress") or {}).get("WATCH_VIDEO", {}).get("value")
                    or 0
                )
                if server_val and server_val > cur:
                    cur = min(target, float(server_val))
        except Exception as e:
            logger.debug(f"Video init ping failed: {e}")

    # Main loop: send incremented timestamps
    fail_count = 0
    max_fails = 5
    start_time = time.time()
    max_time = 25 * 60  # 25 minutes hard cap
    calls = 0

    while cur < target and (time.time() - start_time) < max_time:
        # 2x faster than real-time (Discord native = 7-9.5s, we use 3.5-4.75s)
        delay_ms = random.randint(3500, 4750)
        await asyncio.sleep(delay_ms / 1000)

        # Increment with small jitter
        elapsed = (delay_ms / 1000) + random.uniform(-0.01, 0.01)
        cur += elapsed
        payload_ts = round(min(target, cur), 6)

        try:
            status, data, raw = await _browser_api_call(
                tab, "POST", f"/quests/{quest_id}/video-progress",
                {"timestamp": payload_ts}, logger, "video-progress"
            )
            calls += 1

            if status == 200 and data:
                # Sync with server progress
                server_val = (
                    (data.get("progress") or {}).get(key_name, {}).get("value")
                    or (data.get("progress") or {}).get("WATCH_VIDEO", {}).get("value")
                    or 0
                )
                if server_val and server_val > cur:
                    cur = min(target, float(server_val))
                if data.get("completed_at"):
                    cur = target
                    break
                fail_count = 0
                if calls % 5 == 0:
                    log_info(f"Video progress: {CYN}{cur:.1f}s / {target}s{RS} ({calls} calls)")
            elif status == 429:
                try:
                    retry = float((data or {}).get("retry_after", 3))
                except Exception:
                    retry = 3.0
                logger.warning(f"Video-progress rate-limited, sleeping {retry}s")
                await asyncio.sleep(retry + 0.5)
                fail_count += 1
            elif status in (400, 403, 404, 409, 410):
                return False, f"Quest unavailable (HTTP {status}) — skipping"
            else:
                fail_count += 1
                logger.debug(f"Video-progress HTTP {status}: {raw[:150]}")
        except Exception as e:
            fail_count += 1
            logger.debug(f"Video-progress exception: {e}")

        if fail_count >= max_fails:
            return False, f"Too many network failures ({fail_count})"

    if cur >= target:
        log_ok(f"Video quest complete! {CYN}{cur:.1f}s / {target}s{RS} in {calls} API calls")
        return True, f"Completed in {calls} API calls"
    return False, "Timed out before reaching target"


async def claim_quest_reward_via_browser(
    tab: uc.Tab,
    quest_id: str,
    logger: logging.Logger,
) -> tuple[bool, str]:
    """POST /quests/{id}/claim-reward to claim the Orbs reward."""
    body = {
        "platform": 0,
        "location": 11,
        "is_targeted": False,
        "metadata_raw": None,
        "metadata_sealed": None,
        "traffic_metadata_raw": None,
        "traffic_metadata_sealed": None,
    }
    # Try claim up to 3 times (Discord sometimes needs a moment after task completion)
    for attempt in range(3):
        status, data, raw = await _browser_api_call(
            tab, "POST", f"/quests/{quest_id}/claim-reward", body, logger, f"claim-{quest_id}"
        )
        if status == 200:
            return True, "Reward claimed."
        if status == 429:
            try:
                retry = float((data or {}).get("retry_after", 3))
            except Exception:
                retry = 3.0
            logger.warning(f"Claim rate-limited, sleeping {retry}s")
            await asyncio.sleep(retry + 0.5)
            continue
        if status in (400, 403, 404, 409, 410):
            return False, f"Claim failed: HTTP {status} — {raw[:150]}"
        # 5xx or unknown — retry
        await asyncio.sleep(2)
    return False, f"Claim failed after 3 attempts (last: HTTP {status})"


async def complete_quests_via_api(
    tab: uc.Tab,
    account: Account,
    logger: logging.Logger,
) -> tuple[bool, int]:
    """
    Complete quests using Discord's API directly (no DOM clicking).
    Returns (success, num_completed).
    """
    # Make sure we're on a discord.com page
    if "discord.com" not in (tab.url or ""):
        await tab.get("https://discord.com/channels/@me")
        await asyncio.sleep(3)

    log_info("Fetching available quests via API...")
    quests = await fetch_quests_via_browser(tab, logger)
    if not quests:
        log_warn("No quests returned by Discord API.")
        log_info("This account may not have any quests available (region/age restricted).")
        return False, 0

    log_ok(f"Found {CYN}{len(quests)}{RS} quest(s).")

    completed = 0
    skipped = 0
    failed = 0

    for quest in quests:
        quest_id = quest.get("id")
        if not quest_id:
            continue
        if quest_id == _BLACKLISTED_QUEST_ID:
            log_warn(f"Skipping blacklisted quest {quest_id}")
            skipped += 1
            continue

        quest_name = (quest.get("config") or {}).get("messages", {}).get("questName", "Unknown Quest")
        user_status = quest.get("userStatus") or {}

        # Already completed?
        if user_status.get("completedAt"):
            log_info(f"Quest already completed: {CYN}{quest_name}{RS}")
            # Try to claim the reward anyway (in case it wasn't claimed)
            ok, cmsg = await claim_quest_reward_via_browser(tab, quest_id, logger)
            if ok:
                log_ok(f"Claimed reward for already-completed quest: {CYN}{quest_name}{RS}")
                completed += 1
            continue

        # Detect task type
        task_info = detect_quest_task_type(quest)
        if not task_info:
            log_warn(f"Could not detect task type for: {CYN}{quest_name}{RS} — skipping")
            skipped += 1
            continue

        task_type = task_info["type"]
        target = task_info["target"]
        log_info(f"Quest: {CYN}{quest_name}{RS}  type={CYN}{task_type}{RS}  target={CYN}{target}{RS}")

        # Enroll if not enrolled
        if not user_status.get("enrolledAt"):
            log_info(f"Enrolling in quest: {CYN}{quest_name}{RS}")
            enrolled = False
            for _ in range(3):
                ok, emsg = await enroll_quest_via_browser(tab, quest_id, logger)
                if ok:
                    enrolled = True
                    break
                if "Rate-limited" in emsg:
                    continue
                break
            if not enrolled:
                log_err(f"Failed to enroll in quest {quest_name}: {emsg}")
                failed += 1
                continue
            log_ok(f"Enrolled: {CYN}{quest_name}{RS}")
            await asyncio.sleep(random.uniform(0.8, 1.5))

        # Execute based on type
        if task_type == "WATCH_VIDEO":
            ok, vmsg = await complete_video_quest_via_browser(tab, quest, task_info, logger)
            if not ok:
                log_err(f"Video quest failed: {CYN}{quest_name}{RS} — {vmsg}")
                failed += 1
                continue
        elif task_type == "GAME":
            log_warn(f"GAME quests not supported yet (need fake process injection) — skipping {quest_name}")
            log_info(f"To complete GAME quests manually, play the game for {target} seconds while Discord is open.")
            skipped += 1
            continue
        elif task_type == "STREAM":
            log_warn(f"STREAM quests not supported yet — skipping {quest_name}")
            skipped += 1
            continue
        elif task_type == "ACTIVITY":
            log_warn(f"ACTIVITY quests not supported yet — skipping {quest_name}")
            skipped += 1
            continue
        elif task_type == "ACHIEVEMENT":
            log_warn(f"ACHIEVEMENT quests not supported yet — skipping {quest_name}")
            skipped += 1
            continue
        else:
            log_warn(f"Unknown task type {task_type} — skipping {quest_name}")
            skipped += 1
            continue

        # Claim the reward
        log_info(f"Claiming reward for: {CYN}{quest_name}{RS}")
        ok, cmsg = await claim_quest_reward_via_browser(tab, quest_id, logger)
        if ok:
            log_ok(f"Reward claimed: {CYN}{quest_name}{RS}")
            completed += 1
        else:
            log_err(f"Claim failed: {CYN}{quest_name}{RS} — {cmsg}")
            failed += 1

        await asyncio.sleep(random.uniform(1.0, 2.0))

    log_info(
        f"Quest summary: {GRN}completed={completed}{RS}  "
        f"{YEL}skipped={skipped}{RS}  {RED}failed={failed}{RS}"
    )
    return completed > 0, completed


# ── Quest JS helpers ─────────────────────────────────────────────────────────
_QUEST_JS = (
    "(function(){"
    "function pt(t){"
    "var idx=t.indexOf(':');"
    "if(idx===-1)return null;"
    "var mm=parseInt(t.substring(idx-2,idx),10);"
    "var ss=parseInt(t.substring(idx+1,idx+3),10);"
    "if(isNaN(mm)||isNaN(ss))return null;"
    "return mm*60+ss;"
    "}"
    "var btns=Array.from(document.querySelectorAll('button'));"
    "var best=null;var bestSecs=99999;"
    "for(var i=0;i<btns.length;i++){"
    "var txt=(btns[i].innerText||'').trim();"
    "var lc=txt.toLowerCase();"
    "var isWatch=lc.indexOf('watch')===0;"
    "var isResume=lc.indexOf('resume')===0;"
    "if((isWatch||isResume)&&lc.indexOf('left')!==-1){"
    "var s=pt(txt)||90;"
    "if(s<bestSecs){bestSecs=s;best={btn:btns[i],secs:s,txt:txt};}"
    "}"
    "}"
    "if(best){best.btn.click();return best.secs+'|'+best.txt;}"

    "for(var i=0;i<btns.length;i++){"
    "var txt=(btns[i].innerText||'').trim();"
    "if(txt==='Accept Quest'){btns[i].click();return '90|Accept Quest';}"
    "}"

    "for(var i=0;i<btns.length;i++){"
    "var txt=(btns[i].innerText||'').trim();"
    "if(txt==='Start Video Quest'){btns[i].click();return '0|Start Video Quest';}"
    "}"
    "return null;"
    "})()"
)

_DEBUG_BTN_JS = (
    "Array.from(document.querySelectorAll('button'))"
    ".map(function(b){return(b.innerText||'').trim().split('\\n').join(' ');})"
    ".filter(function(t){return t.length>0;})"
    ".join(' | ')"
)


async def dismiss_reward_error(tab: uc.Tab, logger: logging.Logger) -> bool:
    try:
        dismissed = await js(tab, (
            "(function(){"
            "var btns=Array.from(document.querySelectorAll('button'));"
            "for(var i=0;i<btns.length;i++){"
            "var t=(btns[i].innerText||'').trim();"
            "if(t==='OK'||t==='Dismiss'||t==='Close'||t==='Got it'){btns[i].click();return true;}"
            "}"
            "return false;"
            "})()"
        ))
        if dismissed:
            logger.debug("Dismissed reward error/modal.")
        return bool(dismissed)
    except Exception as e:
        logger.debug(f"dismiss_reward_error: {e}")
        return False


async def click_close(tab: uc.Tab, logger: logging.Logger) -> bool:
    try:
        closed = await js(tab, (
            "(function(){"
            "var btns=Array.from(document.querySelectorAll('button'));"
            "for(var i=0;i<btns.length;i++){"
            "var t=(btns[i].innerText||'').trim();"
            "var ar=btns[i].getAttribute('aria-label')||'';"
            "if(t==='Close'||t==='X'||t==='x'||ar.toLowerCase()==='close'){btns[i].click();return true;}"
            "}"
            "return false;"
            "})()"
        ))
        if closed:
            logger.debug("Closed modal after video.")
        return bool(closed)
    except Exception as e:
        logger.debug(f"click_close: {e}")
        return False


async def wait_for_video(tab: uc.Tab, logger: logging.Logger, duration: int) -> None:
    logger.info(f"Waiting {duration}s for video to complete...")
    interval = 5
    elapsed = 0
    while elapsed < duration:
        await asyncio.sleep(interval)
        elapsed += interval
        remaining = duration - elapsed
        if remaining > 0:
            log_info(f"Video progress: {elapsed}/{duration}s remaining={remaining}s")


async def click_claim_reward(tab: uc.Tab, label: str, logger: logging.Logger) -> bool:
    for attempt in range(3):
        await dismiss_reward_error(tab, logger)
        clicked = (
            await js_click(tab, "Claim Reward") or
            await js_click(tab, "Claim Orbs") or
            await js_click(tab, "Claim")
        )
        if not clicked:
            logger.warning(f"No claim button on attempt {attempt+1}.")
            await asyncio.sleep(2)
            continue
        logger.info(f"Claim clicked (attempt {attempt+1}).")
        await asyncio.sleep(2)
        if await dismiss_reward_error(tab, logger):
            await asyncio.sleep(3)
            continue
        await check_captcha(tab, logger)
        await asyncio.sleep(2)
        return True
    logger.warning("All claim attempts failed.")
    await take_screenshot(tab, label, "claim_failed")
    return False


async def claim_orbs_badge(tab: uc.Tab, label: str, logger: logging.Logger) -> bool:
    """
    Navigate to /shop?tab=orbs and redeem the Orbs badge.

    Tries multiple badge names since Discord has renamed it over time:
      - "Orbs Apprentice Badge"
      - "Orbs Appreciation Badge"
      - Any element containing "Orbs" and "Badge"
    """
    log_info("Claiming Orbs Badge from shop...")
    logger.info("Navigating to shop orbs page...")
    await tab.get("https://discord.com/shop?tab=orbs")
    await asyncio.sleep(5)

    # Badge names to try (in order)
    badge_names = [
        "Orbs Apprentice Badge",
        "Orbs Appreciation Badge",
        "Orbs Apprentice",
        "Orbs Appreciation",
    ]

    try:
        # Scroll to make sure all shop items are loaded
        await js(tab, "window.scrollBy(0,500)")
        await asyncio.sleep(2)
        await js(tab, "window.scrollTo(0,0)")
        await asyncio.sleep(1)

        # Step 1 — find and click the badge card (poll 25s)
        log_info("Searching for Orbs badge in shop...")
        clicked = False
        matched_name = ""
        for _ in range(25):
            for name in badge_names:
                clicked = await js_click(tab, name)
                if not clicked:
                    clicked = await js_click_any(tab, name)
                if clicked:
                    matched_name = name
                    break
            if clicked:
                break
            # Also try a generic search for any element with "Orbs" + "Badge"
            if not clicked:
                clicked = await js(tab, (
                    "(function(){"
                    "var els=Array.from(document.querySelectorAll('*'));"
                    "for(var i=0;i<els.length;i++){"
                    "var el=els[i];"
                    "var t=(el.innerText||'').toLowerCase();"
                    "if(el.childElementCount===0 && t.indexOf('orbs')!==-1 && t.indexOf('badge')!==-1){"
                    "el.click();return true;"
                    "}"
                    "}"
                    "return false;"
                    "})()"
                ))
                if clicked:
                    matched_name = "Orbs * Badge (generic)"
                    break
            await asyncio.sleep(1)

        if not clicked:
            log_warn("Orbs badge not found in shop.")
            logger.warning("Orbs badge not found.")
            await take_screenshot(tab, label, "no_badge")
            return False
        logger.info(f"Clicked Orbs badge: {matched_name}")
        log_ok(f"Found and clicked: {CYN}{matched_name}{RS}")
        await asyncio.sleep(2)

        # Step 2 — wait for "Redeem for" button (try multiple variations)
        log_info("Waiting for Redeem button...")
        redeem_clicked = (
            await wait_and_click(tab, "Redeem for", timeout=15) or
            await wait_and_click(tab, "Redeem", timeout=5) or
            await wait_and_click(tab, "Get", timeout=5) or
            await wait_and_click(tab, "Buy", timeout=5)
        )
        if not redeem_clicked:
            # Try clicking any button that looks like a redeem/buy action
            redeem_clicked = await js(tab, (
                "(function(){"
                "var btns=Array.from(document.querySelectorAll('button,[role=\"button\"]'));"
                "for(var i=0;i<btns.length;i++){"
                "var t=(btns[i].innerText||'').trim().toLowerCase();"
                "if(t.indexOf('redeem')!==-1||t.indexOf('buy')!==-1||t.indexOf('get')!==-1||t.indexOf('purchase')!==-1){"
                "btns[i].click();return true;"
                "}"
                "}"
                "return false;"
                "})()"
            ))
        if not redeem_clicked:
            log_warn("Redeem button not found.")
            await take_screenshot(tab, label, "no_redeem")
            return False
        log_ok("Clicked Redeem.")
        await asyncio.sleep(2)

        # Step 3 — wait for "Claim with Orbs" / "Buy with Orbs" / "Purchase" button
        log_info("Waiting for Claim/Buy with Orbs button...")
        claim_clicked = (
            await wait_and_click(tab, "Claim with Orbs", timeout=15) or
            await wait_and_click(tab, "Buy with Orbs", timeout=5) or
            await wait_and_click(tab, "Purchase", timeout=5) or
            await wait_and_click(tab, "Claim", timeout=5) or
            await wait_and_click(tab, "Buy", timeout=5)
        )
        if not claim_clicked:
            # Try clicking any button that looks like a claim/purchase action
            claim_clicked = await js(tab, (
                "(function(){"
                "var btns=Array.from(document.querySelectorAll('button,[role=\"button\"]'));"
                "for(var i=0;i<btns.length;i++){"
                "var t=(btns[i].innerText||'').trim().toLowerCase();"
                "if(t.indexOf('claim')!==-1||t.indexOf('purchase')!==-1||t.indexOf('buy')!==-1||t==='confirm'){"
                "btns[i].click();return true;"
                "}"
                "}"
                "return false;"
                "})()"
            ))
        if not claim_clicked:
            log_warn("Claim/Buy with Orbs button not found.")
            await take_screenshot(tab, label, "no_claim_orbs")
            return False
        log_ok("Clicked Claim with Orbs — badge redeemed!")
        await asyncio.sleep(2)
        await check_captcha(tab, logger)
        return True
    except Exception as e:
        logger.error(f"Badge claim error: {e}")
        await take_screenshot(tab, label, "badge_error")
        return False


async def complete_quests(tab: uc.Tab, account: Account, logger: logging.Logger) -> tuple[bool, int]:
    if "quest-home" not in (tab.url or ""):
        await tab.get("https://discord.com/quest-home")
    await asyncio.sleep(4)

    await js(tab, "window.scrollBy(0,500)")
    await asyncio.sleep(2)
    await js(tab, "window.scrollTo(0,0)")
    await asyncio.sleep(1)

    triggered = 0

    # Step 0 — already completed? Claim directly
    claim_visible = await js(tab, (
        "(function(){"
        "var btns=Array.from(document.querySelectorAll('button'));"
        "return btns.some(function(b){"
        "var t=b.innerText||'';"
        "return t.indexOf('Claim Reward')!==-1||t.indexOf('Claim Orbs')!==-1;"
        "});"
        "})()"
    ))
    if claim_visible:
        log_info("Quest already done — claiming reward...")
        logger.info("Claim Reward visible, skipping video.")
        if await click_claim_reward(tab, account.label, logger):
            triggered += 1
        if triggered > 0:
            await claim_orbs_badge(tab, account.label, logger)
        return triggered > 0, triggered

    # Step 1 — find and click a quest button
    raw = None
    for attempt in range(10):
        btn_debug = await js(tab, _DEBUG_BTN_JS)
        log_info(f"Buttons: {str(btn_debug)[:250]}")
        logger.debug(f"Attempt {attempt+1}: {btn_debug}")

        raw = await js(tab, _QUEST_JS)
        if raw and isinstance(raw, str) and '|' in raw:
            break

        log_info(f"No quest button yet ({attempt+1}/10)...")
        await asyncio.sleep(2)
        await js(tab, "window.scrollBy(0,500)")
        await asyncio.sleep(1)
        await js(tab, "window.scrollTo(0,0)")
        await asyncio.sleep(1)

    if not raw or not isinstance(raw, str) or '|' not in raw:
        log_info("No video quests available for this token.")
        logger.warning("No Watch/Resume buttons found.")
        await take_screenshot(tab, account.label, "no_quests")
        return False, 0

    pipe = raw.index('|')
    detected_secs = safe_int(raw[:pipe], 90)
    btn_label = raw[pipe + 1:]

    log_info(f"Selected quest button: [{btn_label}]")
    logger.info(f"Quest clicked: [{btn_label}] secs={detected_secs}")

    # Step 2 — handle "Start Video Quest" -> wait for "Accept Quest"
    if btn_label == 'Start Video Quest':
        log_info("Waiting for Accept Quest button...")
        accepted = False
        for _ in range(20):
            await asyncio.sleep(1)
            accept_raw = await js(tab, _QUEST_JS)
            if accept_raw and 'Accept Quest' in str(accept_raw):
                accepted = True
                pipe2 = accept_raw.index('|')
                detected_secs = safe_int(accept_raw[:pipe2], 90)
                btn_label = accept_raw[pipe2 + 1:]
                log_info(f"Accepted quest — [{btn_label}]")
                logger.info("Accepted quest after Start Video Quest click.")
                break
        if not accepted:
            log_warn("Accept Quest not found after Start Video Quest.")
            logger.warning("Accept Quest not found after Start Video Quest.")
            await take_screenshot(tab, account.label, "no_accept")
            return False, 0

    # Step 3 — handle "Accept Quest" -> wait for Watch timer
    if btn_label == 'Accept Quest':
        log_info("Looking for Watch timer after Accept...")
        for _ in range(15):
            await asyncio.sleep(1)
            watch_raw = await js(tab, _QUEST_JS)
            if watch_raw and isinstance(watch_raw, str) and '|' in watch_raw:
                pipe3 = watch_raw.index('|')
                maybe_secs = safe_int(watch_raw[:pipe3], 0)
                maybe_label = watch_raw[pipe3 + 1:]
                if 'left' in maybe_label.lower():
                    detected_secs = maybe_secs
                    btn_label = maybe_label
                    log_info(f"Watch timer: [{btn_label}] {detected_secs}s")
                    break

    wait_secs = max(detected_secs, 30) + CFG["quest_video_buffer_secs"]
    log_info(f"Watching video for {wait_secs}s...")
    logger.info(f"Video duration: {wait_secs}s")

    await asyncio.sleep(2)
    await wait_for_video(tab, logger, duration=wait_secs)

    # Step 4 — close modal
    await click_close(tab, logger)
    await asyncio.sleep(1)

    # Step 5 — claim reward
    if await click_claim_reward(tab, account.label, logger):
        triggered += 1
    else:
        log_err("Quest claim failed.")

    await asyncio.sleep(2)

    # Step 6 — shop badge
    if triggered > 0:
        await claim_orbs_badge(tab, account.label, logger)

    return triggered > 0, triggered


# ── Billing / payment method step ────────────────────────────────────────────
async def add_payment_method(tab: uc.Tab, account: Account, logger: logging.Logger) -> bool:
    """
    Open the billing settings page and prompt the user to add a payment method
    manually. We cannot automate card entry safely (and Discord actively blocks
    automated card entry), so we hand off to the user and wait for confirmation.
    """
    log_info("Opening billing settings page...")
    logger.info("Navigating to /settings/#billing")
    await tab.get("https://discord.com/settings/#billing")
    await asyncio.sleep(5)

    # Verify we landed on a billing-like page (not login)
    url = tab.url or ""
    if "login" in url:
        log_err("Browser is not logged in — cannot open billing page.")
        return False

    # Check if a payment method is already present
    already_has = await js(tab, (
        "(function(){"
        "var txt=document.body.innerText||'';"
        "return txt.indexOf('Default')!==-1 && (txt.indexOf('Visa')!==-1 || txt.indexOf('Mastercard')!==-1 || txt.indexOf('PayPal')!==-1 || txt.indexOf('****')!==-1);"
        "})()"
    ))
    if already_has:
        log_ok("A payment method is already on file.")
        logger.info("Payment method already present — skipping manual step.")
        return True

    # Look for the "Add Payment Method" button and click it
    log_info("Looking for 'Add a Payment Method' button...")
    clicked = (
        await js_click(tab, "Add a Payment Method") or
        await js_click(tab, "Add Payment Method") or
        await js_click(tab, "Add Payment") or
        await js_click_any(tab, "Add Payment Method")
    )
    if clicked:
        logger.info("Clicked Add Payment Method button.")
        log_ok("Opened the 'Add Payment Method' dialog in the browser.")
    else:
        log_warn("Could not auto-click 'Add Payment Method' — please click it manually in the browser.")

    # Hand off to user
    print()
    log_warn("=== MANUAL ACTION REQUIRED ===")
    log_info(f"Browser window is open on the billing page for token ...{account.label}")
    log_info("Please add a valid payment method (credit/debit card or PayPal).")
    log_info("Discord will not charge it — it is required for trial eligibility.")
    print()
    try:
        ans = input(f"{DIM}[{_ts()}]{RS} {LC}[$]{RS} {W}Press ENTER once you have added a payment method (or type 'skip' to skip): {RS}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "skip"

    if ans == "skip":
        log_warn("Skipping payment method step (trial may not trigger without it).")
        return False

    # Re-check that a payment method is now present
    await asyncio.sleep(2)
    has_now = await js(tab, (
        "(function(){"
        "var txt=document.body.innerText||'';"
        "return txt.indexOf('****')!==-1 || txt.indexOf('Visa')!==-1 || txt.indexOf('Mastercard')!==-1 || txt.indexOf('PayPal')!==-1;"
        "})()"
    ))
    if has_now:
        log_ok("Payment method detected on billing page.")
        return True
    log_warn("Could not verify payment method automatically — assuming you added it.")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator — single account
# ─────────────────────────────────────────────────────────────────────────────
async def _humanize_background(account: Account, logger: logging.Logger) -> None:
    """Run humanize in the background — doesn't block the main pipeline."""
    try:
        ok, hmsg = await humanize_account(account, logger)
        if ok:
            log_ok("[Background] Account humanized successfully.")
        else:
            log_warn(f"[Background] Humanize failed: {hmsg}")
    except Exception as e:
        log_warn(f"[Background] Humanize error: {e}")


async def run_account(account: Account) -> AccountResult:
    logger = get_logger(account.label)
    result = AccountResult(account=account, success=False)
    start_time = time.time()

    # ── Stage 1: Token validation (HTTP) ─────────────────────────────────────
    log_stage("Validating token", account.label)
    valid, msg, user_data = await validate_token(account.token or "", logger)

    # ── Stage 1b: Token refresh fallback ────────────────────────────────────
    # If the token is invalid AND we have email+password on file, try to
    # log in fresh and get a new token. Discord rotates tokens after
    # suspicious activity (failed profile edits, captcha, etc.).
    if not valid and account.has_credentials:
        log_warn(f"Token rejected: {msg}")
        log_info("Email+password on file — attempting fresh login to get a new token...")
        refreshed, rmsg, new_token = await refresh_token_via_login(
            account.email or "", account.password or "", logger
        )
        if refreshed and new_token:
            log_ok(rmsg)
            account.token = new_token
            result.extracted_token = new_token  # will be saved at the end
            # Re-validate the fresh token
            valid, msg, user_data = await validate_token(new_token, logger)
            if not valid:
                log_err(f"Fresh token also rejected: {msg}")
        else:
            log_err(f"Token refresh failed: {rmsg}")

    if not valid:
        result.message = msg
        result.stage_reached = "validate"
        log_err(f"Token ...{account.label} REJECTED: {msg}")
        log_err("Please check your token properly:")
        if not account.has_credentials:
            log_info(
                "Tip: add your Discord email and password to tokens.txt in "
                "the format  email:password:token  so the bot can auto-refresh "
                "expired/rotated tokens."
            )
        result.elapsed = time.time() - start_time
        return result

    if user_data:
        account.user_id = user_data.get("id")
        account.username = user_data.get("username")
        account.discriminator = user_data.get("discriminator")
        account.premium_type = int(user_data.get("premium_type", 0) or 0)
        account.verified = bool(user_data.get("verified", False))
        account.flags = int(user_data.get("flags", 0) or 0)

    log_ok(f"Token valid. user={account.username}#{account.discriminator} id={account.user_id} nitro={account.premium_type}")

    # If account already has Nitro, no need to trigger trial
    if account.premium_type >= 1:
        result.success = True
        result.message = "Account already has Nitro — nothing to trigger."
        result.stage_reached = "done"
        log_ok(f"Account already has Nitro — skipping. {account.label}")
        result.elapsed = time.time() - start_time
        return result

    # ── Stage 2: Humanize account (via Humanizer.exe) — NON-BLOCKING ─────────
    # Humanize runs in the BACKGROUND while the bot continues to quests.
    # Wine on macOS is slow (30-60s startup), so we don't wait for it.
    # The trial can still trigger without humanization.
    if CFG["humanize_required"]:
        log_stage("Humanizing account (background)", account.label)
        log_info("Humanizer.exe is running in the background — bot continues to quests.")
        log_info("(Wine on macOS takes 30-60s to start — this is normal.)")
        # Run humanize as a background task (don't await it)
        asyncio.create_task(_humanize_background(account, logger))
    else:
        log_info("Humanize step disabled in config — skipping.")

    # ── Stage 3+: Browser-based steps ─────────────────────────────────────────
    # Pipeline:
    #   1. Login via token
    #   2. Navigate to quest-home
    #   3. Inject JS to complete ONE video quest + claim reward (console approach)
    #   4. Navigate to /shop?tab=orbs and buy Orbs badge
    #   5. Add payment method (billing)
    brave_path = get_brave_path()
    browser = None
    try:
        for attempt in range(1, CFG["max_retries"] + 1):
            result.attempts = attempt
            try:
                logger.info(f"Browser attempt {attempt}/{CFG['max_retries']} — {account.label}")
                browser = await uc.start(
                    browser_executable_path=brave_path,
                    headless=CFG["headless"],
                    browser_args=build_browser_args(),
                )
                tab = await browser.get("about:blank")
                await asyncio.sleep(1)

                # Stage 3a: Browser login via token
                log_stage("Logging into Discord (browser)", account.label)
                if not await login_via_token(tab, account.token, logger):
                    raise RuntimeError("Browser token login failed.")

                # Stage 3a.5: Inject NopeCHA API key (if configured)
                nopecha_key = (
                    os.getenv("NOPECHA_API_KEY", "")
                    or CFG.get("nopecha_api_key", "")
                    or ""
                )
                if nopecha_key:
                    log_stage("Configuring NopeCHA extension", account.label)
                    await inject_nopecha_api_key(tab, nopecha_key, logger)
                else:
                    log_info("No NopeCHA API key configured — captcha solving may fail.")
                    log_info("Get a free key at https://nopecha.com and set nopecha_api_key in config.yaml")

                # Stage 4: Complete ONE quest + claim reward (BLOCKING — can't proceed until claimed)
                log_stage("Completing quest (console injection)", account.label)
                # Navigate to quest-home first
                log_info("Opening https://discord.com/quest-home ...")
                await tab.get("https://discord.com/quest-home")
                await _wait_for_page_load(tab, timeout=20)
                log_info("Waiting for Discord app to fully load (8s)...")
                await asyncio.sleep(8)
                # Scroll down to load quests
                await js(tab, "window.scrollBy(0,500)")
                await asyncio.sleep(2)
                await js(tab, "window.scrollTo(0,0)")
                await asyncio.sleep(1)

                # Inject the quest-completion script
                quest_ok = False
                quest_msg = ""
                try:
                    quest_ok, quest_msg = await complete_one_quest_via_console(tab, account, logger)
                except Exception as qe:
                    log_warn(f"Quest script threw exception: {qe}")
                    quest_ok = False
                    quest_msg = str(qe)

                # complete_one_quest_via_console already tries to claim via API.
                # If it returns True, the quest is completed + claimed (or captcha was solved by NopeCHA).
                if quest_ok:
                    log_ok(f"Quest completed and claimed: {quest_msg}")
                else:
                    # Quest could not be completed OR claim failed.
                    # The quests may be already completed but not claimed.
                    # Try clicking "Claim Reward" button in the Discord UI.
                    log_warn(f"Quest did not complete via console: {quest_msg}")
                    log_info("Quests may be already completed — trying to claim via UI button...")
                    try:
                        ui_claim_ok = await _ui_claim_reward(tab, "completed quest", logger)
                        if ui_claim_ok:
                            log_ok("Claimed reward via UI button click.")
                            quest_ok = True
                            quest_msg = "Claimed via UI"
                        else:
                            log_err("Could not complete or claim any quest.")
                            log_info("Cannot proceed to Orbs badge without completing + claiming a quest.")
                            result.message = "Quest stage failed — no quest completed or claimed."
                            result.stage_reached = "quest"
                            # Skip Orbs and billing — quest is required
                            break
                    except Exception as uce:
                        log_err(f"UI claim exception: {uce}")
                        log_info("Cannot proceed to Orbs badge without claiming a quest.")
                        result.message = "Quest claim failed."
                        result.stage_reached = "quest"
                        break

                # Stage 5: Claim Orbs badge from shop
                log_stage("Buying Orbs badge", account.label)
                orbs_ok = await claim_orbs_badge(tab, account.label, logger)
                if not orbs_ok:
                    log_warn("Orbs badge step failed — continuing to billing anyway.")

                # Stage 6: Add payment method (billing)
                if CFG["payment_method_required"]:
                    log_stage("Adding payment method", account.label)
                    billing_ok = await add_payment_method(tab, account, logger)
                    if not billing_ok:
                        log_warn("Billing step was skipped or failed.")

                result.success = True
                result.message = "All stages completed. Wait 12-48h for trial to appear."
                result.stage_reached = "done"
                break

            except Exception as exc:
                logger.error(f"Browser attempt {attempt} failed: {exc}")
                if attempt < CFG["max_retries"]:
                    delay = CFG["retry_base_delay"] * (2 ** (attempt - 1)) + random.uniform(0, 2)
                    log_warn(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    result.message = f"Browser stage failed: {exc}"
                    result.stage_reached = "browser"
            finally:
                if browser:
                    try:
                        await asyncio.sleep(4)
                        browser.stop()
                    except Exception:
                        pass
                    browser = None

    finally:
        if browser:
            try:
                browser.stop()
            except Exception:
                pass

    result.elapsed = time.time() - start_time
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Account loading
# ─────────────────────────────────────────────────────────────────────────────
def parse_accounts(lines: list, proxies: list) -> list:
    accounts = []
    seen = set()
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Accept formats:
        #   token
        #   email:password
        #   email:password:token
        parts = line.split(":")
        if len(parts) == 1:
            acct = Account(email=None, password=None, token=parts[0], raw_line=line)
            key = parts[0]
        elif len(parts) == 2:
            acct = Account(email=parts[0], password=parts[1], token=None, raw_line=line)
            key = parts[0].lower()
        elif len(parts) >= 3:
            token = ":".join(parts[2:])
            acct = Account(email=parts[0], password=parts[1], token=token, raw_line=line)
            key = token if token else parts[0].lower()
        else:
            log_warn(f"Unrecognized line {i+1}: {line[:40]}")
            continue
        if key in seen:
            log_warn(f"Duplicate skipped: ...{key[-10:]}")
            continue
        seen.add(key)
        acct.proxy = proxies[len(accounts)] if len(accounts) < len(proxies) else None
        accounts.append(acct)
    return accounts


def load_proxies() -> list:
    path = CFG.get("proxies_file", "")
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    return [line.strip() for line in p.read_text().splitlines() if line.strip()]


def load_accounts() -> list:
    path = Path(CFG["tokens_file"])
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Create a 'tokens.txt' file in the same folder "
            "as z_trigger.py and add your Discord tokens (one per line)."
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    proxies = load_proxies()
    return parse_accounts(lines, proxies)


def save_result(raw_line: str, success: bool) -> None:
    filename = "success.txt" if success else "failed.txt"
    try:
        with open(filename, "a", encoding="utf-8") as f:
            f.write(raw_line + "\n")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main() -> None:
    try:
        await _main()
    except Exception as e:
        import traceback
        log_err(f"FATAL ERROR: {e}")
        traceback.print_exc()
    finally:
        print(f"\n{DIM}[{_ts()}]{RS} {LC}[$]{RS} {W}Press Enter to exit.{RS}", end=" ", flush=True)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass


async def _main() -> None:
    print(ASCII_ART)
    accounts = load_accounts()
    total = len(accounts)
    log_info(f"Loaded {total} token(s) from {CFG['tokens_file']}.")

    if total == 0:
        log_err("No tokens found. Add your tokens to tokens.txt and rerun.")
        return

    # Ask for thread count
    max_threads = min(total, 10)  # cap at 10 to avoid Discord rate-limits
    while True:
        try:
            raw = input(
                f"{DIM}[{_ts()}]{RS} {LC}[$]{RS} {W}Enter number of threads (1-{max_threads}): {RS}"
            ).strip()
            thread_count = int(raw)
            if 1 <= thread_count <= max_threads:
                break
            log_warn(f"Please enter a number between 1 and {max_threads}.")
        except ValueError:
            log_warn("Invalid input. Please enter a number.")
    log_info(f"Starting with {thread_count} thread(s)...")

    results: list[AccountResult] = []
    success_count = 0
    completed = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(thread_count)

    async def run_with_semaphore(i: int, account: Account) -> None:
        nonlocal success_count, completed
        async with semaphore:
            log_info(f"Triggering token {i}/{total} — ...{account.label}")
            result = await run_account(account)
            save_result(account.raw_line, result.success)
            async with lock:
                completed += 1
                if result.success:
                    success_count += 1
                    log_ok(f"Success {success_count}/{total} (done {completed}/{total}) — {result.message}")
                else:
                    log_err(f"Failed ...{account.label} (done {completed}/{total}) — {result.message[:80]}")
                results.append(result)

    tasks = [run_with_semaphore(i, acct) for i, acct in enumerate(accounts, 1)]
    await asyncio.gather(*tasks)

    # ── Final summary ────────────────────────────────────────────────────────
    print()
    log_info("─" * 60)

    valid_count = sum(1 for r in results if r.success)
    invalid_count = sum(1 for r in results if not r.success)

    # Stage breakdown
    stage_counts: dict[str, int] = {}
    for r in results:
        stage_counts[r.stage_reached] = stage_counts.get(r.stage_reached, 0) + 1

    total_elapsed = sum(r.elapsed for r in results)

    log_info(f"Checked {total} token(s) in {int(total_elapsed // 60)}m {int(total_elapsed % 60)}s")
    log_ok(
        f"Summary -> "
        f"Checked= {CYN}{total}{RS} {GRN}"
        f"Succeeded= {CYN}{valid_count}{RS} {GRN}"
        f"Failed= {CYN}{invalid_count}{RS}"
    )

    if stage_counts:
        log_info("Stage breakdown:")
        for stage, n in sorted(stage_counts.items()):
            print(f"    {DIM}-{RS} {W}{stage:12}{RS}: {CYN}{n}{RS}")

    # ── Per-token detail ─────────────────────────────────────────────────────
    print()
    log_info("Per-token results:")
    for r in results:
        masked = (r.account.token or "")[:15] + "***.****** " if r.account.token and len(r.account.token) > 15 else (r.account.token or "")
        if r.success:
            print(
                f"    {Fore.GREEN}[OK]{RS}   token= {CYN}{masked}{RS}  "
                f"user= {CYN}{r.account.username or '-'}{RS}  "
                f"stage= {GRN}{r.stage_reached}{RS}"
            )
        else:
            print(
                f"    {RED}[FAIL]{RS} token= {CYN}{masked}{RS}  "
                f"stage= {YEL}{r.stage_reached}{RS}  "
                f"reason= {RED}{r.message[:60]}{RS}"
            )

    # Save extracted / updated tokens if any new ones came back
    new_tokens = [r.extracted_token for r in results if r.extracted_token]
    if new_tokens:
        out = Path("extracted_tokens.txt")
        with open(out, "a", encoding="utf-8") as f:
            f.write("\n".join(new_tokens) + "\n")
        log_ok(f"{len(new_tokens)} new token(s) saved to {out}")

    log_info("Reminder: Wait 12-48 hours for the Nitro trial to appear.")


if __name__ == "__main__":
    asyncio.run(main())
