"use client";

import { useEffect, useRef, useState } from "react";
import { chat, type ChatMessage } from "@/lib/api";
import { usePathname } from "next/navigation";

const GREETING: ChatMessage = {
  role: "assistant",
  content:
    "Hi! I can explain how CreatorPulse works, what the numbers mean, and where they fall short. Ask me anything about the product.",
};

const SUGGESTIONS = [
  "How does brand–creator matching work?",
  "Is the engagement risk real fraud detection?",
  "How is sponsor cost estimated?",
];

function track(event: string) {
  try {
    (window as unknown as { posthog?: { capture?: (e: string) => void } }).posthog?.capture?.(event);
  } catch {
    /* posthog is optional — no-op if absent */
  }
}

function chatContext(pathname: string | null): Record<string, string> | undefined {
  if (!pathname) return undefined;
  const parts = pathname.split("/").filter(Boolean);
  if (parts.length === 2 && parts[0] === "creators") {
    return { page: "creator", channel_id: decodeURIComponent(parts[1]) };
  }
  return undefined;
}

export default function ChatWidget() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([GREETING]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, loading, open]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || loading) return;
    setError("");
    setInput("");
    const next: ChatMessage[] = [...messages, { role: "user", content: q }];
    setMessages(next);
    setLoading(true);
    track("chat_message_sent");
    try {
      // drop the canned greeting; send only real turns (ends with the user's question)
      const history = next.filter((m, i) => !(i === 0 && m === GREETING));
      const { reply } = await chat(history, chatContext(pathname));
      setMessages((m) => [...m, { role: "assistant", content: reply }]);
    } catch (e) {
      setError(
        e instanceof Error && e.message.includes("429")
          ? "I'm getting a lot of questions right now — try again in a moment."
          : "Sorry, I couldn't reach the assistant just now. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        onClick={() => {
          setOpen((o) => !o);
          if (!open) track("chat_opened");
        }}
        aria-label={open ? "Close assistant" : "Ask the CreatorPulse assistant"}
        className="fixed bottom-5 right-5 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-violet to-teal text-bg shadow-lg shadow-violet/20 transition-transform hover:scale-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet"
      >
        {open ? (
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.9-.9L3 21l1.9-5.6a8.5 8.5 0 0 1-.9-3.9 8.38 8.38 0 0 1 8.5-8.5 8.38 8.38 0 0 1 8.5 8.5z" />
          </svg>
        )}
      </button>

      {open && (
        <div className="fixed bottom-24 right-5 z-50 flex h-[32rem] max-h-[calc(100vh-7rem)] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-2xl border border-white/10 bg-surface shadow-2xl">
          <div className="border-b border-white/10 px-4 py-3">
            <p className="font-display text-sm font-bold text-ink">CreatorPulse assistant</p>
            <p className="text-xs text-muted">Grounded in the product — it won&apos;t make up numbers.</p>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={
                    m.role === "user"
                      ? "max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-violet/20 px-3 py-2 text-sm text-ink"
                      : "max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-white/5 px-3 py-2 text-sm text-ink"
                  }
                >
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl rounded-bl-sm bg-white/5 px-3 py-2 text-sm text-muted">…thinking</div>
              </div>
            )}
            {error && <p className="text-xs text-risk-high">{error}</p>}
            {messages.length === 1 && !loading && (
              <div className="space-y-2 pt-1">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="block w-full rounded-lg border border-white/10 px-3 py-2 text-left text-xs text-muted transition-colors hover:border-violet/40 hover:text-ink"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-white/10 p-3">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(input);
                  }
                }}
                rows={1}
                placeholder="Ask about CreatorPulse…"
                className="max-h-24 flex-1 resize-none rounded-lg border border-white/10 bg-bg px-3 py-2 text-sm text-ink placeholder:text-muted focus:border-violet/50 focus:outline-none"
              />
              <button
                onClick={() => send(input)}
                disabled={loading || !input.trim()}
                aria-label="Send"
                className="rounded-lg bg-violet px-3 py-2 text-sm font-semibold text-bg transition-opacity disabled:opacity-40"
              >
                ↑
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
