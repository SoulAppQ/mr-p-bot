# MR P Bot

24/7 Discord server management bot. Runs on free hosting (Railway/Render). No AI, no Ollama, no Instagram — just pure server utilities.

## Features

- **Voice Rooms** — join-to-create lobbies, TTS greetings, lock/limit controls
- **Roles** — self-serve game roles dropdown, color roles
- **Housekeeping** — auto-threads for media, ghost-ping detection, starboard/skullboard
- **Utilities** — match history, leaderboard, roulette, debt tracking, Steam stats, events

## Setup

1. Create a new Discord application at https://discord.com/developers/applications
2. Enable required intents: Message Content, Server Members, Voice States
3. Copy `.env.example` to `.env` and fill in your values
4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Run:

```bash
python main.py
```

## Deploy

Railway/Render — just set the env vars from `.env.example` in the dashboard.

## Ava vs MR P

| | Ava | MR P |
|---|---|---|
| Runs on | Your PC | Free cloud hosting |
| AI chat | Yes (Ollama) | No |
| Instagram DMs | Yes | No |
| Server management | Yes | Yes |
| 24/7 | Only when PC is on | Always |
