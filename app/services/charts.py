from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.config import AppSettings
from app.db import DatabaseAdapter

COLOR_GREEN = "#14532d"
COLOR_GREEN_MID = "#16a34a"
COLOR_NAVY = "#1e3a5f"
COLOR_GOLD = "#d97706"
COLOR_TEAL = "#0f766e"
COLOR_SLATE = "#475569"


def generate_survey_chart(db: DatabaseAdapter, settings: AppSettings, department: str = "ALL") -> Path:
    suffix = "all" if department == "ALL" else department.lower().replace(" ", "_").replace("&", "and")
    out_path = settings.charts_dir / f"survey_analytics_{suffix}.png"

    with db.connection() as conn:
        if department == "ALL":
            topic_rows = db.fetch_all(
                conn,
                "SELECT requested_topic, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_r "
                "FROM firm_surveys GROUP BY requested_topic ORDER BY cnt ASC",
            )
            chamber_rows = db.fetch_all(
                conn,
                "SELECT chamber, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_r "
                "FROM firm_surveys GROUP BY chamber ORDER BY cnt DESC",
            )
            summary = db.fetch_one(
                conn,
                "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating), 2), 0) AS avg_r FROM firm_surveys",
            )
        else:
            topic_rows = db.fetch_all(
                conn,
                "SELECT requested_topic, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_r "
                "FROM firm_surveys WHERE department = %s GROUP BY requested_topic ORDER BY cnt ASC",
                (department,),
            )
            chamber_rows = db.fetch_all(
                conn,
                "SELECT chamber, COUNT(*) AS cnt, ROUND(AVG(rating), 2) AS avg_r "
                "FROM firm_surveys WHERE department = %s GROUP BY chamber ORDER BY cnt DESC",
                (department,),
            )
            summary = db.fetch_one(
                conn,
                "SELECT COUNT(*) AS cnt, COALESCE(ROUND(AVG(rating), 2), 0) AS avg_r "
                "FROM firm_surveys WHERE department = %s",
                (department,),
            )

    total_resp = int(summary["cnt"]) if summary else 0
    avg_sat = float(summary["avg_r"]) if summary else 0.0
    scope = "All Departments" if department == "ALL" else department

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#cbd5e1"})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2), dpi=160)
    fig.patch.set_facecolor("#ffffff")
    fig.suptitle(
        f"ANN & ASSOCIATES LAW FIRM — Survey Intelligence ({scope} | {total_resp} Responses | Avg {avg_sat}/5.0)",
        fontsize=12.5, fontweight="bold", color=COLOR_GREEN, y=0.97,
    )

    if topic_rows:
        topics = [r["requested_topic"] for r in topic_rows]
        counts = [int(r["cnt"]) for r in topic_rows]
        bars = ax1.barh(topics, counts, color=COLOR_GREEN, height=0.58)
        ax1.set_title("Most Requested Legal & Workshop Topics", fontsize=11, fontweight="bold", color=COLOR_NAVY, pad=10)
        ax1.set_xlabel("Requests", fontsize=9, color=COLOR_SLATE)
        ax1.grid(axis="x", linestyle="--", alpha=0.4)
        ax1.set_axisbelow(True)
        for bar, r in zip(bars, topic_rows):
            ax1.text(
                bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                f"{int(r['cnt'])} ({float(r['avg_r']):.1f}/5)",
                va="center", fontsize=9, fontweight="bold", color=COLOR_NAVY,
            )
        ax1.set_xlim(0, max(counts) * 1.35)
    else:
        ax1.text(0.5, 0.5, "No Survey Data Available Yet", ha="center", va="center", color=COLOR_SLATE)
        ax1.axis("off")

    if chamber_rows:
        chambers = [r["chamber"] for r in chamber_rows]
        c_counts = [int(r["cnt"]) for r in chamber_rows]
        palette = [COLOR_NAVY, COLOR_GREEN_MID, COLOR_GOLD, COLOR_TEAL, "#64748b"]
        bars2 = ax2.bar(chambers, c_counts, color=[palette[i % len(palette)] for i in range(len(chambers))], width=0.55)
        ax2.set_title("Responses by Chamber & Network", fontsize=11, fontweight="bold", color=COLOR_NAVY, pad=10)
        ax2.set_ylabel("Responses", fontsize=9, color=COLOR_SLATE)
        ax2.grid(axis="y", linestyle="--", alpha=0.4)
        ax2.set_axisbelow(True)
        for bar, r in zip(bars2, chamber_rows):
            ax2.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.06,
                f"{int(r['cnt'])}\n({float(r['avg_r']):.1f}/5)",
                ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=COLOR_NAVY,
            )
        ax2.set_ylim(0, max(c_counts) * 1.35)
    else:
        ax2.text(0.5, 0.5, "No Chamber Data Available Yet", ha="center", va="center", color=COLOR_SLATE)
        ax2.axis("off")

    stamp = datetime.now(settings.tz).strftime("%d-%b-%Y %H:%M %Z")
    fig.text(0.99, 0.01, f"Generated {stamp} | Ann & Associates Cloud Engine", ha="right", fontsize=8, color="#64748b")
    plt.tight_layout(rect=[0, 0.03, 1, 0.92])
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return out_path


def generate_revenue_and_attendance_chart(db: DatabaseAdapter, settings: AppSettings) -> Path:
    out_path = settings.charts_dir / "firm_revenue_attendance.png"
    today = datetime.now(settings.tz).strftime("%Y-%m-%d")

    with db.connection() as conn:
        pay_rows = db.fetch_all(
            conn,
            "SELECT payment_method, SUM(total_usd) AS rev FROM academy_invoices GROUP BY payment_method",
        )
        att_rows = db.fetch_all(
            conn,
            "SELECT status_flag, COUNT(*) AS cnt FROM employee_work_hours WHERE work_date = %s GROUP BY status_flag",
            (today,),
        )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.6), dpi=150)
    fig.patch.set_facecolor("#ffffff")
    fig.suptitle(
        f"ANN & ASSOCIATES — Academy Revenue & Today's QR Attendance ({today})",
        fontsize=12.5, fontweight="bold", color=COLOR_GREEN, y=0.97,
    )

    if pay_rows:
        labels = [f"{r['payment_method']}\n(${float(r['rev']):,.0f})" for r in pay_rows]
        vals = [float(r["rev"]) for r in pay_rows]
        ax1.pie(vals, labels=labels, autopct="%1.0f%%", startangle=120, colors=[COLOR_GREEN, COLOR_GOLD, COLOR_NAVY])
        ax1.set_title("Academy Revenue by Payment Channel", fontsize=10.5, fontweight="bold", color=COLOR_NAVY)
    else:
        ax1.text(0.5, 0.5, "No Academy Invoices Yet", ha="center", va="center", color=COLOR_SLATE)
        ax1.axis("off")

    if att_rows:
        flags = [r["status_flag"] for r in att_rows]
        cnts = [int(r["cnt"]) for r in att_rows]
        color_map = {"ON_TIME": COLOR_GREEN_MID, "LATE": COLOR_GOLD, "EARLY_LEAVE": COLOR_NAVY}
        bars = ax2.bar(flags, cnts, color=[color_map.get(f, COLOR_TEAL) for f in flags], width=0.5)
        ax2.set_title("Employee & Intern QR Scans Today", fontsize=10.5, fontweight="bold", color=COLOR_NAVY)
        ax2.set_ylabel("Staff Count", fontsize=9, color=COLOR_SLATE)
        ax2.grid(axis="y", linestyle="--", alpha=0.4)
        ax2.set_axisbelow(True)
        for bar, cnt in zip(bars, cnts):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, str(cnt), ha="center", va="bottom", fontweight="bold")
        ax2.set_ylim(0, max(cnts) * 1.3)
    else:
        ax2.text(0.5, 0.5, "No QR Attendance Scans Logged Today", ha="center", va="center", color=COLOR_SLATE)
        ax2.axis("off")

    plt.tight_layout(rect=[0, 0.02, 1, 0.91])
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path
