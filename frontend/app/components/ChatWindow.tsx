"use client";

import { useState, type FormEvent } from "react";
import { ChatMessage, MessageBubble } from "./MessageBubble";
import { Button } from "./ui/Button";
import { EmptyState } from "./ui/EmptyState";
import { StatusLabel } from "./ui/Status";
import { TextInput } from "./ui/Input";
import { SendIcon } from "./ui/icons";

interface ChatWindowProps {
  messages: ChatMessage[];
  onSend: (question: string) => Promise<void> | void;
  isLoading: boolean;
  isSending: boolean;
  error: string | null;
}

export function ChatWindow({ messages, onSend, isLoading, isSending, error }: ChatWindowProps) {
  const [draft, setDraft] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const question = draft.trim();
    if (!question || isSending) return;
    setDraft("");
    await onSend(question);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-4 py-3">
        <p className="text-sm font-semibold text-ink">Ask</p>
        <p className="text-xs text-ink-3">Quick questions about this project, answered directly.</p>
      </div>

      <div className="flex-1 overflow-y-auto px-4">
        {isLoading && (
          <div className="py-4">
            <StatusLabel tone="neutral" pulse>
              Loading history…
            </StatusLabel>
          </div>
        )}

        {!isLoading && messages.length === 0 && (
          <div className="py-6">
            <EmptyState title="No questions yet" description="Ask something below to get started." />
          </div>
        )}

        <div className="flex flex-col">
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}

          {isSending && (
            <div className="border-b border-line py-3 last:border-b-0">
              <StatusLabel tone="accent" pulse>
                Generating answer…
              </StatusLabel>
            </div>
          )}
        </div>
      </div>

      {error && (
        <p className="border-t border-danger/25 bg-danger-soft px-4 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex gap-2 border-t border-line p-3">
        <TextInput
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Ask a question about this project…"
          disabled={isSending}
          className="flex-1"
        />
        <Button type="submit" variant="primary" disabled={isSending || !draft.trim()}>
          <SendIcon />
          Ask
        </Button>
      </form>
    </div>
  );
}
