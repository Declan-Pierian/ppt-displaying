import type { CSSProperties } from "react";
import type { AutoShapeData } from "../../types/slide";
import { emuToPx, getFillStyle, getBorderStyle } from "../../lib/slideUtils";

interface Props {
  shape: AutoShapeData;
}

export default function AutoShapeRenderer({ shape }: Props) {
  const style: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    transform: shape.rotation_degrees ? `rotate(${shape.rotation_degrees}deg)` : undefined,
    overflow: "hidden",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    ...getFillStyle(shape.fill),
    ...getBorderStyle(shape.border),
  };

  // Apply shape-specific border-radius
  const shapeType = shape.auto_shape_type?.toLowerCase() || "";
  if (shapeType.includes("ellipse") || shapeType.includes("oval")) {
    style.borderRadius = "50%";
  } else if (shapeType.includes("round")) {
    style.borderRadius = "12px";
  }

  // Shadow
  if (shape.shadow) {
    const s = shape.shadow;
    const opacity = s.opacity ? s.opacity / 100 : 0.3;
    const blur = s.blur_radius_emu ? emuToPx(s.blur_radius_emu) : 4;
    const dist = s.dist_emu ? emuToPx(s.dist_emu) : 3;
    const color = s.color || `rgba(0,0,0,${opacity})`;
    style.boxShadow = `${dist}px ${dist}px ${blur}px ${color}`;
  }

  const textContent = shape.text_body?.paragraphs?.map((para, i) => (
    <p
      key={i}
      style={{
        margin: 0,
        textAlign: (para.alignment as any) || "center",
        lineHeight: "1.3",
      }}
    >
      {para.runs.map((run, j) => (
        <span
          key={j}
          style={{
            fontFamily: run.font.name ? `"${run.font.name}", sans-serif` : "sans-serif",
            fontSize: run.font.size_pt ? `${run.font.size_pt}pt` : undefined,
            fontWeight: run.font.bold ? "bold" : "normal",
            fontStyle: run.font.italic ? "italic" : "normal",
            color: run.font.color || undefined,
            textDecoration: run.font.underline ? "underline" : undefined,
          }}
        >
          {run.text}
        </span>
      ))}
    </p>
  ));

  const inner = (
    <div style={style}>
      {textContent && <div style={{ padding: "4px 8px", width: "100%", textAlign: "center" }}>{textContent}</div>}
    </div>
  );

  if (shape.hyperlink) {
    return (
      <a href={shape.hyperlink} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
        {inner}
      </a>
    );
  }

  return inner;
}
