# 教師端背景上傳（新增功能）

保留現有 Excel、JSON、TXT、HTML、輸出目錄與 Unity HTTP/WebSocket API。
僅在個人 JSON 成功保存後，將固定快照寫入 `out/student_results/upload_outbox.sqlite3`。
上傳或 outbox 失敗不改變原有成績提交行為；JSON 保存失敗時不會誤將舊 JSON 入列。

## 設定

在本機既有 `.env` 填入（不要提交金鑰）：

```dotenv
RESULT_UPLOAD_URL=https://你的正式教師端/api/results
RESULT_UPLOAD_API_KEY=與教師端UPLOAD_API_KEY相同的值
RESULT_UPLOAD_INCLUDE_EXISTING=0
```

安裝 `python -m pip install -r requirements.txt` 後，依原本方式重新啟動後端。
兩項連線設定任一為空時不會上傳，但新結果仍可入列等待後續啟用。
只接受 HTTPS；本機測試例外允許 localhost、127.0.0.1 的 HTTP。
Unity 不需要設定教師端網址或金鑰，Web 程式也未修改。

## 行為與驗收

- 預設僅掃描首次初始化上傳器後新寫入／修改的結果 JSON，不自動匯入未變動的歷史資料。
  若重送舊結果，它仍會依原有流程重新保存並加入上傳。
  若確定要補傳全部既有日期資料夾，可設 `RESULT_UPLOAD_INCLUDE_EXISTING=1` 並重啟。
- 每個 `sessionId/resultId` 的第一份入列快照固定保存，後續本機報告改寫不會改動它，避免教師端 409。
  如需更正已入列資料，須由維護人員與 Web 組員協調；不要刪除 outbox 或更換識別碼來繞過去重。
- 背景約每 5 秒檢查到期項目、每 30 秒掃描補回遺漏入列的 JSON。
  暫時失敗採退避，最長 1 小時；恢復網路／重啟後會依到期時間重試。
- 教師端只有回覆 HTTP 2xx 且 JSON `ok:true` 才標記 `uploaded`。
  400/409/413/422 標記 `blocked`；401/403 保持待傳，請檢查金鑰後重啟。
- `GET /api/uploads/status` 回傳 `enabled`、`counts` 與 `issues`。
  `enabled:true` 只代表有設定連線資料，不代表教師端已接受結果。
  一筆成功的狀態例：`{"enabled":true,"counts":{"uploaded":1},"issues":[]}`。
- 教師端限制 2 MB、500 句逐字稿、40 個題目、60 個步驟，超限不會自動截斷。
- 使用單一後端程序；首次正式驗收應確認 Unity 提交、本機原有檔案、uploaded 筆數及教師端報告。

程式測試不等於正式上傳驗收：必須有部署完成的教師端與有效金鑰。
斷網補傳僅針對結果上傳，不代表 OpenAI／Deepgram 能離線運作。
