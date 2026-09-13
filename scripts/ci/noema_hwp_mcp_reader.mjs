#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [, , sourceRoot, filePath] = process.argv;
if (!sourceRoot || !filePath || !existsSync(sourceRoot)) {
  process.stderr.write("hwp-mcp source directory and document path are required\n");
  process.exit(2);
}

try {
  const hwpPackage = JSON.parse(readFileSync(join(sourceRoot, "package.json"), "utf8"));
  const require = createRequire(pathToFileURL(join(sourceRoot, "package.json")));
  const rhwpPackage = JSON.parse(
    readFileSync(require.resolve("@rhwp/core/package.json"), "utf8"),
  );
  if (hwpPackage.name !== "hwp-mcp" || hwpPackage.version !== "0.3.0") {
    throw new Error("unexpected hwp-mcp package identity");
  }
  if (rhwpPackage.name !== "@rhwp/core" || rhwpPackage.version !== "0.7.7") {
    throw new Error("unexpected rhwp package identity");
  }
  const documentModule = await import(pathToFileURL(join(sourceRoot, "dist/core/document.js")));
  const toolsModule = await import(pathToFileURL(join(sourceRoot, "dist/tools/read.js")));
  const document = await documentModule.openDocument(filePath);
  documentModule.closeDocument(document);
  const text = await toolsModule.readHwp({ file_path: filePath });
  if (!text || /(?:파일 읽기 오류|File not found|text extraction error)/i.test(text)) {
    throw new Error("hwp-mcp returned an extraction error");
  }
  process.stdout.write(`${text}\n`);
} catch (error) {
  process.stderr.write("hwp-mcp/rhwp document extraction failed\n");
  process.exit(1);
}
