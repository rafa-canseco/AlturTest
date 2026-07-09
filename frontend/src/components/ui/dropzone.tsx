import { ReactNode, useCallback } from "react";
import { FileRejection, useDropzone } from "react-dropzone";

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
            "Choose one WAV or MP3 file under 100 MB.",
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
      maxSize: 100 * 1024 * 1024,
      multiple: false,
      onDrop: handleDrop,
    });

  return (
    <div
      className="dropzone"
      data-accept={isDragAccept}
      data-active={isDragActive}
      data-reject={isDragReject}
      {...getRootProps()}
    >
      <input {...getInputProps()} />
      <span className="dropzone-mark">+</span>
      <div>
        <strong>{file ? file.name : "Drop WAV/MP3 here"}</strong>
        <small>
          {file
            ? `${file.type || "audio"} / ${formatFileSize(file.size)}`
            : "Click to browse. One file, 100 MB max."}
        </small>
        {children}
      </div>
    </div>
  );
}
