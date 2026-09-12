import io
import json
import logging
from typing import Optional, List, Dict, Any

import matplotlib
matplotlib.use("Agg")  # Non-interactive headless backend
import matplotlib.pyplot as plt
import xlsxwriter

from db.models import Essay, User, GroupTopic

logger = logging.getLogger(__name__)


def extract_criterion_band(feedback: Dict[str, Any], key: str, alt_keys: List[str]) -> str:
    """Extracts band score for an IELTS criterion, inspecting official descriptors dict or direct keys."""
    descriptors = feedback.get("scores_by_official_descriptors", {})
    all_keys = [key] + alt_keys
    for k in all_keys:
        val = descriptors.get(k) or feedback.get(k)
        if isinstance(val, dict):
            band = val.get("band")
            if band is not None:
                return str(band)
        elif val is not None and not isinstance(val, (dict, list)):
            return str(val)
    return "-"


def calculate_group_report_data(
    topic: Optional[GroupTopic],
    submissions: List[tuple[Essay, Optional[User]]],
    historical_scores_map: Dict[int, List[float]],
    tracked_users: List[User],
    total_members_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aggregates submission metrics, criteria scores, and progress dynamics for a group.
    """
    topic_text = topic.topic_text if topic else "Umumiy guruh insholari"
    topic_date = topic.created_at if topic else None

    # Group submissions by unique user (keep latest submission per user for the topic)
    user_latest_submission: Dict[int, tuple[Essay, Optional[User]]] = {}
    for essay, user in submissions:
        uid = essay.user_id
        # Since submissions are ordered by created_at asc, subsequent overwrites give the latest
        user_latest_submission[uid] = (essay, user)

    students_results = []
    bands_list = []

    for uid, (essay, user) in user_latest_submission.items():
        # Parse JSON feedback
        feedback = {}
        if essay.feedback_json:
            try:
                feedback = json.loads(essay.feedback_json)
            except Exception:
                feedback = {}

        overall = (
            feedback.get("current_overall_band")
            or feedback.get("overall")
            or feedback.get("overall_band")
            or essay.overall_band
            or 0.0
        )
        try:
            overall = float(overall)
        except Exception:
            overall = essay.overall_band or 0.0
        bands_list.append(overall)

        tr = extract_criterion_band(feedback, "task_response", ["task_achievement", "tr"])
        cc = extract_criterion_band(feedback, "coherence_cohesion", ["coherence", "cc"])
        lr = extract_criterion_band(feedback, "lexical_resource", ["lexical", "lr"])
        gra = extract_criterion_band(feedback, "grammatical_accuracy", ["grammar", "gra", "grammatical_range_and_accuracy"])

        # Calculate progress dynamics (delta from previous essay in this group)
        history = historical_scores_map.get(uid, [])
        # History contains all essays of this student in chronological order
        delta = None
        trend = "new"
        delta_str = "Ilk insho"

        if len(history) >= 2:
            # Current essay is history[-1], previous is history[-2]
            prev_score = history[-2]
            delta = round(overall - prev_score, 1)
            if delta > 0:
                trend = "up"
                delta_str = f"+{delta:.1f}"
            elif delta < 0:
                trend = "down"
                delta_str = f"{delta:.1f}"
            else:
                trend = "same"
                delta_str = "0.0"

        full_name = user.full_name if user and user.full_name else f"Talaba #{uid}"
        username = user.username if user and user.username else ""

        students_results.append({
            "user_id": uid,
            "full_name": full_name,
            "username": username,
            "overall": overall,
            "tr": tr,
            "cc": cc,
            "lr": lr,
            "gra": gra,
            "word_count": essay.word_count or 0,
            "created_at": essay.created_at,
            "delta": delta,
            "trend": trend,
            "delta_str": delta_str,
        })

    # Sort leaderboard by overall band score descending
    students_results.sort(key=lambda s: s["overall"], reverse=True)

    # Assign rank medals
    for i, s in enumerate(students_results):
        rank = i + 1
        if rank == 1:
            s["medal"] = "🥇"
        elif rank == 2:
            s["medal"] = "🥈"
        elif rank == 3:
            s["medal"] = "🥉"
        else:
            s["medal"] = f"{rank}."

    submitted_user_ids = set(user_latest_submission.keys())
    not_submitted_users = [
        u for u in tracked_users if u.id not in submitted_user_ids
    ]

    submitted_count = len(students_results)
    total_tracked = len(tracked_users)
    total_members = total_members_count if total_members_count and total_members_count > 0 else max(total_tracked, submitted_count)

    avg_band = round(sum(bands_list) / len(bands_list), 1) if bands_list else 0.0
    max_band = max(bands_list) if bands_list else 0.0
    min_band = min(bands_list) if bands_list else 0.0

    return {
        "topic_text": topic_text,
        "topic_date": topic_date,
        "total_members": total_members,
        "submitted_count": submitted_count,
        "not_submitted_count": max(0, total_members - submitted_count),
        "not_submitted_users": not_submitted_users,
        "average_band": avg_band,
        "max_band": max_band,
        "min_band": min_band,
        "students": students_results,
    }


def format_report_text(data: Dict[str, Any]) -> str:
    """Formats aggregated report statistics into a clean, modern Telegram HTML message."""
    topic_text = data["topic_text"]
    if len(topic_text) > 100:
        topic_preview = topic_text[:97] + "..."
    else:
        topic_preview = topic_text

    submitted = data["submitted_count"]
    total = data["total_members"]
    pct = round((submitted / total) * 100, 1) if total > 0 else 0

    lines = [
        "📊 <b>IELTS Task 2: Guruh Natijalari Hisoboti</b>\n",
        f"📌 <b>Mavzu:</b> <i>\"{topic_preview}\"</i>\n",
        "📈 <b>Umumiy ko'rsatkichlar:</b>",
        f"• 👥 Guruh a'zolari: <b>{total} ta</b>",
        f"• ✍️ Insho topshirganlar: <b>{submitted} ta</b> ({pct}%)",
        f"• ⏳ Hali topshirmaganlar: <b>{data['not_submitted_count']} ta</b>",
    ]

    if submitted > 0:
        lines.append(
            f"• 🎯 O'rtacha ball: <b>{data['average_band']}</b> | Eng yuqori: <b>{data['max_band']}</b> | Eng past: <b>{data['min_band']}</b>\n"
        )
        lines.append("🏆 <b>O'quvchilar natijalari va Dinamika:</b>")

        for s in data["students"]:
            delta_indicator = ""
            if s["trend"] == "up":
                delta_indicator = f"📈 (+{s['delta']})"
            elif s["trend"] == "down":
                delta_indicator = f"📉 ({s['delta']})"
            elif s["trend"] == "same":
                delta_indicator = "➡️ (0.0)"
            else:
                delta_indicator = "🆕 (Ilk insho)"

            mention = f"@{s['username']}" if s["username"] else s["full_name"]
            line = (
                f"{s['medal']} <b>{mention}</b> — <b>{s['overall']}</b> {delta_indicator}\n"
                f"   └ <i>TR: {s['tr']} | CC: {s['cc']} | LR: {s['lr']} | GRA: {s['gra']} ({s['word_count']} so'z)</i>"
            )
            lines.append(line)
    else:
        lines.append("\nℹ️ <i>Ushbu mavzu bo'yicha hali birorta insho topshirilmagan.</i>")

    # If there are tracked users who haven't submitted
    not_submitted = data.get("not_submitted_users", [])
    if not_submitted and len(not_submitted) <= 10:
        mentions = [
            f"@{u.username}" if u.username else u.full_name
            for u in not_submitted[:10]
        ]
        lines.append(f"\n⏳ <b>Topshirmagan o'quvchilar:</b> {', '.join(mentions)}")

    lines.append("\n📁 <i>Batafsil ma'lumotlar ilova qilingan grafik rasm va Excel jadvalida keltirilgan.</i>")
    return "\n".join(lines)


def generate_report_chart(data: Dict[str, Any]) -> bytes:
    """
    Generates a high-quality visualization graphic (PNG bytes)
    illustrating student IELTS scores, criteria breakdown, and progression dynamics.
    """
    students = data.get("students", [])
    if not students:
        # Generate an empty state card
        fig, ax = plt.subplots(figsize=(8, 4), facecolor="#0f172a")
        ax.set_facecolor("#0f172a")
        ax.text(
            0.5,
            0.5,
            "Hozircha insholar topshirilmagan\n(No submissions yet)",
            ha="center",
            va="center",
            color="#94a3b8",
            fontsize=14,
            fontweight="bold",
        )
        ax.axis("off")
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    # Take top 15 students for clean layout
    display_students = list(reversed(students[:15]))
    names = [s["username"] if s["username"] else s["full_name"][:16] for s in display_students]
    scores = [s["overall"] for s in display_students]

    # Bar colors based on IELTS band
    colors = []
    for sc in scores:
        if sc >= 7.0:
            colors.append("#10b981")  # Green
        elif sc >= 6.0:
            colors.append("#38bdf8")  # Sky blue
        elif sc >= 5.0:
            colors.append("#f59e0b")  # Amber
        else:
            colors.append("#ef4444")  # Red

    fig, ax = plt.subplots(figsize=(10, max(5, len(display_students) * 0.45)), facecolor="#0f172a")
    ax.set_facecolor("#1e293b")

    bars = ax.barh(names, scores, color=colors, height=0.62, edgecolor="#334155", linewidth=1)
    ax.set_xlim(0, 9.5)
    ax.set_xlabel("IELTS Band Score (0.0 - 9.0)", color="#94a3b8", fontsize=11, fontweight="bold", labelpad=10)

    # Title & Topic
    topic_title = data.get("topic_text", "")
    if len(topic_title) > 60:
        topic_title = topic_title[:57] + "..."
    fig.suptitle("IELTS Task 2: O'quvchilar Natijalari va Dinamikasi", fontsize=14, fontweight="bold", color="#f8fafc", y=0.98)
    ax.set_title(f"Mavzu: {topic_title}", fontsize=10, color="#cbd5e1", pad=12)

    # Styling ticks and grid
    ax.tick_params(colors="#cbd5e1", labelsize=10)
    ax.grid(axis="x", color="#334155", linestyle="--", alpha=0.7)
    for spine in ax.spines.values():
        spine.set_color("#334155")

    # Add score and trend labels onto bars
    for bar, st in zip(bars, display_students):
        width = bar.get_width()
        trend_str = ""
        if st["trend"] == "up":
            trend_str = f" (+{st['delta']}) [up]"
        elif st["trend"] == "down":
            trend_str = f" ({st['delta']}) [down]"
        elif st["trend"] == "same":
            trend_str = " (0.0)"
        else:
            trend_str = " [new]"

        label_text = f" {width:.1f}{trend_str}"
        ax.text(
            width + 0.15,
            bar.get_y() + bar.get_height() / 2,
            label_text,
            va="center",
            ha="left",
            color="#f8fafc",
            fontweight="bold",
            fontsize=10,
        )

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def generate_report_excel(data: Dict[str, Any]) -> bytes:
    """
    Generates a professionally styled Excel spreadsheet (.xlsx bytes)
    containing full student criteria breakdowns, word counts, and summary formulas.
    """
    buf = io.BytesIO()
    workbook = xlsxwriter.Workbook(buf, {"in_memory": True})
    worksheet = workbook.add_worksheet("IELTS_Natijalar")

    # Formats
    title_fmt = workbook.add_format({
        "bold": True,
        "font_size": 14,
        "font_color": "#1e3a8a",
        "align": "left",
    })
    subtitle_fmt = workbook.add_format({
        "italic": True,
        "font_size": 10,
        "font_color": "#475569",
    })
    header_fmt = workbook.add_format({
        "bold": True,
        "font_color": "#ffffff",
        "bg_color": "#1e40af",
        "border": 1,
        "align": "center",
        "valign": "vcenter",
    })
    cell_center = workbook.add_format({"align": "center", "valign": "vcenter", "border": 1})
    cell_left = workbook.add_format({"align": "left", "valign": "vcenter", "border": 1})
    cell_int_num = workbook.add_format({"align": "center", "valign": "vcenter", "border": 1, "num_format": "#,##0"})
    cell_score_num = workbook.add_format({"align": "center", "valign": "vcenter", "border": 1, "num_format": "0.0"})
    cell_overall_num = workbook.add_format({"bold": True, "align": "center", "valign": "vcenter", "border": 1, "num_format": "0.0"})
    up_fmt = workbook.add_format({"bold": True, "font_color": "#15803d", "align": "center", "valign": "vcenter", "border": 1})
    down_fmt = workbook.add_format({"bold": True, "font_color": "#b91c1c", "align": "center", "valign": "vcenter", "border": 1})
    summary_fmt = workbook.add_format({"bold": True, "bg_color": "#f1f5f9", "border": 1, "align": "center"})
    summary_score_fmt = workbook.add_format({"bold": True, "bg_color": "#f1f5f9", "border": 1, "align": "center", "num_format": "0.0"})
    summary_int_fmt = workbook.add_format({"bold": True, "bg_color": "#f1f5f9", "border": 1, "align": "center", "num_format": "#,##0"})

    # Title block
    worksheet.write("A1", "IELTS Task 2: O'quvchilar Natijalari Hisoboti", title_fmt)
    worksheet.write("A2", f"Mavzu: {data.get('topic_text', '')}", subtitle_fmt)
    worksheet.write("A3", f"Topshirganlar: {data['submitted_count']} / Jami: {data['total_members']} ta", subtitle_fmt)

    # Headers
    headers = [
        "№", "O'quvchi", "Telegram", "Topshirilgan vaqt",
        "So'zlar", "TR", "CC", "LR", "GRA", "Overall Band", "Dinamika"
    ]
    for col_idx, h in enumerate(headers):
        worksheet.write(4, col_idx, h, header_fmt)

    def _write_num_cell(row, col, val, num_fmt, fallback_fmt):
        """Writes value as a real Excel number if parseable as float, avoiding 'Number Stored as Text'."""
        if val is None:
            worksheet.write(row, col, "-", fallback_fmt)
            return
        try:
            num = float(val)
            worksheet.write_number(row, col, num, num_fmt)
        except (ValueError, TypeError):
            worksheet.write(row, col, str(val), fallback_fmt)

    # Populate rows
    students = data.get("students", [])
    row_idx = 5
    for idx, s in enumerate(students):
        worksheet.write(row_idx, 0, idx + 1, cell_center)
        worksheet.write(row_idx, 1, s["full_name"], cell_left)
        worksheet.write(row_idx, 2, f"@{s['username']}" if s["username"] else "-", cell_left)
        time_str = s["created_at"].strftime("%Y-%m-%d %H:%M") if s["created_at"] else "-"
        worksheet.write(row_idx, 3, time_str, cell_center)
        _write_num_cell(row_idx, 4, s["word_count"], cell_int_num, cell_center)
        _write_num_cell(row_idx, 5, s["tr"], cell_score_num, cell_center)
        _write_num_cell(row_idx, 6, s["cc"], cell_score_num, cell_center)
        _write_num_cell(row_idx, 7, s["lr"], cell_score_num, cell_center)
        _write_num_cell(row_idx, 8, s["gra"], cell_score_num, cell_center)
        _write_num_cell(row_idx, 9, s["overall"], cell_overall_num, cell_center)

        # Dinamika formatting
        if s["trend"] == "up":
            worksheet.write(row_idx, 10, f"+{s['delta']} (O'sish)", up_fmt)
        elif s["trend"] == "down":
            worksheet.write(row_idx, 10, f"{s['delta']} (Pasayish)", down_fmt)
        elif s["trend"] == "same":
            worksheet.write(row_idx, 10, "0.0 (O'zgarishsiz)", cell_center)
        else:
            worksheet.write(row_idx, 10, "Ilk insho", cell_center)

        row_idx += 1

    # Summary row
    if students:
        worksheet.write(row_idx, 0, "O'rtacha:", summary_fmt)
        worksheet.write(row_idx, 1, "", summary_fmt)
        worksheet.write(row_idx, 2, "", summary_fmt)
        worksheet.write(row_idx, 3, "", summary_fmt)

        def _calc_avg(key: str) -> Optional[float]:
            vals = []
            for item in students:
                try:
                    vals.append(float(item[key]))
                except (ValueError, TypeError):
                    pass
            return round(sum(vals) / len(vals), 1) if vals else None

        avg_wc = _calc_avg("word_count")
        avg_tr = _calc_avg("tr")
        avg_cc = _calc_avg("cc")
        avg_lr = _calc_avg("lr")
        avg_gra = _calc_avg("gra")
        avg_ovr = _calc_avg("overall")

        worksheet.write_formula(row_idx, 4, f'=IFERROR(ROUND(AVERAGE(E6:E{row_idx}), 0), "-")', summary_int_fmt, value=round(avg_wc) if avg_wc is not None else None)
        worksheet.write_formula(row_idx, 5, f'=IFERROR(ROUND(AVERAGE(F6:F{row_idx}), 1), "-")', summary_score_fmt, value=avg_tr)
        worksheet.write_formula(row_idx, 6, f'=IFERROR(ROUND(AVERAGE(G6:G{row_idx}), 1), "-")', summary_score_fmt, value=avg_cc)
        worksheet.write_formula(row_idx, 7, f'=IFERROR(ROUND(AVERAGE(H6:H{row_idx}), 1), "-")', summary_score_fmt, value=avg_lr)
        worksheet.write_formula(row_idx, 8, f'=IFERROR(ROUND(AVERAGE(I6:I{row_idx}), 1), "-")', summary_score_fmt, value=avg_gra)
        worksheet.write_formula(row_idx, 9, f'=IFERROR(ROUND(AVERAGE(J6:J{row_idx}), 1), "-")', summary_score_fmt, value=avg_ovr)
        worksheet.write(row_idx, 10, "", summary_fmt)

    # Column widths
    col_widths = [5, 24, 18, 18, 10, 8, 8, 8, 8, 14, 18]
    for i, w in enumerate(col_widths):
        worksheet.set_column(i, i, w)

    workbook.close()
    buf.seek(0)
    return buf.getvalue()
