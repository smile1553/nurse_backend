"""Readable feedback pages made from one practice run.

For every submitted result this writes, next to the plain text file:

  <date>/<studentId>_<resultId8>.json   everything known about the run (the data)
  <date>/<studentId>_<resultId8>.html   one-page feedback report for that student
  <date>/index.html                     overview of everybody who practised that day

The pages are plain HTML with the styles and the chart inside them: they open by
double-click, need no internet and print on one sheet.
"""

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

INTENT_LABELS = {
    "reassure": "安撫",
    "encourage": "鼓勵",
    "neutral": "一般",
    "command": "命令",
    "force": "強迫",
    "threat": "威脅／責罵",
}
RAISING_INTENTS = ("command", "force", "threat")
SOOTHING_INTENTS = ("reassure", "encourage")
STATE_LABELS = {"Calm": "平靜", "Uneasy": "不安", "Crying": "哭泣", "Meltdown": "崩潰"}
INITIAL_TENSION = -5.0

# Reference chart palette: one series colour, status colours with a shape and a label.
SERIES = "#2a78d6"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
MUTED = "#898781"
GRID = "#e1e0d9"

STYLE = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--accent:#2a78d6}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:15px/1.6 "Noto Sans TC","Microsoft JhengHei","PingFang TC",sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 48px}
h1{font-size:24px;margin:0 0 2px;font-weight:700}
h2{font-size:17px;margin:0 0 12px;font-weight:700}
.sub{color:var(--ink2);font-size:13px;margin:0 0 20px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:0 0 16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 16px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.tile .k{color:var(--ink2);font-size:13px}
.tile .v{font-size:30px;font-weight:700;line-height:1.2}
.tile .v small{font-size:15px;font-weight:400;color:var(--muted)}
.tile.main{border-color:var(--accent)}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;color:var(--ink2);font-weight:600;font-size:13px;border-bottom:1px solid var(--line);padding:6px 8px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
tr:last-child td{border-bottom:none}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto}
.tag{display:inline-block;border-radius:999px;padding:0 9px;font-size:12px;line-height:20px;border:1px solid var(--line);color:var(--ink2);white-space:nowrap}
.tag.up{border-color:#d03b3b;color:#a52a2a}
.tag.down{border-color:#0ca30c;color:#0a6b0a}
.note{color:var(--ink2);font-size:13px;margin:8px 0 0}
.empty{color:var(--ink2);margin:0}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--ink2);font-size:13px;margin:0 0 6px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.chart{position:relative}
.chart svg{display:block;width:100%;height:auto}
#tip{position:absolute;display:none;pointer-events:none;background:#0b0b0b;color:#fff;border-radius:6px;padding:6px 9px;font-size:12px;line-height:1.5;max-width:300px;z-index:5}
.bar{height:10px;border-radius:0 4px 4px 0;background:var(--accent)}
.barrow{display:grid;grid-template-columns:150px 1fr 96px;gap:10px;align-items:center;font-size:14px;padding:4px 0}
.barrow.wide{grid-template-columns:230px 1fr 96px}
.barrow .n{text-align:right;color:var(--ink2);font-variant-numeric:tabular-nums}
a{color:#1c5cab}
@media (max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}.barrow,.barrow.wide{grid-template-columns:110px 1fr 84px}}
@media print{body{background:#fff}main{padding:0}.card,.tile{break-inside:avoid}}
"""

TIP_SCRIPT = """
<script>
(function(){
  var tip=document.getElementById('tip');
  if(!tip)return;
  var box=tip.parentNode;
  box.querySelectorAll('[data-tip]').forEach(function(el){
    el.addEventListener('mousemove',function(e){
      var r=box.getBoundingClientRect();
      tip.textContent=el.getAttribute('data-tip');
      tip.style.display='block';
      var x=e.clientX-r.left+12,y=e.clientY-r.top+12;
      if(x+tip.offsetWidth>r.width)x=Math.max(0,e.clientX-r.left-tip.offsetWidth-12);
      tip.style.left=x+'px';tip.style.top=y+'px';
    });
    el.addEventListener('mouseleave',function(){tip.style.display='none';});
  });
})();
</script>
"""


STEP_LABELS = {
    "intro_nurse": "（未分段）",
    "login": "護理站：登入與看病歷",
    "part0": "病房門口：打招呼",
    "part1": "自我介紹與說明",
    "part2": "觀察呼吸、介紹聽診",
    "part3": "貼紙鼓勵、媽媽示範聽心跳",
    "part4": "心尖脈、介紹耳溫",
    "part5": "用小熊示範量耳溫",
    "part6": "量耳溫、介紹血壓計",
    "part7": "選擇壓脈帶",
    "part8": "向媽媽說明為什麼量血壓",
    "part9": "小熊示範、量血壓",
}


def step_label(step_id: Any) -> str:
    text = str(step_id or "")
    return STEP_LABELS.get(text, text)


def clock_text(seconds: Any) -> str:
    """125 -> '2 分 05 秒'."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "—"
    if total < 0:
        return "—"
    return f"{total // 60} 分 {total % 60:02d} 秒"


def practice_seconds(login_time: Any, submitted_at: Any, steps: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """Length of the whole practice: login until the result arrived.

    When either time cannot be read (or they are in the wrong order), the time spent in the
    parts of the story is added up instead.
    """
    try:
        start = datetime.fromisoformat(str(login_time))
        end = datetime.fromisoformat(str(submitted_at))
        seconds = (end - start).total_seconds()
        if 0 <= seconds <= 6 * 3600:
            return round(seconds, 1)
    except (TypeError, ValueError):
        pass
    if steps:
        return round(sum(float(step.get("seconds") or 0) for step in steps), 1)
    return None


def steps_text(steps: Optional[List[Dict[str, Any]]]) -> str:
    """Lines for the plain text file: one per part of the story."""
    if not steps:
        return ""
    lines = ["各步驟花費時間："]
    for step in steps:
        lines.append(f"  {step_label(step.get('id'))}：{clock_text(step.get('seconds'))}")
    return "\n".join(lines) + "\n"


def steps_section(steps: Optional[List[Dict[str, Any]]]) -> str:
    if not steps:
        return '<p class="empty">這次練習沒有各步驟的時間（Unity 端需更新到會回傳的版本）。</p>'
    longest = max(float(step.get("seconds") or 0) for step in steps) or 1.0
    rows = []
    for step in steps:
        seconds = float(step.get("seconds") or 0)
        rows.append(
            f'<div class="barrow wide"><div>{esc(step_label(step.get("id")))}</div>'
            f'<div><div class="bar" style="width:{seconds / longest * 100:.0f}%" title="{esc(clock_text(seconds))}"></div></div>'
            f'<div class="n">{esc(clock_text(seconds))}</div></div>'
        )
    return "".join(rows) + '<p class="note">長條越長代表在這個步驟停留越久。</p>'


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def item_label(item_id: str) -> str:
    text = str(item_id or "")
    if text.startswith("quiz_"):
        return f"考題 {text[5:]}"
    return {"cuff": "選擇壓脈帶", "arm": "壓脈帶箭頭位置"}.get(text, text)


def read_utterances(path: Path) -> List[Dict[str, Any]]:
    """Lines written by ExcelResultService.append_student_transcript (one JSON per line)."""
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            rows.append(row)
    return rows


def with_changes(utterances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add 'before' and 'delta' so each sentence shows what it did to the child."""
    out: List[Dict[str, Any]] = []
    previous = INITIAL_TENSION
    for row in utterances:
        tension = row.get("tension")
        known = isinstance(tension, (int, float))
        after = float(tension) if known else previous
        out.append({**row, "known": known, "before": previous, "after": after, "delta": after - previous})
        previous = after
    return out


def local_clock(ts: Any, login_time: Any) -> str:
    """Sentence times are stored in UTC; show them in the time zone of the login time."""
    try:
        moment = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        zone = datetime.fromisoformat(str(login_time)).tzinfo
        if moment.tzinfo is not None and zone is not None:
            moment = moment.astimezone(zone)
        return moment.strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return str(ts or "")[11:19]


def level(tension: float) -> float:
    """Shown to teachers as 0 (calm) to 10 (meltdown)."""
    return max(0.0, min(10.0, float(tension) + 5.0))


def summarize(record: Dict[str, Any]) -> Dict[str, Any]:
    rows = with_changes(record.get("utterances") or [])
    return {
        "sentences": len(rows),
        "raised": sum(1 for r in rows if str(r.get("intent") or "") in RAISING_INTENTS),
        "soothed": sum(1 for r in rows if str(r.get("intent") or "") in SOOTHING_INTENTS),
        "peak": max([level(r["after"]) for r in rows if r["known"]], default=None),
    }


def tension_chart(rows: List[Dict[str, Any]]) -> str:
    rows = [r for r in rows if r["known"]]
    if not rows:
        return '<p class="empty">這次練習沒有每句話的緊張度紀錄（舊版後端留下的資料不含這項）。</p>'

    width, height = 920, 300
    left, right, top, bottom = 44, 64, 14, 48
    plot_w, plot_h = width - left - right, height - top - bottom
    count = len(rows)

    def x(index: int) -> float:  # index 0 = before the first sentence
        return left + plot_w * (index / max(1, count))

    def y(value: float) -> float:
        return top + plot_h * (1 - level(value) / 10.0)

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="芽芽緊張度隨每句話的變化">']
    # Bands for the four emotion states (same thresholds as the game).
    for low, high, name, fill in ((0, 2.5, "平靜", "#ffffff"), (2.5, 5, "不安", "#f5f4f0"),
                                  (5, 7.5, "哭泣", "#ffffff"), (7.5, 10, "崩潰", "#f5f4f0")):
        y_top, y_bottom = top + plot_h * (1 - high / 10), top + plot_h * (1 - low / 10)
        parts.append(f'<rect x="{left}" y="{y_top:.1f}" width="{plot_w}" height="{y_bottom - y_top:.1f}" fill="{fill}"/>')
        parts.append(f'<text x="{left + plot_w + 8}" y="{(y_top + y_bottom) / 2 + 4:.1f}" font-size="12" fill="{MUTED}">{name}</text>')
    for tick in (0, 2.5, 5, 7.5, 10):
        y_tick = top + plot_h * (1 - tick / 10)
        parts.append(f'<line x1="{left}" y1="{y_tick:.1f}" x2="{left + plot_w}" y2="{y_tick:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y_tick + 4:.1f}" font-size="12" fill="{MUTED}" text-anchor="end">{tick:g}</text>')
    step = max(1, round(count / 12))
    for index in range(1, count + 1):
        if index == 1 or index == count or index % step == 0:
            parts.append(f'<text x="{x(index):.1f}" y="{height - 28}" font-size="12" fill="{MUTED}" text-anchor="middle">{index}</text>')
    parts.append(f'<text x="{left + plot_w / 2:.1f}" y="{height - 6}" font-size="12" fill="{MUTED}" text-anchor="middle">第幾句話</text>')

    points = [(x(0), y(rows[0]["before"]))] + [(x(i + 1), y(r["after"])) for i, r in enumerate(rows)]
    parts.append('<polyline fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" points="%s"/>'
                 % (SERIES, " ".join(f"{px:.1f},{py:.1f}" for px, py in points)))

    for index, row in enumerate(rows, start=1):
        px, py = x(index), y(row["after"])
        label = INTENT_LABELS.get(str(row.get("intent") or ""), str(row.get("intent") or "一般"))
        tip = f"第 {index} 句（{label}）：{row.get('text', '')}　緊張度 {level(row['before']):g} → {level(row['after']):g}"
        if row["delta"] > 0.001:      # worse: red triangle pointing up
            mark = f'<path d="M{px:.1f},{py - 7:.1f} L{px + 6.5:.1f},{py + 5:.1f} L{px - 6.5:.1f},{py + 5:.1f} Z" fill="{CRITICAL}" stroke="#fcfcfb" stroke-width="2"/>'
        elif row["delta"] < -0.001:   # better: green triangle pointing down
            mark = f'<path d="M{px:.1f},{py + 7:.1f} L{px + 6.5:.1f},{py - 5:.1f} L{px - 6.5:.1f},{py - 5:.1f} Z" fill="{GOOD}" stroke="#fcfcfb" stroke-width="2"/>'
        else:
            mark = f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{SERIES}" stroke="#fcfcfb" stroke-width="2"/>'
        parts.append(f'<g data-tip="{esc(tip)}">{mark}<circle cx="{px:.1f}" cy="{py:.1f}" r="13" fill="transparent"/></g>')
    parts.append("</svg>")

    legend = (
        '<div class="legend">'
        f'<span><svg width="14" height="12"><path d="M7,1 L13,11 L1,11 Z" fill="{CRITICAL}"/></svg>這句話讓芽芽更緊張</span>'
        f'<span><svg width="14" height="12"><path d="M7,11 L13,1 L1,1 Z" fill="{GOOD}"/></svg>這句話安撫了芽芽</span>'
        f'<span><svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="{SERIES}"/></svg>沒有變化</span>'
        '</div>'
    )
    return legend + '<div class="chart">' + "".join(parts) + '<div id="tip"></div></div>' \
        + '<p class="note">縱軸是芽芽的緊張度：0 最平靜，10 最緊張。滑鼠移到點上可以看那句話。</p>'


def key_sentences(rows: List[Dict[str, Any]]) -> str:
    chosen = [(i, r) for i, r in enumerate(rows, start=1) if abs(r["delta"]) > 0.001]
    if not chosen:
        return '<p class="empty">這次練習沒有讓芽芽情緒改變的句子。</p>'
    lines = ['<div class="scroll"><table><thead><tr><th class="n">句</th><th>說了什麼</th><th>系統判斷</th><th class="n">緊張度</th></tr></thead><tbody>']
    for index, row in chosen:
        worse = row["delta"] > 0
        label = INTENT_LABELS.get(str(row.get("intent") or ""), str(row.get("intent") or ""))
        arrow = "▲ 更緊張" if worse else "▼ 安撫"
        lines.append(
            f'<tr><td class="n">{index}</td><td>{esc(row.get("text"))}</td>'
            f'<td><span class="tag {"up" if worse else "down"}">{arrow}</span> {esc(label)}</td>'
            f'<td class="n">{level(row["before"]):g} → {level(row["after"]):g}</td></tr>'
        )
    lines.append("</tbody></table></div>")
    return "".join(lines)


def items_table(items: Optional[List[Dict[str, Any]]]) -> str:
    if not items:
        return '<p class="empty">這次練習沒有逐題明細（Unity 端需更新到會回傳明細的版本）。</p>'
    lines = ['<div class="scroll"><table><thead><tr><th>項目</th><th>結果</th><th class="n">答錯次數</th><th class="n">得分</th></tr></thead><tbody>']
    for item in items:
        wrong = int(item.get("wrongAttempts") or 0)
        if not item.get("solved"):
            outcome = '<span class="tag up">✕ 未完成</span>'
        elif wrong == 0:
            outcome = '<span class="tag down">✓ 一次答對</span>'
        else:
            outcome = '<span class="tag">△ 修正後答對</span>'
        lines.append(
            f'<tr><td>{esc(item_label(item.get("id")))}</td><td>{outcome}</td>'
            f'<td class="n">{wrong}</td><td class="n">{int(item.get("points") or 0)}</td></tr>'
        )
    lines.append("</tbody></table></div>")
    return "".join(lines)


def transcript_table(rows: List[Dict[str, Any]], login_time: Any = None) -> str:
    if not rows:
        return '<p class="empty">沒有語音文字紀錄。</p>'
    lines = ['<div class="scroll"><table><thead><tr><th class="n">句</th><th>時間</th><th>步驟</th><th>說了什麼</th><th>系統判斷</th><th class="n">緊張度</th></tr></thead><tbody>']
    for index, row in enumerate(rows, start=1):
        label = INTENT_LABELS.get(str(row.get("intent") or ""), str(row.get("intent") or "—"))
        after = f'{level(row["after"]):g}' if row["known"] else "—"
        lines.append(
            f'<tr><td class="n">{index}</td><td class="n">{esc(local_clock(row.get("ts"), login_time))}</td>'
            f'<td>{esc(step_label(row.get("step")))}</td>'
            f'<td>{esc(row.get("text"))}</td><td>{esc(label)}</td><td class="n">{after}</td></tr>'
        )
    lines.append("</tbody></table></div>")
    return "".join(lines)


def page(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title><style>{STYLE}</style></head><body><main>{body}</main>{TIP_SCRIPT}</body></html>"
    )


def student_report_html(record: Dict[str, Any]) -> str:
    rows = with_changes(record.get("utterances") or [])
    items = record.get("items") or []
    first_try = record.get("correctCount", 0)
    transcript = transcript_table(rows, record.get("loginTime"))
    body = (
        "<h1>測量兒童生命徵象　練習回饋</h1>"
        f'<p class="sub">學號 {esc(record.get("studentId"))}　｜　登入時間 {esc(str(record.get("loginTime") or "").replace("T", " ")[:19])}'
        '　｜　<a href="index.html">回全班總覽</a></p>'
        '<div class="tiles">'
        f'<div class="tile main"><div class="k">總分</div><div class="v">{int(record.get("totalScore", 0))}<small> / 100</small></div></div>'
        f'<div class="tile"><div class="k">測量技術</div><div class="v">{int(record.get("questionScore", 0))}<small> / 80</small></div></div>'
        f'<div class="tile"><div class="k">說話語氣</div><div class="v">{int(record.get("toneScore", 0))}<small> / 20</small></div></div>'
        f'<div class="tile"><div class="k">考題一次答對</div><div class="v">{int(first_try)}<small> / 8</small></div></div>'
        f'<div class="tile"><div class="k">練習時間</div><div class="v" style="font-size:24px;line-height:36px">{esc(clock_text(record.get("durationSeconds")))}</div></div>'
        "</div>"
        f'<section class="card"><h2>芽芽的情緒變化</h2>{tension_chart(rows)}</section>'
        f'<section class="card"><h2>影響芽芽情緒的句子</h2>{key_sentences(rows)}</section>'
        f'<section class="card"><h2>考題與操作</h2>{items_table(items)}</section>'
        f'<section class="card"><h2>各步驟花費時間</h2>{steps_section(record.get("steps"))}</section>'
        f'<section class="card"><h2>完整語音文字紀錄</h2>{transcript}</section>'
    )
    return page(f'{record.get("studentId", "")} 練習回饋', body)


def overview_html(date_text: str, records: List[Dict[str, Any]]) -> str:
    records = sorted(records, key=lambda r: str(r.get("loginTime") or ""))
    count = len(records)

    def average(key: str) -> str:
        return f"{sum(float(r.get(key) or 0) for r in records) / count:.1f}" if count else "—"

    timed = [float(r["durationSeconds"]) for r in records if isinstance(r.get("durationSeconds"), (int, float))]
    average_time = clock_text(sum(timed) / len(timed)) if timed else "—"

    body = [
        "<h1>測量兒童生命徵象　全班總覽</h1>",
        f'<p class="sub">練習日期 {esc(date_text)}　｜　同一位學生練習多次會各列一筆</p>',
        '<div class="tiles">',
        f'<div class="tile main"><div class="k">練習筆數</div><div class="v">{count}</div></div>',
        f'<div class="tile"><div class="k">平均總分</div><div class="v">{average("totalScore")}<small> / 100</small></div></div>',
        f'<div class="tile"><div class="k">平均測量技術</div><div class="v">{average("questionScore")}<small> / 80</small></div></div>',
        f'<div class="tile"><div class="k">平均說話語氣</div><div class="v">{average("toneScore")}<small> / 20</small></div></div>',
        f'<div class="tile"><div class="k">平均練習時間</div><div class="v" style="font-size:24px;line-height:36px">{esc(average_time)}</div></div>',
        "</div>",
    ]

    # Which questions needed more than one try, over the runs that reported details.
    detailed = [r for r in records if r.get("items")]
    body.append('<section class="card"><h2>最多人沒有一次答對的項目</h2>')
    if detailed:
        missed: Dict[str, int] = {}
        order: List[str] = []
        for record in detailed:
            for item in record["items"]:
                item_id = str(item.get("id") or "")
                if item_id not in missed:
                    missed[item_id] = 0
                    order.append(item_id)
                if not item.get("solved") or int(item.get("wrongAttempts") or 0) > 0:
                    missed[item_id] += 1
        for item_id in sorted(order, key=lambda key: -missed[key]):
            share = missed[item_id] / len(detailed)
            body.append(
                f'<div class="barrow"><div>{esc(item_label(item_id))}</div>'
                f'<div><div class="bar" style="width:{share * 100:.0f}%" title="{missed[item_id]} / {len(detailed)}"></div></div>'
                f'<div class="n">{missed[item_id]} / {len(detailed)} 筆</div></div>'
            )
        body.append(f'<p class="note">以有回傳逐題明細的 {len(detailed)} 筆練習計算；長條越長代表越多人答錯過。</p>')
    else:
        body.append('<p class="empty">目前沒有逐題明細（Unity 端需更新到會回傳明細的版本）。</p>')
    body.append("</section>")

    body.append('<section class="card"><h2>每位學生</h2>')
    if records:
        body.append(
            '<div class="scroll"><table><thead><tr><th>學號</th><th class="n">登入時間</th><th class="n">練習時間</th><th class="n">總分</th>'
            '<th class="n">測量技術</th><th class="n">語氣</th><th class="n">命令／威脅</th><th class="n">安撫／鼓勵</th>'
            '<th class="n">最高緊張度</th><th>報告</th></tr></thead><tbody>'
        )
        for record in records:
            info = summarize(record)
            peak = f'{info["peak"]:g}' if info["peak"] is not None else "—"
            body.append(
                f'<tr><td>{esc(record.get("studentId"))}</td><td class="n">{esc(str(record.get("loginTime") or "")[11:16])}</td>'
                f'<td class="n">{esc(clock_text(record.get("durationSeconds")))}</td>'
                f'<td class="n"><b>{int(record.get("totalScore", 0))}</b></td><td class="n">{int(record.get("questionScore", 0))}</td>'
                f'<td class="n">{int(record.get("toneScore", 0))}</td><td class="n">{info["raised"]} 句</td>'
                f'<td class="n">{info["soothed"]} 句</td><td class="n">{peak}</td>'
                f'<td><a href="{esc(record.get("reportFile"))}">開啟</a></td></tr>'
            )
        body.append("</tbody></table></div>")
        body.append('<p class="note">緊張度 0 最平靜、10 最緊張。「命令／威脅」與「安撫／鼓勵」是系統判斷為該類的句數。</p>')
    else:
        body.append('<p class="empty">這一天還沒有練習紀錄。</p>')
    body.append("</section>")
    return page(f"{date_text} 全班總覽", "".join(body))


def load_records(folder: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("resultId"):
            records.append(record)
    return records
