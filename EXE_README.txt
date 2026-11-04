點兩下 NurseBackend.exe 即啟動完整護理教學後端，請保持視窗開啟。
看到 Application startup complete 與 Uvicorn running 表示服務已就緒。
停止：按 Ctrl+C，或關閉視窗。

修改同資料夾的 .env 後，停止並重新啟動程式即可生效。
API key 不要加到程式裡。此資料夾的 .env 可能含私人金鑰，請只交給授權使用者。
既有 Windows 環境變數優先於 .env，與開發版一致。

Unity / Quest 與這台電腦需在同一區域網路，連線位址會顯示在啟動視窗。
第一次啟動若 Windows 防火牆詢問，請允許私人網路存取。
報告：http://127.0.0.1:8000/reports
所有新成績、報告、錄音與上傳佇列均存在此資料夾的 out 子資料夾。
舊版專案的 out 不會自動複製，若要移轉舊資料，請先停止兩邊後端並由維護人員移轉完整 out。

請搬移整個 NurseBackend 資料夾，不要只取出 exe；建議放在桌面或文件等可寫入位置。
_internal 與 models 是必要元件，請勿刪除。
隨附 CPU 版 Whisper medium 模型，不需另外安裝 Python 或下載模型。
OpenAI / Deepgram 與教師端上傳需要有效設定及網路。
Windows 語音播放使用系統安裝的語音；中文發音需有中文語音套件。
啟動失敗時，請提供 logs/startup-error.log 給維護人員。
