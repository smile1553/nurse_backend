"""Measure how often the intent classifier agrees with hand-labelled sentences.

Run it from the backend folder, with the same Python environment as the server:

    python accuracy_test/run_accuracy_test.py

It reads   accuracy_test/test_sentences.csv   (columns: text, expected, labeled_by, note)
and writes accuracy_test/results.csv          every sentence with what the system answered
           accuracy_test/accuracy_page.html   one page with the numbers and the confusion matrix

Nothing here invents a number: every figure on the page is counted from results.csv, and
the line about who labelled the sentences is whatever you pass with --labeled-by (or the
labeled_by column). Describe that truthfully; the page is only as credible as that line.

Options:
    --labeled-by "..."      who decided the expected answers (shown on the page)
    --speech-accuracy 93.5  character accuracy of the speech recognition, if you measured it
    --speech-note "..."     how that was measured (shown next to it)
"""

import argparse
import csv
import html
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

LABELS = ["reassure", "encourage", "neutral", "command", "force", "threat"]
NAMES = {"reassure": "安撫", "encourage": "鼓勵", "neutral": "一般",
         "command": "命令", "force": "強迫", "threat": "威脅／責罵"}
# What a sentence does to the child: the game only reacts to this direction.
DIRECTION = {"reassure": "calm", "encourage": "calm", "neutral": "none",
             "command": "tense", "force": "tense", "threat": "tense"}
RAMP = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281"]


def read_sentences(path: Path):
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            text = (row.get("text") or "").strip()
            expected = (row.get("expected") or "").strip().lower()
            if not text:
                continue
            if expected not in LABELS:
                raise SystemExit(f"'{text}': expected 欄位必須是 {', '.join(LABELS)} 其中之一，現在是 '{expected}'")
            rows.append({"text": text, "expected": expected,
                         "labeled_by": (row.get("labeled_by") or "").strip(),
                         "note": (row.get("note") or "").strip()})
    if not rows:
        raise SystemExit("test_sentences.csv 裡沒有句子")
    return rows


def classify_all(rows):
    import intent_llm
    from semantic_analysis import INTENT_ALIASES

    if intent_llm.openai_client is None:
        raise SystemExit("找不到有效的 OpenAI 金鑰，語意分析沒有啟動，無法測試。請先確認後端的 .env。")

    for index, row in enumerate(rows, start=1):
        result = intent_llm.analyze_intent([], row["text"])
        # The classifier answers with this exact fallback when the model did not reply.
        if result == intent_llm.FALLBACK:
            time.sleep(1.0)
            result = intent_llm.analyze_intent([], row["text"])
        failed = result == intent_llm.FALLBACK
        intent = str(result.get("intent") or "neutral").strip().lower()
        intent = INTENT_ALIASES.get(intent, intent)
        row["predicted"] = "" if failed else (intent if intent in LABELS else "neutral")
        row["failed"] = failed
        row["toxicity"] = result.get("toxicity", 0.0)
        mark = "？" if failed else ("✓" if row["predicted"] == row["expected"] else "✗")
        print(f"{index:3d}/{len(rows)} {mark} {row['text']}  → {NAMES.get(row['predicted'], '沒有回應')}（應為 {NAMES[row['expected']]}）")
    return rows


def write_results(rows, path: Path):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text", "expected", "predicted", "correct", "same_direction", "toxicity", "labeled_by", "note"])
        for row in rows:
            if row["failed"]:
                writer.writerow([row["text"], row["expected"], "(no answer)", "", "", "", row["labeled_by"], row["note"]])
                continue
            writer.writerow([row["text"], row["expected"], row["predicted"],
                             int(row["predicted"] == row["expected"]),
                             int(DIRECTION[row["predicted"]] == DIRECTION[row["expected"]]),
                             row["toxicity"], row["labeled_by"], row["note"]])


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def build_page(rows, labeled_by: str, speech_accuracy, speech_note: str) -> str:
    answered = [r for r in rows if not r["failed"]]
    unanswered = len(rows) - len(answered)
    total = len(answered)
    if total == 0:
        raise SystemExit("系統一句都沒有回應，無法產生結果。")
    correct = sum(1 for r in answered if r["predicted"] == r["expected"])
    same_direction = sum(1 for r in answered if DIRECTION[r["predicted"]] == DIRECTION[r["expected"]])
    matrix = {e: {p: 0 for p in LABELS} for e in LABELS}
    for r in answered:
        matrix[r["expected"]][r["predicted"]] += 1
    per_label = {e: sum(matrix[e].values()) for e in LABELS}
    biggest = max(max(row.values()) for row in matrix.values()) or 1

    # The pair that is confused most often, for the note beside the matrix.
    worst = max(((matrix[e][p], e, p) for e in LABELS for p in LABELS if e != p), default=(0, "", ""))
    worst_note = (f"最常混淆：標註為「{NAMES[worst[1]]}」的句子有 {worst[0]} 句被判成「{NAMES[worst[2]]}」。"
                  if worst[0] else "沒有判錯的句子。")
    example = next((r for r in answered if r["expected"] == worst[1] and r["predicted"] == worst[2]), None) if worst[0] else None

    cells = ['<tr><th class="corner">標註 ＼ 系統判斷</th>' + "".join(f"<th>{NAMES[p]}</th>" for p in LABELS) + '<th class="sum">句數</th></tr>']
    for e in LABELS:
        line = [f"<tr><th>{NAMES[e]}</th>"]
        for p in LABELS:
            count = matrix[e][p]
            step = 0 if count == 0 else 1 + round((len(RAMP) - 2) * count / biggest)
            ink = "#ffffff" if step >= 4 else "#0b0b0b"
            ring = " wrong" if (count and e != p and (count, e, p) == worst) else ""
            line.append(f'<td class="cell{ring}" style="background:{RAMP[step]};color:{ink}" '
                        f'title="標註：{NAMES[e]}　系統：{NAMES[p]}　{count} 句">{count if count else ""}</td>')
        line.append(f'<td class="sum">{per_label[e]}</td></tr>')
        cells.append("".join(line))

    speech_tile = ""
    if speech_accuracy is not None:
        speech_tile = (f'<div class="tile"><div class="k">語音辨識字正確率</div><div class="v">{speech_accuracy:g}<small>%</small></div>'
                       f'<div class="d">{esc(speech_note) or "&nbsp;"}</div></div>')

    example_html = ""
    if example:
        example_html = (f'<div class="example"><b>誤判的例子</b>　「{esc(example["text"])}」　'
                        f'標註為 {NAMES[example["expected"]]}，系統判為 {NAMES[example["predicted"]]}。</div>')
    unanswered_note = f"另有 {unanswered} 句系統沒有回應，未列入計算。" if unanswered else ""
    counts = "、".join(f"{NAMES[e]} {per_label[e]}" for e in LABELS)

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>系統準確度</title><style>
*{{box-sizing:border-box}}
body{{margin:0;background:#f9f9f7;color:#0b0b0b;font:16px/1.6 "Noto Sans TC","Microsoft JhengHei","PingFang TC",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:36px 20px 40px}}
h1{{font-size:30px;line-height:1.3;margin:0 0 6px}}
.lead{{color:#52514e;margin:0 0 24px}}
.grid{{display:grid;grid-template-columns:320px 1fr;gap:20px;align-items:start}}
.tile{{background:#fcfcfb;border:1px solid #e1e0d9;border-radius:10px;padding:16px 18px;margin:0 0 14px}}
.tile.main{{border-color:#2a78d6}}
.tile .k{{color:#52514e;font-size:14px}}
.tile .v{{font-size:52px;font-weight:700;line-height:1.15}}
.tile .v small{{font-size:22px;font-weight:400;color:#898781}}
.tile .d{{color:#52514e;font-size:13px}}
.card{{background:#fcfcfb;border:1px solid #e1e0d9;border-radius:10px;padding:18px 20px}}
h2{{font-size:17px;margin:0 0 12px}}
.scroll{{overflow-x:auto}}
table{{border-collapse:separate;border-spacing:2px;font-size:14px}}
th{{font-weight:600;color:#52514e;padding:6px 10px;white-space:nowrap;text-align:center}}
tr>th:first-child{{text-align:right}}
th.corner{{font-weight:400;font-size:12px;color:#898781}}
td.cell{{width:78px;height:46px;text-align:center;font-weight:700;border-radius:4px;font-variant-numeric:tabular-nums}}
td.cell.wrong{{outline:2px solid #0b0b0b;outline-offset:-2px}}
.sum{{color:#898781;text-align:right;padding-left:12px;font-variant-numeric:tabular-nums}}
.note{{color:#52514e;font-size:14px;margin:12px 0 0}}
.example{{background:#f5f4f0;border-radius:8px;padding:10px 14px;margin:12px 0 0;font-size:14px}}
.source{{color:#52514e;font-size:13px;margin:22px 0 0;border-top:1px solid #e1e0d9;padding-top:12px}}
@media (max-width:820px){{.grid{{grid-template-columns:1fr}}}}
@media print{{body{{background:#fff}}}}
</style></head><body><main>
<h1>語意判斷與人工標註的一致率為 {correct / total * 100:.1f}%</h1>
<p class="lead">以 {total} 句測試句比對系統判斷與標註答案；只看「讓病童更平靜／更緊張／沒有影響」的方向時，一致率為 {same_direction / total * 100:.1f}%。</p>
<div class="grid">
<div>
<div class="tile main"><div class="k">六類意圖完全一致</div><div class="v">{correct / total * 100:.1f}<small>%</small></div><div class="d">{correct} / {total} 句</div></div>
<div class="tile"><div class="k">影響方向一致（平靜／緊張／無影響）</div><div class="v">{same_direction / total * 100:.1f}<small>%</small></div><div class="d">{same_direction} / {total} 句　病童情緒只依這個方向升降</div></div>
{speech_tile}
</div>
<div class="card"><h2>混淆矩陣：每一格是句數</h2>
<div class="scroll"><table>{"".join(cells)}</table></div>
<p class="note">橫列是標註答案，直欄是系統判斷；左上到右下的對角線是判斷一致的句子，顏色越深句數越多。{worst_note}</p>
{example_html}
</div>
</div>
<p class="source">測試集共 {total} 句（{counts}），標註者：{esc(labeled_by)}。系統以文字直接輸入測試，未經語音辨識。{unanswered_note}</p>
</main></body></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sentences", default=str(HERE / "test_sentences.csv"))
    parser.add_argument("--labeled-by", default="")
    parser.add_argument("--speech-accuracy", type=float, default=None)
    parser.add_argument("--speech-note", default="")
    args = parser.parse_args()

    rows = read_sentences(Path(args.sentences))
    labeled_by = args.labeled_by.strip() or "、".join(sorted({r["labeled_by"] for r in rows if r["labeled_by"]}))
    if not labeled_by:
        raise SystemExit('請說明答案是誰標的，例如：--labeled-by "專題團隊三位成員依六類定義標註"\n'
                         "（這句話會印在頁面上，請照實寫。）")

    rows = classify_all(rows)
    write_results(rows, HERE / "results.csv")
    (HERE / "accuracy_page.html").write_text(
        build_page(rows, labeled_by, args.speech_accuracy, args.speech_note), encoding="utf-8")
    answered = [r for r in rows if not r["failed"]]
    correct = sum(1 for r in answered if r["predicted"] == r["expected"])
    print(f"\n一致 {correct} / {len(answered)} 句。已寫出 results.csv 與 accuracy_page.html（在 accuracy_test 資料夾）。")


if __name__ == "__main__":
    main()
