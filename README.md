# MJoobi Telegram Release Publisher

A small Flask web app that:

1. reads a Proton smart-link page,
2. extracts the release title, artist, cover, year, and store links,
3. lets you correct anything manually,
4. publishes the cover and an HTML-formatted caption to a Telegram channel.

## Telegram preparation

1. In Telegram, open **@BotFather**.
2. Send `/newbot` and follow the instructions.
3. Copy the bot token.
4. Add the bot to your Telegram channel as an **administrator** with permission to post messages.
5. Your channel ID can usually be the public username in this format:

   `@yourchannelusername`

   For a private channel, you need its numeric ID, usually beginning with `-100`.

Never put the bot token directly inside the GitHub files.

## Deploy on Render

This repository includes `render.yaml`.

1. Upload all project files to your GitHub repository.
2. In Render, choose **New + → Blueprint**.
3. Connect the GitHub repository.
4. Render detects `render.yaml`.
5. Enter these secret environment variables when requested:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `APP_PASSWORD` — choose any private password for opening/using the tool.
6. Deploy.

You can also create a normal **Web Service** with:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`

## Use

Open the Render URL, enter the same `APP_PASSWORD`, paste a Proton release link, generate, review, and publish.

The app intentionally allows manual corrections because smart-link page structures can change and some stores may not appear until they are active.

## Optional custom domain

After the app works on its `onrender.com` address:

1. Open the service in Render.
2. Go to **Settings → Custom Domains**.
3. Add a subdomain such as `release.mjoobi.com`.
4. Render shows the DNS record to add in Name.com.
5. Add exactly that record in Name.com's DNS settings.

Test the Render address first; connect the domain afterward.
