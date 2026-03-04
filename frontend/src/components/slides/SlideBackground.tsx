import type { CSSProperties } from "react";
import type { BackgroundData } from "../../types/slide";
import { getMediaUrl } from "../../lib/slideUtils";

interface Props {
  background: BackgroundData;
  presentationId: number;
}

export default function SlideBackground({ background, presentationId }: Props) {
  const style: CSSProperties = {
    position: "absolute",
    top: 0,
    left: 0,
    width: "100%",
    height: "100%",
    zIndex: 0,
  };

  if (!background || background.type === "none") {
    return <div style={{ ...style, backgroundColor: "#FFFFFF" }} />;
  }

  if (background.type === "solid") {
    return <div style={{ ...style, backgroundColor: background.color || "#FFFFFF" }} />;
  }

  if (background.type === "gradient" && background.gradient_stops?.length) {
    const stops = background.gradient_stops
      .map((s) => `${s.color} ${Math.round(s.position * 100)}%`)
      .join(", ");
    return <div style={{ ...style, background: `linear-gradient(180deg, ${stops})` }} />;
  }

  if (background.type === "image" && background.image_path) {
    return (
      <div
        style={{
          ...style,
          backgroundImage: `url(${getMediaUrl(presentationId, background.image_path)})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      />
    );
  }

  return <div style={{ ...style, backgroundColor: "#FFFFFF" }} />;
}
