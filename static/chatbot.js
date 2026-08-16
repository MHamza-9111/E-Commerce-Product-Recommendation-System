(function () {
    "use strict";

    const chatbot = document.getElementById("apbot");
    if (!chatbot) return;

    const apiUrl = chatbot.dataset.apiUrl;
    const productsUrl = chatbot.dataset.productsUrl;
    const ordersUrl = chatbot.dataset.ordersUrl;
    const checkoutUrl = chatbot.dataset.checkoutUrl;
    const toggleButton = document.getElementById("apbotToggle");
    const closeButton = document.getElementById("apbotClose");
    const chatWindow = document.getElementById("apbotWindow");
    const messages = document.getElementById("apbotMessages");
    const form = document.getElementById("apbotForm");
    const input = document.getElementById("apbotInput");
    const sendButton = document.getElementById("apbotSend");
    const quickButtons = document.querySelectorAll("[data-apbot-message]");

    function openChatbot() {
        chatWindow.hidden = false;
        toggleButton.setAttribute("aria-expanded", "true");
        input.focus();
    }

    function closeChatbot() {
        chatWindow.hidden = true;
        toggleButton.setAttribute("aria-expanded", "false");
    }

    function scrollToBottom() {
        messages.scrollTop = messages.scrollHeight;
    }

    function addMessage(text, sender, intent, confidence) {
        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-" + sender;

        const bubble = document.createElement("div");
        bubble.className = "apbot-bubble";
        bubble.textContent = text;

        if (sender === "bot" && intent && intent !== "unknown" && intent !== "empty") {
            const meta = document.createElement("small");
            const readableIntent = intent.replaceAll("_", " ");
            const percentage = Math.round(Number(confidence || 0) * 100);
            meta.className = "apbot-meta";
            meta.textContent = readableIntent + " · " + percentage + "% confidence";
            bubble.appendChild(meta);
        }

        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToBottom();
        return row;
    }

    function getIntentAction(intent) {
        const actions = {
            recommendation: {
                label: "View recommended products",
                url: productsUrl + "?sort=rating"
            },
            product_search: {
                label: "Browse all products",
                url: productsUrl
            },
            product_details: {
                label: "Open product catalog",
                url: productsUrl
            },
            similar_products: {
                label: "Find similar products",
                url: productsUrl
            },
            offers: {
                label: "See affordable products",
                url: productsUrl + "?sort=price_low"
            },
            order_tracking: {
                label: "Open my orders",
                url: ordersUrl
            },
            checkout: {
                label: "Continue to checkout",
                url: checkoutUrl
            }
        };

        return actions[intent] || null;
    }

    function addIntentAction(intent) {
        const action = getIntentAction(intent);
        if (!action || !action.url) return;

        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-bot apbot-action-row";

        const link = document.createElement("a");
        link.className = "apbot-action";
        link.href = action.url;
        link.textContent = action.label + "  →";

        row.appendChild(link);
        messages.appendChild(row);
        scrollToBottom();
    }

    function addTypingIndicator() {
        const row = document.createElement("div");
        row.className = "apbot-message apbot-message-bot";

        const bubble = document.createElement("div");
        bubble.className = "apbot-bubble";

        const typing = document.createElement("span");
        typing.className = "apbot-typing";
        typing.innerHTML = "<span></span><span></span><span></span>";

        bubble.appendChild(typing);
        row.appendChild(bubble);
        messages.appendChild(row);
        scrollToBottom();
        return row;
    }

    async function sendMessage(message) {
        addMessage(message, "user");
        input.value = "";
        input.disabled = true;
        sendButton.disabled = true;

        const typingIndicator = addTypingIndicator();

        try {
            const response = await fetch(apiUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: message })
            });

            const data = await response.json();
            typingIndicator.remove();

            if (!response.ok) {
                addMessage(data.reply || "Please check your message and try again.", "bot");
                return;
            }

            addMessage(data.reply, "bot", data.intent, data.confidence);
            addIntentAction(data.intent);
        } catch (error) {
            typingIndicator.remove();
            addMessage("I could not connect to the chatbot. Please try again.", "bot");
            console.error("ApBot error:", error);
        } finally {
            input.disabled = false;
            sendButton.disabled = false;
            input.focus();
        }
    }

    toggleButton.addEventListener("click", function () {
        if (chatWindow.hidden) openChatbot();
        else closeChatbot();
    });

    closeButton.addEventListener("click", closeChatbot);

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        const message = input.value.trim();
        if (message) sendMessage(message);
    });

    quickButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            sendMessage(button.dataset.apbotMessage);
        });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !chatWindow.hidden) closeChatbot();
    });
})();
