import type { CSSProperties } from "react";
import type { ImageShape } from "../../types/slide";
import { emuToPx, getMediaUrl, getBorderStyle } from "../../lib/slideUtils";

interface Props {
  shape: ImageShape;
  presentationId: number;
}

export default function ImageRenderer({ shape, presentationId }: Props) {
  const imgData = shape.image;
  const src = getMediaUrl(presentationId, imgData.media_path);

  const containerStyle: CSSProperties = {
    position: "absolute",
    left: emuToPx(shape.position.left_emu),
    top: emuToPx(shape.position.top_emu),
    width: emuToPx(shape.position.width_emu),
    height: emuToPx(shape.position.height_emu),
    zIndex: shape.z_order + 1,
    transform: shape.rotation_degrees ? `rotate(${shape.rotation_degrees}deg)` : undefined,
    overflow: "hidden",
    ...getBorderStyle(shape.border),
  };

  // Apply crop using CSS clip-path or object-position
  const imgStyle: CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "fill",
    display: "block",
  };

  if (imgData.crop) {
    const { left, top, right, bottom } = imgData.crop;
    // Use clip-path for cropping: inset(top right bottom left)
    imgStyle.clipPath = `inset(${top * 100}% ${right * 100}% ${bottom * 100}% ${left * 100}%)`;
    // Scale up to compensate for cropped area
    const scaleX = 1 / (1 - left - right);
    const scaleY = 1 / (1 - top - bottom);
    imgStyle.transform = `scale(${scaleX}, ${scaleY})`;
    imgStyle.transformOrigin = `${(left / (1 - left - right)) * 100}% ${(top / (1 - top - bottom)) * 100}%`;
  }

  if (!src) {
    return (
      <div style={{ ...containerStyle, backgroundColor: "#f1f5f9", display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ color: "#94a3b8", fontSize: 12 }}>{imgData.alt_text || "Image"}</span>
      </div>
    );
  }

  const content = (
    <img
      src={src}
      alt={imgData.alt_text || ""}
      style={imgStyle}
      loading="lazy"
      draggable={false}
    />
  );

  if (shape.hyperlink) {
    return (
      <a href={shape.hyperlink} target="_blank" rel="noopener noreferrer" style={containerStyle}>
        {content}
      </a>
    );
  }

  return <div style={containerStyle}>{content}</div>;
}
