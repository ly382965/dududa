from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .client import DateRange

WIDTH = 1440
HEIGHT = 900
REGULAR_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
USER_COLORS = (
    "#2563EB",
    "#DC2626",
    "#059669",
    "#D97706",
    "#7C3AED",
    "#0891B2",
    "#DB2777",
    "#4D7C0F",
    "#EA580C",
    "#475569",
)


@dataclass(frozen=True)
class UserTrendSeries:
    label: str
    total: int
    values: tuple[int, ...]


def trend_points(
    snapshot: dict[str, Any], period: DateRange
) -> list[tuple[date, int]]:
    by_day: dict[date, int] = {}
    rows = snapshot.get("trend")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = _row_date(row)
            if day is None or not period.start <= day <= period.end:
                continue
            by_day[day] = by_day.get(day, 0) + _tokens(
                row.get("total_tokens", row.get("tokens"))
            )

    return [
        (
            period.start + timedelta(days=offset),
            by_day.get(period.start + timedelta(days=offset), 0),
        )
        for offset in range(period.days)
    ]


def user_trend_series(
    snapshot: dict[str, Any],
    period: DateRange,
    *,
    reveal_identifiers: bool,
    limit: int = 10,
) -> list[UserTrendSeries]:
    labels: dict[str, str] = {}
    values_by_user: dict[str, dict[date, int]] = {}
    rows = snapshot.get("users_trend")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = _row_date(row)
            if day is None or not period.start <= day <= period.end:
                continue
            username = _clean_identifier(row.get("username"))
            email = _clean_identifier(row.get("email"))
            raw_label = (
                username if username and username.isascii() else email or username
            )
            raw_user_id = str(row.get("user_id") or "").strip()
            if not raw_label and raw_user_id:
                raw_label = f"User #{raw_user_id}"
            label = _clean_identifier(raw_label)
            key = raw_user_id or label
            if not key:
                continue
            labels.setdefault(key, label or "Unknown user")
            daily = values_by_user.setdefault(key, {})
            daily[day] = daily.get(day, 0) + _tokens(
                row.get("tokens", row.get("total_tokens"))
            )

    ranked = sorted(
        values_by_user,
        key=lambda key: (-sum(values_by_user[key].values()), labels[key].lower()),
    )[: max(1, min(limit, len(USER_COLORS)))]
    days = [period.start + timedelta(days=offset) for offset in range(period.days)]
    result: list[UserTrendSeries] = []
    for key in ranked:
        daily = values_by_user[key]
        total = sum(daily.values())
        if total <= 0:
            continue
        result.append(
            UserTrendSeries(
                label=_display_identifier(
                    labels[key], reveal_identifiers=reveal_identifiers
                ),
                total=total,
                values=tuple(daily.get(day, 0) for day in days),
            )
        )
    return result


def cumulative_user_series(
    series: list[UserTrendSeries],
) -> list[UserTrendSeries]:
    result: list[UserTrendSeries] = []
    for item in series:
        running_total = 0
        cumulative_values: list[int] = []
        for value in item.values:
            running_total += value
            cumulative_values.append(running_total)
        result.append(
            UserTrendSeries(
                label=item.label,
                total=item.total,
                values=tuple(cumulative_values),
            )
        )
    return result


def render_total_trend_chart(snapshot: dict[str, Any], period: DateRange) -> bytes:
    points = trend_points(snapshot, period)
    values = [value for _, value in points]
    total = sum(values)
    average = round(total / len(values)) if values else 0
    peak_index = max(range(len(values)), key=values.__getitem__) if values else 0
    peak_day, peak_value = points[peak_index] if points else (period.start, 0)
    latest = values[-1] if values else 0

    image = Image.new("RGB", (WIDTH, HEIGHT), "#F7F9FC")
    draw = ImageDraw.Draw(image)
    title_font = _font(34, bold=True)
    subtitle_font = _font(17)
    metric_label_font = _font(13, bold=True)
    metric_value_font = _font(25, bold=True)
    axis_font = _font(13)
    note_font = _font(12)

    draw.text((80, 38), "Sub2API Total Token Trend", fill="#111827", font=title_font)
    draw.text(
        (80, 84),
        f"{period.start.isoformat()} to {period.end.isoformat()}  |  {period.days} days",
        fill="#64748B",
        font=subtitle_font,
    )

    metrics = (
        ("TOTAL TOKENS", _number(total)),
        ("DAILY AVERAGE", _number(average)),
        ("PEAK DAY", _number(peak_value)),
        ("LATEST DAY", _number(latest)),
    )
    card_y = 124
    card_height = 88
    gap = 16
    card_width = (WIDTH - 160 - gap * 3) // 4
    for index, (label, value) in enumerate(metrics):
        left = 80 + index * (card_width + gap)
        draw.rounded_rectangle(
            (left, card_y, left + card_width, card_y + card_height),
            radius=8,
            fill="#FFFFFF",
            outline="#E2E8F0",
            width=2,
        )
        draw.text(
            (left + 20, card_y + 14), label, fill="#64748B", font=metric_label_font
        )
        value_font = metric_value_font if len(value) <= 15 else _font(20, bold=True)
        draw.text((left + 20, card_y + 42), value, fill="#0F172A", font=value_font)

    plot_left, plot_top, plot_right, plot_bottom = 130, 262, 1345, 776
    draw.rounded_rectangle(
        (80, 232, WIDTH - 80, 826),
        radius=8,
        fill="#FFFFFF",
        outline="#E2E8F0",
        width=2,
    )

    axis_bounds = _draw_y_grid(
        draw,
        values,
        plot_left=plot_left,
        plot_top=plot_top,
        plot_right=plot_right,
        plot_bottom=plot_bottom,
        axis_font=axis_font,
    )
    coordinates = _coordinates(
        values,
        axis_bounds=axis_bounds,
        plot_left=plot_left,
        plot_top=plot_top,
        plot_right=plot_right,
        plot_bottom=plot_bottom,
    )
    if coordinates:
        curve = smooth_curve(coordinates)
        area = [
            (curve[0][0], plot_bottom),
            *curve,
            (curve[-1][0], plot_bottom),
        ]
        draw.polygon(area, fill="#DBEAFE")
        if len(coordinates) > 1:
            draw.line(curve, fill="#2563EB", width=4)
        marker_indices = (
            range(len(coordinates))
            if len(coordinates) <= 31
            else _tick_indices(len(coordinates), maximum=12)
        )
        for index in marker_indices:
            x, y = coordinates[index]
            draw.ellipse(
                (x - 4, y - 4, x + 4, y + 4),
                fill="#FFFFFF",
                outline="#2563EB",
                width=3,
            )

    _draw_x_labels(
        draw,
        [day for day, _ in points],
        coordinates,
        plot_bottom=plot_bottom,
        axis_font=axis_font,
    )
    if coordinates and peak_value > 0:
        _draw_callout(
            draw,
            coordinates[peak_index],
            f"Peak {_compact(peak_value)}",
            _font(12),
            plot_left,
            plot_right,
            minimum_top=238,
        )

    footer = (
        f"Peak: {peak_day.strftime('%Y-%m-%d')}  |  "
        "Source: Sub2API admin snapshot-v2 (read-only)"
    )
    draw.text((80, 858), footer, fill="#64748B", font=note_font)
    return _png_bytes(image)


def render_user_trend_chart(
    snapshot: dict[str, Any],
    period: DateRange,
    *,
    reveal_identifiers: bool,
    limit: int = 10,
    cumulative: bool = False,
) -> bytes:
    series = user_trend_series(
        snapshot,
        period,
        reveal_identifiers=reveal_identifiers,
        limit=limit,
    )
    if cumulative:
        series = cumulative_user_series(series)
    values = [value for item in series for value in item.values]
    days = [period.start + timedelta(days=offset) for offset in range(period.days)]

    image = Image.new("RGB", (WIDTH, HEIGHT), "#F7F9FC")
    draw = ImageDraw.Draw(image)
    title_font = _font(32, bold=True)
    subtitle_font = _font(16)
    axis_font = _font(13)
    legend_font = _font(13)
    legend_rank_font = _font(13, bold=True)
    note_font = _font(12)

    title = (
        "Sub2API Top 10 User Cumulative Tokens"
        if cumulative
        else "Sub2API Top 10 User Token Trends"
    )
    draw.text((72, 34), title, fill="#111827", font=title_font)
    draw.text(
        (72, 78),
        f"{period.start.isoformat()} to {period.end.isoformat()}  |  "
        f"ranked by {period.days}-day token total"
        + ("  |  cumulative from period start" if cumulative else ""),
        fill="#64748B",
        font=subtitle_font,
    )

    draw.rounded_rectangle(
        (70, 120, WIDTH - 70, 650),
        radius=8,
        fill="#FFFFFF",
        outline="#E2E8F0",
        width=2,
    )
    plot_left, plot_top, plot_right, plot_bottom = 120, 150, 1340, 602
    axis_scale = "linear" if cumulative else "sqrt"
    axis_bounds = _draw_y_grid(
        draw,
        values,
        plot_left=plot_left,
        plot_top=plot_top,
        plot_right=plot_right,
        plot_bottom=plot_bottom,
        axis_font=axis_font,
        scale=axis_scale,
    )

    all_coordinates: list[list[tuple[int, int]]] = []
    for item in series:
        all_coordinates.append(
            _coordinates(
                list(item.values),
                axis_bounds=axis_bounds,
                plot_left=plot_left,
                plot_top=plot_top,
                plot_right=plot_right,
                plot_bottom=plot_bottom,
                scale=axis_scale,
            )
        )

    for index in reversed(range(len(series))):
        coordinates = all_coordinates[index]
        color = USER_COLORS[index]
        if len(coordinates) > 1:
            draw.line(smooth_curve(coordinates), fill=color, width=3)
        marker_indices = (
            _tick_indices(len(coordinates), maximum=7)
            if len(coordinates) <= 14
            else [len(coordinates) - 1]
        )
        for point_index in marker_indices:
            x, y = coordinates[point_index]
            draw.ellipse(
                (x - 3, y - 3, x + 3, y + 3),
                fill="#FFFFFF",
                outline=color,
                width=2,
            )

    if all_coordinates:
        _draw_x_labels(
            draw,
            days,
            all_coordinates[0],
            plot_bottom=plot_bottom,
            axis_font=axis_font,
        )
    else:
        message = "No user usage in this period"
        box = draw.textbbox((0, 0), message, font=subtitle_font)
        draw.text(
            (
                (WIDTH - (box[2] - box[0])) / 2,
                (plot_top + plot_bottom) / 2,
            ),
            message,
            fill="#64748B",
            font=subtitle_font,
        )

    draw.text(
        (72, 676),
        f"TOP {len(series)} USERS BY PERIOD TOTAL",
        fill="#475569",
        font=_font(13, bold=True),
    )
    column_width = 640
    for index, item in enumerate(series):
        column = index // 5
        row = index % 5
        left = 72 + column * (column_width + 8)
        y = 711 + row * 31
        color = USER_COLORS[index]
        draw.line((left, y + 8, left + 24, y + 8), fill=color, width=4)
        draw.ellipse((left + 9, y + 4, left + 17, y + 12), fill=color)
        draw.text(
            (left + 36, y), f"#{index + 1}", fill="#334155", font=legend_rank_font
        )
        total_text = _compact(item.total)
        total_box = draw.textbbox((0, 0), total_text, font=legend_rank_font)
        total_x = left + column_width - (total_box[2] - total_box[0])
        label_x = left + 72
        label = _fit_text(
            draw,
            item.label,
            legend_font,
            max_width=max(40, total_x - label_x - 18),
        )
        draw.text((label_x, y), label, fill="#334155", font=legend_font)
        draw.text((total_x, y), total_text, fill=color, font=legend_rank_font)

    draw.text(
        (72, 874),
        "Source: Sub2API admin users_trend (read-only)",
        fill="#64748B",
        font=note_font,
    )
    return _png_bytes(image)


def render_trend_chart(snapshot: dict[str, Any], period: DateRange) -> bytes:
    return render_total_trend_chart(snapshot, period)


def sqrt_axis_bounds(
    values: list[int], *, occupancy: float = 0.9
) -> tuple[float, float]:
    transformed = [math.sqrt(max(0, value)) for value in values] or [0.0]
    data_min = min(transformed)
    data_max = max(transformed)
    target = max(0.5, min(float(occupancy), 0.98))
    data_span = data_max - data_min
    if data_span <= 1e-9:
        padding = max(0.25, abs(data_max) * 0.05)
        return max(0.0, data_min - padding), data_max + padding

    axis_span = data_span / target
    extra = axis_span - data_span
    axis_min = max(0.0, data_min - extra / 2)
    axis_max = axis_min + axis_span
    if axis_max < data_max:
        axis_max = data_max
        axis_min = max(0.0, axis_max - axis_span)
    return axis_min, axis_max


def linear_axis_bounds(
    values: list[int], *, occupancy: float = 0.9
) -> tuple[float, float]:
    maximum = max((max(0, value) for value in values), default=0)
    if maximum <= 0:
        return 0.0, 1.0
    target = max(0.5, min(float(occupancy), 0.98))
    return 0.0, maximum / target


def smooth_curve(
    points: list[tuple[int, int]], *, samples_per_segment: int = 10
) -> list[tuple[int, int]]:
    if len(points) < 3:
        return points.copy()
    samples = max(2, min(int(samples_per_segment), 30))
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    spacing = [xs[index + 1] - xs[index] for index in range(len(xs) - 1)]
    if any(value <= 0 for value in spacing):
        return points.copy()
    deltas = [
        (ys[index + 1] - ys[index]) / spacing[index]
        for index in range(len(spacing))
    ]

    slopes = [0.0] * len(points)
    slopes[0] = _endpoint_slope(spacing[0], spacing[1], deltas[0], deltas[1])
    slopes[-1] = _endpoint_slope(
        spacing[-1], spacing[-2], deltas[-1], deltas[-2]
    )
    for index in range(1, len(points) - 1):
        before = deltas[index - 1]
        after = deltas[index]
        if before == 0 or after == 0 or before * after <= 0:
            slopes[index] = 0.0
            continue
        weight_before = 2 * spacing[index] + spacing[index - 1]
        weight_after = spacing[index] + 2 * spacing[index - 1]
        slopes[index] = (weight_before + weight_after) / (
            weight_before / before + weight_after / after
        )

    result: list[tuple[int, int]] = []
    for index in range(len(points) - 1):
        width = spacing[index]
        for step in range(samples):
            position = step / samples
            position_squared = position * position
            position_cubed = position_squared * position
            start_weight = 2 * position_cubed - 3 * position_squared + 1
            start_slope_weight = position_cubed - 2 * position_squared + position
            end_weight = -2 * position_cubed + 3 * position_squared
            end_slope_weight = position_cubed - position_squared
            x = xs[index] + position * width
            y = (
                start_weight * ys[index]
                + start_slope_weight * width * slopes[index]
                + end_weight * ys[index + 1]
                + end_slope_weight * width * slopes[index + 1]
            )
            rendered = (round(x), round(y))
            if not result or rendered != result[-1]:
                result.append(rendered)
    result.append(points[-1])
    return result


def _draw_y_grid(
    draw: ImageDraw.ImageDraw,
    values: list[int],
    *,
    plot_left: int,
    plot_top: int,
    plot_right: int,
    plot_bottom: int,
    axis_font,
    scale: str = "sqrt",
) -> tuple[float, float]:
    linear = scale == "linear"
    axis_min, axis_max = (
        linear_axis_bounds(values, occupancy=0.9)
        if linear
        else sqrt_axis_bounds(values, occupancy=0.9)
    )
    draw.text(
        (plot_left, plot_top - 23),
        "TOKENS (LINEAR SCALE)" if linear else "TOKENS (SQRT SCALE)",
        fill="#64748B",
        font=axis_font,
    )
    tick_count = 5
    for tick in range(tick_count + 1):
        ratio = tick / tick_count
        y = round(plot_bottom - ratio * (plot_bottom - plot_top))
        scale_value = axis_min + ratio * (axis_max - axis_min)
        value = max(0, round(scale_value if linear else scale_value * scale_value))
        draw.line((plot_left, y, plot_right, y), fill="#E8EDF4", width=2)
        label = _compact(value)
        box = draw.textbbox((0, 0), label, font=axis_font)
        draw.text(
            (plot_left - 14 - (box[2] - box[0]), y - 8),
            label,
            fill="#64748B",
            font=axis_font,
        )
    return axis_min, axis_max


def _coordinates(
    values: list[int],
    *,
    axis_bounds: tuple[float, float],
    plot_left: int,
    plot_top: int,
    plot_right: int,
    plot_bottom: int,
    scale: str = "sqrt",
) -> list[tuple[int, int]]:
    count = len(values)
    axis_min, axis_max = axis_bounds
    axis_span = max(1e-9, axis_max - axis_min)
    result: list[tuple[int, int]] = []
    for index, value in enumerate(values):
        x_ratio = index / (count - 1) if count > 1 else 0.5
        x = round(plot_left + x_ratio * (plot_right - plot_left))
        scale_value = (
            float(max(0, value)) if scale == "linear" else math.sqrt(max(0, value))
        )
        y_ratio = min(1.0, max(0.0, (scale_value - axis_min) / axis_span))
        y = round(plot_bottom - y_ratio * (plot_bottom - plot_top))
        result.append((x, y))
    return result


def _draw_x_labels(
    draw: ImageDraw.ImageDraw,
    days: list[date],
    coordinates: list[tuple[int, int]],
    *,
    plot_bottom: int,
    axis_font,
) -> None:
    for index in _tick_indices(len(days), maximum=9):
        x, _ = coordinates[index]
        label = days[index].strftime("%m-%d")
        box = draw.textbbox((0, 0), label, font=axis_font)
        draw.text(
            (x - (box[2] - box[0]) / 2, plot_bottom + 14),
            label,
            fill="#64748B",
            font=axis_font,
        )


def _draw_callout(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    text: str,
    font,
    left_bound: int,
    right_bound: int,
    *,
    minimum_top: int,
) -> None:
    x, y = point
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0] + 20
    height = box[3] - box[1] + 14
    left = min(max(x - width // 2, left_bound), right_bound - width)
    top = max(minimum_top, y - height - 14)
    draw.rounded_rectangle(
        (left, top, left + width, top + height), radius=6, fill="#0F172A"
    )
    draw.text((left + 10, top + 5), text, fill="#FFFFFF", font=font)


def _row_date(row: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(row.get("date") or "")[:10])
    except ValueError:
        return None


def _tokens(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _clean_identifier(value: Any) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:160]


def _display_identifier(value: str, *, reveal_identifiers: bool) -> str:
    if reveal_identifiers:
        return value
    if "@" in value:
        local, domain = value.rsplit("@", 1)
        visible = local[:2] if len(local) > 1 else local[:1]
        return f"{visible}***@{domain}"
    if len(value) <= 3:
        return (value[:1] or "U") + "***"
    return f"{value[:2]}***{value[-1]}"


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, *, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    candidate = text
    while candidate and draw.textlength(candidate + suffix, font=font) > max_width:
        candidate = candidate[:-1]
    return candidate + suffix if candidate else suffix


def _font(size: int, *, bold: bool = False):
    path = BOLD_FONT if bold else REGULAR_FONT
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _endpoint_slope(
    first_width: float,
    second_width: float,
    first_delta: float,
    second_delta: float,
) -> float:
    slope = (
        (2 * first_width + second_width) * first_delta
        - first_width * second_delta
    ) / (first_width + second_width)
    if slope * first_delta <= 0:
        return 0.0
    if first_delta * second_delta < 0 and abs(slope) > abs(3 * first_delta):
        return 3 * first_delta
    return slope


def _compact(value: int) -> str:
    units = (
        (1_000_000_000_000, "T"),
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    )
    for divisor, suffix in units:
        if abs(value) >= divisor:
            rendered = value / divisor
            return f"{rendered:.1f}".rstrip("0").rstrip(".") + suffix
    return str(value)


def _number(value: int) -> str:
    return f"{value:,}"


def _tick_indices(count: int, *, maximum: int) -> list[int]:
    if count <= 0:
        return []
    if count <= maximum:
        return list(range(count))
    return sorted(
        {round(index * (count - 1) / (maximum - 1)) for index in range(maximum)}
    )


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
