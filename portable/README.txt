護你童行：Windows 64 位元可攜版

1. 將 ZIP 完整解壓縮至可寫入的資料夾，不要直接在 ZIP 裡執行。
2. 雙擊「編輯設定.bat」，填入 OPENAI_API_KEY 與 DEEPGRAM_API_KEY，儲存。
   也可直接用記事本開啟 backend/.env。請保留檔名，不要另存成 .env.txt。
3. 雙擊「啟動.bat」。看到 Application startup complete / Uvicorn running 即啟動完成。
4. 保持視窗開啟。停止時按 Ctrl+C；若出現終止批次工作提示，輸入 Y。

報告：http://127.0.0.1:8000/reports
Quest / Unity 使用啟動視窗顯示的區網位址，不能填 localhost 或 0.0.0.0。
電腦與頭盔需在可互連的同一區域網路；防火牆詢問時允許私人網路存取。
若校園 Wi-Fi 隔離裝置，請向網管確認可互連的網路。

設定檔：backend/.env（修改後重新啟動）
成績、Excel、報告、錄音及上傳佇列：backend/out
啟動錯誤：backend/logs/startup-error.log
保留整個資料夾，不要只移動 BAT 或 python.exe。
未移入舊成績；移轉前先停止兩邊服務，備份後再移轉完整 out。

不需另外安裝 Python。內附 Python 官方 3.13.9 x64 與預先安裝的套件。
語音辨識沿用現有 EXE 的 Deepgram 雲端方式，需有效金鑰與網路。
ASR_WARMUP_ON_START 請保持 0；本版未附本機 faster-whisper 與模型。
Windows 中文語音播放需系統已安裝可用的中文語音。
既有系統環境變數優先於 .env，與原專案一致。
請勿公開或提交填好金鑰的 .env；其中金鑰可被取得資料夾的人讀取。

本版沒有關閉或繞過 Windows 防護。官方 python.exe 簽章已驗證，
但老師電腦的智慧型應用程式控制仍可能檢查 BAT、DLL 或擴充套件。
如仍封鎖，請保留被擋檔名與畫面交由維護者或網管確認。
本機驗證不代表已通過老師電腦、實體頭盔或雲端服務測試。
