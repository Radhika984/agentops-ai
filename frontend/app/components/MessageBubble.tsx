export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  confidence?: number;
  createdAt: string;
}

/** A single Q/A transcript row — deliberately not a messaging-app speech
 * bubble (no left/right alternation, no colored bubble background): this
 * is a log of questions asked against a project, not a conversation with
 * a chat companion. */
export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <div className="flex gap-3 border-b border-line py-3 text-sm last:border-b-0">
      <span
        className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-semibold ${
          isUser ? "bg-surface-2 text-ink-2" : "bg-accent-soft text-accent"
        }`}
      >
        {isUser ? "Q" : "A"}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium tracking-wide text-ink-3 uppercase">
          {isUser ? "Question" : "Answer"}
        </p>
        <p className="mt-1 leading-relaxed whitespace-pre-wrap text-ink">{message.content}</p>
        {message.confidence !== undefined && (
          <p className="mt-1.5 text-xs text-ink-3">
            Confidence {(message.confidence * 100).toFixed(0)}%
          </p>
        )}
      </div>
    </div>
  );
}
