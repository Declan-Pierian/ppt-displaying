"""Extract chart shapes with data and render fallback images."""

import os


def extract_chart_shape(shape, base: dict, media_dir: str) -> dict:
    """Extract chart data and render a fallback PNG image."""
    chart = shape.chart
    chart_type = "unknown"
    chart_title = None
    chart_data = {"categories": [], "series": []}

    try:
        chart_type = str(chart.chart_type).split("(")[0].strip()
    except Exception:
        pass

    try:
        if chart.has_title:
            chart_title = chart.chart_title.text_frame.text
    except Exception:
        pass

    # Extract chart data
    try:
        plot = chart.plots[0]

        categories = []
        try:
            categories = [str(c) for c in plot.categories]
        except Exception:
            pass

        series_list = []
        for series in plot.series:
            s_data = {"name": None, "values": []}
            try:
                # Series name
                try:
                    s_data["name"] = str(series.tx.strRef.strCache[0])
                except Exception:
                    pass

                # Series values
                try:
                    s_data["values"] = [float(v) if v is not None else 0 for v in series.values]
                except Exception:
                    pass

            except Exception:
                pass
            series_list.append(s_data)

        chart_data = {"categories": categories, "series": series_list}
    except Exception:
        pass

    # Render fallback image
    rendered_filename = f"chart_{base.get('shape_id', 'unknown')}.png"
    rendered_path = os.path.join(media_dir, rendered_filename)
    _render_chart_image(chart_data, chart_type, chart_title, rendered_path)

    base.update({
        "shape_type": "chart",
        "chart": {
            "chart_type": chart_type,
            "rendered_image_path": f"media/{rendered_filename}",
            "data": chart_data,
            "title": chart_title,
        },
    })
    return base


def _render_chart_image(chart_data: dict, chart_type: str, title: str | None, output_path: str):
    """Render a chart as a PNG image using matplotlib."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        fig.patch.set_facecolor('white')

        categories = chart_data.get("categories", [])
        series_list = chart_data.get("series", [])

        chart_lower = chart_type.lower()

        if not series_list or not categories:
            ax.text(0.5, 0.5, "Chart Data", ha='center', va='center', fontsize=14,
                    color='#666666', transform=ax.transAxes)
        elif "pie" in chart_lower:
            values = series_list[0]["values"] if series_list else []
            if values and categories:
                colors = plt.cm.Set3.colors[:len(categories)]
                ax.pie(values, labels=categories, autopct='%1.1f%%', colors=colors)
        elif "bar" in chart_lower and "stacked" not in chart_lower:
            import numpy as np
            x = np.arange(len(categories))
            width = 0.8 / max(len(series_list), 1)
            colors = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
            for i, series in enumerate(series_list):
                offset = (i - len(series_list) / 2 + 0.5) * width
                ax.bar(x + offset, series["values"], width, label=series.get("name"),
                       color=colors[i % len(colors)])
            ax.set_xticks(x)
            ax.set_xticklabels(categories, rotation=45, ha='right')
            if any(s.get("name") for s in series_list):
                ax.legend()
        elif "line" in chart_lower:
            colors = ['#4472C4', '#ED7D31', '#A5A5A5', '#FFC000', '#5B9BD5', '#70AD47']
            for i, series in enumerate(series_list):
                ax.plot(categories, series["values"], marker='o', label=series.get("name"),
                        color=colors[i % len(colors)])
            if any(s.get("name") for s in series_list):
                ax.legend()
            plt.xticks(rotation=45, ha='right')
        else:
            # Generic bar chart fallback
            if series_list and categories:
                ax.bar(categories, series_list[0]["values"], color='#4472C4')
                plt.xticks(rotation=45, ha='right')

        if title:
            ax.set_title(title, fontsize=13, fontweight='bold', pad=10)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)

    except Exception:
        # Create a simple placeholder image
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGB', (640, 400), 'white')
            draw = ImageDraw.Draw(img)
            draw.text((250, 180), "Chart", fill='#666666')
            img.save(output_path)
        except Exception:
            pass
