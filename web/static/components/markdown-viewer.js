import { escapeHtml, renderMarkdown } from "../utils.js";

class MarkdownViewer extends HTMLElement {
  connectedCallback() {
    this.isOpen = false;
    this.asset = null;
    this.markdown = "";
    this.rendered = "";
    this.loading = false;
    this.error = null;
    this.copyNotice = "";
    this.boundOpen = (event) => this.open(event.detail || {});
    this.boundKeydown = (event) => {
      if (event.key === "Escape" && this.isOpen) {
        this.close();
      }
    };
    document.addEventListener("markdown:open", this.boundOpen);
    document.addEventListener("keydown", this.boundKeydown);
    this.render();
  }

  disconnectedCallback() {
    document.removeEventListener("markdown:open", this.boundOpen);
    document.removeEventListener("keydown", this.boundKeydown);
  }

  async open({ title, url, filename }) {
    if (!url) return;
    this.isOpen = true;
    this.asset = {
      title: title || "Markdown preview",
      url,
      filename: filename || "report.md",
    };
    this.loading = true;
    this.error = null;
    this.copyNotice = "";
    this.markdown = "";
    this.rendered = "";
    this.render();
    try {
      const resp = await fetch(url);
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || resp.statusText);
      }
      this.markdown = await resp.text();
      this.rendered = renderMarkdown(this.markdown, this.asset?.url || "");
    } catch (err) {
      this.error = `Failed to load markdown: ${err.message}`;
    } finally {
      this.loading = false;
      this.render();
    }
  }

  close() {
    this.isOpen = false;
    this.render();
  }

  async copyToClipboard() {
    if (!this.markdown) return;
    try {
      await navigator.clipboard.writeText(this.markdown);
      this.copyNotice = "Copied.";
    } catch (err) {
      const field = document.createElement("textarea");
      field.value = this.markdown;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try {
        document.execCommand("copy");
        this.copyNotice = "Copied.";
      } catch (copyErr) {
        this.copyNotice = "Copy failed.";
      } finally {
        document.body.removeChild(field);
      }
    }
    this.render();
    if (this.copyNotice === "Copied.") {
      setTimeout(() => {
        this.copyNotice = "";
        this.render();
      }, 1500);
    }
  }

  render() {
    if (!this.isOpen) {
      this.innerHTML = "";
      return;
    }

    const title = this.asset?.title || "Markdown preview";
    const downloadUrl = this.asset?.url || "";
    const filename = this.asset?.filename || "report.md";
    let body = "";

    if (this.loading) {
      body = "<div class=\"status\">Loading markdown...</div>";
    } else if (this.error) {
      body = `<div class="status">${escapeHtml(this.error)}</div>`;
    } else {
      body = `<article class="markdown-body">${this.rendered}</article>`;
    }

    this.innerHTML = `
      <div class="markdown-viewer">
        <div class="markdown-backdrop" data-action="close"></div>
        <div class="markdown-panel" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
          <div class="markdown-header">
            <div>
              <h3>${escapeHtml(title)}</h3>
              ${this.copyNotice ? `<div class="status">${escapeHtml(this.copyNotice)}</div>` : ""}
            </div>
            <div class="markdown-actions">
              <button class="secondary" data-action="copy" ${!this.markdown ? "disabled" : ""}>Copy</button>
              ${
                downloadUrl
                  ? `<a class="button-link secondary" href="${downloadUrl}" download="${escapeHtml(filename)}">Download</a>`
                  : ""
              }
              <button class="secondary" data-action="close">Close</button>
            </div>
          </div>
          <div class="markdown-content">
            ${body}
          </div>
        </div>
      </div>
    `;

    this.querySelectorAll("[data-action='close']").forEach((btn) => {
      btn.addEventListener("click", () => this.close());
    });
    this.querySelector("[data-action='copy']")?.addEventListener("click", () => this.copyToClipboard());
  }
}

if (!customElements.get("markdown-viewer")) {
  customElements.define("markdown-viewer", MarkdownViewer);
}
