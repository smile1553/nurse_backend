點兩下 NurseBackend.exe 即啟動完整護理教學後端，請保持視窗開啟。
看到 Application startup complete 與 Uvicorn running 表示服務已就緒。
停止：按 Ctrl+C，或關閉視窗。

第一次使用請先用記事本開啟同資料夾的 .env，填入 OPENAI_API_KEY 與 DEEPGRAM_API_KEY。
修改 .env 後，停止並重新啟動程式即可生效。
請勿把填好私人金鑰的 .env 再推回公開 GitHub。
既有 Windows 環境變數優先於 .env，與開發版一致。

Unity / Quest 與這台電腦需在同一區域網路，連線位址會顯示在啟動視窗。
第一次啟動若 Windows 防火牆詢問，請允許私人網路存取。
報告：http://127.0.0.1:8000/reports
所有新成績、報告、錄音與上傳佇列均存在此資料夾的 out 子資料夾。
舊版專案的 out 不會自動複製，若要移轉舊資料，請先停止兩邊後端並由維護人員移轉完整 out。

請保留 NurseBackend.exe、.env 與 README.txt 在同一個 Windows 資料夾。
所有執行元件都已包進單一 exe；第一次開啟或每次啟動可能會稍等幾秒鐘。
不需安裝 Python；語音辨識使用 .env 內設定的 Deepgram。
OpenAI / Deepgram 與教師端上傳需要有效設定及網路。
Windows 語音播放使用系統安裝的語音；中文發音需有中文語音套件。
啟動失敗時，請提供 logs/startup-error.log 給維護人員。
