"use client";

import { useParams } from "next/navigation";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../components/AppShell";
import { ChatWindow } from "../../../components/ChatWindow";
import type { ChatMessage } from "../../../components/MessageBubble";
import { RunAgentPanel } from "../../../components/RunAgentPanel";
import { ChevronLeftIcon } from "../../../components/ui/icons";
import {
  ApiError,
  askQuestion,
  clearToken,
  getProject,
  listInteractions,
  type InteractionRead,
} from "../../../lib/api";
import { useRequireAuth } from "../../../lib/useRequireAuth";

function interactionsToMessages(interactions: InteractionRead[]): ChatMessage[] {
  return interactions.flatMap((i) => [
    { id: `${i.id}-q`, role: "user" as const, content: i.question, createdAt: i.created_at },
    { id: `${i.id}-a`, role: "assistant" as const, content: i.answer, createdAt: i.created_at },
  ]);
}

export default function ChatPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
    enabled: checkedAuth,
  });

  const historyQuery = useQuery({
    queryKey: ["interactions", projectId],
    queryFn: () => listInteractions(projectId),
    enabled: checkedAuth,
  });

  const askMutation = useMutation({
    mutationFn: (question: string) => askQuestion(projectId, question),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["interactions", projectId] });
    },
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const messages = historyQuery.data ? interactionsToMessages(historyQuery.data) : [];

  const breadcrumb = (
    <div className="min-w-0">
      <a
        href="/projects"
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Projects
      </a>
      <p className="truncate text-sm font-semibold text-ink">
        {projectQuery.data?.name ?? "Loading project…"}
      </p>
      {projectQuery.data?.description && (
        <p className="hidden truncate text-xs text-ink-3 md:block">
          {projectQuery.data.description}
        </p>
      )}
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="mx-auto flex h-[calc(100vh-57px)] w-full max-w-6xl flex-col gap-4 p-4 md:h-[calc(100vh-65px)] md:flex-row md:p-6">
        {/* The evaluation console is the primary, flexible column — this
            is an agent evaluation platform first, a Q&A box second. */}
        <div className="flex min-h-0 flex-1">
          <RunAgentPanel projectId={projectId} />
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface shadow-sm md:w-80 md:shrink-0 lg:w-96">
          <ChatWindow
            messages={messages}
            isLoading={historyQuery.isLoading}
            isSending={askMutation.isPending}
            error={
              askMutation.isError
                ? askMutation.error instanceof ApiError
                  ? askMutation.error.message
                  : "Could not get an answer. Please try again."
                : historyQuery.isError
                  ? "Could not load chat history."
                  : null
            }
            onSend={async (question) => {
              await askMutation.mutateAsync(question);
            }}
          />
        </div>
      </div>
    </AppShell>
  );
}
