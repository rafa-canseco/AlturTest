import { ReactNode, useCallback } from "react";
import { FileRejection, useDropzone } from "react-dropzone";

const MAX_UPLOAD_BYTES = 500 * 1024 * 1024;
const MAX_UPLOAD_LABEL = "500 MB";

type DropzoneProps = {
  file: File | null;
  onFileChange: (file: File | null) => void;
  onReject: (message: string) => void;
  children?: ReactNode;
};

const formatFileSize = (size: number) => {
  if (size < 1024 * 1024) return `${Math.ceil(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
};

export function Dropzone({
  children,
  file,
  onFileChange,
  onReject,
}: DropzoneProps) {
  const handleDrop = useCallback(
    (acceptedFiles: File[], fileRejections: FileRejection[]) => {
      const rejectedFile = fileRejections[0];
      if (rejectedFile) {
        onFileChange(null);
        onReject(
          rejectedFile.errors[0]?.message ??
            `Choose one WAV or MP3 file under ${MAX_UPLOAD_LABEL}.`,
        );
        return;
      }

      onFileChange(acceptedFiles[0] ?? null);
    },
    [onFileChange, onReject],
  );

  const { getInputProps, getRootProps, isDragAccept, isDragReject, isDragActive } =
    useDropzone({
      accept: {
        "audio/mpeg": [".mp3"],
        "audio/wav": [".wav"],
        "audio/x-wav": [".wav"],
      },
      maxFiles: 1,
      maxSize: MAX_UPLOAD_BYTES,
      multiple: false,
      onDrop: handleDrop,
    });

  return (
    <div
      className="dropzone"
      {...getRootProps()}
      aria-label="Choose or drop one WAV or MP3 audio file"
      data-accept={isDragAccept}
      data-active={isDragActive}
      data-reject={isDragReject}
      role="button"
    >
      <input {...getInputProps()} />
      <span className="dropzone-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" role="img">
          <path d="M12 4v16m8-8H4" />
        </svg>
      </span>
      <div>
        <strong>{file ? file.name : "Drop WAV/MP3 here"}</strong>
        <small>
          {file
            ? `${file.type || "audio"} / ${formatFileSize(file.size)}`
            : `Click to browse. One file, ${MAX_UPLOAD_LABEL} max.`}
        </small>
        {children}
      </div>
    </div>
  );
}
