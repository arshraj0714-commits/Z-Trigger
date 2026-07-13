# NopeCHA Extension Folder

Put the NopeCHA extension files here (unpacked extension with manifest.json).

## Step 1: Get the NopeCHA extension files

### Option A — Download from nopecha.com
1. Go to https://nopecha.com
2. Download the Chrome/Brave extension (.crx or .zip)
3. If .crx: rename to .zip and extract it
4. Put the extracted files (including manifest.json) in this folder

### Option B — Copy from your Brave profile (if already installed)
1. Install NopeCHA in Brave from https://nopecha.com
2. Find the extension folder:
   Windows:  %LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\Default\Extensions\dknlfmiahfcgjclgjepdohbbmdchhiaf\
   macOS:    ~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Extensions/dknlfmiahfcgjclgjepdohbbmdchhiaf/
   Linux:    ~/.config/BraveSoftware/Brave-Browser/Default/Extensions/dknlfmiahfcgjclgjepdohbbmdchhiaf/
3. Inside that folder, there's a version subfolder (e.g. 2.1.0_0)
4. Copy the CONTENTS of that version subfolder into this nopecha/ folder
   (so that manifest.json is directly inside nopecha/)

## Step 2: Get a NopeCHA API key

NopeCHA requires an API key for reliable captcha solving. Without it, you'll
get errors when the extension tries to solve hCaptcha.

1. Go to https://nopecha.com
2. Sign up for a free account
3. Go to your dashboard → API keys
4. Copy your API key (looks like: abc123def456...)
5. Paste it in config.yaml:
     nopecha_api_key: "your-api-key-here"

Or set the NOPECHA_API_KEY environment variable:
  export NOPECHA_API_KEY="your-api-key-here"

Free tier: 100 solves per day (enough for quest claiming)

## How it works

When the bot starts:
1. Brave loads with the NopeCHA extension from this folder
2. The bot navigates to the NopeCHA extension's options page
3. The bot injects your API key into the extension's storage via chrome.storage.local
4. When Discord shows an hCaptcha during quest reward claiming, NopeCHA
   automatically solves it using your API key

## What it does:

When Discord shows an hCaptcha during quest reward claiming, NopeCHA
automatically solves it. Without NopeCHA, you would need to solve the
captcha manually in the browser window.
