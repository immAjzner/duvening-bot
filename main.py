name: Daily Tefillah Update

on:
  schedule:
    - cron: '*/5 * * * *'
  workflow_dispatch:
    inputs:
      preview_date:
        description: "Optional preview date (YYYY-MM-DD). Sends only to MY_CHAT_ID; never broadcasts."
        required: false
        default: ""
      force_send:
        description: "With preview_date: number of preview messages (0 means 1). Without it: 0 = normal run, N>0 = N previews from today. Previews go only to MY_CHAT_ID."
        required: false
        default: "0"

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - run: pip install requests convertdate pyluach

      - run: python main.py
        env:
          BOT_TOKEN: ${{ secrets.BOT_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # workflow_dispatch => MANUAL_RUN=1: full broadcast anytime (FORCE_SEND=0), no morning window / no "already today" skip.
          # schedule => MANUAL_RUN=0: once per civil day in the morning window using last_run.json
          MANUAL_RUN: ${{ github.event_name == 'workflow_dispatch' && '1' || '0' }}
          # An optional date always takes the private preview path and never broadcasts.
          PREVIEW_DATE: ${{ github.event.inputs.preview_date || '' }}
          # Scheduled runs have no workflow inputs; this falls back to 0. Manual runs use the value below (0, 1, 3, ...).
          FORCE_SEND: ${{ github.event.inputs.force_send || '0' }}
