import type { ChatRequest, ChatResponse, WorkflowEvent } from "../types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function responseError(response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
  } catch {
    return new Error(`请求失败（HTTP ${response.status}）`);
  }
}

export async function chat(
  request: ChatRequest,
  signal?: AbortSignal,
): Promise<ChatResponse> {
  const response = await fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  return (await response.json()) as ChatResponse;
}

function parseFrame(frame: string): WorkflowEvent | null {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) {
    return null;
  }
  return JSON.parse(data) as WorkflowEvent;
}

export async function streamChat(
  request: ChatRequest,
  onEvent: (event: WorkflowEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(apiUrl("/api/chat/stream"), {
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw await responseError(response);
  }
  if (!response.body) {
    throw new Error("当前浏览器无法读取 SSE 响应流");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const event = parseFrame(frame);
      if (event) {
        onEvent(event);
      }
    }
    if (done) {
      break;
    }
  }
  const finalEvent = parseFrame(buffer.trim());
  if (finalEvent) {
    onEvent(finalEvent);
  }
}
