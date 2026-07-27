# MJoobi Telegram Release Publisher

This Flask app can generate a Telegram release post from a Proton/smart-link page, but it also works completely manually when the smart link is unavailable.

## Version 2 features

- Manual mode: no Proton link is required.
- Add, remove, edit, and reorder streaming links.
- Upload a custom JPG, PNG, or WebP cover.
- Remote or uploaded covers are resized to a maximum of 1280 px and compressed to a Telegram-friendly JPEG, normally under about 1.2 MB.
- Fully editable caption layout using placeholders:
  - `{title}` — bold clickable artist/title
  - `{links}` — clickable platform list in the chosen order
  - `{artist}`
  - `{release}`
  - `{year}`
- The uploaded image is processed in memory and is not stored permanently on Render.

## Telegram preparation

1. Open **@BotFather** in Telegram.
2. Send `/newbot` and follow the instructions.
3. Copy the bot token.
4. Add the bot to your Telegram channel as an administrator with permission to post messages.
5. A public channel ID can usually be entered as `@yourchannelusername`.

Never put the bot token directly inside GitHub files.

## Deploy on Render

This repository includes `render.yaml`.

1. Upload all files to GitHub.
2. In Render, connect the repository as a Blueprint or Web Service.
3. Keep these environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `APP_PASSWORD`
4. Render automatically redeploys after a GitHub commit.

## Updating an existing installation

Replace the existing repository files with this version and commit the changes. Render should automatically deploy the update. No changes to your Telegram token, channel ID, or password are required.
