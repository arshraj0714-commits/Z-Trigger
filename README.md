# Z Trigger

A Discord Nitro trial trigger tool. Uses the **new method** that works after
Discord's recent patch.

> Reported success rate: **80–90%**. The trial appears in the account
> **12–48 hours** after the pipeline finishes.

---

## How it works

For every token in `tokens.txt`, Z Trigger runs the following pipeline:

| Stage | What it does                                              | How             |
| ----- | --------------------------------------------------------- | --------------- |
| 1     | **Validate token** against Discord's `/users/@me` API     | HTTP            |
| 2     | **Humanize account** — change avatar (from `pfp/` folder), bio, username, pronouns | HTTP → browser fallback |
| 3     | **Complete ONE quest** — inject JS into Discord console to complete first video quest via Discord's internal API | Browser (console injection) |
| 4     | **Claim the reward** — done automatically by the injected JS | Browser (console injection) |
| 5     | **Buy Orbs badge** — navigate to `/shop?tab=orbs`, find badge, click Redeem → Buy with Orbs | Browser (DOM clicking) |
| 6     | **Add payment method** — open `/settings/#billing`        | Browser + manual |

The quest completion (stages 3–4) uses **console injection** — the same approach
as pasting a script into DevTools. It accesses Discord's internal webpack modules
(`QuestStore` + `API`) to call the quest API with real session context, then
sends fake `video-progress` timestamps until the quest completes (2x speed).

**NopeCHA extension** can be loaded to auto-solve any hCaptcha that appears.

Stage 6 is **manual**: Discord actively blocks automated card entry, so the
bot opens the billing page and waits for you to add the card yourself.

---

## Setup

### 1. Install Python 3.10+

Download from <https://www.python.org/downloads/>.

### 2. Install dependencies

```bash
cd z_trigger
pip install -r requirements.txt
```

### 3. Install Brave Browser

Download from <https://brave.com/download/>.

Z Trigger will auto-detect Brave at the standard install paths. If it can't
find it, set `BRAVE_PATH` in a `.env` file:

```
BRAVE_PATH=/path/to/brave.exe
```

Chrome is also supported as a fallback.

### 4. Add your tokens

Edit `tokens.txt` and put one Discord token per line:

```
MTA1xxxxxxxxxxxxxxx.xxxxxx.xxxxxxxxxxxxxxxxxxxxxxxxxxx
```

To get your token: open Discord in your browser → DevTools (F12) → Network →
click any request to discord.com → copy the `Authorization` header value.

### 5. Add your avatar images (optional but recommended)

Drop avatar images (`.png`, `.jpg`, `.jpeg`) into the `pfp/` folder. The bot
will pick a random one for each account during the humanize step.

```bash
cp /path/to/your/avatars/*.png z_trigger/pfp/
```

If the folder is empty, the bot generates a random colored PNG as fallback.

### 6. Configure (optional)

Edit `config.yaml` to change thread count limits, retries, headless mode,
screenshot-on-error, etc.

### 7. (Optional) Set up NopeCHA for auto-solving captchas

NopeCHA is a browser extension that automatically solves hCaptcha, reCaptcha,
and Cloudflare Turnstile. If Discord shows a captcha during the pipeline,
NopeCHA will solve it automatically.

**Option A — Download and extract the .crx:**
1. Go to https://nopecha.com and download the Chrome extension (.crx file)
2. Extract the .crx (it's a zip file) to a folder, e.g. `z_trigger/nopecha/`
3. Set the path in `config.yaml`:
   ```yaml
   nopecha_extension_path: "nopecha"
   ```
   Or set the `NOPECHA_PATH` environment variable.

**Option B — Find the extension in your Brave profile:**
1. Install NopeCHA in Brave from https://nopecha.com
2. Find the extension folder:
   - **Windows:** `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Extensions\dknlfmiahfcgjclgjepdohbbmdchhiaf\`
   - **macOS:** `~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Extensions/dknlfmiahfcgjclgjepdohbbmdchhiaf/`
   - **Linux:** `~/.config/BraveSoftware/Brave-Browser/Default/Extensions/dknlfmiahfcgjclgjepdohbbmdchhiaf/`
3. Inside that folder, there's a version subfolder (e.g. `2.1.0_0`). Use that path:
   ```yaml
   nopecha_extension_path: "/full/path/to/dknlfmiahfcgjclgjepdohbbmdchhiaf/2.1.0_0"
   ```

If the path is set correctly, you'll see this at startup:
```
[$] NopeCHA extension loaded from: /path/to/nopecha
```

---

## Run

```bash
python z_trigger.py
```

You'll be asked how many threads to run (1–10), then the bot starts.

---

## Output files

| File                  | Purpose                                                |
| --------------------- | ------------------------------------------------------ |
| `logs/main.log`       | Combined debug log of every run                        |
| `logs/acct_<id>.log`  | Per-account log                                        |
| `logs/acct_*_*.png`   | Screenshots taken when a stage fails                   |
| `success.txt`         | Tokens that completed all stages successfully          |
| `failed.txt`          | Tokens that failed at some stage                       |
| `extracted_tokens.txt`| Any new tokens extracted during the run (if applicable)|

---

## Notes on reliability

- **Headless mode is off by default.** Discord is more likely to challenge
  headless browsers with captchas. Keep `headless: false` unless you know
  what you're doing.
- **Don't run more than 5–10 threads.** Discord rate-limits aggressively.
  Higher thread counts will hurt your success rate.
- **Token validation is strict.** If a token is invalid, expired, locked, or
  unverified, the bot skips it immediately and tells you
  *"Please check your token properly."*
- **Quests vary by region.** Some accounts may not see a video quest at all.
  In that case the bot reports `"No video quests available"` and moves on to
  the billing stage anyway.
- **Billing requires a real card.** Discord will not charge it, but it must
  be a valid card or PayPal account. Prepaid cards often get rejected.

---

## Troubleshooting

**"Brave browser not found"**
Set `BRAVE_PATH` in `.env` to the full path of your Brave executable.

**"Token is invalid or expired (401)"**
Your token is wrong or has been rotated. Re-extract it from the browser.

**"Browser token login failed"**
Discord may have flagged the account. Try with `headless: false` so you can
see what's happening, and solve any captcha that appears.

**"No video quests available"**
The account's region or age doesn't qualify for a quest. Try a different
account.

**"Orbs Apprentice Badge not found"**
The shop layout may have changed. Check the screenshot in `logs/` and adjust
the button text in `claim_orbs_badge()` if needed.

**Captcha loop**
Solve the captcha in the browser window when prompted. The bot waits up to
5 minutes per captcha.

---

## Disclaimer

This tool is provided for **educational purposes only**. Automating Discord
may violate their Terms of Service. You alone are responsible for any
consequences — banned accounts, legal action, etc. — that result from using
this tool. Use it only on accounts you own.
