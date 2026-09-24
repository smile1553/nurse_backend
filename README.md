# nurse_backend

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

輸入限制：

- `loginTime` 必須是含時區的 ISO 8601。
- `correctCount` 必須是整數 `0～8`。
- `toneScore` 必須是整數 `0～20`。
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

啟動程式時，如果專案目錄沒有 `openai_api.json`，系統會自動建立：

```json
{
  "apiKey": "PASTE_YOUR_OPENAI_API_KEY_HERE"
}
```

請將範例文字替換成自己的 OpenAI API key。此檔案已加入 `.gitignore`，不會提交到 Git。
