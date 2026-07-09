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

type AuditEvent = {
  id: string;
  type: string;
  message: string;
  metadata?: unknown;
  createdAt?: string;
};

type ProcessingDiagnostics = {
  status?: string;
  stage?: string;
  attemptCount?: number;
  maxAttempts?: number;
  availableAt?: string;
  lockedAt?: string;
  lockedBy?: string;
  startedAt?: string;
  completedAt?: string;
  failedAt?: string;
  lastErrorCode?: string;
  lastErrorMessage?: string;
};

type CallDetail = CallSummary & {
  transcript?: string;
  analysis?: unknown;
  errorMessage?: string;
  processing?: ProcessingDiagnostics;
  events: AuditEvent[];
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

const TAG_CATEGORIES = [
  { key: "topics", label: "Topics" },
  { key: "customer_intents", label: "Customer intents" },
  { key: "products", label: "Products" },
  { key: "risks", label: "Risks" },
  { key: "outcomes", label: "Outcomes" },
] as const;

type TagCategory = {
  key: (typeof TAG_CATEGORIES)[number]["key"];
  label: string;
  values: string[];
};

type AnalysisView = {
  summary?: string;
  intent?: string;
  sentiment?: string;
  nextAction?: string;
  tags: TagCategory[];
  raw?: unknown;
};

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

const pickNumber = (record: ApiRecord, keys: string[]): number | undefined => {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim().length > 0) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
};

const toStringList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return [];

  return value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      const record = toRecord(item);
      if (!record) return undefined;
      return pickString(record, ["label", "name", "value", "text"]);
    })
    .filter((item): item is string => Boolean(item));
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

const normalizeProcessingDiagnostics = (
  value: unknown,
  parent?: ApiRecord,
): ProcessingDiagnostics | undefined => {
  const record = toRecord(value);
  if (!record && !parent) return undefined;

  const source = record ?? parent;
  if (!source) return undefined;

  const diagnostics: ProcessingDiagnostics = {
    status: pickString(source, ["status", "job_status", "jobStatus"]),
    stage: pickString(source, [
      "stage",
      "current_stage",
      "currentStage",
      "processing_stage",
      "processingStage",
    ]),
    attemptCount: pickNumber(source, [
      "attempt_count",
      "attemptCount",
      "attempts",
    ]),
    maxAttempts: pickNumber(source, ["max_attempts", "maxAttempts"]),
    availableAt: pickString(source, ["available_at", "availableAt"]),
    lockedAt: pickString(source, ["locked_at", "lockedAt", "claimed_at", "claimedAt"]),
    lockedBy: pickString(source, ["locked_by", "lockedBy", "worker", "worker_id"]),
    startedAt: pickString(source, ["started_at", "startedAt"]),
    completedAt: pickString(source, ["completed_at", "completedAt"]),
    failedAt: pickString(source, ["failed_at", "failedAt"]),
    lastErrorCode: pickString(source, ["last_error_code", "lastErrorCode"]),
    lastErrorMessage: pickString(source, [
      "last_error_message",
      "lastErrorMessage",
      "error_message",
      "errorMessage",
    ]),
  };

  return Object.values(diagnostics).some((value) => value !== undefined)
    ? diagnostics
    : undefined;
};

const normalizeEvent = (value: unknown): AuditEvent | null => {
  const record = toRecord(value);
  if (!record) return null;

  const id = pickString(record, ["event_id", "eventId", "id"]);
  const type = pickString(record, ["event_type", "eventType", "type"]);
  const message = pickString(record, ["message"]);

  if (!id || !type || !message) return null;

  return {
    id,
    type,
    message,
    metadata: record.metadata,
    createdAt: pickString(record, ["created_at", "createdAt"]),
  };
};

const normalizeDetail = (value: unknown): CallDetail | null => {
  const summary = normalizeSummary(value);
  const record = toRecord(value);
  if (!summary || !record) return null;

  const transcriptRecord = toRecord(record.transcript);
  const processingRecord =
    toRecord(record.processing) ??
    toRecord(record.processing_diagnostics) ??
    toRecord(record.processingDiagnostics) ??
    toRecord(record.job) ??
    toRecord(record.job_diagnostics) ??
    toRecord(record.jobDiagnostics);
  const events = Array.isArray(record.events)
    ? record.events
        .map(normalizeEvent)
        .filter((event): event is AuditEvent => event !== null)
    : [];

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
    processing: normalizeProcessingDiagnostics(processingRecord, record),
    events,
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

const buildAnalysisView = (analysis: unknown): AnalysisView | null => {
  if (typeof analysis === "string") {
    return analysis.trim() ? { summary: analysis.trim(), tags: [] } : null;
  }

  const record = toRecord(analysis);
  if (!record) return null;

  const tagRecord =
    toRecord(record.tags) ??
    toRecord(record.tag_groups) ??
    toRecord(record.categories) ??
    record;

  const tags = TAG_CATEGORIES.map(({ key, label }) => ({
    key,
    label,
    values: toStringList(tagRecord[key]),
  })).filter((category) => category.values.length > 0);

  return {
    summary: pickString(record, [
      "summary",
      "call_summary",
      "callSummary",
      "overview",
      "abstract",
    ]),
    intent: pickString(record, [
      "intent",
      "primary_intent",
      "primaryIntent",
      "customer_intent",
      "customerIntent",
    ]),
    sentiment: pickString(record, [
      "sentiment",
      "customer_sentiment",
      "customerSentiment",
    ]),
    nextAction: pickString(record, [
      "next_action",
      "nextAction",
      "recommended_next_action",
      "recommendedNextAction",
      "follow_up",
      "followUp",
    ]),
    tags,
    raw: analysis,
  };
};

const formatEventType = (value: string) =>
  value
    .replace(/[._-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const hasMetadata = (metadata: unknown) => {
  if (metadata === undefined || metadata === null) return false;
  if (typeof metadata !== "object") return true;
  if (Array.isArray(metadata)) return metadata.length > 0;
  return Object.keys(metadata).length > 0;
};

const renderEventMetadata = (metadata: unknown) => {
  if (!hasMetadata(metadata)) return null;

  return (
    <pre className="audit-metadata">
      {typeof metadata === "string"
        ? metadata
        : JSON.stringify(metadata, null, 2)}
    </pre>
  );
};

const hasAnalysisContent = (analysis: AnalysisView | null) =>
  Boolean(
    analysis?.summary ??
      analysis?.intent ??
      analysis?.sentiment ??
      analysis?.nextAction ??
      analysis?.tags.length,
  );

const formatStage = (value?: string) => {
  if (!value) return "Processing";
  return formatEventType(value);
};

const buildProcessingPanel = (call: CallSummary, detail: CallDetail | null) => {
  const diagnostics = detail?.processing;
  const jobStatus = diagnostics?.status?.toLowerCase() ?? call.status;
  const isClaimed = Boolean(diagnostics?.lockedAt ?? diagnostics?.lockedBy);
  const isFailed = call.status === "failed" || jobStatus === "failed";
  const showPanel =
    call.status === "queued" || call.status === "processing" || isFailed;

  if (!showPanel) return null;

  const isWaiting =
    call.status === "queued" &&
    !isClaimed &&
    jobStatus !== "processing" &&
    jobStatus !== "running";
  const stage = isFailed ? "Failed" : formatStage(diagnostics?.stage);
  const title = isFailed
    ? "Processing needs attention"
    : isWaiting
      ? "Waiting for worker"
      : "Processing active";
  const message = isFailed
    ? "The latest processing attempt did not complete."
    : isWaiting
      ? "This call is queued and will start when a worker is available."
      : `The worker is running ${stage.toLowerCase()}.`;
  const timingLabel = isFailed
    ? "Failed"
    : isClaimed
      ? "Started"
      : "Available";
  const timingValue =
    (isFailed ? diagnostics?.failedAt : undefined) ??
    diagnostics?.startedAt ??
    diagnostics?.lockedAt ??
    diagnostics?.availableAt;
  const attemptLabel =
    diagnostics?.attemptCount !== undefined
      ? diagnostics.maxAttempts !== undefined
        ? `${diagnostics.attemptCount} of ${diagnostics.maxAttempts}`
        : String(diagnostics.attemptCount)
      : "Not available";

  return {
    title,
    message,
    tone: isFailed ? "failed" : isWaiting ? "waiting" : "active",
    stage,
    jobStatus: diagnostics?.status ?? STATUS_LABELS[call.status],
    attemptLabel,
    timingLabel,
    timingValue,
    lockedBy: diagnostics?.lockedBy,
    lastError:
      diagnostics?.lastErrorMessage ??
      detail?.errorMessage ??
      diagnostics?.lastErrorCode,
  };
};

const renderTagGroups = (tags: TagCategory[]) => {
  if (tags.length === 0) {
    return <p className="empty-copy">No tags have been generated yet.</p>;
  }

  return (
    <div className="tag-groups">
      {tags.map((category) => (
        <div className="tag-group" key={category.key}>
          <span>{category.label}</span>
          <div className="tag-chip-list">
            {category.values.map((value) => (
              <em className={`tag-chip tag-${category.key}`} key={value}>
                {value}
              </em>
            ))}
          </div>
        </div>
      ))}
    </div>
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
  const analysisView = buildAnalysisView(selectedCall?.analysis);
  const analysisReady = hasAnalysisContent(analysisView);
  const transcriptReady = Boolean(selectedCall?.transcript);
  const analysisFailed =
    displayedCall?.status === "failed" && transcriptReady && !analysisReady;
  const processingPanel = displayedCall
    ? buildProcessingPanel(displayedCall, selectedCall)
    : null;

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
                  <h3>
                    {transcriptReady ? "Analysis failed" : "Processing failed"}
                  </h3>
                  <p>
                    {selectedCall?.errorMessage ??
                      (transcriptReady
                        ? "The transcript is available, but analysis could not be completed for this call."
                        : "The backend could not process this file.")}
                  </p>
                </section>
              ) : null}

              {processingPanel ? (
                <section
                  className="processing-panel"
                  data-tone={processingPanel.tone}
                  aria-label="Processing status"
                >
                  <div className="processing-panel-copy">
                    <span>{processingPanel.stage}</span>
                    <h3>{processingPanel.title}</h3>
                    <p>{processingPanel.message}</p>
                  </div>
                  <dl className="processing-grid">
                    <div>
                      <dt>Job status</dt>
                      <dd>{processingPanel.jobStatus}</dd>
                    </div>
                    <div>
                      <dt>Attempts</dt>
                      <dd>{processingPanel.attemptLabel}</dd>
                    </div>
                    <div>
                      <dt>{processingPanel.timingLabel}</dt>
                      <dd>{formatDate(processingPanel.timingValue)}</dd>
                    </div>
                    {processingPanel.lockedBy ? (
                      <div>
                        <dt>Worker</dt>
                        <dd>{processingPanel.lockedBy}</dd>
                      </div>
                    ) : null}
                    {processingPanel.lastError ? (
                      <div className="processing-grid-wide">
                        <dt>Last error</dt>
                        <dd>{processingPanel.lastError}</dd>
                      </div>
                    ) : null}
                  </dl>
                </section>
              ) : null}

              <section className="detail-section">
                <div className="section-heading">
                  <h3>Transcript</h3>
                  <span>{transcriptReady ? "Ready" : "Pending"}</span>
                </div>
                {selectedCall?.transcript ? (
                  <p className="transcript-copy">{selectedCall.transcript}</p>
                ) : (
                  <p className="empty-copy">
                    {displayedCall.status === "queued"
                      ? "Transcript will appear after this call leaves the queue."
                      : displayedCall.status === "processing"
                        ? "Transcript is being prepared."
                        : "No transcript is available for this call."}
                  </p>
                )}
              </section>

              <section className="detail-section">
                <div className="section-heading">
                  <h3>Summary</h3>
                  <span>{analysisView?.summary ? "Ready" : "Pending"}</span>
                </div>
                {analysisView?.summary ? (
                  <p className="summary-copy">{analysisView.summary}</p>
                ) : (
                  <p className="empty-copy">
                    {analysisFailed
                      ? "Summary was not generated for this call."
                      : "Summary will appear after analysis completes."}
                  </p>
                )}
              </section>

              <section className="detail-section tag-section">
                <div className="section-heading">
                  <h3>Tags</h3>
                  <span>{analysisView?.tags.length ?? 0}</span>
                </div>
                {renderTagGroups(analysisView?.tags ?? [])}
              </section>

              <section className="detail-section">
                <div className="section-heading">
                  <h3>Intent, sentiment, next action</h3>
                  <span>{analysisReady ? "Ready" : "Pending"}</span>
                </div>
                <dl className="ops-grid">
                  <div>
                    <dt>Intent</dt>
                    <dd>{analysisView?.intent ?? "Not available"}</dd>
                  </div>
                  <div>
                    <dt>Sentiment</dt>
                    <dd>{analysisView?.sentiment ?? "Not available"}</dd>
                  </div>
                  <div>
                    <dt>Next action</dt>
                    <dd>{analysisView?.nextAction ?? "Not available"}</dd>
                  </div>
                </dl>
              </section>

              {analysisView?.raw &&
              !analysisView.summary &&
              analysisView.tags.length === 0 &&
              !analysisView.intent &&
              !analysisView.sentiment &&
              !analysisView.nextAction ? (
                <section className="detail-section">
                  <div className="section-heading">
                    <h3>Analysis payload</h3>
                    <span>Raw</span>
                  </div>
                  <pre className="analysis-json">
                    {JSON.stringify(analysisView.raw, null, 2)}
                  </pre>
                </section>
              ) : null}

              <section className="detail-section audit-section">
                <div className="section-heading">
                  <h3>Audit trail</h3>
                  <span>{selectedCall?.events.length ?? 0}</span>
                </div>
                {selectedCall?.events.length ? (
                  <ol className="audit-timeline" aria-label="Processing events">
                    {selectedCall.events.map((event) => (
                      <li className="audit-event" key={event.id}>
                        <div className="audit-event-marker" aria-hidden="true" />
                        <div className="audit-event-body">
                          <div className="audit-event-head">
                            <strong>{formatEventType(event.type)}</strong>
                            <time dateTime={event.createdAt}>
                              {formatDate(event.createdAt)}
                            </time>
                          </div>
                          <p>{event.message}</p>
                          <small>{event.id}</small>
                          {renderEventMetadata(event.metadata)}
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : detailState === "loading" ? (
                  <p className="empty-copy">Loading audit trail.</p>
                ) : (
                  <p className="empty-copy">No processing events yet.</p>
                )}
              </section>
            </>
          )}
        </section>
      </section>
    </main>
  );
}

export default App;
