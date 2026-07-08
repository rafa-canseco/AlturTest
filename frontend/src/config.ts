const trimTrailingSlash = (value: string) => value.replace(/\/+$/, "");

export const config = {
  apiBaseUrl: trimTrailingSlash(import.meta.env.VITE_API_BASE_URL ?? ""),
};
