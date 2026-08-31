import { fetchAndVerifyHostedBundle, verifyBundleFiles } from "./verifier.mjs?v=20260901b";

const header = document.querySelector("[data-header]");
const input = document.querySelector("#bundle-input");
const result = document.querySelector("#verification-result");
const hostedButtons = [...document.querySelectorAll("[data-verify-hosted]")];
const hostedStatus = document.querySelector("[data-hosted-status]");

function setResult(state, title, detail) {
  result.dataset.state = state;
  const marks = { idle: "—", working: "…", valid: "✓", invalid: "!" };
  result.querySelector(".result-mark").textContent = marks[state];
  result.querySelector("strong").textContent = title;
  result.querySelector("p").textContent = detail;
}

function setHostedStatus(state, label) {
  if (!hostedStatus) return;
  hostedStatus.dataset.state = state;
  hostedStatus.textContent = label;
}

function normalizeSelectedPath(file) {
  const raw = file.webkitRelativePath || file.name;
  const segments = raw.split("/").filter(Boolean);
  return segments.length > 1 ? segments.slice(1).join("/") : segments[0];
}

async function selectedFilesToMap(fileList) {
  const files = new Map();
  for (const file of fileList) {
    const path = normalizeSelectedPath(file);
    if (!path || files.has(path)) throw new Error(`duplicate selected path: ${path || "(empty)"}`);
    files.set(path, new Uint8Array(await file.arrayBuffer()));
  }
  return files;
}

async function verifyHostedReference(event) {
  event?.preventDefault();
  document.querySelector("#verify")?.scrollIntoView({ behavior: "smooth", block: "start" });
  if (hostedButtons.some((button) => button.getAttribute("aria-busy") === "true")) return;
  hostedButtons.forEach((button) => {
    button.setAttribute("aria-busy", "true");
    button.setAttribute("aria-disabled", "true");
  });
  setHostedStatus("working", "Verifying");
  setResult(
    "working",
    "Verifying the live reference",
    "Fetching the bounded evidence set from this origin, then recomputing every digest and the Ed25519 attestation.",
  );
  try {
    const verified = await fetchAndVerifyHostedBundle();
    setResult(
      "valid",
      "Live reference is cryptographically valid",
      `${verified.entries} payload files match ${verified.root}. Signer: ${verified.did}`,
    );
    setHostedStatus("valid", "Verified");
  } catch (error) {
    setResult(
      "invalid",
      "Live verification failed closed",
      error instanceof Error ? error.message : "Unknown verification error",
    );
    setHostedStatus("invalid", "Failed");
  } finally {
    hostedButtons.forEach((button) => {
      button.removeAttribute("aria-busy");
      button.removeAttribute("aria-disabled");
    });
  }
}

hostedButtons.forEach((button) => button.addEventListener("click", verifyHostedReference));

input?.addEventListener("change", async () => {
  if (!input.files?.length) {
    setResult("idle", "Ready to verify", "Run the live reference check or select your own bundle directory.");
    return;
  }
  setResult("working", "Verifying locally", `Reading ${input.files.length} selected files. Nothing is uploaded.`);
  try {
    const verified = await verifyBundleFiles(await selectedFilesToMap(input.files));
    setResult(
      "valid",
      "Cryptographically valid bundle",
      `${verified.entries} payload files match ${verified.root}. Signer: ${verified.did}`,
    );
  } catch (error) {
    setResult("invalid", "Verification failed closed", error instanceof Error ? error.message : "Unknown verification error");
  }
});

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const target = document.querySelector(button.dataset.copy);
    if (!target) return;
    try {
      await navigator.clipboard.writeText(`sha256:${target.textContent.trim()}`);
      button.textContent = "Copied";
      window.setTimeout(() => { button.textContent = "Copy"; }, 1600);
    } catch {
      button.textContent = "Select";
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(target);
      selection.removeAllRanges();
      selection.addRange(range);
    }
  });
});

function updateHeader() {
  header?.classList.toggle("is-scrolled", window.scrollY > 12);
}

updateHeader();
window.addEventListener("scroll", updateHeader, { passive: true });
