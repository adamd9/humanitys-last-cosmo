import { escapeHtml } from "../utils.js";

class ChartViewer extends HTMLElement {
  connectedCallback() {
    this.isOpen = false;
    this.asset = null;
    this.error = null;
    this.boundOpen = (event) => this.open(event.detail || {});
    this.boundKeydown = (event) => {
      if (event.key === "Escape" && this.isOpen) {
        this.close();
      }
    };
    document.addEventListener("chart:open", this.boundOpen);
    document.addEventListener("keydown", this.boundKeydown);
    this.render();
  }

  disconnectedCallback() {
    document.removeEventListener("chart:open", this.boundOpen);
    document.removeEventListener("keydown", this.boundKeydown);
  }

  open({ title, url, filename }) {
    if (!url) return;
    this.isOpen = true;
    this.asset = {
      title: title || "Chart preview",
      url,
      filename: filename || "chart.png",
    };
    this.error = null;
    this.render();
  }

  close() {
    this.isOpen = false;
    this.render();
  }

  handleImageError() {
    this.error = "Failed to load chart image.";
    this.render();
  }

  render() {
    if (!this.isOpen) {
      this.innerHTML = "";
      return;
    }

    const title = this.asset?.title || "Chart preview";
    const downloadUrl = this.asset?.url || "";
    const filename = this.asset?.filename || "chart.png";
    const body = this.error
      ? `<div class="status">${escapeHtml(this.error)}</div>`
      : `<img src="${escapeHtml(downloadUrl)}" alt="${escapeHtml(title)}" />`;

    this.innerHTML = `
      <div class="chart-viewer">
        <div class="chart-backdrop" data-action="close"></div>
        <div class="chart-panel" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
          <div class="chart-header">
            <h3>${escapeHtml(title)}</h3>
            <div class="chart-actions">
              ${
                downloadUrl
                  ? `<a class="button-link secondary" href="${downloadUrl}" download="${escapeHtml(filename)}">Download</a>`
                  : ""
              }
              <button class="secondary" data-action="close">Close</button>
            </div>
          </div>
          <div class="chart-content">
            ${body}
          </div>
        </div>
      </div>
    `;

    this.querySelectorAll("[data-action='close']").forEach((btn) => {
      btn.addEventListener("click", () => this.close());
    });
    this.querySelector("img")?.addEventListener("error", () => this.handleImageError());
  }
}

if (!customElements.get("chart-viewer")) {
  customElements.define("chart-viewer", ChartViewer);
}
