# nurse_backend

<<<<<<< HEAD
## Unity 學生成績 API

Backend 將每輪實驗的學生結果保存於：

```text
out/student_results/
```

每個 Session 對應一份 Excel。Backend 會保存目前 Session，重新啟動後不會刪除既有 Excel。

Quest 必須使用 Backend 電腦的區網位址，例如 `http://192.168.1.100:8000`，不可使用 `localhost` 或 `127.0.0.1`。

### 1. 建立新一輪 Session

```http
POST /api/sessions
```

只有整輪實驗重新開始時才呼叫。`StartScenario()` 或單一學生登入不可呼叫這支 API。

### 2. 學生開始流程

```http
POST /api/student-runs/start
Content-Type: application/json
```

```json
{
  "sessionId": "20260921_103000_a12b3c4d",
  "resultId": "550e8400-e29b-41d4-a716-446655440000",
  "studentId": "412345678",
  "loginTime": "2026-09-21T10:35:00+08:00"
}
```

這會清除上一位學生留在 Backend 的語意歷史與 tension。

### 3. 提交學生結果

```http
PUT /api/sessions/{sessionId}/results/{resultId}
Content-Type: application/json
```

```json
{
  "studentId": "412345678",
  "loginTime": "2026-09-21T10:35:00+08:00",
  "correctCount": 7,
  "toneScore": 18
}
```

Backend 計算：

```text
QuestionScore = CorrectCount × 10
TotalScore = QuestionScore + ToneScore
```

`questionScore`（選填）：Unity 算好的細部題目分數，整數 `0～80`。內容包含
8 題考題（每答錯一次扣分）與兩個操作題（選壓脈帶、選壓脈帶箭頭位置）。有帶這個
欄位時：

```text
QuestionScore = questionScore
TotalScore = QuestionScore + ToneScore
```

沒帶時維持原本的 `CorrectCount × 10`，舊版 Unity 不受影響。`correctCount` 仍然是
「第一次就答對」的題數，Excel 的「答對題數」欄照舊顯示它。

```json
{
  "studentId": "412345678",
  "loginTime": "2026-09-21T10:35:00+08:00",
  "correctCount": 6,
  "toneScore": 18,
  "questionScore": 68
}
```

輸入限制：

- `loginTime` 必須是含時區的 ISO 8601。
- `correctCount` 必須是整數 `0～8`。
- `toneScore` 必須是整數 `0～20`。
- `questionScore` 可省略；有帶時必須是整數 `0～80`。
- 未知欄位會被拒絕。

Excel 欄位為：

```text
登入時間 | 學號 | 答對題數 | 題目分數 | 語氣分數 | 總分
```

同一次 Unity 重試必須沿用相同的 `resultId`。相同 `resultId` 與相同資料會回傳成功且標示 `duplicate: true`，不會重複新增 Excel 列；相同 `resultId` 搭配不同資料會回傳 HTTP 409。

### 4. 查詢目前 Session

```http
GET /api/sessions/current
```

## OpenAI API Key
=======
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
>>>>>>> f637901e4dc893f5d0b83538265402abaa5a7705

啟動程式時，如果專案目錄沒有 `openai_api.json`，系統會自動建立：

```json
{
  "apiKey": "PASTE_YOUR_OPENAI_API_KEY_HERE"
}
```

請將範例文字替換成自己的 OpenAI API key。此檔案已加入 `.gitignore`，不會提交到 Git。

### 每位學生的成績檔（依日期分資料夾）

每次成績送出成功後，除了 session 的 Excel 之外，還會另外寫一個該學生的文字檔：

```text
out/student_results/<YYYY-MM-DD>/<學號>_<resultId 前 8 碼>.txt
```

日期取自 `loginTime`（學生登入當天）。檔案內容為學號、登入時間、答對題數、題目分數、
語氣分數、總分，以及該學生的語音文字紀錄。同一個 `resultId` 重送只會覆寫同一個檔案。
Excel 仍是主要紀錄；這個檔案寫入失敗只會在 console 印出訊息，不會讓成績送出失敗。

## 回饋報告與全班總覽

每次學生結果送出後，除了原本的 Excel 和文字檔，還會在 `out/student_results/<日期>/` 產生：

| 檔案 | 內容 |
|---|---|
| `<學號>_<resultId 前 8 碼>.html` | 這位學生的一頁回饋報告：分數、芽芽情緒曲線、影響情緒的句子、逐題結果、完整逐字稿 |
| `<學號>_<resultId 前 8 碼>.json` | 報告用的原始資料 |
| `index.html` | 當天全班總覽：平均分數、最多人沒有一次答對的項目、每位學生一列並連到個人報告 |

開啟方式：

- 直接在檔案總管點兩下 `index.html`（不需要網路）。
- 後端執行中時，用瀏覽器開 `http://<後端位址>:8000/reports`（最近一天），或 `http://<後端位址>:8000/reports/2026-10-04`。

說明：

- 情緒曲線的資料來自每句話的緊張度，存在 `transcripts/<session>/<學號>_<id>.jsonl`。更新後端之前的練習沒有這個檔，報告會顯示「沒有每句話的緊張度紀錄」。
- 逐題明細由 Unity 在送出結果時附上（`items`，選填，不影響分數，也不列入重送比對）。舊版 Unity 不會送，報告會顯示沒有逐題明細。
- 緊張度在報告上顯示為 0（最平靜）到 10（最緊張），等於系統內部的 -5 到 5 加 5。

### 時間資料

- 每句話的時間改用這台電腦的時區記錄（例如 `2026-10-05T00:12:03+08:00`），和登入時間一致。之前是 UTC（結尾為 `Z`），比台灣時間慢 8 小時。
- 每筆成績多記三項，文字檔、JSON、個人報告和全班總覽都會顯示：
  - `submittedAt`：成績送到後端的時間。
  - `durationSeconds`：練習時間，從登入到成績送達。
  - `steps`：各步驟花費的時間，由 Unity 隨成績送出（選填，不影響分數）。
- 每句話的 `step` 現在是實際所在的步驟（`login`、`part0` … `part9`），報告的逐字稿會顯示步驟名稱。舊紀錄裡是 `intro_nurse`，顯示為「（未分段）」。
