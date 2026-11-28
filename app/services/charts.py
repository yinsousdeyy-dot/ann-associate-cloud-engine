import os
import tempfile
import threading
from datetime import datetime
from functools import wraps
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.config import AppSettings
from app.db import DatabaseAdapter

COLOR_INK = "#0f1b33"
COLOR_NAVY = "#1b2a49"
COLOR_SLATE = "#3d4a5f"
COLOR_MUTED = "#5a6578"
COLOR_GOLD = "#b8893a"
COLOR_OK = "#2b6a1c"
COLOR_GRID = "#e3dfd6"
PALETTE = [COLOR_NAVY, COLOR_GOLD, "#6b7a99", COLOR_SLATE, COLOR_OK]

# pyplot keeps global state, so concurrent renders (the API now runs them in worker threads) must take turns.
_RENDER_LOCK = threading.RLock()


def _serialised(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _RENDER_LOCK:
            return fn(*args, **kwargs)
    return wrapper


def _save_atomic(fig, out_path: Path, dpi: int) -> None:
    """Writes to a temp file then renames, so a reader never sees a half-written PNG."""
    fd, tmp_name = tempfile.mkstemp(suffix=".png", dir=out_path.parent)
    os.close(fd)
    try:
        fig.savefig(tmp_name, dpi=dpi, format="png")
        os.replace(tmp_name, out_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _style_axes(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(COLOR_GRID)
    ax.tick_params(colors=COLOR_SLATE, labelsize=9)


@_serialised
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
    scope = "All departments" if department == "ALL" else department

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": COLOR_GRID})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2), dpi=160)
    fig.patch.set_facecolor("#ffffff")
    fig.suptitle(
        f"Survey intelligence: {scope}, {total_resp} responses, average {avg_sat:.2f} / 5",
        fontsize=12.5, fontweight="bold", color=COLOR_INK, y=0.97,
    )

    if topic_rows:
        topics = [r["requested_topic"] for r in topic_rows]
        counts = [int(r["cnt"]) for r in topic_rows]
        bars = ax1.barh(topics, counts, color=COLOR_NAVY, height=0.58)
        ax1.set_title("Most requested topics", fontsize=11, fontweight="bold", color=COLOR_SLATE, pad=10, loc="left")
        ax1.set_xlabel("Requests", fontsize=9, color=COLOR_MUTED)
        ax1.grid(axis="x", linestyle="-", color=COLOR_GRID)
        ax1.set_axisbelow(True)
        _style_axes(ax1)
        for bar, r in zip(bars, topic_rows):
            ax1.text(
                bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                f"{int(r['cnt'])} (avg {float(r['avg_r']):.1f})",
                va="center", fontsize=9, fontweight="bold", color=COLOR_SLATE,
            )
        ax1.set_xlim(0, max(1.0, max(counts) * 1.4))
    else:
        ax1.text(0.5, 0.5, "No survey data yet", ha="center", va="center", color=COLOR_MUTED)
        ax1.axis("off")

    if chamber_rows:
        chambers = [r["chamber"] for r in chamber_rows]
        c_counts = [int(r["cnt"]) for r in chamber_rows]
        bars2 = ax2.bar(chambers, c_counts, color=[PALETTE[i % len(PALETTE)] for i in range(len(chambers))], width=0.55)
        ax2.set_title("Responses by chamber and network", fontsize=11, fontweight="bold", color=COLOR_SLATE, pad=10, loc="left")
        ax2.set_ylabel("Responses", fontsize=9, color=COLOR_MUTED)
        ax2.grid(axis="y", linestyle="-", color=COLOR_GRID)
        ax2.set_axisbelow(True)
        _style_axes(ax2)
        for bar, r in zip(bars2, chamber_rows):
            ax2.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.06,
                f"{int(r['cnt'])}\n(avg {float(r['avg_r']):.1f})",
                ha="center", va="bottom", fontsize=8.5, fontweight="bold", color=COLOR_SLATE,
            )
        ax2.set_ylim(0, max(1.0, max(c_counts) * 1.4))
    else:
        ax2.text(0.5, 0.5, "No chamber data yet", ha="center", va="center", color=COLOR_MUTED)
        ax2.axis("off")

    stamp = datetime.now(settings.tz).strftime("%d %b %Y %H:%M %Z")
    fig.text(0.99, 0.01, f"Generated {stamp}", ha="right", fontsize=8, color=COLOR_MUTED)
    plt.tight_layout(rect=[0, 0.03, 1, 0.92])
    _save_atomic(fig, out_path, 160)
    plt.close(fig)
    return out_path


@_serialised
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
        f"Academy revenue and today's attendance ({today})",
        fontsize=12.5, fontweight="bold", color=COLOR_INK, y=0.97,
    )

    total_rev = sum(float(r["rev"]) for r in pay_rows) if pay_rows else 0.0
    if pay_rows and total_rev > 0:
        labels = [f"{r['payment_method']}\n(${float(r['rev']):,.0f})" for r in pay_rows]
        vals = [float(r["rev"]) for r in pay_rows]
        colors = [PALETTE[i % len(PALETTE)] for i in range(len(vals))]
        _, _, autotexts = ax1.pie(
            vals, labels=labels, autopct="%1.0f%%", startangle=120, colors=colors,
            textprops={"color": COLOR_SLATE, "fontsize": 9},
            wedgeprops={"edgecolor": "#ffffff", "linewidth": 1.5},
        )
        for t in autotexts:
            t.set_color("#ffffff")
            t.set_fontweight("bold")
        ax1.set_title("Revenue by payment channel", fontsize=10.5, fontweight="bold", color=COLOR_SLATE, loc="left")
    else:
        ax1.text(0.5, 0.5, "No Academy revenue yet", ha="center", va="center", color=COLOR_MUTED)
        ax1.axis("off")

    if att_rows:
        flags = [r["status_flag"] for r in att_rows]
        cnts = [int(r["cnt"]) for r in att_rows]
        color_map = {"ON_TIME": COLOR_OK, "LATE": COLOR_GOLD, "EARLY_LEAVE": COLOR_SLATE}
        labels = [f.replace("_", " ").title() for f in flags]
        bars = ax2.bar(labels, cnts, color=[color_map.get(f, COLOR_NAVY) for f in flags], width=0.5)
        ax2.set_title("Staff scanned in today", fontsize=10.5, fontweight="bold", color=COLOR_SLATE, loc="left")
        ax2.set_ylabel("Staff", fontsize=9, color=COLOR_MUTED)
        ax2.grid(axis="y", linestyle="-", color=COLOR_GRID)
        ax2.set_axisbelow(True)
        _style_axes(ax2)
        for bar, cnt in zip(bars, cnts):
            ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05, str(cnt),
                     ha="center", va="bottom", fontweight="bold", color=COLOR_SLATE)
        ax2.set_ylim(0, max(1.0, max(cnts) * 1.3))
    else:
        ax2.text(0.5, 0.5, "No scans recorded today", ha="center", va="center", color=COLOR_MUTED)
        ax2.axis("off")

    plt.tight_layout(rect=[0, 0.02, 1, 0.91])
    _save_atomic(fig, out_path, 150)
    plt.close(fig)
    return out_path
