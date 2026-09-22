import fs from "node:fs/promises";
import fsSync from "node:fs";
import path from "node:path";

export interface FileMetadata {
  path: string;
  size: number;
  contentType?: string;
  updatedAt: Date;
}

export interface PutFileResult {
  path: string;
  size: number;
}

export interface GetFileResult {
  data: Buffer;
  contentType?: string;
  size: number;
}

export interface FileStorageClient {
  put(
    filePath: string,
    data: Buffer | Uint8Array | string,
    options?: { contentType?: string },
  ): Promise<PutFileResult>;
  get(filePath: string): Promise<GetFileResult | null>;
  delete(filePath: string): Promise<boolean>;
  list(prefix?: string): Promise<FileMetadata[]>;
}

export class FileStorageError extends Error {
  constructor(
    message: string,
    public readonly code: string,
  ) {
    super(message);
    this.name = "FileStorageError";
  }
}

export class PlatformFileStorage implements FileStorageClient {
  public readonly baseDir: string;

  constructor(customBaseDir?: string) {
    if (customBaseDir) {
      this.baseDir = path.resolve(customBaseDir);
    } else if (process.env.CAPSULE_BLOB_DIR) {
      this.baseDir = path.resolve(process.env.CAPSULE_BLOB_DIR);
    } else if (
      process.env.CAPSULE_EMULATOR === "true" ||
      process.env.NODE_ENV !== "production"
    ) {
      this.baseDir = path.resolve(process.cwd(), ".capsule", "blobs");
    } else {
      this.baseDir = "/data/blobs";
    }

    if (!fsSync.existsSync(this.baseDir)) {
      fsSync.mkdirSync(this.baseDir, { recursive: true });
    }
  }

  /**
   * Validate and resolve safe relative path within storage root, preventing path traversal.
   */
  private resolveSafePath(filePath: string): {
    fullPath: string;
    relPath: string;
  } {
    if (!filePath || typeof filePath !== "string") {
      throw new FileStorageError(
        "File path must be a non-empty string",
        "INVALID_PATH",
      );
    }

    // Strip leading slashes to make relative
    const cleanPath = filePath.replace(/^[/\\]+/, "");
    const normalized = path.normalize(cleanPath);

    if (normalized.startsWith("..") || path.isAbsolute(normalized)) {
      throw new FileStorageError(
        `Access denied: path traversal detected for '${filePath}'`,
        "PATH_TRAVERSAL",
      );
    }

    const fullPath = path.join(this.baseDir, normalized);

    // Verify it doesn't escape baseDir
    if (!fullPath.startsWith(this.baseDir)) {
      throw new FileStorageError(
        `Access denied: path '${filePath}' escapes storage root`,
        "PATH_TRAVERSAL",
      );
    }

    return { fullPath, relPath: normalized.replace(/\\/g, "/") };
  }

  async put(
    filePath: string,
    data: Buffer | Uint8Array | string,
    options: { contentType?: string } = {},
  ): Promise<PutFileResult> {
    const { fullPath, relPath } = this.resolveSafePath(filePath);
    const parentDir = path.dirname(fullPath);

    await fs.mkdir(parentDir, { recursive: true });

    const buffer = Buffer.isBuffer(data)
      ? data
      : typeof data === "string"
        ? Buffer.from(data, "utf8")
        : Buffer.from(data);

    await fs.writeFile(fullPath, buffer);

    // Store metadata if contentType provided
    if (options.contentType) {
      const metaPath = `${fullPath}.meta.json`;
      await fs.writeFile(
        metaPath,
        JSON.stringify({
          contentType: options.contentType,
          updatedAt: new Date().toISOString(),
        }),
        "utf8",
      );
    }

    return {
      path: relPath,
      size: buffer.length,
    };
  }

  async get(filePath: string): Promise<GetFileResult | null> {
    const { fullPath } = this.resolveSafePath(filePath);

    try {
      const data = await fs.readFile(fullPath);
      let contentType: string | undefined;

      const metaPath = `${fullPath}.meta.json`;
      try {
        const metaRaw = await fs.readFile(metaPath, "utf8");
        const meta = JSON.parse(metaRaw);
        contentType = meta.contentType;
      } catch {
        // No metadata file, ignore
      }

      return {
        data,
        contentType,
        size: data.length,
      };
    } catch (err: any) {
      if (err.code === "ENOENT") {
        return null;
      }
      throw err;
    }
  }

  async delete(filePath: string): Promise<boolean> {
    const { fullPath } = this.resolveSafePath(filePath);

    try {
      await fs.unlink(fullPath);
      // Clean up metadata file if it exists
      try {
        await fs.unlink(`${fullPath}.meta.json`);
      } catch {
        // ignore
      }
      return true;
    } catch (err: any) {
      if (err.code === "ENOENT") {
        return false;
      }
      throw err;
    }
  }

  async list(prefix = ""): Promise<FileMetadata[]> {
    const results: FileMetadata[] = [];
    const normalizedPrefix = prefix
      ? prefix.replace(/^[/\\]+/, "").replace(/\\/g, "/")
      : "";

    async function scan(dir: string, base: string) {
      let entries;
      try {
        entries = await fs.readdir(dir, { withFileTypes: true });
      } catch (err: any) {
        if (err.code === "ENOENT") return;
        throw err;
      }

      for (const entry of entries) {
        if (entry.name.endsWith(".meta.json")) continue; // Skip metadata files

        const fullEntryPath = path.join(dir, entry.name);
        const relEntryPath = path
          .relative(base, fullEntryPath)
          .replace(/\\/g, "/");

        if (entry.isDirectory()) {
          await scan(fullEntryPath, base);
        } else if (entry.isFile()) {
          if (!normalizedPrefix || relEntryPath.startsWith(normalizedPrefix)) {
            const stat = await fs.stat(fullEntryPath);
            let contentType: string | undefined;
            try {
              const metaRaw = await fs.readFile(
                `${fullEntryPath}.meta.json`,
                "utf8",
              );
              const meta = JSON.parse(metaRaw);
              contentType = meta.contentType;
            } catch {
              // ignore
            }

            results.push({
              path: relEntryPath,
              size: stat.size,
              contentType,
              updatedAt: stat.mtime,
            });
          }
        }
      }
    }

    await scan(this.baseDir, this.baseDir);
    return results;
  }
}

let defaultFilesInstance: PlatformFileStorage | null = null;

export function getFiles(customBaseDir?: string): PlatformFileStorage {
  if (!defaultFilesInstance || customBaseDir) {
    const instance = new PlatformFileStorage(customBaseDir);
    if (!defaultFilesInstance) {
      defaultFilesInstance = instance;
    }
    return instance;
  }
  return defaultFilesInstance;
}
