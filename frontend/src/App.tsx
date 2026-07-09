import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Dropzone } from "./components/ui/dropzone";
import { config } from "./config";
import "./App.css";

type CallStatus = "queued" | "processing" | "completed" | "failed";

type ApiRecord = Record<string, unknown>;

type CallSummary = {
  id: string;
  filename: string;
  status: CallStatus;
  createdAt?: string;
  updatedAt?: string;
};

type CallDetail = CallSummary & {
  transcript?: string;
  analysis?: unknown;
  errorMessage?: string;
};

type LoadState = "idle" | "loading" | "ready" | "error";

const STATUS_LABELS: Record<CallStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

const STATUS_ORDER: CallStatus[] = [
  "queued",
  "processing",
  "completed",
  "failed",
];

const toRecord = (value: unknown): ApiRecord | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as ApiRecord)
    : null;

const toStringValue = (value: unknown): string | undefined =>
  typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : undefined;

const normalizeStatus = (value: unknown): CallStatus => {
  const status = toStringValue(value)?.toLowerCase();
  return STATUS_ORDER.includes(status as CallStatus)
    ? (status as CallStatus)
    : "queued";
};

const pickString = (
  record: ApiRecord,
  keys: string[],
  fallback?: string,
): string | undefined => {
  for (const key of keys) {
    const value = toStringValue(record[key]);
    if (value) return value;
  }
  return fallback;
};

const normalizeSummary = (value: unknown): CallSummary | null => {
  const record = toRecord(value);
  if (!record) return null;

  const id = pickString(record, ["id", "call_id", "callId"]);
  if (!id) return null;

  return {
    id,
    filename:
      pickString(record, ["filename", "file_name", "name", "original_filename"]) ??
      `Call ${id.slice(0, 8)}`,
    status: normalizeStatus(record.status),
    createdAt: pickString(record, [
      "created_at",
      "createdAt",
      "uploaded_at",
      "uploadedAt",
    ]),
    updatedAt: pickString(record, ["updated_at", "updatedAt"]),
  };
};

const normalizeDetail = (value: unknown): CallDetail | null => {
  const summary = normalizeSummary(value);
  const record = toRecord(value);
  if (!summary || !record) return null;

  const transcriptRecord = toRecord(record.transcript);

  return {
    ...summary,
    transcript:
      (transcriptRecord
        ? pickString(transcriptRecord, ["text", "transcript", "transcription"])
        : undefined) ?? pickString(record, ["transcript", "transcription", "text"]),
    analysis: record.analysis ?? record.insights ?? record.result,
    errorMessage: pickString(record, [
      "error",
      "error_message",
      "errorMessage",
      "failure_reason",
    ]),
  };
};

const extractList = (value: unknown): unknown[] => {
  if (Array.isArray(value)) return value;

  const record = toRecord(value);
  if (!record) return [];

  for (const key of ["calls", "items", "results", "data"]) {
    const nested = record[key];
    if (Array.isArray(nested)) return nested;
  }

  return [];
};

const buildApiUrl = (path: string) => {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${config.apiBaseUrl}${normalizedPath}`;
};

const parseApiError = async (response: Response, fallback: string) => {
  try {
    const payload = (await response.json()) as unknown;
    const record = toRecord(payload);
    const detail = record
      ? pickString(record, ["detail", "message", "error"])
      : undefined;
    return detail ?? fallback;
  } catch {
    return fallback;
  }
};

const formatDate = (value?: string) => {
  if (!value) return "No timestamp";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
};

const renderAnalysis = (analysis: unknown) => {
  if (analysis === undefined || analysis === null || analysis === "") {
    return <p className="empty-copy">No analysis yet.</p>;
  }

  if (typeof analysis === "string") {
    return <p className="analysis-copy">{analysis}</p>;
  }

  return (
    <pre className="analysis-json">
      {JSON.stringify(analysis, null, 2)}
    </pre>
  );
};

function App() {
  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [selectedCall, setSelectedCall] = useState<CallDetail | null>(null);
  const [listState, setListState] = useState<LoadState>("idle");
  const [detailState, setDetailState] = useState<LoadState>("idle");
  const [uploadState, setUploadState] = useState<LoadState>("idle");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCalls = useCallback(async () => {
    setListState((current) => (current === "ready" ? current : "loading"));
    try {
      const response = await fetch(buildApiUrl("/calls"));
      if (!response.ok) {
        throw new Error(
          await parseApiError(response, "Could not load calls right now."),
        );
      }
      const payload = (await response.json()) as unknown;
      const nextCalls = extractList(payload)
        .map(normalizeSummary)
        .filter((call): call is CallSummary => call !== null);

      setCalls(nextCalls);
      setListState("ready");
      setNotice(null);
      setSelectedCallId((current) => current ?? nextCalls[0]?.id ?? null);
    } catch (error) {
      setListState("error");
      setNotice(
        error instanceof Error
          ? error.message
          : "Could not load calls right now.",
      );
    }
  }, []);

  const loadCallDetail = useCallback(async (callId: string) => {
    setDetailState((current) => (current === "ready" ? current : "loading"));
    try {
      const response = await fetch(
        buildApiUrl(`/calls/${encodeURIComponent(callId)}`),
      );
      if (!response.ok) {
        throw new Error(
          await parseApiError(response, "Could not load this call."),
        );
      }
      const payload = (await response.json()) as unknown;
      const detail = normalizeDetail(payload);
      if (!detail) throw new Error("The call response was not readable.");

      setSelectedCall(detail);
      setDetailState("ready");
      setNotice(null);
    } catch (error) {
      setDetailState("error");
      setNotice(
        error instanceof Error ? error.message : "Could not load this call.",
      );
    }
  }, []);

  useEffect(() => {
    void loadCalls();
    const intervalId = window.setInterval(() => {
      void loadCalls();
    }, 8_000);

    return () => window.clearInterval(intervalId);
  }, [loadCalls]);

  useEffect(() => {
    if (!selectedCallId) {
      setSelectedCall(null);
      setDetailState("idle");
      return;
    }

    void loadCallDetail(selectedCallId);
  }, [loadCallDetail, selectedCallId]);

  useEffect(() => {
    if (
      !selectedCallId ||
      (selectedCall?.status !== "queued" &&
        selectedCall?.status !== "processing")
    ) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadCallDetail(selectedCallId);
    }, 4_000);

    return () => window.clearInterval(intervalId);
  }, [loadCallDetail, selectedCall?.status, selectedCallId]);

  const statusCounts = useMemo(
    () =>
      STATUS_ORDER.reduce(
        (counts, status) => ({
          ...counts,
          [status]: calls.filter((call) => call.status === status).length,
        }),
        {} as Record<CallStatus, number>,
      ),
    [calls],
  );

  const activeCallCount = statusCounts.queued + statusCounts.processing;

  const handleUpload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setNotice("Choose a WAV or MP3 file first.");
      return;
    }

    setUploadState("loading");
    setNotice("Upload received. Processing will continue on the backend.");

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(buildApiUrl("/calls"), {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(
          await parseApiError(response, "Upload failed. Try another audio file."),
        );
      }

      const payload = (await response.json()) as unknown;
      const createdCall = normalizeDetail(payload) ?? normalizeSummary(payload);

      setSelectedFile(null);
      setUploadState("ready");
      setNotice("Upload queued. The status will update here.");
      await loadCalls();

      if (createdCall?.id) {
        setSelectedCallId(createdCall.id);
      }
    } catch (error) {
      setUploadState("error");
      setNotice(
        error instanceof Error
          ? error.message
          : "Upload failed. Try another audio file.",
      );
    }
  };

  const displayedCall =
    selectedCall ??
    calls.find((call) => call.id === selectedCallId) ??
    null;

  return (
    <main className="app-shell" data-api-base-url={config.apiBaseUrl}>
      <header className="top-bar">
        <div className="brand-block">
          <span className="brand-mark" aria-hidden="true">
            A
          </span>
          <div>
            <p className="eyebrow">Altur / Operations</p>
            <h1>Call processing console</h1>
            <p className="header-copy">
              Upload audio, monitor queue progress, and review call outcomes.
            </p>
          </div>
        </div>
        <div className="header-actions">
          <dl className="header-metrics" aria-label="Call queue summary">
            <div>
              <dt>Active</dt>
              <dd>{activeCallCount}</dd>
            </div>
            <div>
              <dt>Completed</dt>
              <dd>{statusCounts.completed}</dd>
            </div>
          </dl>
          <button
            aria-label="Refresh calls"
            className="secondary-button"
            type="button"
            onClick={loadCalls}
          >
            Refresh
          </button>
        </div>
      </header>

      <section className="workspace" aria-label="Call processing workspace">
        <aside className="left-rail" aria-label="Upload and call list">
          <form className="upload-panel" onSubmit={handleUpload}>
            <div className="section-heading compact">
              <h2>Upload</h2>
              <span>WAV or MP3</span>
            </div>
            <Dropzone
              file={selectedFile}
              onFileChange={(file) => {
                setSelectedFile(file);
                setNotice(null);
              }}
              onReject={setNotice}
            />
            <button
              className="primary-button"
              aria-busy={uploadState === "loading"}
              data-loading={uploadState === "loading"}
              type="submit"
              disabled={uploadState === "loading"}
            >
              {uploadState === "loading" ? "Uploading" : "Queue upload"}
            </button>
            <p className="upload-copy">
              Files enter a processing queue. Completed calls unlock transcript
              and analysis.
            </p>
          </form>

          <section className="status-strip" aria-label="Call status counts">
            {STATUS_ORDER.map((status) => (
              <div className="status-count" key={status}>
                <span>{STATUS_LABELS[status]}</span>
                <strong>{statusCounts[status]}</strong>
              </div>
            ))}
          </section>

          <section className="call-list" aria-label="Calls">
            <div className="section-heading">
              <h2>Calls</h2>
              <span>{listState === "loading" ? "Loading" : calls.length}</span>
            </div>

            {calls.length === 0 && listState !== "loading" ? (
              <p className="empty-copy">No calls yet.</p>
            ) : null}

            <div className="call-list-items">
              {calls.map((call) => (
                <button
                  className="call-row"
                  data-active={call.id === selectedCallId}
                  aria-pressed={call.id === selectedCallId}
                  key={call.id}
                  type="button"
                  onClick={() => setSelectedCallId(call.id)}
                >
                  <span className={`status-dot status-${call.status}`} />
                  <span>
                    <strong>{call.filename}</strong>
                    <small>{formatDate(call.createdAt ?? call.updatedAt)}</small>
                  </span>
                  <em>{STATUS_LABELS[call.status]}</em>
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="detail-panel" aria-label="Call detail">
          {notice ? (
            <div className="notice" role="status" aria-live="polite">
              {notice}
            </div>
          ) : null}

          {!displayedCall ? (
            <div className="empty-detail">
              <h2>No call selected</h2>
              <p>Upload audio or select a call from the list.</p>
            </div>
          ) : (
            <>
              <div className="detail-head">
                <div>
                  <p className="eyebrow">Call detail</p>
                  <h2>{displayedCall.filename}</h2>
                  <p>Call ID {displayedCall.id}</p>
                </div>
                <span className={`status-badge status-${displayedCall.status}`}>
                  {STATUS_LABELS[displayedCall.status]}
                </span>
              </div>

              <div className="meta-grid">
                <div>
                  <span>Created</span>
                  <strong>{formatDate(displayedCall.createdAt)}</strong>
                </div>
                <div>
                  <span>Updated</span>
                  <strong>{formatDate(displayedCall.updatedAt)}</strong>
                </div>
                <div>
                  <span>Detail</span>
                  <strong>
                    {detailState === "loading" ? "Refreshing" : "Loaded"}
                  </strong>
                </div>
              </div>

              {displayedCall.status === "failed" ? (
                <section className="failure-panel">
                  <h3>Processing failed</h3>
                  <p>
                    {selectedCall?.errorMessage ??
                      "The backend could not process this file."}
                  </p>
                </section>
              ) : null}

              <section className="detail-section">
                <div className="section-heading">
                  <h3>Transcript</h3>
                  <span>
                    {displayedCall.status === "completed" ? "Ready" : "Pending"}
                  </span>
                </div>
                {selectedCall?.transcript ? (
                  <p className="transcript-copy">{selectedCall.transcript}</p>
                ) : (
                  <p className="empty-copy">No transcript yet.</p>
                )}
              </section>

              <section className="detail-section">
                <div className="section-heading">
                  <h3>Analysis</h3>
                  <span>
                    {selectedCall?.analysis ? "Ready" : "Pending"}
                  </span>
                </div>
                {renderAnalysis(selectedCall?.analysis)}
              </section>
            </>
          )}
        </section>
      </section>
    </main>
  );
}

export default App;
