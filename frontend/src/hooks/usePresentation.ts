import { useState, useEffect, useCallback } from "react";
import api from "../lib/api";
import type { PresentationData, PresentationMeta } from "../types/slide";

export function usePresentationList() {
  const [presentations, setPresentations] = useState<PresentationMeta[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/presentations");
      setPresentations(res.data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load presentations");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { presentations, loading, error, refresh };
}

export function usePresentationSlides(presentationId: number | null) {
  const [data, setData] = useState<PresentationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!presentationId) return;
    setLoading(true);
    api
      .get(`/presentations/${presentationId}/slides`)
      .then((res) => {
        setData(res.data);
        setError(null);
      })
      .catch((err) => {
        setError(err.message || "Failed to load slides");
      })
      .finally(() => setLoading(false));
  }, [presentationId]);

  return { data, loading, error };
}
