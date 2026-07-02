(function () {
    function createAIButton() {
        if (document.getElementById("ask-percona-ai")) {
            return;
        }

        const search = document.querySelector(".md-search");

        if (!search || !search.parentNode) {
            return;
        }

        const button = document.createElement("button");

        button.id = "ask-percona-ai";
        button.type = "button";

        button.innerHTML = `
            <span class="percona-star">✨</span>
            <span class="percona-text">Ask Percona AI</span>
        `;

        // Place button AFTER search component
        search.parentNode.insertBefore(button, search.nextSibling);
    }

    function loadKapa() {
        // Prevent duplicate loading
        if (document.getElementById("kapa-widget-script")) {
            return;
        }

        const script = document.createElement("script");

        script.id = "kapa-widget-script";

        script.src = "https://widget.kapa.ai/kapa-widget.bundle.js";

        script.async = true;

        // REQUIRED CONFIG
        script.setAttribute(
            "data-website-id",
            "0e0d55cf-6370-4a6d-a987-96670a7fe935"
        );

        script.setAttribute(
            "data-modal-override-open-selector",
            "#ask-percona-ai"
        );

        script.setAttribute(
            "data-button-hide",
            "true"
        );

        script.setAttribute(
            "data-project-name",
            "Percona"
        );

        script.setAttribute(
            "data-modal-title",
            "Percona AI Assistant"
        );

        script.setAttribute(
            "font-size",
            "0.875rem"
        );

        // MODAL CONTENT
        script.setAttribute(
            "data-modal-disclaimer",
            "The **Percona AI Assistant** helps you find simple, clear answers to your Percona questions using [official documentation](https://docs.percona.com/), resolved [forum posts](https://forums.percona.com/) and [blog posts](https://www.percona.com/blog/). Note, do not enter personal or confidential information. Before using Percona AI assistant, read the [Legal Notice](https://docs.percona.com/pg-tde/legal-notice.html)."
        );

        script.setAttribute(
            "data-modal-example-questions",
            "What is pg_tde?, How do I install pg_tde?, How do I use pg_tde?, How do I deploy pg_tde in production?"
        );

        script.setAttribute(
            "data-project-logo",
            "https://docs.percona.com/pg-tde/documentation/docs/_static/percona-logomark-one-color-dark.png"
        );

        document.head.appendChild(script);
    }

    createAIButton();
    loadKapa();

    document.addEventListener("navigation.instant", () => {
        createAIButton();
        loadKapa();
    });
})();
