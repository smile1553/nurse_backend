# nurse_backend

啟動 Server 時，如果專案目錄沒有 `.env.example`，系統會自動建立：

```dotenv
DEEPGRAM_API_KEY=PASTE_YOUR_DEEPGRAM_API_KEY_HERE
OPENAI_API_KEY=PASTE_YOUR_OPENAI_API_KEY_HERE
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SEC=3.0
ASR_WARMUP_ON_START=0
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=zh
DEEPGRAM_SAMPLE_RATE=16000
DEEPGRAM_ENDPOINTING_MS=200
```

請將 API key 複製到對應的等號後方，取代 `PASTE_YOUR_..._HERE`。既有的
`.env.example` 不會被覆寫，且此檔案已加入 `.gitignore`。系統現有環境變數與
`.env` 的設定優先於 `.env.example`。

啟動程式時，如果專案目錄沒有 `openai_api.json`，系統會自動建立：

```json
{
  "apiKey": "PASTE_YOUR_OPENAI_API_KEY_HERE"
}
```

請將範例文字替換成自己的 OpenAI API key。此檔案已加入 `.gitignore`，不會提交到 Git。
