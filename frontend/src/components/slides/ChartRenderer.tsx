import type { CSSProperties } from "react";
import type { ChartShape } from "../../types/slide";
import { emuToPx, getMediaUrl } from "../../lib/slideUtils";

interface Props {
  shape: ChartShape;
  presentationId: number;
}

export default function ChartRenderer({ shape, presentationId }: Props) {
  const style: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    overflow: "hidden",
  };

  const imgSrc = getMediaUrl(presentationId, shape.chart.rendered_image_path);

  if (imgSrc) {
    return (
      <div style={style}>
        <img
          src={imgSrc}
          alt={shape.chart.title || "Chart"}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
          loading="lazy"
          draggable={false}
        />
      </div>
    );
  }

  // Fallback: show chart info as text
  return (
    <div
      style={{
        ...style,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "#f8fafc",
        border: "1px solid #e2e8f0",
        borderRadius: 4,
        flexDirection: "column",
        gap: 4,
      }}
    >
      <span style={{ fontSize: 14, fontWeight: 600, color: "#475569" }}>
        {shape.chart.title || "Chart"}
      </span>
      <span style={{ fontSize: 11, color: "#94a3b8" }}>
        {shape.chart.chart_type}
      </span>
    </div>
  );
}
