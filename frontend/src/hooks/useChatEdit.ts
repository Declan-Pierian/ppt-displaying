import { useState, useCallback } from "react";
import api from "../lib/api";
import type { ChatMessage, EditHistoryData } from "../types/slide";

export function useChatEdit(presentationId: number) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [editHistory, setEditHistory] = useState<EditHistoryData>({
    versions: [],
    current_version: 0,
  });

  const fetchHistory = useCallback(async () => {
    try {
      const res = await api.get(
        `/admin/presentations/${presentationId}/edit-history`
      );
      setEditHistory(res.data);
    } catch {
      // History may not exist yet — that's fine
    }
  }, [presentationId]);

  const sendEdit = useCallback(
    async (prompt: string, slideNumbers?: number[]) => {
      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: prompt,
        timestamp: new Date().toISOString(),
        slideNumbers,
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        const res = await api.post(
          `/admin/presentations/${presentationId}/chat-edit`,
          {
            prompt,
            slide_numbers: slideNumbers ?? null,
          }
        );

        const assistantMsg: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: res.data.message,
          timestamp: new Date().toISOString(),
          version: res.data.version,
          success: res.data.success,
          tokenUsage: res.data.token_usage,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        await fetchHistory();
        return true;
      } catch (err: unknown) {
        const errorMsg =
          err instanceof Error
            ? err.message
            : (err as { response?: { data?: { detail?: string } } })?.response
                ?.data?.detail || "Edit failed";
        const assistantMsg: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: `Error: ${errorMsg}`,
          timestamp: new Date().toISOString(),
          success: false,
        };
        setMessages((prev) => [...prev, assistantMsg]);
        return false;
      } finally {
        setLoading(false);
      }
    },
    [presentationId, fetchHistory]
  );

  const undo = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.post(
        `/admin/presentations/${presentationId}/undo`
      );
      const undoMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: res.data.message,
        timestamp: new Date().toISOString(),
        version: res.data.version,
        success: true,
      };
      setMessages((prev) => [...prev, undoMsg]);
      await fetchHistory();
      return true;
    } catch (err: unknown) {
      const errorMsg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response
              ?.data?.detail || "Undo failed";
      const undoMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: `Undo error: ${errorMsg}`,
        timestamp: new Date().toISOString(),
        success: false,
      };
      setMessages((prev) => [...prev, undoMsg]);
      return false;
    } finally {
      setLoading(false);
    }
  }, [presentationId, fetchHistory]);

  return { messages, loading, sendEdit, undo, editHistory, fetchHistory };
}
