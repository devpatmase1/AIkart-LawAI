import { state } from "../state.js";

/**
 * UI Element containing:
 * - Main text input (message)
 * - "Ask" button
 * - "Stop" button
 * - "Settings" button
 * - "Inspect" button
 *
 * Automatically populates:
 * - `state.message` (on key up)
 *
 * Automatically enables / disables relevant inputs based on app state.
 */
export class ChatInput extends HTMLElement {
  /** Holds reference to interval function calling `this.stateCheck` */
  stateCheckInterval = null;

  /** Reference to `form > textarea` */
  inputTextAreaRef = null;

  /** Reference to `form > .actions > button[data-action="stop"]` */
  stopButtonRef = null;

  /** Reference to `form > .actions > button[data-action="ask"] */
  askButtonRef = null;

  connectedCallback() {
    // Enforce singleton
    for (const node of [...document.querySelectorAll("chat-flow")].slice(1)) {
      node.remove();
    }

    this.renderInnerHTML();

    // Grab shared element references
    this.inputTextAreaRef = this.querySelector("textarea");
    this.stopButtonRef = this.querySelector(`button[data-action="stop"]`);
    this.askButtonRef = this.querySelector(`button[data-action="ask"]`);

    // Event listeners for Settings / Inspect dialogs
    for (const dialogName of ["settings", "inspect"]) {
      const button = this.querySelector(
        `button[data-action="open-${dialogName}"]`
      );

      button.addEventListener("click", (e) => {
        e.preventDefault();
        document.querySelector(`${dialogName}-dialog`).open();
      });
    }

    // Event listener for submit ("Ask")
    this.querySelector("form").addEventListener("submit", (e) => {
      e.preventDefault();
      document.querySelector("chat-flow").ask();
    });

    // Event listener for "Stop"
    this.stopButtonRef.addEventListener("click", (e) => {
      e.preventDefault();
      document.querySelector("chat-flow").stopStreaming();
    });

    // Event listener to capture text input (message) and Enter shortcut
    this.inputTextAreaRef.addEventListener("input", (e) => {
      state.message = this.inputTextAreaRef.value.trim();
    });

    this.inputTextAreaRef.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        state.message = this.inputTextAreaRef.value.trim();
        if (state.message && !this.askButtonRef.hasAttribute("disabled")) {
          document.querySelector("chat-flow").ask();
        }
      }
    });

    // Check every 100ms what parts of this component need to be disabled
    this.stateCheckInterval = setInterval(this.stateCheck, 100);
  }

  disconnectedCallback() {
    clearInterval(this.stateCheckInterval);
  }

  /**
   * Determines what parts of this component need to be disabled based on app state.
   * To be called periodically.
   * @returns {void}
   */
  stateCheck = () => {
    // Input textarea: disabled while processing
    if (state.processing) {
      this.inputTextAreaRef.setAttribute("disabled", "disabled");
      this.inputTextAreaRef.placeholder = "Processing request ...";
    } else {
      this.inputTextAreaRef.removeAttribute("disabled");
      this.inputTextAreaRef.placeholder = "Ask any legal research question or search CourtListener case law...";
    }

    if (
      !state.processing &&
      !state.streaming &&
      state.model &&
      state.temperature != null &&
      state.message
    ) {
      this.askButtonRef.removeAttribute("disabled");
    } else {
      this.askButtonRef.setAttribute("disabled", "disabled");
    }

    // "Stop" button: enabled while streaming
    if (state.streaming) {
      this.stopButtonRef.removeAttribute("disabled");
    } else {
      this.stopButtonRef.setAttribute("disabled", "disabled");
    }
  };

  renderInnerHTML = () => {
    this.innerHTML = /*html*/ `
    <form class="glass-composer">
      <textarea 
        id="message" 
        placeholder="Ask any legal research question or search CourtListener case law..." 
        rows="1"
        required></textarea>
      
      <div class="composer-toolbar">
        <div class="left-actions">
          <button type="button" class="glass-pill pill-btn" data-action="open-settings" title="Change LLM Settings">
            ⚙️ <span>Settings</span>
          </button>
          <button type="button" class="glass-pill pill-btn" data-action="open-inspect" title="Inspect RAG Logs">
            📊 <span>Inspect</span>
          </button>
        </div>

        <div class="right-actions">
          <button type="button" class="glass-pill pill-btn stop-btn" data-action="stop" disabled>Stop</button>
          <button type="submit" class="ask-btn" data-action="ask" disabled>
            <span>Ask</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
          </button>
        </div>
      </div>
    </form>
    `;
  };
}
customElements.define("chat-input", ChatInput);
