import { API_BASE } from "./env";
import { getAccessToken } from "./auth-store";
import { ApiError } from "./api";
import type { ApiErrorBody } from "./types";

export function apiUpload<T>(
  path: string,
  formData: FormData,
  onProgress?: (percent: number) => void,
): Promise<T> {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    const token = getAccessToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      const status = xhr.status;
      let body: ApiErrorBody = {
        error: { code: "internal_error", message: xhr.statusText || "Upload failed" },
      };
      try {
        if (xhr.responseText) body = JSON.parse(xhr.responseText) as ApiErrorBody;
      } catch {
        /* empty */
      }
      if (status >= 200 && status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T);
        } catch {
          resolve(undefined as T);
        }
        return;
      }
      reject(new ApiError(status, body));
    };

    xhr.onerror = () => {
      reject(new Error("Network error during upload"));
    };

    xhr.send(formData);
  });
}
